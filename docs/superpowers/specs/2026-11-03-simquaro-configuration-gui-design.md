# Persistent configuration and mandatory local GUI

**Status:** proposed technical design, awaiting user approval; no product code
has been implemented by writing this document. Completes the previously outlined
configuration/GUI milestones of the combined delivery.

**Related design:** [shared client and console](2026-11-03-protocol-client-console-design.md).
The hardware contract remains `docs/hardware_protocol.md`; this tool is not a
Synqaro Device runtime or a redesign of `docs/device.md`.

## Outcome and engineering choices

The user must be able to install Simquaro, launch its GUI, start the example
receiver, exchange requests, inject failures, and inspect results without editing
installed Python code. CLI and automatic checks remain usable independently.
Configuration, CLI, GUI, and tests reuse the same validation and communication
logic. The delivery is incomplete without verified browser use.

Choose JSON rather than YAML (no parser dependency) or Python configuration
(not appropriate for an operator editor). Choose an optional FastAPI/Uvicorn web
extra, consistent with the project's HTTP direction, rather than hand-writing an
HTTP server. Use packaged HTML/CSS/JavaScript with no frontend framework, Node
build, CDN, database, message broker, or WebSocket dependency. HTTP event polling
reads local buffers, not hardware. These are engineering proposals, not choices
previously made by the user.

The optional `web` extra adds FastAPI and Uvicorn; the base library/CLI retains no
third-party runtime dependencies. Dependency ranges must be selected and verified
in the implementation environment, with installed versions recorded at handoff.
Browser automation uses the Python Playwright library as a development extra,
not a dependency for users opening the GUI in their own browser.

## Persistent inventory

Use one versioned JSON file. Global `simquaro --config PATH ...` selects a file;
otherwise use `$XDG_CONFIG_HOME/simquaro/instances.json` when that environment
variable is an absolute path, or `~/.config/simquaro/instances.json`. Print the
selected path in GUI configuration and `config show`. Do not change runtime
socket paths or use the configuration directory as a runtime directory.

```json
{
  "version": 1,
  "instances": [
    {
      "name": "receiver-a",
      "kind": "simulator",
      "model": "fictitious_receiver",
      "host": "127.0.0.1",
      "port": 9001,
      "receiver": {
        "hardware_id": "example-receiver-01",
        "initial_frequency": 5
      }
    }
  ]
}
```

`kind` is `simulator` (default) or `hardware`. Both select the explicit registered
model/profile, not an import path. Hardware entries are connection targets only:
never start/stop/restart them, apply simulator settings, or inject simulator
faults. They must explicitly provide their expected `hardware_id`; do not infer
it from the peer. The same receiver settings type may supply defaults, but its
simulation timing/initial-state fields have no hardware effect.

An `InventoryEntry(config: InstanceConfig, kind: str)` wraps existing instance
configuration; do not change the worker bootstrap's current serialized record.
An immutable `InventorySnapshot` contains entries, revision, path, and source.
Reuse the selected model's settings constructor and `validate_inventory` after
normalizing optional settings from defaults. Reject unknown fields, duplicate
JSON keys/names/endpoints, invalid profile values, NaN/infinity, unsupported
versions, and files larger than 1 MiB. No arbitrary code, includes, overlays, or
automatic discovery. The actual frequency/procedure limits remain profile-fixed.

If the implicit default path does not exist, use the existing built-in example
in memory and label it "Built-in defaults — not saved". Do not write merely to
list instances or launch the GUI. The first explicit save or `config init` writes
the file. A missing explicit `--config` path or an existing invalid file is an
actionable error, never a reason to replace settings with defaults. `config init`
may explicitly create that missing path; it never overwrites an existing file.
Programmatic `main(inventory=...)` and direct constructors remain test seams;
reject combining an injected inventory with an explicit configuration path.

New CLI commands are `config init`, `config show [INSTANCE]`, `config validate`,
and `config apply INSTANCE`, with existing global `--json`/`--config` options.
`init` creates defaults or reports already initialized after validating the file.
Users may edit JSON while no editor save is in progress; this is not a general
multi-writer configuration system. New instances of registered models may be
added in the file. GUI creation/deletion/rename/model/kind changes are out of scope;
the GUI edits existing targets and instructs users to stop affected instances
before making identity/model/kind changes manually.

## Save, active state, and apply

