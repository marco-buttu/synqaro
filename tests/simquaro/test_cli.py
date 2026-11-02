"""Exercise the public CLI in isolated subprocesses and private runtimes."""

import asyncio
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import signal
import socket
import sys
import tempfile
import unittest

from simquaro.config import InstanceConfig
from simquaro._ownership import Directory, ProcessIdentity
from simquaro.faults import FaultEffect, FaultRule, Scenario
from simquaro.runtime import Runtime


class CliTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sq-cli-")
        self.root = Path(self.temp.name) / "run"
        self.runtime = Runtime(self.root)
        self.children = []
        self.processes = []
        self.logs = tempfile.TemporaryFile()
        self.stderr_fd = os.dup(2)
        os.dup2(self.logs.fileno(), 2)
        self.inventory = {}
        for name in ("receiver-a", "receiver-b", "receiver-c"):
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            self.inventory[name] = InstanceConfig(name, "fictitious_receiver", "127.0.0.1", port)

    async def asyncTearDown(self):
        for process in self.processes:
            if process.returncode is None:
                process.kill()
        for result in self.children:
            if result.child and result.child.returncode is None:
                result.child.signal(signal.SIGKILL)
                await result.child.wait()
        # Any failed assertion must still reclaim CLI-created workers.
        for name in self.inventory:
            await self.runtime.stop(name)
        for process in self.processes:
            await asyncio.wait_for(process.wait(), 5)
        os.dup2(self.stderr_fd, 2)
        os.close(self.stderr_fd)
        self.logs.close()
        self.temp.cleanup()

    async def launch(self, *arguments, inventory=None, module=False):
        if module:
            command = [sys.executable, "-m", "simquaro", *arguments]
        else:
            configurations = [asdict(value) for value in (inventory or self.inventory).values()]
            script = (
                "import json,sys; from pathlib import Path; "
                "from simquaro.config import InstanceConfig,ReceiverConfig; "
                "from simquaro.cli import main; "
                "configs=json.loads(sys.argv[1]); "
                "inventory={c['name']:InstanceConfig(**{**c,'receiver':ReceiverConfig(**c['receiver'])}) for c in configs}; "
                "sys.exit(main(sys.argv[3:],inventory=inventory,runtime_root=Path(sys.argv[2])))"
            )
            command = [sys.executable, "-c", script, json.dumps(configurations), str(self.root), *arguments]
        process = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        self.processes.append(process)
        return process

    async def run_cli(self, *arguments, **kwargs):
        process = await self.launch(*arguments, **kwargs)
        stdout, stderr = await asyncio.wait_for(process.communicate(), 10)
        return process.returncode, stdout.decode(), stderr.decode()

    async def start(self, name="receiver-a", scenario=Scenario()):
        result = await self.runtime.start(self.inventory[name], scenario=scenario)
        self.children.append(result)
        self.assertTrue(result.outcome["ok"], result.outcome)
        return result

    async def event(self, process, event, instance=None):
        while True:
            line = await asyncio.wait_for(process.stdout.readline(), 8)
            if not line:
                self.fail((await asyncio.wait_for(process.stderr.read(), 2)).decode())
            record = json.loads(line)
            self.assertEqual(record["version"], 1)
            if record["event"] == event and (instance is None or record.get("instance") == instance):
                return record

    async def test_module_and_every_command_help(self):
        paths = [[], ["fault"], ["list"], ["status"], ["start"], ["stop"], ["restart"]]
        paths += [["fault", action] for action in ("list", "status", "activate", "clear", "schedule", "cancel")]
        for path in paths:
            with self.subTest(path=path):
                code, stdout, stderr = await self.run_cli(*path, "--help", module=True)
                self.assertEqual(code, 0, stderr)
                self.assertIn("usage:", stdout)
                self.assertEqual(stderr, "")

    async def test_offline_list_and_catalog(self):
        code, stdout, stderr = await self.run_cli("list")
        self.assertEqual(code, 0, stderr)
        self.assertIn("receiver-a", stdout)
        self.assertIn("127.0.0.1", stdout)
        self.assertNotIn("implementation", stdout.lower())
        code, stdout, stderr = await self.run_cli("--json", "fault", "list", "receiver-a")
        self.assertEqual(code, 0, stderr)
        record = json.loads(stdout)
        self.assertEqual(record["instance"], "receiver-a")
        catalog = {item["name"]: item for item in record["result"]["catalog"]}
        self.assertEqual(catalog["delay_response"]["parameters"]["delay_ms"]["max"], 60000)
        self.assertTrue(catalog["synthesizer_failure"]["persistent"])

    async def test_invalid_usage_is_two_with_actionable_json(self):
        invalid = [[], ["status", "missing"], ["fault", "activate", "all", "clock_untrusted"],
                   ["fault", "activate", "receiver-a", "nonsense"],
                   ["fault", "schedule", "receiver-a", "drop_response", "--when", "nonsense"],
                   ["fault", "schedule", "receiver-a", "drop_response", "--when", "calibrate_reference_measurement"],
                   ["fault", "activate", "receiver-a", "drop_response"],
                   ["fault", "schedule", "receiver-a", "delay_response", "--when", "response_ready"],
                   ["stop", "receiver-a", "--force"], ["status", "receiver-a.sock"]]
        for arguments in invalid:
            with self.subTest(arguments=arguments):
                code, stdout, stderr = await self.run_cli("--json", *arguments)
                self.assertEqual(code, 2, stderr)
                record = json.loads(stdout)
                self.assertFalse(record["ok"])
                self.assertEqual(record["error"]["code"], "INVALID_USAGE")
                self.assertTrue(record["error"]["actions"])
                self.assertTrue(stderr)

    async def test_status_health_fault_is_query_success_without_consuming_rule(self):
        await self.start(scenario=Scenario((FaultEffect("synthesizer_failure"),),
                                          (FaultRule("drop_response", "response_ready"),)))
        code, stdout, stderr = await self.run_cli("--json", "status", "all")
        self.assertEqual(code, 0, stderr)
        record = json.loads(stdout)
        self.assertEqual(record["version"], 1)
        item = record["result"]["instances"][0]
        self.assertEqual(item["status"]["model"]["reported"]["general"]["health"], "fault")
        self.assertFalse(item["status"]["runtime"]["hardware_communication_verified"])
        self.assertEqual(item["status"]["faults"]["rules"][0]["remaining"], 1)
        code, stdout, stderr = await self.run_cli("status", "receiver-a")
        self.assertEqual(code, 0, stderr)
        for word in ("running", "responsive", "listening", "fault", "unprobed", "unverified"):
            self.assertIn(word, stdout)
        self.assertIn("SYNTHESIZER_FAILURE: Diagnostics confirm a synthesizer fault", stdout)

    async def test_fixed_fault_grammar_round_trip_and_runtime_failures(self):
        await self.start()
        commands = [
            ["activate", "receiver-a", "calibration_reference_unavailable"],
            ["status", "receiver-a"],
            ["clear", "receiver-a", "calibration_reference_unavailable"],
            ["schedule", "receiver-a", "drop_response", "--when", "frequency_set_verified", "--times", "1"],
            ["cancel", "receiver-a", "rule-1"],
            ["schedule", "receiver-a", "calibration_reference_unavailable", "--when", "calibrate_reference_measurement"],
            ["schedule", "receiver-a", "delay_response", "--when", "response_ready", "--delay-ms", "2500"],
        ]
        for command in commands:
            code, stdout, stderr = await self.run_cli("--json", "fault", *command)
            self.assertEqual(code, 0, (command, stderr, stdout))
            self.assertTrue(json.loads(stdout)["ok"])
        code, stdout, stderr = await self.run_cli("--json", "fault", "cancel", "receiver-a", "rule-99")
        self.assertEqual(code, 1)
        self.assertTrue(json.loads(stdout)["error"]["actions"])
        code, stdout, stderr = await self.run_cli("--json", "fault", "status", "receiver-b")
        self.assertEqual(code, 1)
        self.assertIn("simquaro start receiver-b", stderr)

    async def test_already_running_has_copyable_commands_and_does_not_adopt(self):
        owned = await self.start()
        code, stdout, stderr = await self.run_cli("start", "receiver-a")
        self.assertEqual(code, 0, stderr)
        self.assertIn("already_running", stdout)
        self.assertIn("simquaro status receiver-a", stdout)
        self.assertIsNone(owned.child.returncode)

    async def test_stop_and_restart_single_and_all(self):
        code, stdout, stderr = await self.run_cli("--json", "stop", "all")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(len(json.loads(stdout)["result"]["instances"]), 3)
        await self.start()
        process = await self.launch("--json", "restart", "receiver-a")
        self.assertTrue((await self.event(process, "restart", "receiver-a"))["ok"])
        process.send_signal(signal.SIGINT)
        stdout, stderr = await asyncio.wait_for(process.communicate(), 8)
        self.assertEqual(process.returncode, 0, stderr.decode())
        self.assertFalse((self.root / "receiver-a.json").exists())
        process = await self.launch("--json", "restart", "all")
        for name in self.inventory:
            self.assertTrue((await self.event(process, "restart", name))["ok"])
        process.send_signal(signal.SIGTERM)
        await asyncio.wait_for(process.communicate(), 8)
        self.assertEqual(process.returncode, 0)

    async def test_start_all_two_injected_instances_and_signals_in_supervision(self):
        for sig in (signal.SIGINT, signal.SIGTERM):
            with self.subTest(signal=sig):
                existing = await self.start()
                process = await self.launch("--json", "start", "all", inventory={k: self.inventory[k] for k in ("receiver-a", "receiver-b")})
                first = await self.event(process, "start", "receiver-a")
                self.assertEqual(first["result"]["outcome"], "already_running")
                await self.event(process, "start", "receiver-b")
                process.send_signal(sig)
                stdout, stderr = await asyncio.wait_for(process.communicate(), 8)
                self.assertEqual(process.returncode, 0, stderr.decode())
                records = [json.loads(line) for line in stdout.splitlines()]
                self.assertTrue(any(item["event"] == "interrupted" for item in records))
                self.assertFalse((self.root / "receiver-b.json").exists())
                self.assertIsNone(existing.child.returncode)
                self.assertTrue((await self.runtime.stop("receiver-a"))["ok"])
        code, stdout, stderr = await self.run_cli("--json", "list", module=True)
        self.assertEqual(code, 0, stderr)
        self.assertEqual([item["name"] for item in json.loads(stdout)["result"]["instances"]], ["receiver-a"])

    async def test_configuration_errors_point_to_loader_and_help_remains_usable(self):
        duplicate = {"receiver-a": self.inventory["receiver-a"],
                     "receiver-b": replace(self.inventory["receiver-b"], port=self.inventory["receiver-a"].port)}
        code, stdout, stderr = await self.run_cli("--json", "list", inventory=duplicate)
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(stdout)["error"]["code"], "CONFIGURATION_ERROR")
        self.assertIn("src/simquaro/instances.py", stderr)
        self.assertNotIn("Traceback", stderr)
        code, stdout, stderr = await self.run_cli("--help", inventory=duplicate)
        self.assertEqual(code, 0, stderr)

    async def test_stop_all_continues_after_failed_instance(self):
        await self.start("receiver-b")
        (self.root / "receiver-a.json").write_text("invalid metadata")
        (self.root / "receiver-a.json").chmod(0o600)
        code, stdout, stderr = await self.run_cli("--json", "stop", "all")
        self.assertEqual(code, 1, stderr)
        record = json.loads(stdout)
        self.assertFalse(record["ok"])
        outcomes = {item["instance"]: item for item in record["result"]["instances"]}
        self.assertFalse(outcomes["receiver-a"]["ok"])
        self.assertEqual(outcomes["receiver-b"]["outcome"], "stopped")
        self.assertTrue(outcomes["receiver-c"]["ok"])

    async def test_worker_crash_is_failure_and_is_not_restarted(self):
        process = await self.launch("--json", "start", "receiver-a")
        await self.event(process, "start", "receiver-a")
        with Directory(self.root) as directory:
            record, _ = directory.read("receiver-a")
        target = ProcessIdentity(record)
        try:
            target.send(signal.SIGKILL)
            stdout, stderr = await asyncio.wait_for(process.communicate(), 8)
        finally:
            target.close()
        self.assertEqual(process.returncode, 1, stderr.decode())
        self.assertFalse((self.root / "receiver-a.json").exists())
        records = [json.loads(line) for line in stdout.splitlines()]
        self.assertEqual(next(item for item in records if item["event"] == "exited")["result"]["returncode"], -9)

    async def test_observed_worker_crash_remains_failure_after_interrupting_other_worker(self):
        inventory = {name: self.inventory[name] for name in ("receiver-a", "receiver-b")}
        for sig in (signal.SIGINT, signal.SIGTERM):
            with self.subTest(signal=sig):
                process = await self.launch("--json", "start", "all", inventory=inventory)
                await self.event(process, "start", "receiver-a")
                await self.event(process, "start", "receiver-b")
                with Directory(self.root) as directory:
                    record, _ = directory.read("receiver-a")
                target = ProcessIdentity(record)
                try:
                    target.send(signal.SIGKILL)
                    exited = await self.event(process, "exited", "receiver-a")
                    self.assertEqual(exited["result"]["returncode"], -9)
                    self.assertIsNone(process.returncode)
                    self.assertEqual((await self.runtime.inspect(inventory["receiver-b"]))["outcome"], "running")
                    process.send_signal(sig)
                    stdout, stderr = await asyncio.wait_for(process.communicate(), 8)
                    self.assertEqual(process.returncode, 1, stderr.decode())
                    records = [json.loads(line) for line in stdout.splitlines()]
                    self.assertEqual(next(item for item in records if item["event"] == "finished")["result"]["exit_code"], 1)
                    self.assertFalse((self.root / "receiver-a.json").exists())
                    self.assertFalse((self.root / "receiver-b.json").exists())
                finally:
                    target.send(signal.SIGKILL)
                    await target.wait(3)
                    target.close()

    async def test_interrupted_cleanup_failure_is_reported_and_owned_child_is_reaped(self):
        process = await self.launch("--json", "start", "receiver-a")
        await self.event(process, "start", "receiver-a")
        with Directory(self.root) as directory:
            record, _ = directory.read("receiver-a")
        target = ProcessIdentity(record)
        try:
            # Runtime must preserve an invalid record, while the CLI still has
            # its directly retained child/pidfd and must not wait forever.
            (self.root / "receiver-a.json").write_text("invalid metadata")
            process.send_signal(signal.SIGTERM)
            try:
                await asyncio.wait_for(process.wait(), 6)
            except TimeoutError:
                self.fail("foreground cleanup did not finish after metadata validation failed")
            stdout, stderr = await asyncio.wait_for(process.communicate(), 2)
            self.assertEqual(process.returncode, 1, stderr.decode())
            records = [json.loads(line) for line in stdout.splitlines()]
            failures = [item for item in records if item["event"] == "cleanup" and not item["ok"]]
            self.assertTrue(failures, records)
            self.assertTrue(failures[0]["error"]["actions"])
            self.assertEqual(next(item for item in records if item["event"] == "finished")["result"]["exit_code"], 1)
            self.assertTrue(target.exited)
            self.assertEqual((self.root / "receiver-a.json").read_text(), "invalid metadata")
        finally:
            target.send(signal.SIGKILL)
            await target.wait(3)
            target.close()

    async def hanging(self, name="receiver-c"):
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "tests.simquaro.support.processes", "hanging", str(self.root), name,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        self.processes.append(process)
        self.assertEqual(await asyncio.wait_for(process.stdout.readline(), 3), b"ready\n")
        return process

    async def test_signals_during_partial_all_startup_keep_unrelated_instances(self):
        for sig in (signal.SIGINT, signal.SIGTERM):
            with self.subTest(signal=sig):
                existing = await self.start()
                hanging = await self.hanging()
                process = await self.launch("--json", "start", "all")
                await self.event(process, "start", "receiver-a")
                await self.event(process, "start", "receiver-b")
                async with asyncio.timeout(3):
                    while not (self.root / "receiver-c.connected").exists():
                        await asyncio.sleep(.01)
                # Hold the owned worker so both signals land during the real
                # two-second graceful-stop budget, rather than after CLI exit.
                with Directory(self.root) as directory:
                    record, _ = directory.read("receiver-b")
                target = ProcessIdentity(record)
                try:
                    target.send(signal.SIGSTOP)
                    process.send_signal(sig)
                    await asyncio.sleep(.05)
                    process.send_signal(sig)
                    stdout, stderr = await asyncio.wait_for(process.communicate(), 8)
                finally:
                    target.close()
                self.assertEqual(process.returncode, 0, stderr.decode())
                self.assertFalse((self.root / "receiver-b.json").exists())
                self.assertIsNone(existing.child.returncode)
                self.assertIsNone(hanging.returncode)
                hanging.kill()
                await hanging.wait()
                await self.runtime.stop("receiver-c")
                (self.root / "receiver-c.connected").unlink(missing_ok=True)
                await self.runtime.stop("receiver-a")

    async def test_unresponsive_status_and_partial_all_with_recovery_commands(self):
        hanging = await self.hanging()
        code, stdout, stderr = await self.run_cli("status", "all")
        self.assertEqual(code, 1)
        self.assertIn("unresponsive", stdout + stderr)
        self.assertIn("simquaro restart receiver-c", stdout + stderr)
        process = await self.launch("--json", "start", "all")
        await self.event(process, "start", "receiver-a")
        await self.event(process, "start", "receiver-b")
        failed = await self.event(process, "start", "receiver-c")
        self.assertFalse(failed["ok"])
        self.assertIsNone(process.returncode)
        self.assertTrue((await self.runtime.inspect(self.inventory["receiver-b"]))["ok"])
        process.send_signal(signal.SIGINT)
        stdout, stderr = await asyncio.wait_for(process.communicate(), 8)
        self.assertEqual(process.returncode, 1, stderr.decode())
        hanging.kill()
        await hanging.wait()

    async def test_worker_logs_only_on_stderr_and_child_exit_is_reported(self):
        process = await self.launch("--json", "start", "receiver-a")
        await self.event(process, "start", "receiver-a")
        await self.run_cli("fault", "activate", "receiver-a", "clock_untrusted")
        stopped = await self.runtime.stop("receiver-a")
        self.assertTrue(stopped["ok"])
        stdout, stderr = await asyncio.wait_for(process.communicate(), 8)
        self.assertEqual(process.returncode, 0, stderr.decode())
        events = [json.loads(line)["event"] for line in stdout.splitlines()]
        self.assertIn("exited", events)
        log_records = [json.loads(line) for line in stderr.splitlines()]
        self.assertTrue(log_records)
        self.assertTrue(all(record.get("instance") == "receiver-a" for record in log_records))


if __name__ == "__main__":
    unittest.main()
