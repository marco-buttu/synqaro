# Shared Protocol Client and Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** approved by the user on 2026-11-03. Tasks 1–5 detail
the client/console component. The configuration/GUI milestones are now detailed
as Tasks 6–11 in the [companion plan](2026-11-03-simquaro-configuration-gui.md),
also approved. The delivery is not complete after Task 5.

**Goal:** Deliver a reusable managed TCP client, an unrestricted diagnostic
console, shared readable hardware checks, persistent instance configuration, and
a usable mandatory GUI without duplicate client logic.

**Architecture:** Extract the generic wire modules into `synqaro_protocol` and
promote the tested client state machine behind an explicit contract binding.
Console and managed client share byte transport, not protocol validation. The
explicit simulator registry selects client/check bindings; Devices need not use it.

**Tech Stack:** Python 3.12+, asyncio, unittest, existing setuptools distribution;
no new base runtime dependencies or required web service for CLI/library use.
GUI dependencies are isolated in the companion plan's web installation extra.

**Spec:** [Delivery-2 design](../specs/2026-11-03-protocol-client-console-design.md).
Also read `docs/hardware_protocol.md`; the plan does not change its wire contract.

## Global Constraints

- Work in `/home/marco/repos/synqaro` on the existing `codex/` branch; preserve
  unrelated `src/simquaro/.server.py.swp` and never stage it.
- English docs/source, Python 3.12+, no new base runtime dependencies.
- Generic library imports neither `simquaro` nor `tests`; no duplicate recovery
  state machine, serializer, functional suite, or required gateway server.
- Receiver limits: 4096-byte frames including LF; 2-second frame/response/connect
  deadlines; four admitted requests; 5-second failed-reconnect pause; 500-ms polls.
- Monotonic deadlines; uncertain modifications are never automatically replayed.
- Raw console adds no hidden requests, IDs, LF, recovery, or validation.
- Automated checks default read-only; modifications require `--allow-changes`.
- External editable configuration and mandatory GUI are milestones in this same
  delivery; a CLI-only result is not completion.
- Individual local commits may checkpoint implementation. Do not perform the
  GitHub completion workflow unless the user asks to complete the step.

## Review Focus

1. EOF just after a valid bootstrap/refresh: stale replies must not enable writes.
2. A mislabeled check or recovery path: read-only mode must still forbid mutations.
3. Terminal controls, malformed escapes, and oversized raw input: exact safe output,
   no accidental send, no unbounded buffers.
4. Remote closure while stdin stays open: console must terminate without a stuck
   reader or input worker.
5. Valid replies from the wrong hardware, or unavailable external endpoints:
   no self-trusted identity, local simulator dependency, or false passing report.

---

## File map

Create `src/synqaro_protocol/{__init__,codec,errors,clock,transport,client}.py`
and `profiles/{__init__,fictitious_receiver}.py`. Move, rather than copy, the
corresponding generic `simquaro` modules; migrate imports and remove obsolete
receiver error definitions after their catalog moves to the shared profile.

Create `src/simquaro/{console,checks}.py` and
`src/simquaro/models/fictitious_receiver/checks.py`. Modify `registry.py`,
`cli.py`, `session.py`, model imports, and `pyproject.toml` package discovery.
Reduce `tests/simquaro/support/client.py` to construction-only fixtures or remove it.
Keep existing independent peer fixtures and internal tests.

New focused tests: `tests/simquaro/test_protocol_transport.py`,
`test_console.py`, `test_checks.py`, and `test_test_cli.py`. Existing codec,
conformance, recovery, model-boundary, CLI, and smoke tests remain regression gates.

### Task 1: Shared codec and byte transport

**Interfaces:** Keep `Request`, `Response`, `NumericToken`, `Value`, parsing/error
semantics. Add `encode_request(request: Request) -> bytes` with quoted strings.
Provide async `TcpConnection.open(host, port, *, clock, timeout=2.0)`,
`send(data: bytes) -> None`, `receive() -> bytes`, `shutdown_write() -> None`,
and `close() -> None`; transfer chunks at most 4096 bytes. Clock deadline helper
owns and joins its operation/timer tasks on every exit.

- [ ] Add transport tests asserting `b"a\x00\xff"` is sent unchanged, a 4097-byte
  payload is allowed, fragmented/coalesced data is returned without interpretation,
  EOF is empty bytes, late connect completion is closed, and send deadlines do
  not reset per chunk. Add literal request-encoding expectations and package
  import checks independent of simulator/test modules.
- [ ] Run `env PYTHONPATH=src python3 -m unittest tests.simquaro.test_protocol_transport -v`;
  confirm failure from the absent new public API, not a broken fixture.
- [ ] Move shared codec/errors/clock, add transport and request encoding, update
  imports and package discovery (`simquaro*`, `synqaro_protocol*`). Reuse existing
  bounded deadline behavior; do not maintain parallel helper implementations.
