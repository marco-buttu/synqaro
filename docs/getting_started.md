# Getting started with Simquaro

Simquaro emulates hardware for development and manual failure testing. It is not
the Synqaro control system or a Device. This guide starts the fictitious receiver;
its protocol is described in [Hardware Protocol](hardware_protocol.md).

## 1. Prepare Python

Use a Linux machine with Python 3.12 or newer, `/proc`, and Linux pidfd support.
Linux Mint is the initial test environment; support for every Ubuntu derivative
or Python version is not implied. Check your interpreter first:

```sh
python3 --version
```

If the version is older than 3.12, select an installed supported interpreter or
install it through your normal system provisioning before continuing. Do not
change your system's default Python just for Simquaro. No pyenv is required.
If virtual-environment creation reports missing venv/ensurepip, install the venv
support package matching that interpreter through your distribution's package
manager, then retry. Do not use `sudo pip`.

## 2. Install in an isolated environment

Open a terminal in the Synqaro repository directory:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[web]'
.venv/bin/simquaro --help
.venv/bin/simquaro list
```

If using another supported interpreter, replace only the first `python3` with its
path. The `.venv` directory keeps dependencies separate from your system Python.
The `-e` installation uses this checkout's source, so development changes are
available without reinstalling ordinary Python modules. Build tooling may need
an approved package download. Commands below use explicit `.venv/bin` paths so
you need not activate the environment.

The `web` extra installs the GUI server. CLI/library-only users may install `-e .`
instead; those commands require no web server or third-party runtime packages.
On Linux Mint 22.x / Ubuntu 24.04 using default Python 3.12, missing venv support
can be installed with `sudo apt install python3-venv`. This guide does not require
pyenv, system-Python replacement, or `sudo pip`.

## First use: the browser GUI

```sh
.venv/bin/simquaro gui
```

Keep the terminal open. It prints `http://127.0.0.1:8765` and opens your browser
after HTTP startup succeeds. If opening fails, copy the URL manually. For a busy
port use `.venv/bin/simquaro gui --port 8766`; `--no-browser` suppresses opening.
Launching the GUI does not start a simulator automatically.

1. Select **receiver-a**, click **Start simulator**, and wait for `start: succeeded`.
   This confirms the local process, not physical-hardware health.
2. In **Console**, keep **Guided** mode and click **Connect**. This explicitly
   reads hardware configuration/status. Each tab has its own TCP connection;
   a second tab can select another target independently.
3. In **Control**, enter a frequency and click **Set frequency** / **Read frequency**.
   Inspect the parsed response and actual TX/RX bytes. The receiver applies
   `5.1234565` GHz as `5.123457` GHz; input spelling reaches firmware unchanged.
4. Click **Run calibrate**, then **Read procedure status**. Explicitly enable
   **Monitor procedure** for status requests every 500 ms; it is off by default.
   Open **Scan settings** for a ten-point scan; choose **Procedure → scan** to
   inspect/cancel it. This console does not associate scientific data with scan points.
5. Select **Raw** in **Console mode** (disconnecting the old connection), click
   **Connect**, enter `#nonsense <id=77>\n`, then **Send literal request**.
   Expect `code=UNKNOWN_VERB`. Raw escapes are `\n`, `\r`, `\t`, `\xNN`, and `\\`;
   no LF/ID/probe/retry is added. **Literal line** instead appends LF. A two-second
   no-data notice leaves TCP open. Invalid protocol messages are allowed.
6. Open **Simulator fault injection**, click **Refresh faults**, select
   `frequency_read_failure`, then **Activate fault**. Guided frequency reads now
   report an error. **Clear fault** removes the cause. Scheduling uses explicit
   trigger events and occurrence counts; reads/monitoring may consume matching rules.
7. Click **Disconnect** before **Tests → Run checks**. Read-only is the default.
   Modifying checks require the checkbox and confirmation for each run. Close
   other GUI connections to that target and isolate external clients yourself.

The four sections share one page, with navigation links. Selecting a target or
polling event/job displays sends no hardware TCP requests. Physical-hardware
targets have no simulator process or fault controls.

### Save and apply startup configuration

**Configuration** shows its path and distinguishes editor draft, saved settings,
and trusted active startup settings. Initially the example is **Built-in defaults
— not saved**. The first explicit Save creates the file; Save alone never restarts
an instance. **Apply saved settings** explicitly restarts only this simulator,
losing current state/fault schedules. A failed apply leaves saved values saved:
inspect whether the process is stopped/running/unknown; no rollback is claimed.
A stale editor cannot overwrite another tab's save: reload first.

New connections/check jobs use saved endpoint/identity settings. Existing sessions
retain their original snapshot until explicit reconnect. If saved and active
settings differ, Apply before connecting to a changed endpoint. Active startup
frequency is not the live frequency after operational commands.

Default file: `$XDG_CONFIG_HOME/simquaro/instances.json` when that variable is an
absolute path, otherwise `~/.config/simquaro/instances.json`. To select another:

```sh
.venv/bin/simquaro --config /absolute/path/instances.json config init
.venv/bin/simquaro --config /absolute/path/instances.json gui
```

Use the same global `--config` for related CLI commands. GUI editing covers
existing targets only. Add instances of registered models in version-1 JSON,
run `config validate`, and Reload inventory; see the [operator guide](simquaro.md)
before identity/model/kind changes. The terminal-only alternative follows.

## 3. Start the receiver

In the first terminal:

```sh
.venv/bin/simquaro start receiver-a
```

Keep this terminal open. The initial example listens on `127.0.0.1:9001` with a
frequency of 5 GHz. Startup output confirms the local process/control listener;
that is not a protocol or physical-hardware health measurement.

## 4. Exchange requests manually

Open a second terminal in the same repository:

```sh
.venv/bin/simquaro console receiver-a
```

Type `#get <id=1>: name=frequency` and press Enter. You should receive an `ok`
reply with `value=5, unit=GHz`. The console appends the required newline but does
not insert IDs or repair input. Send `#status <id=2>` for general hardware state.
IDs must increase on each connection. A second console has an independent ID
sequence. Ctrl+C closes only that console, not the hardware procedure/simulator.

Use raw mode for bytes or deliberately incomplete requests:

```sh
.venv/bin/simquaro console receiver-a --raw
```

Here type `#status <id=1>\n`: the two characters `\n` represent one LF byte.
Enter does not append another LF. `text\x00\xFF\n` includes arbitrary bytes.
Invalid escape notation is rejected locally; invalid protocol messages are sent.
Missing replies, malformed replies, and closure are shown honestly; no fake error
response is invented. For exact framing/timeout rules see the operator guide.

## 5. Run readable checks

Close the console, then run:

```sh
.venv/bin/simquaro test receiver-a
```

This performs five read-only checks and clearly skips five checks requiring
changes. The report distinguishes passed, failed, and not executed. The default
run does not calibrate, change frequency, cancel an action, or reboot.

Only for an isolated target where changing state is authorized:

```sh
.venv/bin/simquaro test receiver-a --allow-changes
```

This also tests rounding, calibration, scan, cancellation, and reboot. It leaves
state changed and does not restore earlier calibration/history. A failed or
uncertain test prevents later modifying checks. Neither reads nor `accepted`
responses prove the physical output of real hardware is correct.

## 6. Stop

```sh
.venv/bin/simquaro stop receiver-a
```

Alternatively Ctrl+C in the terminal that started the simulator cleans its owned
processes. Ctrl+C in the GUI server terminal closes sessions and stops only
simulator children created by that server, leaving preexisting instances alone.
Closing a browser tab does not stop the server/simulator. Unused TCP sessions
expire after 120 seconds; closing TCP never automatically cancels firmware work.
If stop needs escalation it handles that internally; no `--force` is needed.
After a crash use normal start/status/stop/restart, not manual socket/lock deletion.

## Troubleshooting

- Connection refused: start the selected simulator, check its printed endpoint,
  and retry console/test. These commands never start a simulator implicitly.
- Already running: use it, or run `.venv/bin/simquaro restart receiver-a` if you
  explicitly need a restart. Process status and hardware-protocol health differ.
- No response: inspect the console's byte evidence and the framing rules; a
  timeout does not prove a modifying command was not executed. Do not blindly
  repeat it.
- For injected faults, detailed diagnostics, and JSON output, read the
  [operator guide](simquaro.md).
- Missing GUI packages: run `.venv/bin/python -m pip install -e '.[web]'` in the
  repository, not a different Python environment.
- Expired session: explicitly reconnect; the UI never resends a lost command.
- Lost HTTP response during a change: inspect **Recent jobs** and explicitly query
  hardware state; do not repeat blindly. Recent jobs are not a permanent log.
- Invalid/missing explicit configuration: correct the printed path/file and run
  `config validate` / `config init`; existing invalid files never fall back to defaults.

Persistent startup settings can now be inspected with
`.venv/bin/simquaro config show` and explicitly initialized with
`.venv/bin/simquaro config init`. Saving settings alone does not change a running
instance; `.venv/bin/simquaro config apply receiver-a` applies them through a
foreground restart. See the operator guide before editing/applying configuration.

## Scope and developer verification

This is a trusted single-user workbench bound only to `127.0.0.1`, not an
authenticated remote service. Configuration persists, but historical software/
configuration snapshots and a permanent audit store are not implemented. Keep
configuration under your own change control when historical reconstruction matters.
Bulk scientific transfer and exact scan-frequency/data association remain open
protocol topics. Simulator tests do not establish physical-hardware correctness.

Run base and required web/browser suites separately:

```sh
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -t . -v
.venv/bin/python -m pip install -e '.[web,browser-test]'
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests/web -v
```

Browser tests use installed Google Chrome with isolated temporary contexts and
normal Chromium sandbox. Playwright is developer tooling, not needed for manual
GUI use. Tested versions/results are recorded in the operator guide.