`ConfigStore.load() -> InventorySnapshot` and
`save(entries, *, expected_revision) -> InventorySnapshot` are the sole file
codec/persistence path. A SHA-256 revision identifies exact saved bytes; built-in
defaults use a distinct revision namespace. A stale save returns
`CONFIG_CONFLICT`: reload before saving, never silently overwrite another tab.
Use a bounded advisory sibling lock (2-second acquisition), a same-directory
temporary file, file flush/fsync, atomic replace, and directory fsync. New files
are mode 0600 and newly created application directories mode 0700. Reject
symlink/nonregular or foreign-owned configuration/lock files; do not delete lock
files, and never ask users to clean stale locks after a crash. A failed save must
leave the previous valid file intact. Offload bounded filesystem work from the
event loop and join owned writes on cancellation; report uncertain durability if
the final durability confirmation fails after replacement.

GUI editing supports host/port and an explicit model-owned allowlist of settings.
For the receiver: hardware identity, firmware version/build, initial frequency,
tuning/stop durations, and three calibration phase durations. Profile invariants
are shown read-only. For hardware targets only endpoint and expected identity are
editable here; no firmware version is written into physical hardware by this tool.
Reuse dataclass validation, including cross-field timing constraints. Add no
general schema engine. Parse frequency input without binary rounding before
existing startup validation; reject off-grid values instead of silently changing
saved settings. Save a normalized complete record. The form submits numeric
setting text with the tagged-number notation used by the HTTP API below. Validate
the exact decimal spelling before converting to the existing settings type;
serialize ordinary JSON numbers only after confirming that normalization
preserves the accepted value. File parsing likewise must not silently round an
off-grid startup value through an intermediate binary float.

Show three distinct states: editor draft, saved startup configuration, and active
startup configuration from trusted Runtime metadata. "Active" does not mean live
frequency: procedure/set requests change runtime state without editing startup
settings. If metadata/control verification fails, show active state as unknown.
No difference means "In sync" only when the trusted process record agrees.

All new connections and check jobs pin the latest saved snapshot, or the labeled
built-in snapshot when unsaved. This applies equally to GUI and CLI and does not
require a local simulator process or administration probe. Existing sessions keep
their original endpoint/profile/expected identity; saving does not silently
retarget them. Show their pinned revision and a newer-saved-settings indicator.
If active simulator settings are known to differ, warn that Connect/Tests use the
saved endpoint, which may not be serving yet, and suggest Apply or edit/reload.
Never claim that a reachable saved endpoint is the current local process.

Start and Restart also pin saved settings: Start on an already-running instance
reports that instance without applying differences; Restart explicitly stops and
starts using saved settings, equivalent to applying them. Stop targets only the
verified named local simulator process, not the configured TCP endpoint.

Save does not affect a running process. "Apply saved settings" is a separate
explicit action, warns about state loss, and restarts only that simulator if it
is running; for a stopped simulator it starts with saved settings. Pin the saved
revision and return the requested configuration plus actual startup evidence.
If a later save happens during apply, show newer saved values as still pending.
Serialize lifecycle operations through the existing per-instance coordination;
make restart one coordinated stop/start operation rather than exposing a race
between those steps. No unverified PID termination or global system restart.

Do not automatically apply partial changes or roll back after restart failure.
Saved settings stay saved; report whether the instance is stopped, running with
the previous settings, or unknown, and provide retry/edit instructions. Existing
fault schedules/state are not promised to survive a configuration restart.
Disconnect GUI sessions for the affected target before lifecycle/apply operations;
reject them while a GUI check job is running on that target. Other external
clients may disconnect and are not silently retargeted to a new endpoint.
The apply result retains the `StartResult` when a child was created, so its caller
can supervise/clean that child rather than lose process ownership in a JSON
report. CLI apply follows the existing foreground start/restart policy; GUI apply
is a tracked server-owned job.

## Launch, browser layout, and operator workflow

```text
python -m pip install -e '.[web]'   # from the repository, inside its venv
simquaro gui
simquaro --config /absolute/path/instances.json gui --port 8766 --no-browser
```

`gui` runs in the foreground on `127.0.0.1:8765`, one worker, no reload. It prints
the URL and opens the default browser only after HTTP startup succeeds;
`--no-browser` suppresses that attempt. Browser-launch failure is nonfatal and
leaves a copyable URL. A busy port is an error with a working `--port` example;
do not kill the listener or assume it is Simquaro. Exposing a network listen
address is out of scope. Missing web dependencies produce the exact install
instruction, while base CLI/library imports continue to work.

