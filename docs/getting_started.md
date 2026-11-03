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
.venv/bin/python -m pip install -e .
.venv/bin/simquaro --help
.venv/bin/simquaro list
```

If using another supported interpreter, replace only the first `python3` with its
path. The `.venv` directory keeps dependencies separate from your system Python.
The `-e` installation uses this checkout's source, so development changes are
available without reinstalling ordinary Python modules. Build tooling may need
an approved package download. Commands below use explicit `.venv/bin` paths so
you need not activate the environment.

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
processes. If stop needs escalation, it handles that internally; no `--force` is
needed. After a crash, retry normal start/status/restart; never delete runtime
socket/lock files manually.

## Troubleshooting and next interfaces

- Connection refused: start the selected simulator, check its printed endpoint,
  and retry console/test. These commands never start a simulator implicitly.
- Already running: use it, or run `.venv/bin/simquaro restart receiver-a` if you
  explicitly need a restart. Process status and hardware-protocol health differ.
- No response: inspect the console's byte evidence and the framing rules; a
  timeout does not prove a modifying command was not executed. Do not blindly
  repeat it.
- For injected faults, detailed diagnostics, and JSON output, read the
  [operator guide](simquaro.md).

The combined delivery also requires persistent external configuration and a
browser GUI. They are not yet available at this implementation checkpoint; this
guide will be extended with their actual launch/use commands before final handoff.
