# Persistent Configuration and Mandatory GUI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** proposed implementation plan, awaiting design/plan approval. No
application implementation has started for this component.

**Goal:** Finish the combined delivery with persistent editable configuration and
a tested local browser interface the user can use immediately.

**Architecture:** A shared JSON configuration store feeds existing validated
instances. A local FastAPI/Uvicorn server owns per-tab TCP sessions and bounded
jobs, calling the production client, shared checks, and safe Runtime/control
APIs. Packaged HTML/CSS/JavaScript uses those HTTP APIs, never CLI subprocesses.

**Tech Stack:** Python 3.12+, standard-library JSON/filesystem primitives,
optional FastAPI/Uvicorn `web` extra, plain browser assets; Python Playwright in
a development `browser-test` extra (also HTTPX for API tests). No Node build,
database, broker, or WebSocket.

**Spec:** [configuration/GUI design](../specs/2026-11-03-simquaro-configuration-gui-design.md).
Prerequisite: Tasks 1–5 of the [client/console plan](2026-11-03-protocol-client-console.md).
Read both designs and `docs/hardware_protocol.md` before execution.

## Global Constraints

- Preserve unrelated workspace files, especially `src/simquaro/.server.py.swp`.
- English docs/UI/source; Python 3.12+; base CLI/library has no third-party runtime
  dependencies. Optional web imports must not affect base commands or tests.
- Do not change hardware wire syntax or bypass TCP for operational requests.
- Reuse client/checks/raw decoder/runtime; no duplicate protocol or scenario suite.
- JSON version 1, maximum file/API body 1 MiB; explicit file never falls back to defaults.
- Atomic CAS saves, 2-second lock acquisition; no save-triggered restart.
- GUI listener `127.0.0.1:8765`, one worker, no reload/CORS/remote bind.
- 16 sessions, four per target, 120-second lease, 10-second heartbeat, 500-ms
  cached-event polling; 256 events/1 MiB per session; 16 active jobs/64 completed reports.
- Raw mode has no probes or polling; modifying tests require per-run authorization.
- Entire delivery is incomplete without real browser verification and launch instructions.
- No GitHub completion workflow until the user asks to complete the step.

## Review Focus

1. Two tabs or CLI/GUI save concurrently: a stale revision must not overwrite new settings.
2. Save succeeds but apply fails: distinguish saved/active/unknown without false rollback claims.
3. A foreign web page or physical target calls simulator controls: reject before side effects.
4. Lost browser/HTTP request during a mutation: no hidden replay/cancel or leaked TCP/tasks.
5. Installed distribution, without a checkout or Node: include assets and keep base commands importable.

---

## File and interface map

Create `src/simquaro/configuration.py` for `InventoryEntry`, `InventorySnapshot`,
`ConfigStore`, and `ConfigurationService`; split persistence internals only if
needed for readability. Keep `config.py` responsible for instance validation and
the worker's existing record, not HTTP/file lifetime. Modify `instances.py`,
`cli.py`, `registry.py`, and `runtime.py` for loading, editable allowlists, and
coordinated restart. Do not change bootstrap serialization to add target kind.

Create `src/simquaro/web/{__init__,app,sessions,jobs}.py` and
`src/simquaro/web/static/{index.html,app.js,style.css}`. `app.py` owns routing,
strict HTTP schemas/security and lifespan; sessions own TCP/evidence; jobs own
bounded long-running tasks/reports. Imports flow toward shared services, not CLI.
Modify package metadata for extras and static package data. Add focused tests
under `tests/simquaro/test_configuration.py`, `test_configuration_cli.py`,
`test_web_sessions.py`, plus `tests/web/test_api.py` and `tests/web/test_browser.py`.
Keep `tests/web` without a package marker so base unittest discovery does not
import optional web dependencies. Run that directory explicitly as a required
separate acceptance command; do not present the base suite as GUI verification.

### Task 6: Persistent inventory codec and safe saves

**Produces:** `InventoryEntry(config: InstanceConfig, kind: str)`;
`InventorySnapshot(entries, revision, path, source)`; `ConfigStore(path=None)`
with synchronous `load() -> InventorySnapshot`,
`save(entries, *, expected_revision) -> InventorySnapshot`, and `initialize()`.
Filesystem operations called from async services run off-loop, with owned work
joined on cancellation. Settings normalization uses existing registered config types.

