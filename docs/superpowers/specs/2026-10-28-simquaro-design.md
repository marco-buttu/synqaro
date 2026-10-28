# Simquaro: First Receiver Simulator Design

**Status:** approved direction for the first implementation, including the configuration boundary confirmed on 2026-10-28. Technical choices remain explicitly identified. Execution of the related plan is authorized with implementer subagents and independent task reviews; this design itself is not executable conformance evidence.

**Authority:** [Hardware Protocol](../../hardware_protocol.md) defines the wire contract and fictitious-receiver behavior. [Device Architecture](../../device.md#10-configuration-and-simulator-parity) defines simulator parity. This design must not silently change either document. The choices marked **implementation choice** below are proposals by the implementer, not earlier user decisions.

## 1. Intent and scope

Build a standalone replacement for the fictitious receiver's hardware and firmware, usable before Synqaro Devices exist. Exercise normal operation, unreliable communication, incorrect firmware behavior, and physical-model failures through repeatable tests. The same future Device must communicate with simulator or real hardware through the actual hardware protocol, not a simulation-only Device API.

Approved direction: keep the package in the Synqaro repository; use Python and `asyncio`; expose the `simquaro` CLI; use flat instance names such as `receiver-a`; support individual and `all` lifecycle commands; supply scenarios programmatically without requiring files; keep fault control outside the hardware connection. Stop must escalate automatically when necessary, and users must never need to remove sockets/locks or find PIDs. Errors must explain a concrete corrective action.

The first inventory contains only `receiver-a`. `all` means the instances explicitly declared in that inventory, not every installed simulator implementation. Multiple real firmware families, a plugin framework, hierarchical namespaces, a deployment daemon, scientific acquisition, bulk transfer, and physical coupling between simulated apparatus are not initial deliverables. Device configuration/history infrastructure, Device caching, and a production communication library remain separate work.

## 2. Approaches and rationale

- **Reuse DISCOS simulators as the runtime:** useful separation of networking and models, but would require replacing shared parser state, in-band administrative commands, lifecycle discovery, and timing/concurrency behavior. Do not adopt that runtime for this prototype.
- **Build a general simulator framework first:** potentially reusable, but introduces interfaces and extension rules before a second simulator demonstrates their need. Rejected for the first slice.
- **Selected direction: one standalone receiver with small, separable modules.** Reuse ordinary functions and composition where useful; extract a common runtime only when a second implementation justifies it. The tradeoff is a possible later refactoring rather than speculative infrastructure now.

## 3. Code location and responsibility boundaries

```text
src/simquaro/
    cli.py                 CLI parsing and human/structured output
    config.py              validated immutable instance/model configuration
    instances.py           initial Python inventory and its loader
    runtime.py             subprocess lifecycle and instance ownership
    control.py             local test-control client/server
    protocol.py            ASCII framing, parsing, encoding, symbolic errors
    session.py             one hardware TCP connection and its pending replies
    faults.py              validated fault catalog, triggers, occurrence rules
    receivers/fictitious.py receiver state, diagnostics, calibration and scan
tests/simquaro/             unit, protocol, subprocess, and fault tests
pyproject.toml             package metadata and simquaro entry point
```

This is a responsibility map, not a requirement for a class in each file or a base-class hierarchy. Small helper modules and test support may be added for readability. No Device, NATS, HTTP service, database, agent runtime, or external simulator framework is required to run it.

**Implementation choice:** Linux and Python 3.12+ are the first supported platform; standard-library runtime facilities suffice. Use standard-library `unittest`, including async tests, initially. Native Windows lifecycle/control support is deferred, not claimed by packaging.

## 4. Identity, configuration, and Python model

Keep these identities separate:

- **Instance name:** `receiver-a`, used by the CLI and local runtime.
- **Apparatus identity/model:** the emulated `hardware_id` and `hardware_model` in the descriptor.
- **Emulated firmware:** declared version/build and supported behavior; not the Python package version or a claim that a real firmware binary is running.
- **Simulator build and process run:** diagnostic identity of this implementation and this OS-process execution.
- **Firmware boot:** hardware-protocol `boot_id`, which changes on simulated firmware reboot without requiring a new OS process.

Use one `FictitiousReceiverSimulator` model implementation with validated immutable configuration and fresh mutable state per instance. Instances may reuse that class and a supported behavior profile while differing in identity or legitimate hardware parameters. A firmware release label alone neither creates a new class nor enables unimplemented behavior. New commands/state semantics require code changes or a distinct implementation when justified. A profile is data, not a programming language or unrestricted interpreter.

The initial inventory in `src/simquaro/instances.py` is an explicit Python mapping from `receiver-a` to its allowlisted model factory, supported profile, and configuration: loopback `127.0.0.1:9001`, protocol-v1 fictitious receiver, and no injected faults. The loader returns validated immutable configuration objects defined in `config.py`. Models, session handling, and procedure logic receive those objects; they never import the inventory or depend on its source format. Tests construct alternate objects directly, without editing the inventory or shared globals. A future external inventory loader must produce the same validated objects; it will still need its own parsing, schema/version, and error tests. This boundary makes migration limited in scope, not free of work.

Keep configuration source separate from activation policy. Operating frequency changes through the hardware protocol, and test conditions change through the dedicated fault interface, without restarting the simulator. Hardware/model characteristics, firmware profile, endpoints, and initial settings are startup configuration: changing them requires restarting only the affected instance, not a coordinated restart of all simulators or Synqaro. Existing dependent operations/connections can still be interrupted, and endpoint changes require matching client configuration. No general hot reload is included. Before many hardware instances make the Python inventory cumbersome, introduce an external inventory through that loader boundary; do not build multiple loaders now.

Validate names and unique endpoints before spawning. Names match `[a-z][a-z0-9_-]{0,47}`; `all` is reserved. No path traversal, module-import expression, arbitrary callable, or firmware string from a control request is executed.

**Implementation choice:** normal startup verifies an initial frequency of 5 GHz, leaves calibration invalid, and establishes a fresh firmware boot token. Procedure history begins `unknown` when no prior history is retained; tests may construct an explicitly known fresh observation period to exercise `never_started`. Startup/restart must not pretend an earlier attempt succeeded. All fixed limits, supported properties, rounding, and procedure policies remain those in the Hardware Protocol. Configuration overrides must form a supported coherent profile, not arbitrary contradictory descriptor values.

## 5. Runtime and CLI

```sh
simquaro list
simquaro status receiver-a
simquaro status all
simquaro start receiver-a
simquaro start all
simquaro stop receiver-a
simquaro stop all
simquaro restart receiver-a
simquaro restart all
simquaro fault list receiver-a
simquaro fault status receiver-a
simquaro fault activate receiver-a calibration_reference_unavailable
simquaro fault clear receiver-a calibration_reference_unavailable
simquaro fault schedule receiver-a drop_response --when frequency_set_verified --times 1
simquaro fault schedule receiver-a calibration_reference_unavailable --when calibrate_reference_measurement --times 1
simquaro fault cancel receiver-a rule-1
simquaro --help
simquaro fault --help
```

The CLI's fault family uses the selected fixed noun/action grammar, not natural-language interpretation. `fault list` describes supported fault/effect names, allowed triggers, parameters, persistence, and examples; it does not require the instance to be running. `fault status` shows current injections and scheduled-rule counters separately from firmware-reported health. Fault mutation targets one named instance, not `all`, in this first version.

`start` runs in the foreground, launching one child process per newly started instance and showing instance-tagged logs. The launcher waits for those children, forwards interruption, and does not introduce an always-running manager. `Ctrl+C` stops only children that this invocation started. An already-running instance is inspected, not duplicated or reconfigured; a live but unresponsive instance produces a recovery instruction such as `simquaro restart receiver-a`. There is no automatic restart after a child crash.

For `all`, take a snapshot of the configured inventory, validate it, then report each instance's result. Successful starts remain running if another start fails; do not hide partial success or roll back unrelated instances. The foreground launcher continues to supervise its own successful children. Stop/restart process all selected instances even if one fails; restart starts an instance only after its previous process is confirmed terminated. With one initial entry, `all` has no additional orchestration behavior.

`list` omits the confusing implementation column from ordinary output. `status` distinguishes process presence, control responsiveness, listener state, model health/activity, and injected conditions. Control responsiveness alone is not proof of hardware-protocol reachability or health. Read status through the test-control interface without silently consuming a one-shot hardware fault; report unprobed hardware communication as unverified. Intentional initial faults do not become startup errors merely because the emulated hardware is unhealthy: runtime readiness means listeners/control are initialized and their known condition is reported.

**Implementation choices:** one 5-second startup deadline; one 2-second control-exchange deadline. Stop requests graceful process shutdown by signal, allows 2 seconds, then forcibly terminates the verified target automatically, allowing another 2 seconds to confirm termination. No `--force` or manual cleanup step. Already stopped is success. Permission failures, unverifiable process identity, or unconfirmed termination are explicit failures, never a false success. These are local process-management budgets, not the hardware's 5-second controlled-stop deadline or client reconnect policy.

Exit codes are 0 for a successful operation, 1 for runtime/partial failure, and 2 for invalid CLI usage. A successful status query reporting a simulated hardware fault is still a successful query. Add a global `--json` output option for agents: versioned JSON records instead of human text, with foreground startup producing JSON Lines events. Ordinary logs go to stderr. Structured failures retain symbolic codes, per-instance outcomes, and suggested command argument lists; human errors show copyable commands with the actual instance name. Help, errors, and diagnostics must agree with the implemented grammar.

## 6. Local ownership, crash recovery, and control transport

Use a private, local-filesystem runtime directory belonging to the current user, preferably below a validated `XDG_RUNTIME_DIR`, otherwise a validated `/tmp/simquaro-<uid>` directory, with mode 0700. Derive socket and metadata names from validated instance names; ordinary commands require no `.sock` argument. Refuse unsafe ownership, symlinks, or unexpected file types rather than deleting them. Remote/multi-user administration is not supported initially.

Each simulator child holds an exclusive OS file lock for its lifetime. The lock descriptor is not inherited by unrelated children. The lock file itself may remain: existence is never treated as ownership. Startup acquires the lock before touching stale state, so two concurrent starts cannot both claim one instance. Only an old socket positively established as stale inside the owned directory is removed; an ambiguous or live endpoint is not unlinked. Shutdown removes only paths still belonging to that process run. Crash residues are recovered on the next normal start without user intervention.

Publish process metadata atomically: PID, user, host-boot/process-birth identity, and a fresh run token. **Implementation choice:** use Linux pidfds with validated process-birth identity for signaling, holding the pidfd through escalation and confirmation; do not fall back to killing an unverified PID. A failed control connection is not evidence that a process is dead. Lock files are not unlinked to 'release' a lock. Status/stop/restart must not target unrelated processes after PID reuse or race with a newly started replacement.

Fault control uses a separate Unix stream socket and explicit allowlisted handlers, never reflection over arbitrary model methods. **Implementation choice:** versioned, LF-delimited JSON requests/responses, one request per control connection; 8 KiB request and 64 KiB response ceilings, 2-second framing/exchange deadlines, four concurrent control connections. JSON on this channel does not alter the ASCII hardware grammar. Bound catalog/status output and text fields to the response ceiling and report an explicit control error rather than truncating structured results.

`stop` works without that socket by signaling the verified process. Ordinary hardware silence, disconnect, malformed-response, and dropped-acceptance injections must leave the control channel functional. An actual OS-process hang/crash need not preserve control responsiveness; lifecycle commands handle that distinction.

## 7. Hardware sessions and receiver state

One model owns shared simulated physical state, firmware diagnostics, the active procedure, and retained outcomes. Every TCP client has its own framing buffer, first-byte deadline, high-water ID, pending requests, and serialized writer. Never share a partial-message parser or request-ID state across clients. Process complete frames in receive order for ID admission; execute admitted work asynchronously so status remains serviceable and replies can be reordered. Serialize incompatible state changes without an implicit unbounded command queue.

Retain the protocol's 4096-byte framing ceiling, 2-second incomplete-frame deadline, and four-pending-request limit. Reserve an admitted request slot until its response is sent or a bounded injection deliberately drops it; release procedure-start slots after acceptance handling, not procedure completion. A delayed reply retains its slot. Emit whole response frames without interleaving; do not hold the writer lock while waiting for an injected delay. Cancellation of a TCP session does not cancel an accepted firmware procedure.

**Implementation choice:** at most 16 simultaneous hardware TCP clients, 64 scheduled fault rules per instance, and four held ordinary responses per hardware connection. Additional connections may be refused before protocol admission. Backpressure and write waits are bounded; a client that does not read cannot cause unlimited buffering. The plan must specify and test exact output-buffer bounds and write-failure cleanup, without presenting platform capacity as unlimited.

Track physical value/validity separately from requested targets and reported state. Frequency reads are fresh model observations; no firmware acquisition cache is added. Use exact decimal/scaled-integer arithmetic for grammar validation, range checks, ties-up grid rounding, and ten-point rational target generation. Bound numeric work by input/resource limits and explicitly reject unsupported representational capacity; never silently overflow, underflow, or turn a string into a number.

All procedure, framing, stop, and runtime deadlines use a monotonic clock. UTC is separate; normal simulation assumes the host clock is trustworthy, while an injected trust failure produces `CLOCK_UNTRUSTED` and omits unreliable new timestamps without altering deadlines. Preserve reliable historical timestamps. Inject a small clock/sleeper dependency for deterministic tests rather than changing process-wide wall time.

## 8. Procedures and reboot

Implement all wire behavior from the approved receiver profile: `get` configuration/frequency; `set` frequency; general and named `status`; `run` calibrate/scan; named `cancel`; dedicated `reboot`. Rejections do not replace the prior retained outcome. No `operation_id`, notifications, implicit ownership, or automatic replay is introduced.

**Implementation choices:** nominal tuning/verification takes 100 ms and normal controlled stop takes 100 ms. Calibration normally takes about 10 seconds: 1 second preparation, 8 seconds reference-measurement sequence, and 1 second non-client-cancellable finalization, including saved-frequency restoration and checks. Its model actions and verification, not elapsed time alone, establish success. Define `calibrate_reference_measurement` at entry to that sequence, after the attempt is registered/accepted; `frequency_set_verified` occurs after a valid external `set` is applied/verified and before its reply is transmitted. Do not emit the latter hook for scan tuning or calibration restoration. Calibration progress may be omitted; scan progress counts completed held points.

Enforce tuning's 1-second, calibration's 30-second, scan's 20-second, and additional controlled-stop 5-second deadlines independently of nominal timing. Scan generates exactly ten rounded distinct targets, verifies then holds every point, and leaves the last actual verified value unless invalidated. Scan accepts cancellation throughout; calibration rejects it only in finalization. Natural completion can win a cancellation race. Repeated cancel does not extend stopping. An unconfirmed stop never becomes terminal merely because its timer expires; `STOP_TIMEOUT`, actual/unknown activity, and incompatible-operation blocking must agree with model evidence.

Simulated firmware reboot keeps the OS process/control endpoint alive, closes hardware sessions, interrupts activities without inventing outcomes, resets firmware state/history as declared, and generates a new `boot_id`. A process restart additionally reconstructs the configured model and scenario; it is not the wire `reboot` command. No Device cache or external client is restored or replayed.

Before normal reboot teardown, fully enqueue acceptance, await bounded transport draining and orderly closure using the chosen Linux TCP stack's documented completion conditions. `drain()` alone is not proof of remote application receipt, and a fixed sleep is not a transmission guarantee. The implementation plan must identify the concrete completion observation and bounded failure policy and test complete acceptance-before-EOF on the normal path. A lost-acceptance scenario intentionally preserves outcome uncertainty. Production firmware TCP stacks/startup guarantees remain outside this Python simulator's evidence.

## 9. Fault and scenario semantics

An optional typed `Scenario` is supplied to model/runtime construction. There is no mandatory file or hot-reloaded configuration. The initial CLI inventory supplies the empty scenario; direct Python tests may supply initial faults and deferred rules. CLI and Python controls call the same validated injection operations. Unknown names, incompatible effects/triggers, invalid parameters, and capacity overflow fail without partially changing the scenario.

Distinguish three injection locations:

- **Physical model:** reference loss, synthesizer/read/lock failure, untrusted clock, continued activity despite a requested stop. Firmware must react through its normal diagnostic/state paths.
- **Firmware behavior:** stalled procedure advancement or deliberately incorrect reports, without blocking the whole event loop. Preserve actual model state as an independent test oracle.
- **Wire delivery:** suppress, delay, truncate, corrupt, reorder, or disconnect a response after the relevant execution stage. Applying a setting and losing its response must not undo the setting.

Start with a finite catalog covering the Hardware Protocol's initial matrix, not a general rule-expression language. Examples of persistent conditions are `calibration_reference_unavailable`, `synthesizer_failure`, `frequency_read_failure`, `clock_untrusted`, `procedure_stall`, and `stop_unconfirmed`. Examples of delivery effects are `drop_response`, `delay_response`, `omit_lf`, `malformed_response`, `reorder_responses`, and `disconnect`. Document the allowed event/parameter combinations and corresponding physical/reporting effects in that catalog. Tests use a raw/faulty client for malformed requests, duplicate IDs, overload, and request framing; those are not fake hardware faults.

Scheduling is prospective: it never retroactively modifies an already-passed phase. A rule with `--times N` applies to the next N matching events, default 1; each effect consumes one occurrence atomically, including under multiple clients. Its default scope is that simulator instance, regardless of requesting client, with request/session context retained in diagnostics. Phase hooks fire once per actual entry; repeated polling does not retrigger them. Trigger choice is an allowlisted event identifier, not code or free-form conditions.

Rules have local `rule-N` identifiers, ordered by creation. **Implementation choice:** reject incompatible effects on the same matching event rather than choosing a hidden precedence; compatible effects run in creation order and are logged. `fault cancel` removes an unconsumed rule (or its remaining occurrences), not an already-triggered physical condition. `fault clear` removes a persistent injected cause and causes diagnostic reevaluation; it does not erase incidents, fabricate restored lock, or rewrite a failed/completed procedure. A one-shot activation can therefore leave a persistent fault until cleared.

TCP reconnect does not clear injections or rules. **Implementation choice:** injected environmental conditions and rule counters also survive a simulated firmware reboot because they belong to the external test controller; firmware diagnostics are recomputed after reboot. Full process restart re-applies only the declared initial scenario, not ad-hoc CLI changes. Log scheduling, actual activation, consumption, removal, physical effects, and emitted/dropped wire evidence, with process run, boot, rule, session/request context when available, UTC provenance, and monotonic ordering. This is diagnostic test evidence, not a claim of durable incident-time system reconstruction.

## 10. Verification and acceptance

The implementation is accepted only with executable evidence, not because its examples resemble the contract:

- Parser/encoder tests cover ASCII/control characters, quoted strings, flat lists, duplicate fields, exact numeric boundaries, timestamp preservation, invalid IDs, and malformed-but-correlatable requests. Use explicit expected bytes as well as round trips; sharing one codec on both sides is not an independent oracle.
- Real TCP tests cover fragmentation/coalescing, 4096-byte and first-byte deadline boundaries, independent client buffers/IDs, high-water consumption, four-pending admission, reordered/delayed/late replies, and all receiver operations and retained outcomes.
- Model and virtual-time tests cover ten distinct ascending/descending targets, every-point dwell, calibration restoration/finalization, cancellation races, execution/stop deadlines, persistent active faults, clock trust, and reboot identity. A stopped task is not the oracle for stopped simulated activity.
- Fault tests compare injected cause, actual model state, firmware-reported state, bytes delivered, and client outcome. Each row of the existing initial fault matrix maps to a test or explicitly identified later-layer test; Device cache behavior remains a future Device test, not falsely implemented firmware behavior.
- A small test client uses persistent sessions and increasing IDs, correlates replies, exposes uncertainty and diagnostics, and exercises the approved staged probe/reconnect policy without replaying modifications. It is test support before the production communication library, not an alternate Device framework. Keep deliberately faulty-client tests separate from this conforming client.
- Subprocess CLI tests cover clean start/stop/restart, already-running/stopped instances, stale sockets and lock files after forced death, concurrent starts, PID-reuse/wrong-target protection, unresponsive control with automatic signal escalation, busy ports, partial `all` outcomes, and actionable human/JSON errors. Test helpers may declare additional instances without shipping invented receiver models.
- Use deterministic barriers and injectable monotonic scheduling for edge cases, plus a small real-clock/socket smoke suite. Do not speed tests by silently changing the advertised production profile. Conformance to real hardware still requires independent later validation.

## 11. Approval boundary and remaining scope

This document records the confirmed design direction and explicitly identified implementation choices that fill simulator-specific gaps. The user confirmed proceeding with validated configuration objects, a separate Python loader, and no general hot reload. Keep the hardware contract unchanged and cross-reference this design when implementation starts. No code scaffolding, dependency installation, GitHub issue/PR, or implementation commit has occurred during design preparation.

The implementation plan specifies test/command evidence and resolves ordinary coding details: module factoring, control envelopes/catalog parameter schemas, safe Linux process/transport primitives and their failure tests, packaging, bounded buffering, and calibration sub-actions. Do not infer a new requirement or change public behavior to fill an implementation gap. If a primitive cannot meet the promised identity/stop/reboot guarantees, report the limitation rather than silently weakening them.

Deferred capabilities remain those in the Hardware Protocol: scientific-data/frequency association, bulk and continuous data, hard real-time feedback, interlocks, production watchdogs/clock accuracy, persistent Device configuration/history, arbitrary scenario files, remote control, and coupled whole-system simulation. These do not block the standalone receiver and its tests.
