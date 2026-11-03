"""Fixed operator grammar and foreground lifecycle policy for Simquaro."""

import argparse
import asyncio
from collections.abc import Mapping, Sequence
from contextlib import suppress
import json
from pathlib import Path
import re
import shlex
import signal
import sys

from simquaro.config import InstanceConfig, instance_record, validate_inventory
from simquaro.control import control_request
from synqaro_protocol.errors import ERROR_CATALOG
from simquaro.faults import FaultRule
from simquaro.registry import get_model
from simquaro.runtime import Runtime


class _Usage(ValueError):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise _Usage(message)


def _parser():
    parser = _Parser(prog="simquaro", description="Run configured hardware simulators in the foreground.",
                     allow_abbrev=False)
    parser.add_argument("--json", action="store_true", help="emit version-1 JSON records; foreground commands emit JSON Lines")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="list the explicit configured inventory")
    console = commands.add_parser("console", help="exchange literal diagnostic text/bytes with a target")
    console.add_argument("instance", metavar="INSTANCE")
    console.add_argument("--raw", action="store_true", help="decode escapes; do not append LF")
    for action in ("status", "start", "stop", "restart"):
        command = commands.add_parser(action, help=f"{action} one configured instance or all")
        command.add_argument("instance", metavar="INSTANCE|all")
    fault = commands.add_parser("fault", help="inspect or change external test conditions")
    actions = fault.add_subparsers(dest="fault_action", required=True)
    for action in ("list", "status", "activate", "clear", "schedule", "cancel"):
        command = actions.add_parser(action, help={
            "list": "show the offline finite catalog", "status": "show active conditions and remaining rules",
            "activate": "activate a persistent cause", "clear": "remove a persistent cause",
            "schedule": "schedule the next matching finite events", "cancel": "cancel a remaining rule",
        }[action], allow_abbrev=False)
        command.add_argument("instance", metavar="INSTANCE")
        if action in ("activate", "clear", "schedule"):
            command.add_argument("name", metavar="FAULT")
        if action == "cancel":
            command.add_argument("rule_id", metavar="RULE_ID")
        if action == "schedule":
            command.add_argument("--when", required=True, metavar="EVENT")
            command.add_argument("--times", type=int, default=1, metavar="N", help="next N matching events (default: 1)")
            command.add_argument("--delay-ms", type=int, metavar="MS", help="delay_response only: integer 1–60000")
    return parser


def _error(code, message, actions):
    return {"code": code, "message": message, "actions": actions}


class _Output:
    def __init__(self, structured):
        self.structured = structured

    def emit(self, event, *, instance=None, result=None, error=None):
        record = {"version": 1, "event": event, "ok": error is None}
        if instance is not None:
            record["instance"] = instance
        record["error" if error is not None else "result"] = error if error is not None else result
        if self.structured:
            print(json.dumps(record, ensure_ascii=True, allow_nan=False, separators=(",", ":")), flush=True)
        elif error is None:
            self._human(event, instance, result)
        if error is not None:
            print(f"{instance + ': ' if instance else ''}{error['code']}: {error['message']}", file=sys.stderr, flush=True)
            for action in error["actions"]:
                print("  " + (shlex.join(action) if isinstance(action, list) else action), file=sys.stderr, flush=True)

    def outcome(self, event, value):
        error = None if value["ok"] else {
            **value["error"], "outcome": {key: item for key, item in value.items() if key != "error"}}
        self.emit(event, instance=value["instance"], result=value if value["ok"] else None,
                  error=error)

    def _human(self, event, instance, result):
        if isinstance(result, dict) and "instances" in result:
            for item in result["instances"]:
                if "outcome" in item:
                    self.outcome(event, item)
                else:
                    print(f"{item['name']}  {item['host']}:{item['port']}  {item['model']}", flush=True)
        elif isinstance(result, dict) and "outcome" in result:
            text = f"{instance}: {result['outcome']}"
            if "process" in result:
                text += f"; process={result['process']}; control={result.get('control', 'not_running')}"
            status = result.get("status")
            if status:
                runtime = status["runtime"]
                general = status["model"]["reported"]["general"]
                text += (f"; listener={runtime['hardware_listener']}; hardware communication={runtime['hardware_communication']}"
                         f" ({'verified' if runtime['hardware_communication_verified'] else 'unverified'})"
                         f"; health={general['health']}; activity={general['activity']}")
            print(text, flush=True)
            if result["outcome"] == "already_running":
                print(f"  simquaro status {instance}\n  simquaro restart {instance}", flush=True)
            if status:
                print("  injections: " + json.dumps(status["faults"], sort_keys=True), flush=True)
                codes = list(general.get("fault_codes", []))
                codes += [incident.get("code") for incident in status["model"].get("incidents", [])]
                startup = result.get("startup_config") or result.get("configured") or {}
                catalog = get_model(startup["model"]).error_catalog if "model" in startup else ERROR_CATALOG
                for code in dict.fromkeys(codes):
                    definition = catalog.get(code)
                    if definition:
                        print(f"  {code}: {definition.message}. {definition.action}", flush=True)
        elif isinstance(result, dict) and "catalog" in result:
            for item in result["catalog"]:
                print(f"{item['name']}: {'persistent cause' if item['persistent'] else 'delivery effect'}; {item['effect']}", flush=True)
                print("  events: " + ", ".join(item["events"]) + "; parameters: " + json.dumps(item["parameters"]), flush=True)
                print("  compatible with: " + ", ".join(item["compatible_with"]), flush=True)
                command = ["simquaro", "fault", "activate" if item["persistent"] else "schedule", instance, item["name"]]
                if not item["persistent"]:
                    command += ["--when", item["example"]["when"], "--times", "1"]
                if item["parameters"]:
                    command += ["--delay-ms", "2500"]
                print("  " + shlex.join(command), flush=True)
        else:
            print(f"{instance + ': ' if instance else ''}{event}: {json.dumps(result, sort_keys=True)}", flush=True)