- [ ] Run the focused command and
  `env PYTHONPATH=src python3 -m unittest discover -s tests -t . -v`; require all pass.
- [ ] Inspect the diff and commit only this task's files.

### Task 2: Production managed client and receiver profile

**Interfaces:** `ClientLimits` carries frame, incomplete-frame, response, connect,
reconnect-pause, and pending-count limits. `ClientContract` supplies those limits,
`validate_descriptor(response, expected_hardware_id) -> None`,
`validate_status(response) -> None`,
`refresh_usable(target: tuple[str, str], response: Response) -> bool`, and catalog.
`ProtocolClient(host, port, *, contract, expected_hardware_id, clock=None,
read_only=False, observe=None)` exposes the methods/properties in the design. Export the
receiver binding as `FICTITIOUS_RECEIVER_CONTRACT`.

- [ ] Add tests for explicit profile/identity binding, read-only rejection of all
  four mutation verbs including during recovery, and an importable client without
  simulator modules. Retain independent literals and existing EOF-after-bootstrap,
  EOF-after-refresh, full admission, reserved-error, late-response, cancellation,
  and uncertain-outcome regressions.
- [ ] Run `env PYTHONPATH=src python3 -m unittest tests.simquaro.test_conformance tests.simquaro.test_recovery -v`;
  demonstrate the new binding/safety assertions fail before promotion.
- [ ] Move the client state machine to production, replace direct stream usage
  with Task 1 transport, and move receiver validators/catalog to its shared
  profile. Replace test-only behavior with a construction fixture; migrate tests
  that patch transport internals without weakening their behavioral assertions.
  Preserve bounded human-readable evidence and unknown error codes.
  Include the optional exact-wire evidence observer required by the companion
  GUI plan, with observer exceptions isolated from request handling.
- [ ] Run the focused command and full discovery command; require all pass.
- [ ] Inspect the diff and commit only this task's files.

### Task 3: Manual console and CLI selection

**Interfaces:** `console.py` provides `decode_raw(text: str) -> bytes`,
`render_bytes(data: bytes) -> str`, and async
`run_console(config, *, raw: bool, structured: bool) -> int`. CLI adds
`console INSTANCE [--raw]`; global `--json` uses the existing version-1 envelope.
Dispatch this command before creating/inspecting simulator Runtime.

- [ ] Add subprocess/peer tests for normal literal ASCII+LF, all five raw escape
  forms, no LF insertion, missing-LF input, invalid escape sending nothing,
  4097-byte input allowed, 64-KiB decoded cap, safe reversible ESC/non-ASCII output,
  partial replies, EOF with stdin still open, Ctrl+C, piped stdin observation,
  one nonclosing no-data observation after two seconds, and JSON events without
  prompts. Assert the peer sees no hidden bootstrap,
  status, retries, or extra request IDs. Test endpoints without a simulator process.
- [ ] Run `env PYTHONPATH=src python3 -m unittest tests.simquaro.test_console tests.simquaro.test_cli -v`;
  confirm absent console behavior fails.
- [ ] Implement input/display/cleanup using Task 1 transport. Bound encoded input
  to four times 64 KiB plus terminator; stdin EOF half-closes and observes for
  at most two seconds. Remote EOF exits with a copyable reopen command.
- [ ] Run focused tests and full discovery; require all pass.
- [ ] Add console usage/troubleshooting to `docs/simquaro.md`, then commit the task.

### Task 4: Shared safe checks and readable test command

**Interfaces:** `Check(name: str, mutating: bool, run: Callable)` receives the
production client; its async callable returns normally on pass or raises a
bounded diagnostic failure. `CheckResult(name, state, reason, duration)` uses
`passed|failed|skipped`. Async
`run_checks(client, checks, *, allow_changes: bool, emit) -> CheckReport` runs
ordered checks, reports each result, and blocks subsequent mutations after failure.
`CheckReport` exposes results, identity evidence, and exit_code.
Extend `ModelDefinition` with defaulted `client_factory=None`, `checks=()`;
factory signature is `(host, port, settings, *, read_only=False) -> ProtocolClient`.
CLI adds `test INSTANCE [--allow-changes]`, not `test all`.

- [ ] Add runner tests for permission skips, zero checks, wrong identity,
  unsupported profile, bad preconditions, failed/uncertain operation, and a
  mislabeled mutating check stopped by the client's read-only gate. Assert
  no reset, replay, simulator start, or blind restoration. Keep the existing
  five-argument test model registration working and the console unbound to profiles.
- [ ] Run `env PYTHONPATH=src python3 -m unittest tests.simquaro.test_checks tests.simquaro.test_test_cli -v`;
  confirm absent runner/command failures.