One page has an instance selector and target kind/model/endpoint header, with
four sections: **Control**, **Console**, **Tests**, **Configuration**. It supports
keyboard operation, labeled inputs, visible focus, textual status (not color
alone), and a readable narrow-window layout. A second browser tab may connect to
another target, or independently to the same one. Do not share TCP sessions
between tabs. UI text is English, consistent with the repository.

Control provides explicit simulator Start/Stop/Restart and fault controls using
the finite existing catalog, plus guided receiver frequency/set/get, general or
procedure status, calibrate, scan, cancel, and reboot. Hardware commands always
use TCP through the library, not model calls. Reboot/state-changing actions are
labeled; reboot and restart require confirmation. Stop retains existing automatic
escalation policy, not a new `--force` prompt. Physical-hardware targets hide and
server-side reject simulator administration actions.

Console selects guided, literal line, or raw mode. Guided mode uses a managed
client; line/raw modes use only the shared byte transport and existing escape
decoder/renderer. Switching mode closes the old connection first. A Connect
button explains that managed mode sends configuration/status probes; raw/line
connect sends no bytes. Connect, refresh, submit, monitor, and disconnect are
explicit. Reconnecting never resubmits a mutation. Show actual TX/RX evidence,
local times with provenance, errors, EOF, uncertainty, and dropped-history notices.
Render firmware strings with `textContent`, never HTML.

No automatic hardware polling occurs when opening/selecting a target. Optional
"Monitor procedure" is an explicit action using 500-ms status polling while
enabled; label it as traffic that may consume scheduled faults. Raw/line mode has
no hardware polling, probes, validation, hidden ID assignment, or recovery. Its
two-second no-data notice is only a local observation and leaves TCP open.

Tests runs the shared suite on a dedicated managed connection, read-only by
default. A modifying-test checkbox and confirmation authorize changes for that
run only. Require other GUI connections for that target to be closed first;
external-client isolation is the operator's responsibility. Stream case names,
passed/failed/skipped results, and uncertainty. HTTP polling never reruns a job.
Do not offer "cancel hardware" by cancelling an HTTP job. Configuration shows
draft/saved/active values, validation errors, the path, and separate Save/Apply.

## Server ownership, events, and limits

Use FastAPI lifespan to own the session/job managers and Runtime supervision.
The server calls library functions and existing administration APIs, not shell
commands. It starts no simulators automatically. Stop on server shutdown only
children created by that server, with matching run tokens; leave already-running
instances alone. Closing a browser tab is not server shutdown. A server crash may
leave simulators running; existing safe runtime discovery/stop/restart handles
that and the guide must explain it. Never weaken current ownership checks.

At most 16 GUI TCP sessions, at most four per target; a mode switch creates at
most one session for its page. Managed and raw sessions have one reader each.
Session IDs are random opaque values, not hardware request IDs. GET event polling
every 500 ms reads bounded server memory only. An inactive session expires after
120 seconds without browser heartbeat, closing its connection but not cancelling
firmware work. The UI sends a heartbeat every 10 seconds while open; browser
background suspension may expire it and requires explicit reconnect. Disconnect
uses best effort on page close; the server lease is authoritative.

Keep 256 events and at most 1 MiB per session, evicting oldest events. Events have
increasing cursor, kind, escaped data/structured result, and local receipt time;
return oldest/newest cursors and an explicit gap marker when the caller fell
behind. Reuse the client's evidence observer for exact successful/error TX/RX,
not reconstructed wire strings. Observer failures must not break client handling.
Raw chunks are at most 4096 bytes and submissions at most 64 KiB decoded.
Keep at most 16 active jobs and the last 64 completed reports, bounded to 1 MiB
per report. Reject excess work instead of unbounded queues. Long jobs expose
running/result/error state and run to their own documented check/lifecycle bounds;
they do not depend on a single HTTP request staying open. Server shutdown joins
owned tasks and marks interrupted work uncertain; no implicit firmware cancel.

## HTTP interface and local access

Use `/api` routes and the existing version-1 success/error style. Hardware errors
remain parsed hardware responses; HTTP errors describe local API failures only.
All routes reject unknown targets, arbitrary host/path overrides, unknown fields,
nonfinite JSON, and request bodies over 1 MiB. Numeric protocol values cross JSON
as `{"number":"5.1234565"}`; strings/bools/lists keep their types. Plain JSON
numbers are not accepted as protocol numeric values. This preserves lexical
precision without confusing numbers with quoted protocol strings.

