# Simquaro operator guide

Simquaro runs a deterministic fictitious receiver for protocol and failure tests.
It is independent of the Synqaro Device runtime. The initial configured instance
is `receiver-a`, listening at `127.0.0.1:9001`, with a verified frequency of 5 GHz,
invalid calibration, fresh firmware boot identity, unknown prior procedure history,
and no injected faults. Its hardware commands follow the
[Hardware Protocol](hardware_protocol.md).

## Install and run

Use Linux with `/proc`, pidfds, a supported local filesystem, and Python 3.12 or
newer. Python 3.12.3 is the tested interpreter; Python 3.13-specific transport
cleanup has been checked in source, not executed in that interpreter.
There are no runtime dependencies. Setuptools is ordinary build tooling.

From the repository root, create an isolated environment and install:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/simquaro --help
```

If the host lacks venv/ensurepip, install its Python venv support through your
normal environment provisioning. Build tooling may need an approved package
download. Do not install into the system interpreter. For development, use
`.venv/bin/python -m pip install -e .` so source inventory edits apply to the
next command. A normal installation copies the package; after source edits,
reinstall it into the same environment before restarting an instance.

Source execution needs no install or pip:

```sh
PYTHONPATH=src python3 -m simquaro --help
PYTHONPATH=src python3 -m simquaro list
```

`python -m simquaro` and the installed `simquaro` executable use the same entry
point. Examples below assume the environment's `bin` directory is on `PATH`.
Use the same environment and user in both terminals.

## Inventory and startup configuration

The explicit Python loader is
[`src/simquaro/instances.py`](../src/simquaro/instances.py), function
`load_inventory()`. It returns validated frozen `InstanceConfig` and
`ReceiverConfig` objects defined in
[`src/simquaro/config.py`](../src/simquaro/config.py).
Edit that mapping to add named instances or change their endpoint, hardware
identity, supported firmware profile, or initial settings. For an installed
copy, locate the actual loader with:

```sh
python -c 'import simquaro.instances; print(simquaro.instances.__file__)'
```

Names are flat: `[a-z][a-z0-9_-]{0,47}`. `all` is reserved. Each inventory entry
needs a unique host/port and a fixed port from 1 through 65535. Adding another
instance reuses the implemented `fictitious_receiver` model with independent
state. Changing a firmware label does not implement new firmware behavior.
`all` selects exactly this validated inventory, never every installed module.

Configuration describes startup. Current frequency, physical state, procedure
results, active faults, and remaining rule counters are separate live state.
Changing startup configuration requires restarting only the affected instance;
connections and operations on that instance can be interrupted. Endpoint changes
also require matching client configuration. An already running instance is
inspected, never silently reconfigured. `status` JSON includes both `configured`
(current loader values) and `startup_config` (the running process's values).
There is no external file loader or general hot reload in this version.

Programmatic tests can construct configurations and typed
`Scenario(initial_faults=(FaultEffect(...),), rules=(FaultRule(...),))` directly,
then pass the scenario to `Runtime.start(config, scenario=scenario)`; files are
not required. The CLI inventory starts with an empty scenario. Tests may also
inject inventories and private roots into `simquaro.cli.main` without changing
the global loader.

## Foreground operation

```sh
simquaro list
simquaro start receiver-a
```

Keep that terminal open. The launcher owns one child process per newly started
instance and waits for it, with instance/run/boot-tagged JSON evidence on stderr.
Ctrl+C or SIGTERM stops only children that this invocation created, including
interruption during partial startup. Repeated signals do not cancel its cleanup.
There is no persistent manager or automatic restart after a worker crash.
Starting an already running instance reports `already_running` and exits if it
owns no new children.

In another terminal:

```sh
simquaro status receiver-a
simquaro status all
simquaro stop receiver-a
simquaro restart receiver-a
```

`restart` also runs in the foreground. It starts only after the old process is
confirmed stopped. `start all` and `restart all` report every attempted instance;
successful children keep running after another instance fails. `stop all`
continues through per-instance failures. A partial failure yields exit code 1,
including when the foreground command later receives Ctrl+C. Already stopped
is success. Shutdown allows two seconds for SIGTERM, then sends SIGKILL to the
verified process and waits up to two more seconds. No `--force` is needed.

Status distinguishes process presence, control responsiveness, hardware listener,
firmware health/activity, and external injections. Hardware communication remains
`unprobed`/`unverified`: a working local control channel does not verify the TCP
hardware protocol. Status does not consume scheduled hardware response faults.
An intentional simulated `health=fault` does not make a successful query fail.
Human status expands known fault codes using the diagnostic error catalog;
JSON retains the original structured model state.

## Fault injection in two terminals

Terminal 1:

```sh
simquaro start receiver-a
```

Terminal 2:

```sh
simquaro fault list receiver-a
simquaro fault activate receiver-a calibration_reference_unavailable
simquaro fault status receiver-a
simquaro status receiver-a
simquaro fault clear receiver-a calibration_reference_unavailable
simquaro fault schedule receiver-a drop_response --when frequency_set_verified --times 1
simquaro fault cancel receiver-a rule-1
simquaro fault schedule receiver-a calibration_reference_unavailable --when calibrate_reference_measurement --times 1
```

Use the actual `rule_id` returned by schedule; `rule-1` above assumes a fresh
process and that the rule has not yet been consumed. Use `fault status` to find
remaining IDs. An independently connected hardware client must execute the
corresponding frequency setting or calibration for a scheduled hook to occur.
There is no free-text hardware command interpreter in the operator CLI.
Fault commands target one configured instance, never `all`.

`fault list` is offline and describes effects, allowed events, parameter bounds,
persistence, compatibility, and copyable examples. Persistent causes are
`calibration_reference_unavailable`, `frequency_lock_failure`,
`synthesizer_failure`, `frequency_read_failure`, `clock_untrusted`,
`procedure_stall`, and `stop_unconfirmed`. Wire effects are `drop_response`,
`delay_response`, `omit_lf`, `malformed_response`, `reorder_responses`, and
`disconnect`. Wire effects require scheduling, not immediate activation.

Allowed hooks are `response_ready`, `frequency_set_verified`, and
`calibrate_reference_measurement`. All faults can use the first two; the
calibration-phase hook admits only persistent causes. It fires once on actual
phase entry, not on polling. Scheduling is prospective and instance-wide across
clients; `--times N` consumes the next N matching events, default 1, maximum
4294967295. At most 64 unconsumed rules exist per instance.

Only `delay_response` accepts a parameter:

```sh
simquaro fault schedule receiver-a delay_response --when response_ready --times 1 --delay-ms 2500
```

`--delay-ms` is an integer from 1 through 60000; all other effects accept no
parameters. A dropped reply after a verified setting does not undo that setting.
Compatible wire pairs are delay/omit-LF, delay/malformed, and omit-LF/malformed;
their triple is allowed. Duplicate wire effects conflict. Drop, disconnect, and
reorder each conflict with every other wire effect. Compatibility is conservative
across different reply hooks because those hooks may affect the same reply.
Cancel the conflicting pending rule before scheduling another one.

`fault cancel` removes only remaining occurrences. An already-triggered
persistent cause stays active until `fault clear`. Clearing the cause re-evaluates
diagnostics but does not erase incidents, fabricate a restored frequency lock,
or rewrite a completed/failed procedure. TCP reconnect and simulated firmware
reboot preserve external conditions and rule counters. Process restart discards
ad-hoc fault changes and reapplies only its initial scenario. Firmware reboot
changes `boot_id` and loses unpromised procedure history; it is not a process
restart.

## Failure recovery

For a live but unresponsive process:

```sh
simquaro status receiver-a
simquaro restart receiver-a
```

Stop uses verified process identity even when local control cannot respond.
For an occupied hardware port, correct the endpoint in the loader (and clients)
or stop the process that you know owns that endpoint, then restart the affected
instance. A hardware protocol timeout after a modification means its outcome
is uncertain; inspect actual state and procedure status before deciding the next
operation. Never automatically replay a modification.

Runtime paths are derived from the instance name, under validated
`$XDG_RUNTIME_DIR/simquaro` when available, otherwise `/tmp/simquaro-<uid>`.
The directory is private, mode 0700, on a supported local filesystem. Keep both
terminals in the same runtime environment. Commands need no `.sock` argument.
Positively identified crash residues are recovered by a normal start. Permission,
identity, foreign-owner, symlink, and ambiguous-state errors are explicit: repair
the reported directory/environment ownership with its administrator, or select a
new valid private XDG runtime directory and use it consistently. A new directory
does not stop an old process; resolve the original owner and endpoint first.
Do not delete sockets/lock files or signal an unverified PID to force recovery.
If foreground cleanup cannot validate metadata, the launcher can still terminate
its directly retained original child by pidfd. It preserves questionable paths,
reports the cleanup error, and exits with code 1 even if that child then stops.
It never substitutes a same-named replacement process as the signal target.

## Agent output and limits

```sh
simquaro --json list
simquaro --json status all
simquaro --json fault status receiver-a
simquaro --json start all
```

The global `--json` goes before the command. Queries emit one version-1 JSON
record with `event`, `ok`, optional `instance`, and `result` or `error`. `list`
and `status all`/`stop all` put per-instance results in `result.instances`;
an all-result `ok=false` preserves all successes and failures in that array.
Single-instance errors retain `code`, `message`, and copyable command argument
lists in `actions`. Runtime failures also retain their complete per-instance
context under `error.outcome`. Configuration errors include explicit loader
repair instructions. Ordinary diagnostics and worker JSON logs go to stderr.
Help remains ordinary usage text, including when `--json` is supplied.

Foreground start/restart emit JSON Lines: one `start`/`restart` result per
attempted instance, `exited` with a child `returncode`, `interrupted` with the
signal name when interrupted, and `finished` with the command `exit_code`.
Failed shutdown verification additionally emits `cleanup` error records.
Already running instances have no owned child and therefore no `exited` event.
Exit codes are 0 for success, 1 for runtime/configuration/partial failure, and 2
for invalid CLI usage. Hardware health is independent of query success.

This slice emulates one fictitious receiver profile and ASCII/TCP protocol.
It is not a real firmware binary, scientific transfer system, coupled system
simulation, remote multi-user administrator, Device runtime/cache, database,
or NATS service. Runtime ownership depends deliberately on Linux pidfds and
local filesystem semantics. Hardware frames include LF within 4096 bytes;
incomplete requests expire after 2000 ms from first byte, with four pending
requests per connection and at most 16 hardware clients. Local control allows
four clients, 8 KiB requests, 64 KiB responses, and a 2000 ms exchange deadline.