def _fault_arguments(args, definition):
    action = args.fault_action
    if action in ("list", "status"):
        return {}
    if action == "cancel":
        if re.fullmatch(r"rule-[1-9][0-9]{0,18}", args.rule_id) is None:
            raise _Usage("invalid rule ID; run simquaro fault status " + args.instance)
        return {"rule_id": args.rule_id}
    faults = definition.fault_factory()
    catalog = {entry["name"]: entry for entry in faults.catalog()}
    if args.name not in catalog:
        raise _Usage("unknown fault " + repr(args.name) + "; run simquaro fault list " + args.instance)
    entry = catalog[args.name]
    if action == "schedule":
        parameters = {} if args.delay_ms is None else {"delay_ms": args.delay_ms}
        try:
            rule = FaultRule(args.name, args.when, args.times, parameters)
            faults.validate_rule(rule)
        except ValueError as error:
            raise _Usage(str(error) + "; run simquaro fault list " + args.instance) from None
        return {"name": rule.name, "when": rule.when, "times": rule.times, "parameters": dict(rule.parameters)}
    if not entry["persistent"]:
        raise _Usage("delivery effects require fault schedule/cancel; run simquaro fault list " + args.instance)
    return {"name": args.name}


async def _foreground(runtime, configs, action, output):
    """Own signals once, cancel once, and await all owned cleanup before exit."""
    started, observers = [], {}
    interrupted = False
    failure = False
    loop = asyncio.get_running_loop()

    async def observe(child):
        nonlocal failure
        returncode = await child.wait()
        # Retain crashes already observed before a shutdown request. A later
        # SIGKILL can be the expected escalation of that requested shutdown.
        if not interrupted:
            failure |= returncode != 0
        output.emit("exited", instance=child.name, result={"returncode": returncode})

    async def operate():
        nonlocal failure
        try:
            for config in configs:
                result = await (runtime.start(config) if action == "start" else runtime.restart(config))
                started.append(result)
                failure |= not result.outcome["ok"]
                output.outcome(action, result.outcome)
                if result.child is not None:
                    observers[asyncio.create_task(observe(result.child))] = result.child
        except (asyncio.CancelledError, OSError, ValueError):
            # Cancellation inside start/restart has already rolled back its
            # in-flight child. Supervision cleans only earlier owned run tokens.
            cleanup = asyncio.create_task(runtime.supervise(started))
            await asyncio.sleep(0)
            cleanup.cancel()
            with suppress(asyncio.CancelledError):
                await cleanup
            raise
        return await runtime.supervise(started)

    task = asyncio.create_task(operate())

    def interrupt(sig):
        nonlocal interrupted
        if not interrupted:
            interrupted = True
            output.emit("interrupted", result={"signal": sig.name})
            task.cancel()

    previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        # No await between task creation and installing both handlers.
        for sig in previous:
            loop.add_signal_handler(sig, interrupt, sig)
        try:
            result = await task
        except (asyncio.CancelledError, OSError, ValueError) as error:
            if not isinstance(error, asyncio.CancelledError):
                failure = True
                output.emit("cleanup", error=_error("RUNTIME_FAILURE", str(error),
                            [["simquaro", "status", config.name] for config in configs]))
            by_name = {config.name: config for config in configs}
            for owned in started:
                child = owned.child
                if child is None:
                    continue
                state = await runtime.inspect(by_name[child.name])
                if not state["ok"]:
                    failure = True
                    output.outcome("cleanup", state)
                if child.returncode is None:
                    failure = True
                    output.emit("cleanup", instance=child.name,
                                error=_error("STOP_UNCONFIRMED", "Runtime cleanup did not confirm the owned child stopped; terminating only its retained original pidfd. Inspect the reported runtime state before restarting.",
                                             [["simquaro", "status", child.name]]))
                    try:
                        await child.terminate()
                    except (OSError, ValueError) as cleanup_error:
                        output.emit("cleanup", instance=child.name,
                                    error=_error("STOP_UNCONFIRMED", str(cleanup_error),
                                                 [["simquaro", "status", child.name]]))
            result = int(failure)
        # An unconfirmed kernel-level termination must not turn this bounded
        # error into an unlimited observer wait. Never signal a name/replacement.
        for observer, child in observers.items():
            if child.returncode is None:
                observer.cancel()
        await asyncio.gather(*observers, return_exceptions=True)
        output.emit("finished", result={"exit_code": result})
        return result
    finally:
        for sig, handler in previous.items():
            loop.remove_signal_handler(sig)
            signal.signal(sig, handler)