| Route | Purpose |
| --- | --- |
| `GET /api/targets` | Inventory and model/kind metadata, no hardware requests. |
| `GET /api/config` | Saved normalized inventory, revision, source, and path. |
| `PUT /api/config/{name}` | Full editable target record with expected global revision; save only. |
| `GET /api/targets/{name}/admin` | Verified runtime/fault/active-config information; simulator only, no hardware TCP. |
| `POST /api/targets/{name}/lifecycle` | Start/stop/restart/apply as a tracked job. |
| `GET /api/targets/{name}/faults` | Offline catalog plus explicit local-control query for active conditions. |
| `POST /api/targets/{name}/faults` | Existing activate/clear/schedule/cancel grammar only. |
| `POST /api/sessions` | Connect target with `managed`, `line`, or `raw` mode. |
| `POST /api/sessions/{id}/requests` | One managed verb/fields request or one line/raw text submission. |
| `GET /api/sessions/{id}/events?after=N` | Read event buffer, never probe hardware. |
| `POST /api/sessions/{id}/heartbeat` | Renew local session lease only. |
| `DELETE /api/sessions/{id}` | Close TCP; never cancel hardware automatically. |
| `POST /api/targets/{name}/tests` | Run shared checks, with explicit per-run `allow_changes`. |
| `GET /api/jobs/{id}` | Read current job state/report, no repeat execution. |
| `GET /api/targets/{name}/jobs` | Read bounded recent jobs, including a job whose submit response was lost. |

Session connect may take its bounded TCP/bootstrap time; other long actions return
202 plus job ID. Managed submission returns a parsed response or local failure;
disconnect after transmission must retain uncertain outcome evidence. Use 400 for
invalid notation/API arguments, 403 for forbidden origin/kind/action, 404 for
unknown resources, 409 for stale revisions/busy state, 413 for body limits, 429
for resource caps, and 503 for unavailable local services. Framework validation
errors are normalized into this envelope, never unbounded stack traces.
If an HTTP submit result is lost, show unknown submission outcome, do not retry,
and let the operator inspect retained jobs or explicitly query hardware state.
Recent-job listing is observation, not an idempotency or causality guarantee.

This is a trusted single-user workstation tool, not a remote/multi-user service.
Bind loopback only; allow the exact configured Host and same Origin, disable CORS
and forwarded-header trust, and require `application/json` plus custom
`X-Simquaro-Client: 1` for state-changing routes (including empty-body deletes).
Reject foreign/null Origin and cross-site fetch metadata before any side effect;
Origin may be absent for nonbrowser clients with the explicit custom header.
Serve bundled scripts/styles with a restrictive self-only CSP, no inline scripts,
no framing, and no caching of API results. Do not treat loopback as authentication
against other malicious local users/processes; remote access requires a separate
security design. Runtime/config filesystem protections remain in force.

## Verification and handoff

Add storage/config tests, concurrent-save/apply and process-ownership tests,
HTTP/API security/resource/session cleanup tests, and Playwright browser tests
against real local endpoints. Reuse functional checks; browser tests verify UI
wiring, not a second full firmware scenario suite. Malformed raw-input tests
retain independent literal byte expectations. Run base tests without web extras
and web/browser tests with their documented extras; missing dependencies must
not silently count the required GUI acceptance as passed.

Verify the actual documented sequence: install, `simquaro gui`, select/start the
receiver, set/get frequency, run and inspect calibrate/scan, send malformed/raw
input, activate/schedule a fault, run safe checks, save/apply configuration, open
another tab, and clean up. Record the tested OS/browser/package versions. The
handoff includes one copyable launch command and explicit remaining limitations.
No claim of completed implementation or physical-hardware validation follows
from this design document or browser use of the simulator.

## Primary implementation references

An independent builder review identified the saved-versus-active connection
selection ambiguity. The explicit snapshot binding and Start/Restart rules above
resolve it without adding a connection-selection mode or changing the protocol.
This is design review, not evidence of working implementation.

- [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/) for owned startup/shutdown resources.
- [FastAPI static files](https://fastapi.tiangolo.com/tutorial/static-files/) for packaged browser assets.
- [FastAPI origin model](https://fastapi.tiangolo.com/tutorial/cors/) for same-origin boundaries; CORS itself is not authentication.
- [Uvicorn deployment](https://uvicorn.dev/deployment/) for programmatic single-process serving.
- [Playwright Python library](https://playwright.dev/python/docs/library) for browser verification without a Node application build.