- [ ] Add failing tests for the exact example JSON in the design, normalized
  defaults, explicit hardware identity, malformed/duplicate/unknown/nonfinite
  input, version/file-size boundaries, duplicate endpoint/name, and existing
  profile invariants. Test implicit missing defaults versus explicit missing error.
- [ ] Run `env PYTHONPATH=src python3 -m unittest tests.simquaro.test_configuration -v`;
  require new tests fail because the new API is absent.
- [ ] Implement path selection, typed snapshot/entry normalization, exact-byte
  revision comparison, sibling bounded lock, safe atomic replacement and fsync.
  Preserve previous valid data on pre-replace failure and report post-replace
  durability uncertainty honestly. Validate owner/type and reject symlink targets.
- [ ] Add concurrent stale-save, busy-lock, crash-left-lock, permission, write/fsync
  failure, and byte-boundary tests. Ensure init never overwrites existing data.
- [ ] Run focused tests plus full base discovery; require pass, inspect and commit
  scoped files only.

### Task 7: Configuration CLI, active state, and coordinated apply

**Consumes:** Task 6 snapshots and existing Runtime.
**Produces:** `ConfigurationService(store, runtime)` with async
`inspect(name) -> dict` and `apply(name, *, expected_revision) -> ApplyResult`;
`ApplyResult(outcome: dict, started: StartResult | None)` retains child ownership
for caller supervision and trusted effective evidence for reports. Existing
`Runtime.restart(config, *, scenario=...) -> StartResult` becomes one coordinated
stop/start without weakening ownership or public stop/start semantics.

- [ ] Add CLI tests for global `--config`, init/show/validate/apply, independent
  programmatic inventory, invalid-file actions, and kind restrictions. Assert
  `start all` operates only simulator entries and clearly reports skipped hardware.
- [ ] Run `env PYTHONPATH=src python3 -m unittest tests.simquaro.test_configuration_cli -v`;
  confirm new behavior fails.
- [ ] Wire inventory loading once per CLI invocation, preserving selected file
  path in suggested recovery commands. Add the registry's explicit editable
  setting allowlist; do not create a new plugin/schema framework.
- [ ] Implement saved/active comparison and explicit apply. Add tests: save alone
  does not restart; only selected instance restarts; concurrent lifecycle cannot
  interleave between stop/start; failed apply reports real state; later save stays
  pending; physical target rejects admin actions before touching Runtime.
- [ ] Add tests that new sessions/check jobs and Start/Restart pin saved settings,
  Start on an existing instance does not apply changes, and existing sessions
  retain their original endpoint/identity/revision. Do not require local Runtime
  readiness to open a console against a configured endpoint.
- [ ] Run focused tests plus existing runtime/ownership/CLI regression tests and
  full base discovery. Update CLI config documentation and commit scoped files.

### Task 8: GUI session and job services

**Consumes:** `ProtocolClient`, `TcpConnection`, shared raw functions/checks,
configuration snapshots, Runtime/control APIs.
**Produces:** `SessionManager` async `connect(target, mode)`,
`submit(session_id, payload)`, `disconnect(session_id)`, `close()`;
sync `events(session_id, after)` and `heartbeat(session_id)` on the same loop.
`JobManager.start(kind, target, coroutine) -> job_id`, `get(job_id) -> dict`,
`list(target) -> list[dict]`,
and async `close()`; cap and own every task/report.
Session/job IDs are opaque; jobs have `running|succeeded|failed|interrupted` state.

- [ ] Add tests asserting independent per-tab connections, raw connect sends zero
  bytes, one owner reader, exact byte rendering, idle lease cleanup, event gaps,
  resource caps, and managed evidence preserving exact TX/RX rather than re-encoding.
- [ ] Run `env PYTHONPATH=src python3 -m unittest tests.simquaro.test_web_sessions -v`;
  confirm missing services fail.
- [ ] Add optional `observe: Callable[[Evidence], None] | None = None` to the
  production client; record successful/error TX/RX at the actual wire boundary,
  bound records, and isolate observer exceptions. Keep one state machine and
  migrate only fixture seams that need the new event hook.
- [ ] Implement services with design caps, no automatic hardware polling, explicit
  monitoring only, dedicated test connections, and target busy checks. Cancelling
  an HTTP request/job never sends firmware cancel or replays a mutation. Preserve
  uncertainty and close/join sessions/tasks. Supervise only server-owned children.
- [ ] Test disconnect/late response, abandoned tab, unfinished job, external
  instance ownership, CLI-started instance survival, and server-owned cleanup.
  Run focused and full base tests, then commit scoped changes.

