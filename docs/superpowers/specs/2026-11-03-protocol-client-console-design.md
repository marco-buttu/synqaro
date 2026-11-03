# Shared protocol client, manual console, and validation checks

**Status:** proposed detailed design for the client/console component of the
combined delivery; awaiting user approval. No application implementation is
authorized by this document alone.

Approved requirements are recorded in the consolidated delivery roadmap.
Module/API names, resource bounds, and test-case selections below are proposed
engineering choices, not additional decisions already approved by the user.

## Purpose and scope

Provide one communication library usable by a future Device, the CLI, and the
future GUI server. Provide a console for arbitrary hardware input and a readable
functional validation suite that can target either the simulator or compatible
physical hardware. The approved wire contract remains unchanged.

Delivery 1 introduced the explicit simulator model registry. The user has now
required the next delivery to include the previously separate configuration and
GUI milestones: the work is not complete when only the library/CLI is available.
This document details the shared client/console component; persistent instance
configuration and the mandatory GUI are detailed in the
[configuration/GUI design](2026-11-03-simquaro-configuration-gui-design.md), also
awaiting approval. They are included in the delivery, not deferred
enhancements. No new models, firmware, agent, or system orchestration is included.
Documentation accompanies every milestone.

## Architecture

```text
Future Device / future GUI server       simquaro test INSTANCE
                 |                              |
                 +-------- ProtocolClient ------+
                                  |
simquaro console INSTANCE ---- TcpConnection
                                  |
                           TCP hardware protocol
                                  |
                     Simulator OR physical hardware
```

These are Python modules, not additional servers. The CLI works without the GUI
server. The diagnostic console shares TCP primitives, not the managed client's
validation, startup requests, or recovery. Each connection has exactly one reader;
raw input and managed transactions never share a connection.

Alternatives rejected: a mandatory gateway would add deployment and failure
points without helping this delivery; separate client implementations would
duplicate correlation and recovery; one validating path for all input would
prevent malformed-input diagnostics.

## Package boundaries and reuse

Create `src/synqaro_protocol/`, installed by the existing distribution, with no
new base runtime dependencies; GUI extras are separate. Its generic modules must import neither `simquaro`
nor `tests`. Do not create a second repository or packaging project now.

| Location | Responsibility |
| --- | --- |
| `synqaro_protocol/codec.py`, `errors.py`, `clock.py` | Move the existing shared codec, core error catalog, and clock; add request encoding and reuse owned-task monotonic deadline handling. |
| `synqaro_protocol/transport.py` | Byte-oriented TCP connection, bounded connect/send/close; no protocol interpretation or automatic requests. |
| `synqaro_protocol/client.py` | Request IDs, bounded admission, correlation, framing, evidence, uncertainty, and recovery. |
| `synqaro_protocol/profiles/fictitious_receiver.py` | Receiver contract validation and its specific error catalog, shared by client and simulator. |
| `simquaro/console.py`, `checks.py` | Manual terminal interaction and small ordered check runner respectively. |
| `simquaro/models/fictitious_receiver/checks.py` | Receiver functional check definitions; use the public client, not simulator internals. |
| `simquaro/registry.py`, `cli.py` | Explicit profile/check wiring and command selection; no automatic discovery. |

Move reusable behavior from `tests/simquaro/support/client.py`; do not retain a
second serializer or recovery state machine there. A thin test fixture may only
construct the production client with the receiver profile. Update imports rather
than add compatibility forwarding modules without an actual external consumer.
Receiver physics, procedure implementation, configuration, and fault causes stay
under its simulator model. Core modules must not import receiver validators.

## Library behavior

`TcpConnection.open(host, port, *, clock, timeout=2.0)` returns a connection with
`send(data: bytes)`, `receive() -> bytes`, and `close()` async operations. Empty
receive means EOF. Transfer chunks are at most 4096 bytes; sends use one total
deadline, not a refreshed deadline per chunk. It accepts non-ASCII and oversized
protocol input for diagnostics. A console-only write-half-close operation supports
end-of-input observation. No background reader or retry exists in this module.

`ProtocolClient(host, port, *, contract, expected_hardware_id, clock=None,
read_only=False, observe=None)` exposes async `connect()`, `request(verb, fields=None)`, `close()`,
and `ready`, `writes_enabled`, `descriptor`, `general`, and bounded diagnostic
evidence. `request` returns the parsed `Response`, including hardware error
responses; local/transport failures raise `LocalFailure(code, request_id=None,
uncertain=False)`. Numeric inputs use `NumericToken`, not implicit float coercion.
The optional synchronous evidence observer receives bounded exact TX/RX events
at the wire boundary for GUI transcripts; observer exceptions must not affect
protocol handling. It adds no requests, extra reader, or new recovery logic.