async def _run(args, configs, runtime_root, output, fault_arguments):
    if args.command == "console":
        from simquaro.console import run_console
        return await run_console(configs[0], raw=args.raw, structured=output.structured, emit=output.emit)
    runtime = Runtime(runtime_root)
    if args.command in ("start", "restart"):
        return await _foreground(runtime, configs, args.command, output)
    if args.command in ("status", "stop"):
        results = []
        for config in configs:
            results.append(await (runtime.inspect(config) if args.command == "status" else runtime.stop(config.name)))
        if args.instance == "all":
            failed = any(not item["ok"] for item in results)
            # One record preserves all per-instance outcomes, including partial
            # failures; human diagnostics are also written to stderr.
            if output.structured:
                record = {"version": 1, "event": args.command, "ok": not failed, "result": {"instances": results}}
                print(json.dumps(record, separators=(",", ":"), allow_nan=False), flush=True)
                for item in results:
                    if not item["ok"]:
                        _Output(False).outcome(args.command, item)
            else:
                output.emit(args.command, result={"instances": results})
        else:
            output.outcome(args.command, results[0])
        return int(any(not item["ok"] for item in results))
    config = configs[0]
    state = await runtime.inspect(config)
    if not state["ok"]:
        output.outcome("fault." + args.fault_action, state)
        return 1
    if state["outcome"] == "stopped":
        output.emit("fault." + args.fault_action, instance=config.name,
                    error=_error("NOT_RUNNING", "Instance is stopped; start it before live fault control.",
                                 [["simquaro", "start", config.name]]))
        return 1
    response = await control_request(runtime.root / (config.name + ".sock"), "fault." + args.fault_action, fault_arguments)
    error = response.get("error")
    if error:
        error = {**error, "actions": [["simquaro", "fault", "status", config.name],
                                      ["simquaro", "fault", "list", config.name],
                                      ["simquaro", "restart", config.name]]}
    output.emit("fault." + args.fault_action, instance=config.name, result=response.get("result"), error=error)
    return int(not response["ok"])


def main(argv: Sequence[str] | None = None, *, inventory: Mapping[str, InstanceConfig] | None = None,
         runtime_root: Path | None = None) -> int:
    """Run the same entry point from source, console script or isolated tests."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    output = _Output("--json" in arguments)
    args = None
    try:
        args = _parser().parse_args(arguments)
        try:
            if inventory is None:
                # Keep help usable even when the editable loader cannot import.
                from simquaro.instances import load_inventory
                inventory = load_inventory()
            configs = validate_inventory(inventory)
        except (ValueError, TypeError, OSError, SyntaxError, ImportError) as error:
            output.emit("error", error=_error("CONFIGURATION_ERROR", str(error),
                        ["Correct startup configuration in src/simquaro/instances.py (or the installed simquaro/instances.py), then rerun the command.",
                         ["simquaro", "list"], ["simquaro", "--help"]]))
            return 1
        if args.command == "list":
            output.emit("list", result={"instances": [instance_record(config) for config in configs.values()]})
            return 0
        if args.instance == "all" and args.command in ("start", "stop", "restart", "status"):
            selected = list(configs.values())
        elif args.instance in configs:
            selected = [configs[args.instance]]
        else:
            raise _Usage("unknown instance " + repr(args.instance) + "; run simquaro list and select a configured name")
        definition = get_model(selected[0].model) if args.command == "fault" else None
        fault_arguments = _fault_arguments(args, definition) if args.command == "fault" else None
        if args.command == "fault" and args.fault_action == "list":
            output.emit("fault.list", instance=args.instance, result={"catalog": definition.fault_factory().catalog()})
            return 0
        return asyncio.run(_run(args, selected, runtime_root, output, fault_arguments))
    except SystemExit as error:
        return int(error.code)
    except KeyboardInterrupt:
        return 130
    except _Usage as error:
        actions = [["simquaro", "--help"], ["simquaro", "list"]]
        if args is not None and args.command == "fault" and args.instance in configs:
            actions.insert(0, ["simquaro", "fault", "list", args.instance])
        output.emit("usage", error=_error("INVALID_USAGE", str(error), actions))
        return 2
    except (ValueError, OSError) as error:
        output.emit("error", error=_error("RUNTIME_FAILURE", str(error),
                    [["simquaro", "status", getattr(args, "instance", "all")], ["simquaro", "--help"]]))
        return 1