### Task 9: Local HTTP API and packaged launch command

**Produces:** `create_app(store, *, runtime_root=None, origin) -> FastAPI`;
async lifespan owns Task 8 services. CLI `gui [--port N] [--no-browser]` accepts
global config/json options. Map the design's exact `/api` routes and error codes;
use strict bounded bodies and tagged protocol numbers, not float conversion.

- [ ] Add API tests for every route's normal mapping and unknown/extra inputs,
  simulator-vs-hardware restrictions, stale revision, body and resource limits,
  hardware/local error distinction, exact number spelling, and GET producing no
  hardware traffic. Test lifecycle/test jobs execute once when their result is polled.
- [ ] Run `env PYTHONPATH=src python3 -m unittest discover -s tests/web -p test_api.py -v`;
  confirm absent API behavior fails.
- [ ] Add optional `web` dependencies and static package data. Implement routes,
  same-Origin/Host/custom-header/JSON checks, no CORS/forwarded trust, CSP and safe
  error envelope. Test foreign/null Origin, bad Host, cross-site fetch, and HTML
  firmware payloads; reject before any connection or filesystem/process mutation.
- [ ] Implement foreground single-worker loopback launch, readiness before browser
  open, nonfatal opener failure, busy-port action, missing-extra instruction, and
  clean server shutdown. `--json gui` emits lifecycle JSONL, not browser logs on stdout.
- [ ] Run API/session/base tests, test a core-only temporary venv and a web-enabled
  install, and record resolved dependency versions. Commit scoped files.

### Task 10: Browser UI and real endpoint acceptance

**Produces:** Packaged accessible four-section UI described in the design. UI
modules may be split when needed; no frontend framework or build system.

- [ ] Add browser tests for target selection, independent tabs, Start/Stop,
  frequency set/get through managed client, raw malformed input with literal
  expected bytes, phase/status display, error handling, tests/report, and saved
  versus active settings. Use Playwright's Python library under unittest rather
  than copy firmware assertions into a second suite.
- [ ] Run `env PYTHONPATH=src python3 -m unittest discover -s tests/web -p test_browser.py -v`
  in the browser-test environment; confirm absent controls fail before UI coding.
- [ ] Implement selector/header and Control/Console/Tests/Configuration sections.
  Preserve numeric text, render data with textContent, label mutation/monitoring
  traffic and confirmations, and expose copyable corrective actions. Mode switch
  disconnects first; browser polling reads only buffers except explicit monitoring.
- [ ] Verify failed load/reconnect, no automatic repeat after HTTP loss, background
  tab expiry, keyboard/narrow-window operation, and firmware HTML/ANSI text safety.
  Verify scheduled fault remains untouched until the intended explicit request.
- [ ] Run browser/API/base tests; record OS/browser versions and inspect the
  actual page manually. Required GUI acceptance cannot be silently skipped for
  absent development dependencies or a mocked-only backend. Commit scoped files.

### Task 11: Combined delivery handoff

- [ ] Consolidate README, `docs/getting_started.md`, and `docs/simquaro.md` with
  exact installed commands, venv/web-extra setup, file location, independent CLI,
  foreground shutdown, and browser walkthrough from the design. State persistence,
  uncertain outcomes, trusted-local security scope, and unsupported features.
- [ ] Install from a built distribution in a temporary venv, including static
  assets; verify core without web extras, then web enabled. Run full base and
  web/browser suites separately with explicit counts and no hidden skips:
  `env PYTHONPATH=src python3 -m unittest discover -s tests -t . -v` and
  `env PYTHONPATH=src python3 -m unittest discover -s tests/web -v`.
- [ ] Verify the documented browser walkthrough against local running simulators,
  config save/apply and cleanup. Run `git diff --check` and local documentation
  link/fence checks. Seek required approvals for socket/network/browser tooling;
  do not work around sandbox restrictions.
- [ ] Obtain independent whole-change review, fix substantive findings and rerun
  verification. Record the runnable GUI launch command and tested versions before
  claiming completion. Do not claim physical-hardware measurements were tested.
- [ ] Commit only scoped files. Perform issue/push/PR/merge/closure only on the
  user's explicit step-completion request.

## Planning self-review

Tasks 6–7 implement configuration; 8–10 implement the mandatory GUI through the
same client/admin paths; 11 verifies the combined handoff. Each review-focus risk
has an owning task and regression assertions. No runtime scaffolding, GUI mockup,
or client-only checkpoint satisfies combined-delivery completion.