The small immutable `ClientContract` supplies a `ClientLimits` record, descriptor
and general-status validators, a refresh-result validator, and an error catalog.
Validators reject incompatible replies rather than silently change the contract.
The receiver profile preserves the existing exact fictitious-v1 validation.
Identity is checked against independently configured `hardware_id`, never learned
as the expected value from the peer being checked.

Preserve the existing tested client behavior: initial configuration/status
validation; one increasing connection-scoped ID; four admitted requests including
sends waiting on the writer lock; out-of-order correlation; partial/coalesced
frames; late/duplicate/foreign response evidence; reserved uncorrelated errors;
and no automatic replay of modifying commands. Strings remain quoted in encoded
requests so independent literal peer fixtures remain useful.

Receiver limits are 4096 bytes including LF, 2-second incomplete-frame, response,
and connect deadlines, and a 5-second pause after a failed reconnect attempt.
These are receiver profile values, not universal hardware assumptions. Keep
them as the only supported profile values in this delivery; introducing a profile
with different wire limits will require explicit codec/profile compatibility work,
not merely trusting larger limits advertised by an unknown firmware.
Preserve absolute monotonic deadlines and cancel/join owned tasks and late connections.
An uncertain outcome blocks mutations until fresh usable state is acquired.
Probe once when framing is sound; retain a well-formed fault response; reconnect
when the probe fails or framing is broken. Recovery attempts continue while the
client is requested open; no fixed global reboot/startup deadline is introduced.
EOF during bootstrap or refresh must never enable writes from stale state.

`read_only=True` also rejects `set`, `run`, `cancel`, and `reboot` at dispatch,
including after recovery. It is a local safety gate, not a claim that arbitrary
firmware treats reads as physically harmless. Closing never cancels a hardware
procedure. Error codes have readable bounded log descriptions; unknown codes
remain visible. Keep evidence bounded (256 records, each bounded by frame limits).

## Manual console

```text
simquaro console receiver-a
simquaro console receiver-a --raw
```

The inventory supplies host/port. Neither command requires a local simulator
process or administration socket: the endpoint can be compatible physical
hardware. Normal mode sends the entered ASCII line followed by LF, without
validating protocol syntax or inserting IDs. The prompt identifies target and
endpoint. A second terminal opens an independent connection.

Raw mode interprets only `\n`, `\r`, `\t`, `\xNN` (exactly two hex digits),
and `\\`. Enter sends exactly those bytes, with no added LF:

```text
#status <id=1>\n       # complete request
#status <id=1>         # deliberately incomplete request
text\x00\xFF\r\n      # arbitrary bytes
```

The comments above explain examples; they are not part of the input. Invalid
escape notation or non-ASCII literal input is a local error and sends nothing.
Protocol-invalid bytes remain allowed. Limit decoded submissions to 64 KiB,
separately from the firmware's 4096-byte limit; permit 4097-byte fault cases.
Bound the input representation to four times that limit plus the line terminator.

Show actual received chunks without assuming read boundaries are message
boundaries. Escape nonprintable bytes, backslashes, and terminal control sequences
reversibly; never execute received ANSI controls. Do not fabricate firmware
errors, silently fix requests, bootstrap, probe, retry, or reconnect. Explain that
some malformed input produces an error and some requires connection closure.
The two-second absence-of-data observation is diagnostic, not a firmware reply.
After a submission, report this observation once if no bytes arrive within two
seconds; keep the connection open. New submissions restart this local observation,
not any hardware deadline. Receiving any bytes clears it, without asserting that
a complete response has arrived.

Remote EOF ends the console and displays the copyable command to reopen it.
Ctrl+C closes promptly. On stdin EOF, half-close the write side and observe for
up to two seconds before closing, so piped requests can receive replies. Keep
terminal input nonblocking and remove readers/tasks when the remote end closes.
Idle interactive consoles remain open; no periodic observation spam is required.

Global `--json` produces version-1 JSON Lines events `console.connected`,
`console.tx`, `console.rx`, `console.closed`, and `console.error`, following the
existing CLI envelope, plus `console.observation` for the local no-data observation.
Byte events carry reversible escaped data and byte length;
no prompts or unescaped terminal controls appear on stdout.

## Shared functional checks

```text
simquaro test receiver-a
simquaro test receiver-a --allow-changes
```

Use the configured endpoint directly, not runtime administration readiness.
Extend `ModelDefinition` with optional defaulted `client_factory` and `checks`
bindings; preserve existing five-argument registrations. A factory supplies the
receiver contract and independent identity from settings. The library itself
does not depend on this simulator registry. Missing bindings are an explicit
unsupported-profile error; the raw console still works.