- [ ] Implement the ten ordered receiver cases and exact values/bounds in the
  design. Reboot is last, sent once, and verified by new validated boot identity
  within a separate 30-second test budget; preserve uncertain causality. A scan
  cancellation race is not a successful cancellation assertion.
- [ ] Wire explicit registry bindings and direct endpoint CLI execution, with
  readable and version-1 JSONL reports. Exit 0 requires at least one executed
  check, all executed checks passed, and only permission-related skips;
  failure/no executable checks/runtime-precondition skips exit 1;
  malformed CLI invocation exits 2. Report intentional read-only skips distinctly.
- [ ] Reuse the nominal shared cases from `test_smoke.py` rather than copy their
  logic. Keep independent raw-wire and simulator-only fault tests. Run focused
  commands and full discovery; require all pass. Commit only task files.

### Task 5: Client/console documentation and component verification

**Interfaces:** Documentation reflects implemented CLI behavior, not future claims.

- [ ] Create `docs/getting_started.md`: Python 3.12+, venv/install, explicit
  prerequisites, foreground simulator in one terminal, console/checks in another,
  raw byte examples, safe defaults, modifications and remaining state, and
  actionable errors. Link from README and the operator guide. Include the design
  diagram and explain administration status versus TCP protocol status.
- [ ] Test documented installation in a temporary venv; verify both packages are
  installed, no runtime import needs `tests`, and entry-point help lists commands.
  Smoke-test documented workflows on Linux Mint 22.1; do not assert other OS
  releases or physical measurements were verified. Record results and limits.
- [ ] Run `env PYTHONPATH=src python3 -m unittest discover -s tests -t . -v`,
  `git diff --check`, local Markdown link/fence checks, and scoped diff inspection.
  If sandbox socket restrictions block tests, request escalation rather than
  silently substituting incomplete verification.
- [ ] Obtain one independent component code review, resolve substantive
  findings with regression tests, and rerun affected/full checks before claiming
  component completion. Record configuration and mandatory GUI as still required
  within the ongoing delivery.
- [ ] Commit scoped component changes. Do not declare the user's task complete;
  continue with the configuration and GUI milestones after their concrete design.

### Milestone 6: Persistent external instance configuration

The following milestone lists are scope summaries, not a second execution plan.
Use companion-plan Tasks 6–11 for concrete interfaces, files, and verification.

- [ ] Define and review storage format/location, supported editable fields,
  validation, atomic persistence, and saved-versus-active state before coding.
- [ ] Load instance definitions without editing installed Python modules; preserve
  the explicit model registry and existing programmatic construction interfaces.
- [ ] Expose one configuration service for CLI/GUI use. Saving alone does not
  silently change a running instance; explicit apply restarts only the affected
  simulator. Reject invalid settings without damaging the saved configuration.
- [ ] Verify persistence across restarts, validation failures, and failed apply;
  document the effective state and actionable recovery instructions.

### Milestone 7: Mandatory usable browser GUI

- [ ] Define and review the concrete local HTTP API, UI layout, session/connection
  ownership, dependency choices, local-access protections, and launch command.
  This milestone is required, not an optional follow-up.
- [ ] Implement target selection and connection feedback, guided requests,
  normal/raw diagnostic console, actual request/response display, and long-action
  state. Reuse the library; do not invoke the CLI from the server or duplicate TCP.
- [ ] Expose the same shared checks with readable progress/results and explicit
  authorization for modifying tests. Keep simulator lifecycle/fault controls
  separate from hardware protocol requests and unavailable for physical hardware.
- [ ] Add supported configuration editing through Milestone 6, showing saved and
  effective values and explicit save/apply actions. Avoid implicit polling that
  consumes scheduled fault scenarios; keep raw and managed connections separate.
- [ ] Verify browser behavior, server/API failures, disconnect/cleanup, and that
  CLI/checks still work when the GUI server is stopped.

### Milestone 8: Whole-delivery handoff and verification

- [ ] Extend the beginner guide with actual GUI installation/startup and a short
  hands-on walkthrough: select receiver, set/get frequency, run a procedure,
  submit malformed input, inject a fault, run checks, and save/apply settings.
- [ ] Verify that walkthrough in a browser on the supported local machine, plus
  the complete regression suite, package installation, and documentation checks.
  Record any unverified claims explicitly; a mockup is not a delivered GUI.
- [ ] Obtain independent whole-change review, fix substantive findings, and rerun
  verification. Declare completion only with an installed/launchable GUI and
  actionable user instructions. GitHub completion remains user-triggered.

## Planning self-review

The five review-focus risks are pinned by Tasks 2–4. The shared transport has one
owner per connection; public signatures match consuming tasks. No plan task
changes firmware grammar, requires a server for the CLI, or turns simulator-internal
tests into physical-hardware validation. Configuration and GUI are mandatory in
the same delivery, with detailed proposals now provided by the companion plan.
User review of this plan and design is required before implementation begins.