One ordered suite has five read-only checks: configuration, general status,
frequency, calibrate status, and scan status. Another five checks require
`--allow-changes`: frequency rounding/readback; calibrate; scan; scan cancellation;
and reboot, last. Defaults never dispatch modifications, even if a check is
misclassified. Permission-skipped checks are not counted as passes.

Receiver modifying cases require a healthy idle target and an operator-arranged
isolated test context. Use `5.1234565 GHz -> 5.123457 GHz` for rounding, scan from
`5` to `5.2 GHz` with ten points and `dwell_ms=1`, and `dwell_ms=1000` for the
cancellation case. Poll at 500 ms. Use advertised procedure/stop bounds plus one
2-second response allowance for observations; admission still has its own limit.
Reboot is sent once, and a new validated `boot_id` is required. The check has a
30-second observation budget, explicitly a test-runner limit, not a new protocol
or library recovery deadline. A new boot proves execution, not which requester
caused it. A missing acceptance followed by a new boot remains causally uncertain.

After a failed or uncertain check, skip subsequent mutations with an explanation;
safe reads may continue if the connection is usable. No blind retries, reset,
restoration, or automatic simulator start/stop is permitted. Tests leave state
changed; calibration history and reboot identity cannot be restored. A cancellation
that loses a race to completion must be reported honestly, not as cancellation.

`Check(name, mutating, run)` and an ordered runner produce `CheckResult` records
with `passed`, `failed`, or `skipped`, reason, and duration. Stream readable case
results and a final summary; include profile, endpoint, identity/firmware/boot
evidence when available and uncertainty explicitly. JSON mode uses version-1
`test.started`, `test.case`, and `test.finished` events. Exit 0 means all executed
checks passed and at least one ran; exit 1 means failure or no executable checks;
exit 2 means invalid CLI usage. Permission skips still yield a clearly labeled
read-only report, not an assertion of full hardware validation.
Only permission skips are expected: missing prerequisites, interrupted checks,
or skips caused by failure make the run incomplete and yield exit 1 even when
other executed checks passed.

Reuse these cases in simulator integration tests. Keep independent literal wire
oracles, narrow malformed-wire conformance checks, internal unit tests, and
simulator fault-injection tests. Do not redirect all existing tests at real
hardware or duplicate the whole suite. Replies alone cannot prove the actual
physical frequency; external measurement is outside this delivery.

## Documentation, verification, and deferred work

Add `docs/getting_started.md`, linked from README: Python 3.12+, standard `venv`,
installation, separate terminals, start/stop, normal/raw console examples,
read-only versus modifying checks, results, and actionable failures. Initial
validation target is this Linux Mint 22.1 machine (Ubuntu noble family); do not
claim other releases were tested. No mandatory pyenv; CLI/checks need no web server.

Update the operator guide with the diagram and explain the distinction between
`simquaro status` (administration) and protocol status. Mark GUI and configuration
milestones as pending until delivered. Do not describe proposed commands as available
until implemented and verified.

Acceptance requires the existing regression suite, managed-client scripted-peer
tests, console byte-exact subprocess tests, read-only safety tests, shared-case
integration tests, package/import checks, and a clean documentation diff. External
configuration/editor behavior and GUI dependency/API choices are now proposed
in the linked configuration/GUI design and its companion plan. Those documents
complete the technical proposal and await user approval before implementation.

## Mandatory GUI and combined-delivery completion

The implementation sequence is shared protocol, managed client, CLI console,
shared checks, persistent external instance configuration, mandatory browser GUI,
and whole-delivery documentation/verification. This is the approved scope update;
the linked companion documents now provide the proposed detailed design.

The GUI must let the user select a configured instance, connect/disconnect,
submit guided requests or arbitrary diagnostic text/bytes, inspect actual replies
and connection errors, run the same checks and read their results, administer
supported simulator lifecycle/fault conditions, and edit supported persistent
startup settings. Distinguish saved settings from active settings; applying
startup changes restarts only the affected simulator with explicit user action.

A local HTTP server calls the same library and simulator-administration APIs;
the GUI does not shell out to CLI commands or implement another TCP client.
Raw and managed interactions use separate connections. Background monitoring must
not consume a fault scenario intended for a manual request. CLI and automated
checks remain usable without the GUI server.

Completion requires a documented launch workflow and a verified browser session
covering target selection, normal and malformed requests, a long procedure,
fault injection, readable check results, configuration save/apply, and cleanup.
Delivering only a mockup, web server scaffold, or CLI is not completion.

Planning review: an independent read-only builder check of the client/console
component found no material unanswered design questions before this scope update.
That review did not cover a concrete configuration/GUI design and does not approve
implementation or replace verification of future code.
