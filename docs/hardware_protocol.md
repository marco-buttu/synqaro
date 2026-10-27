# Hardware Protocol

**Status:** protocol version 1 and an approved fictitious-receiver profile, ready to guide the first simulator. This document specifies behavior; it does not claim that firmware, libraries, or conformance tests are already implemented.

## Purpose

This protocol provides a common text-based interface for controlling different types of hardware over TCP.

It supports:

- reading and setting properties;
- starting and cancelling procedures and inspecting their state and outcome;
- requesting a hardware restart and checking the receiver after reconnection;
- distinguishing invalid requests, hardware failures, and communication problems;
- straightforward implementation and testing of firmware, communication libraries, and simulators.

Message structure and general behavior are shared across hardware types. Each hardware specification defines its supported properties, procedures, parameters, and specific error codes.

The protocol is intended for control and diagnostics, not bulk data transfer.

### Why Generic Verbs

The protocol uses a fixed set of verbs instead of a separate verb for every hardware capability. Properties are selected through `name`, assigned through `value`, and accessed through `get` and `set`. Procedures are selected through `name`, started through `run`, inspected through `status`, and interrupted through `cancel` when supported.

Cancellation is a request to control an existing procedure, not a separate procedure started through `run`. This avoids introducing a second execution lifecycle just to stop the first one.

`reboot` is also a dedicated verb because it controls the lifecycle of the whole receiver. Its completion is checked after reconnection through general status, rather than through a procedure state that would have to survive the restart.

This provides a uniform interaction model across hardware types. The communication library handles framing, request identifiers, responses, errors, and timeouts without per-property or per-procedure branches. Hardware-specific specifications and firmware handlers still define supported functionality, validation, and effects.

Explicit hardware-specific verbs could also be carried by a generic communication library. The reason for choosing generic verbs is the consistent interface and validation structure, not an assumption that explicit verbs necessarily require library changes.

Using literal `name` and `value` keys makes the property-selection structure predictable: the target property is not inferred from field order or from whichever field key happens to match a property. This also avoids collisions between property names and qualifiers such as `unit`. The additional bytes are accepted in exchange for simpler implementation, generation, and testing.

## Message Format

Messages use ASCII characters, begin with `#`, and end with a single LF character, represented here as `\n`.

A message has one of these forms:

```text
#verb <metadata>\n
#verb <metadata>: fields\n
```

Angle brackets are transmitted literally. Metadata and fields use named values:

```text
#verb <key=value, key=value>: key=value, key=value\n
```

Metadata is mandatory for requests and ordinary responses. Fields are optional; when absent, the colon is omitted. The only response without metadata is the diagnostic `#error: code=INVALID_ID\n`, when a complete request has no reliably recoverable valid ID. It is not an unsolicited notification and cannot complete a pending request.

### Quick Examples

**Set a property:**

```text
REQUEST:
#set <id=10>: name=frequency, value=5.5, unit=GHz\n

RESPONSE:
#ok <id=10>: name=frequency, value=5.5, unit=GHz\n
```

The client requests a frequency change. `ok` confirms that the setting has been applied.

**Start a procedure:**

```text
REQUEST:
#run <id=11>: name=calibrate\n

RESPONSE:
#accepted <id=11>\n
```

The receiver accepts the calibration procedure. Acceptance does not mean completion: the client subsequently uses `status` to inspect its progress or outcome.

In both examples, the client assigns `id`, and the response echoes it to identify the corresponding request. It identifies a request on that TCP connection, not a procedure execution. Detailed rules follow below.

## Names, Values, and Separators

- Verbs and field keys are case-sensitive.
- Verbs and field keys start with a lowercase letter and contain lowercase letters, digits, or `_`.
- Every field consists of a key, followed by an equals sign (`=`), followed by its value. Positional parameters are not supported.
- Commas outside quoted strings and lists separate fields. Field order does not affect meaning.
- A key must not occur twice within the same section.
- The decimal separator is always `.`, regardless of system locale.
- Boolean values are `true` and `false`.
- Simple scalar values may be unquoted. String values containing spaces, commas, or structural delimiters must be enclosed in double quotes. Lists use the syntax defined below and are not enclosed in quotes.
- Within quoted strings, `\"` represents a double quote and `\\` represents a backslash.
- Control characters and embedded newlines are not allowed.
- Colons within values in the fields section, such as timestamps, do not require escaping.
- Spaces around `=`, `,`, and the separating `:` are allowed and have no meaning outside quoted strings. Tabs and CR characters are not allowed.

Quoted values such as `"true"` and `"100"` are strings. Each property or parameter specification defines its required type.

For example, in `name=frequency`, the key is `name` and its value is `frequency`. In `value=100`, the key is `value` and its value is `100`.

### Numeric Syntax

The common numeric grammar is:

```text
[+-]?[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]+)?
```

This regular expression describes an entire unquoted numeric token, using ASCII digits. The sign is optional. A decimal point requires at least one digit on each side. An exponent requires at least one digit after its optional sign. There are no spaces within a numeric token.

Valid examples are `5`, `+5`, `-5`, `0.5`, `005.50`, `5.5e0`, `1E-6`, and `2e+3`. All numbers are base ten: `010` means ten, never octal. `.5`, `5.`, `1e`, `NaN`, `Inf`, and `Infinity` are not valid numbers. Quoting a token makes it a string, not a number.

These rules apply to numeric fields in requests, responses, and lists. Each field still defines its type, range, unit, and representability constraints. Fields declared as integers use decimal digits without a fraction or exponent, with a sign only where their contract permits one. Request IDs and timestamps retain their dedicated formats.

Syntactically valid input does not require unlimited numeric range or precision. Values outside the field's range or representational capacity must be rejected explicitly; conversion must never silently produce infinity, zero through underflow, or a different value. Property-specific approximation is allowed only when declared, as for the receiver's frequency. Exact decimal arithmetic or an equivalent scaled-integer implementation must preserve the decisions at range and rounding boundaries; a language's permissive floating-point parser is not the grammar.

### List Values

A property value may be a scalar or a flat list. Lists use square brackets, with comma-separated scalar elements and optional spaces around elements:

```text
#set <id=12>: name=frequencies, value=[100, 105.3, 77.99], unit=GHz\n
```

The key remains `value`, not `values`, regardless of whether the property contains a scalar or a list. The same list syntax applies when returning a property value. Nested lists are not supported.

Commas inside a list separate elements, while commas outside lists and quoted strings separate fields. Quoted string elements follow the same escaping rules as scalar strings. A parser must recognize quoted strings and list boundaries; splitting a message on every comma is not valid.

Each property's hardware specification defines:

- the permitted element types and value constraints;
- the required list length or allowed length range, including whether an empty list is valid;
- the meaning of element positions, or whether element order is irrelevant.

For example, a property could require exactly three numeric values, with positions corresponding to channels 1, 2, and 3. This is an illustration, not a requirement for the fictitious receiver. Positional meaning does not imply that numeric values must be sorted.

A list is the value of one property. Updates to different properties use separate `set` requests; list syntax does not introduce batching or atomic updates across properties.

## Metadata and Request Identification

Every request includes the mandatory `id` metadata field. Its response echoes the same identifier.

The identifier:

- is assigned by the client;
- consists of ASCII decimal digits and has a numeric value between `1` and `4294967295`; signs, fractions, and exponents are not permitted;
- identifies a request within one TCP connection;
- must be strictly greater than the maximum valid ID already received on that connection; gaps are allowed, but reuse and decreasing IDs are not;
- does not identify a procedure execution across reconnections.

Different connections may use identical identifiers. There is no `operation_id`.

The library normally generates `1, 2, 3, ...` in actual send order. Leading zeros do not create a different ID: comparisons and correlation are numeric. The firmware starts with a high-water mark of zero. Once a complete message has an unambiguous valid ID greater than that mark, it advances the mark before other request validation or admission checks. Thus an ID is consumed even if its request is subsequently rejected. Invalid or non-increasing IDs do not advance the mark.

Requiring increasing rather than consecutive IDs lets a client skip a reserved number without resynchronizing the session. It also lets the firmware detect retired IDs with one high-water mark instead of retaining every request forever. Responses may still arrive out of order. At ID exhaustion, the client drains pending requests and establishes a new connection rather than wrapping on the existing one. If draining times out, no new probe ID is available: close and reconnect directly, preserving uncertain outcomes and never replaying old operations.

### Non-increasing IDs

A complete request whose ID is not greater than the high-water mark is rejected without hardware effects. The connection stays open:

```text
REQUEST, AFTER ID 17 HAS ALREADY BEEN RECEIVED:
#run <id=17>: name=calibrate\n

RESPONSE:
#error <id=17>: code=ID_NOT_INCREASING, last_id=17, rejected_verb=run, rejected_name=calibrate, received_at=2026-10-27T10:15:30.123Z\n
```

`rejected_verb` identifies the rejected request's verb when recoverable. `rejected_name` identifies its property or procedure when present and recoverable; it is absent for `reboot`. `received_at` is optional and records when the complete rejected request was received, only when that UTC time is trustworthy. Do not echo arbitrary full requests into diagnostics.

`ID_NOT_INCREASING` replaces the earlier proposed `DUPLICATE_ID`: it covers both repeated and decreasing identifiers. The library treats it as a rejection diagnostic for the new occurrence, **not** as completion or failure of any original pending request with that ID. The original request proceeds normally, and its ordinary response may arrive before or after this diagnostic. Other errors must not use this reserved code merely to bypass normal correlation.

### Missing or Invalid IDs

If a complete, bounded message lacks an unambiguous valid ID, the firmware does not execute it and returns:

```text
REQUEST:
#get: name=frequency\n

RESPONSE:
#error: code=INVALID_ID\n
```

The connection remains open. The library records an uncorrelated diagnostic without completing a pending request. No synthetic ID such as zero is assigned. This exception does not apply to oversized or timed-out incomplete frames, which require closure.

Multiple metadata fields are separated by commas. An optional `client_id` may provide attribution and diagnostic context. It does not change response correlation or grant ownership or exclusive control.

## Request Types

| Verb | Purpose |
|---|---|
| `get` | Read a property, including the read-only hardware descriptor `configuration` |
| `set` | Apply a property value within a bounded, short execution time |
| `run` | Start a procedure |
| `status` | Read general hardware state, or a procedure's state and retained outcome |
| `cancel` | Request interruption of the currently executing named procedure |
| `reboot` | Request restart of the receiver's firmware |

`get`, `set`, `run`, and `cancel` select a property or procedure through `name`. `set` also requires `value`. Additional fields depend on the selected functionality.

Without `name`, `status` describes the hardware. With `name`, it describes the selected procedure.

`reboot` accepts no fields. The common metadata rules still apply.

A `set` must complete the setting before confirming success. Work requiring prolonged execution is modeled as a procedure started through `run`.

## Responses

Every valid request receives exactly one response:

| Response | Meaning |
|---|---|
| `ok` | The read, setting, or status query has completed |
| `accepted` | A procedure start, cancellation, or reboot request has been accepted; acceptance does not establish completion |
| `error` | The request was rejected, or its short execution failed |

`get`, `set`, and `status` return `ok` or `error`. `run`, `cancel`, and `reboot` return `accepted` or `error`.

After `run` or `cancel`, the client queries the named procedure through `status`. After `reboot`, it reconnects and queries general receiver status.

The hardware does not send unsolicited notifications. Even a procedure that finishes quickly follows the `run` acceptance-and-status model.

An `ok` response to `status` may report a failed procedure: successful status retrieval and successful procedure execution are separate outcomes.

The receiver profile defines each response's fields. Ordinary property reads use `value`; `get` of `configuration` instead returns the flat descriptor fields specified below, not a nested object or an encoded file.

## Procedure State

The protocol distinguishes these states:

| State | Meaning |
|---|---|
| `unknown` | Information is unavailable |
| `never_started` | No attempt has occurred within the period for which the firmware retains knowledge |
| `running` | Execution is in progress |
| `cancelling` | Cancellation has been requested but has not completed |
| `succeeded` | Execution completed successfully |
| `failed` | Execution ended with an error |
| `cancelled` | Cancellation completed |

Each procedure specification defines its applicable states and allowed transitions.

`started_at` records when an attempt began. `finished_at` records when it ended, including failure or cancellation. Their format and availability follow the [timestamp rules](#timestamps).

`progress` is optional. When provided, it represents a percentage between `0` and `100`.

Reading status does not modify or clear it. State and outcomes remain available across disconnections according to the procedure's declared retention rules. Retention across a hardware restart requires an explicit guarantee.

## Timestamps

Timestamps use UTC, with an optional fractional part of variable length:

```text
YYYY-MM-DDTHH:MM:SS[.fraction]Z
```

Square brackets in this format indicate optional notation; they are not transmitted. If the decimal point is present, at least one fractional digit must follow it. Valid examples include:

```text
2026-10-23T10:15:30Z
2026-10-23T10:15:30.123Z
2026-10-23T10:15:30.123456789Z
```

There is no separate limit on fractional digits; the maximum message length still applies. Parsers and libraries must preserve the supplied fractional digits without silent rounding or truncation, rather than converting timestamps to floating-point numbers.

The number of fractional digits describes representation precision, not clock accuracy. Timestamps require a trustworthy clock. Unavailable or nonexistent timestamps must not be replaced with fabricated dates.

The fictitious receiver uses the simulator host's UTC clock; host synchronization is an environment prerequisite, not a timing guarantee of this protocol. The simulator must also support an untrusted-clock fault scenario. New unreliable UTC timestamps are omitted, while existing event timestamps known to have been acquired reliably are retained. A missing timestamp for an event that never happened is not a clock fault.

Because this receiver declares UTC-clock support, loss of clock trust is an explicit active fault, `CLOCK_UNTRUSTED`, visible through general status and the Device's diagnostic log/alarm state. Omitting timestamps alone is insufficient. This condition need not prevent UTC-independent operations or invalidate otherwise valid readings; operations requiring trustworthy UTC must be rejected while it persists. An apparatus that explicitly declares no UTC capability is not faulty merely for lacking it. No clock-setting or synchronization command is introduced here; synchronization mechanisms and trust assessment on real hardware remain platform-specific.

### Sample Timestamps

`sampled_at` is the UTC timestamp at which the returned value was acquired from the hardware. It is not the time at which the response was generated or transmitted.

If a cached value is returned, `sampled_at` retains its original acquisition timestamp. It must not be replaced with the current time.

When a trustworthy acquisition timestamp is available:

```text
#ok <id=10>: value=5.5, unit=GHz, sampled_at=2026-10-23T10:15:30.123456Z\n
```

Otherwise, the field is omitted:

```text
#ok <id=10>: value=5.5, unit=GHz\n
```

Absence means that no trustworthy acquisition timestamp is available. It does not, by itself, invalidate the returned value. Clients do not need to enable this field. Each hardware specification declares which properties can provide `sampled_at`.

For this receiver, an untrusted clock must additionally be reported as specified above. A Device may record its own receipt time, but must distinguish it from the hardware acquisition time rather than substituting it for `sampled_at`.

## Errors and Diagnostics

An `error` response includes a stable symbolic `code`. It may include structured diagnostic fields and an optional textual `description`.

Software uses codes and structured fields to make decisions. It must not interpret free text for control logic.

When `status` reports a failed procedure, its failure code appears in `error_code`. Failure to retrieve status itself produces an `error` response.

Unsupported functionality, unknown fields, invalid values, and duplicate fields are explicitly rejected. Request validation occurs before hardware side effects.

A failure during execution does not automatically guarantee that the previous hardware state remains unchanged.

### Error Catalog and Human-readable Logs

The common catalog reserves the codes below. Diagnostic field keys are part of the contract; quoted descriptions are not control inputs. A response uses the applicable code and fields rather than a free-text substitute.

| Code | Meaning and principal structured context |
|---|---|
| `INVALID_ID` | No valid, unambiguous request ID; the response has no ID |
| `ID_NOT_INCREASING` | Reused or decreasing ID; `last_id`, recoverable `rejected_verb` and `rejected_name`, optional `received_at` |
| `MALFORMED_REQUEST` | Complete request has invalid syntax but a reliably recoverable valid ID |
| `TOO_MANY_PENDING_REQUESTS` | Request exceeds the connection's admission limit; `limit` |
| `UNKNOWN_VERB` | Verb is unsupported; `verb` |
| `UNKNOWN_PROPERTY` | Property is unsupported; `parameter=name`, `value` |
| `UNKNOWN_PROCEDURE` | Procedure is unsupported; `name` |
| `READ_ONLY_PROPERTY` | A `set` targets a read-only property; `name` |
| `MISSING_PARAMETER` | Required field absent; `parameter` |
| `UNKNOWN_PARAMETER` | Unsupported field supplied; `parameter` |
| `DUPLICATE_PARAMETER` | Field repeated within a section; `parameter` |
| `INVALID_TYPE` | Value has the wrong type; `parameter`, `expected` |
| `OUT_OF_RANGE` | Value outside the allowed interval; `parameter`, applicable `min`, `max`, and `unit` |
| `UNSUPPORTED_UNIT` | Unit is not supported; `parameter=unit`, `expected` |
| `INVALID_PARAMETER` | Other parameter constraint violated; `parameter`, symbolic `reason` |
| `BUSY` | Current activity prevents the requested operation |
| `VALUE_UNAVAILABLE` | Property currently cannot provide a valid value; symbolic `reason` |
| `STATUS_UNAVAILABLE` | A usable status response cannot be obtained |
| `HARDWARE_FAULT` | A known active fault prevents this operation |
| `NOT_RUNNING` | Selected procedure is not active; `name` |
| `NOT_CANCELLABLE` | Procedure or its current phase cannot accept cancellation; `name` |

Codes are stable uppercase identifiers matching `[A-Z][A-Z0-9_]*`. The receiver-specific catalog adds:

| Code | Meaning / default human-readable message |
|---|---|
| `FREQUENCY_LOCK_FAILED` | The synthesizer did not reach and verify the requested frequency within its allowed time |
| `FREQUENCY_READ_FAILED` | The synthesizer frequency could not be read reliably |
| `CALIBRATION_REFERENCE_UNAVAILABLE` | The calibration reference is unavailable |
| `CALIBRATION_TIMEOUT` | Calibration exceeded its execution deadline |
| `SCAN_TIMEOUT` | The scan exceeded its execution deadline |
| `SYNTHESIZER_FAILURE` | Diagnostics confirm a synthesizer fault |
| `STOP_TIMEOUT` | Controlled stop was not confirmed within its deadline |
| `CLOCK_UNTRUSTED` | UTC clock is unavailable or untrusted; new UTC timestamps are omitted |

Common codes also have human-readable catalog messages derived from their definitions, with applicable fields rendered into the log. Define codes, meanings, messages, and hardware-specific parameters together so documentation and generated firmware/library catalogs do not drift. An agent may implement and maintain them from the hardware team's reviewed contract; shared generation provides consistency, not proof that the physical specification is correct.

The library accepts a syntactically valid hardware error even when its code is not built into the library. It preserves the original code, fields, and optional `description`, reports the request error, and does not reconnect, reboot, or retry merely because the code is unfamiliar. Contract validation can separately flag undeclared codes. The log combines a known catalog message with structured context and any supplied description; for an unknown code it explicitly says the code is unrecognized and preserves the supplied description when available. An operator must not need to search a source file to understand a known error. Include Device identity, request ID when known, verb/target when known, and receipt time with its provenance; sanitize and bound any diagnostic text.

### Complete but Malformed Messages

A complete request with a valid recoverable ID but malformed fields returns `MALFORMED_REQUEST`, has no hardware effects, and leaves the connection open. An optional description may explain the syntax problem. A correctly formed out-of-range value instead retains its specific validation error.

```text
REQUEST:
#set <id=30>: name=frequency value=5, unit=GHz\n

RESPONSE:
#error <id=30>: code=MALFORMED_REQUEST\n
```

A malformed ordinary response with a trustworthy pending ID ends that request with a local protocol error, not a receiver-confirmed execution failure. The library preserves the evidence, does not update state from it, keeps other requests and the connection active, and sends no response to a response. A complete response that cannot be attributed safely is logged and discarded; outstanding requests retain their original deadlines. The defined uncorrelated `INVALID_ID` diagnostic is not itself malformed.

## TCP Framing, Limits, and Timeouts

TCP carries a byte stream. A read may contain part of a message or multiple messages. Implementations accumulate bytes and recognize complete messages using LF.

Each implementation declares:

- maximum message length, including LF;
- maximum time to receive an incomplete message;
- maximum response and procedure execution times.

The incomplete-message timeout begins with the first byte and is not restarted by subsequent bytes. An idle connection alone is not an incomplete message.

No request is executed before its entire message has been received and validated.

An oversized message, or one that remains incomplete beyond its deadline, is discarded and the connection closed. If an identifier cannot be recovered reliably, the receiver must not invent one for a response.

The communication library distinguishes at least:

- hardware-reported errors;
- malformed responses;
- unexpected response identifiers;
- timeouts;
- disconnections.

A timeout or disconnection may leave a request's outcome uncertain. Neither proves procedure failure nor authorizes automatic procedure retries.

Timeouts use a monotonic clock, independently of wall-clock adjustments.

### Receiver Profile and Client Defaults

These are concrete values for the fictitious receiver and its first client, not universal limits imposed on every hardware type:

| Setting | Value | Owner / meaning |
|---|---|---|
| Maximum message, including LF | 4096 bytes | Firmware and library receive framing; requests and responses |
| Incomplete-message deadline | 2000 ms | Each receiver of bytes; starts with the first byte, never extended by later bytes |
| Ordinary response deadline | 2000 ms | Client; complete valid response after request transmission finishes |
| TCP connection-attempt deadline | 2000 ms | Client; each initial or recovery connection attempt |
| Pause after failed reconnection | 5000 ms | Client; first recovery attempt is immediate, later attempts wait after failure |
| Pending requests per connection | 4 | Client admission and firmware enforcement; not running procedures after acceptance |
| Procedure-status polling default | 500 ms | Client, configurable; not a firmware capability |
| Frequency application and verification | 1000 ms | Firmware; one `set` or one scan-point tuning phase |
| Calibration execution deadline | 30000 ms | Firmware; includes sequence, final checks, and frequency restoration |
| Scan execution deadline | 20000 ms | Firmware; includes tuning, verification, and all holding intervals |
| Controlled-stop deadline | 5000 ms | Firmware; additional to an expired execution deadline, or after accepted cancellation |

4096 bytes provides room for a complete flat descriptor without adding fragmentation. Short messages do not become padded to that size; implementations must still bound per-connection resource use. Before discovery, the prototype library already enforces the known 4096-byte bootstrap ceiling. The advertised limit is checked against the library's supported/configured limits; it is not permission for unbounded allocation or automatic buffer expansion. Future larger profiles require an explicit compatible bootstrap policy, not oversized discovery messages.

The response timer covers the entire response and is not restarted by partial bytes or by other requests' responses. For `run`, `cancel`, and `reboot`, it waits for `accepted` or `error`, not completion of the long activity. A response deadline and an incomplete-frame deadline are distinct: if a frame remains incomplete, its framing deadline still requires closure even if the associated request has already timed out.

### Persistent Connections and Staged Recovery

TCP connections are persistent, not opened and closed for each request. A normal `error` does not close a connection. Oversized frames and incomplete-frame timeouts do close it, because the framing contract has been violated.

A single response timeout does **not** immediately close a well-framed connection. The library marks only that request timed out and leaves its outcome uncertain. It suspends new modifying requests, coalesces any concurrent recovery needs, and sends one general `status` probe with a new increasing ID and the ordinary response deadline. If IDs are exhausted, bypass the impossible probe and reconnect directly as specified above. It never retransmits the timed-out operation automatically.

- If a usable probe response arrives, retain the connection. A reported hardware fault is still a successful communication probe, not proof of health. Read the affected property or procedure state as needed before dependent operations; a probe alone does not prove the original command's outcome.
- If the probe fails or the transport/framing is broken, close the connection and begin reconnection. Outstanding requests without valid responses retain uncertain outcomes.
- Attempt reconnection immediately, with a 2000 ms limit per TCP attempt and a 5000 ms pause after each failed attempt. Only one attempt runs at a time. Continue while the Device is running and the hardware link is requested; the Device remains reachable for status and diagnostics and explicitly reports the hardware link unavailable.
- On reconnection, read `configuration` and general status before resuming operational writes, checking identity, protocol compatibility, current activity, and faults. Connection success is not proof of health. Do not replay old modifying commands.

Reconnection resets the transport session only; it does not cancel procedures, clear faults, restore operating values, or reboot firmware. No automatic `reboot`, generic `reset`, or speculative `recover` is implied. A firmware that cannot process commands cannot reliably be repaired by sending another command through that same path; watchdogs and external reset belong to the separate protection design.

There is no additional ten-second global reboot-verification timer. Reconnection and visible diagnostics continue until reachability returns; evidence of a new firmware execution is handled using `boot_id` in general status.

## Concurrent Access

Multiple clients may communicate with the hardware. Firmware protects shared state and serializes incompatible changes.

A successful setting response confirms what was applied at that time. It does not prevent another client from changing it later.

Each hardware specification declares incompatibilities between properties and procedures. The protocol does not implicitly provide request queues, procedure ownership, or exclusive control.

The prototype permits four requests awaiting ordinary responses on one connection. The library rejects a fifth local submission rather than creating an implicit queue. If a faulty client nevertheless exceeds the firmware's limit, the firmware rejects only the excess request with `TOO_MANY_PENDING_REQUESTS, limit=4`, keeps the connection open, and continues accepted requests. An admission error does not consume a pending execution slot, but its valid increasing ID is still consumed. A procedure no longer occupies a pending-response slot after its `accepted` response is sent.

Responses may arrive in a different order from requests; each has its own deadline and is matched by ID. The firmware may use simple sequential processing where sufficient. Clients requiring an execution dependency wait for actual completion of the earlier command or procedure, not merely for a later-numbered response. Shared hardware changes remain serialized or rejected according to their incompatibility rules.

Late replies to timed-out requests are diagnostic evidence, not retroactive success and not automatic state updates. An ordinary response with an ID never sent, or a second ordinary response to an already completed request, is a protocol anomaly: record and discard it without completing another request or immediately closing the connection. Normal replies continue; silence invokes the staged timeout recovery. The special `ID_NOT_INCREASING` diagnostic is handled before ordinary pending-response matching so it cannot consume the original request.

## Worked Example: A Fictitious Receiver

This section illustrates the protocol through a fictitious receiver. Its purpose is to make requests, responses, state changes, and failure handling concrete; it does not describe real receiver hardware.

The receiver exposes a `frequency` property and supports procedures such as calibration and scanning. Their behavior is introduced separately.

In the exchanges below, `REQUEST` and `RESPONSE` are explanatory labels and are not transmitted. `\n` represents the message-terminating LF character.

Each example block is an independent exchange or scenario unless a shared connection is explicitly described; repeated IDs across separate blocks do not instruct a client to reuse an ID.

### Reading the Hardware Configuration

`configuration` is a read-only descriptor of the connected apparatus, not a Device configuration file or an operation that changes firmware settings:

```text
REQUEST:
#get <id=1>: name=configuration\n

RESPONSE:
#ok <id=1>: name=configuration, protocol_version=1, hardware_id="example-receiver-01", hardware_model=fictitious_receiver, firmware_version="0.1.0", firmware_build="example-build", readonly_properties=[configuration], readwrite_properties=[frequency], supported_procedures=[calibrate, scan], frequency_min=1, frequency_max=10, frequency_unit=GHz, frequency_resolution=0.000001, frequency_rounding=nearest_ties_up, max_message_bytes=4096, incomplete_message_timeout_ms=2000, max_pending_requests=4, max_tuning_ms=1000, calibrate_timeout_ms=30000, scan_timeout_ms=20000, procedure_stop_timeout_ms=5000, scan_points=10, scan_max_dwell_ms=1000, calibrate_cancellation=except_finalization, scan_cancellation=always, utc_clock_supported=true, sampled_at_properties=[frequency]\n
```

This is one ASCII line, terminated by one LF. Identity and build strings above are illustrative, not claims about installed firmware. Names of fields and the receiver-profile values in this example define its flat descriptor; no nested lists, embedded JSON, or truncation are used. The complete response must fit within the bootstrap/message limit. A future need for larger descriptions may justify section queries, but they are not part of this prototype.

The descriptor declares:

- **Identity:** `hardware_id` identifies the apparatus; `hardware_model` identifies its model; `firmware_version` is its human-facing version and `firmware_build` uniquely identifies the installed build. Release labels alone must not ambiguously identify different binaries.
- **Protocol:** `protocol_version=1` identifies these common wire and interaction rules, independently of firmware release numbering. Compatible firmware bug fixes do not require a new protocol version. Unsupported protocol versions are explicit incompatibilities: do not enable operational writes by assuming compatibility or substituting a local profile.
- **Property access:** every exposed property appears in exactly one of `readonly_properties` and `readwrite_properties`. Both support `get`; only the second supports `set`. The prototype has no write-only property class. These are capabilities, not user permissions or promises of availability in every activity. Listing a property twice is a descriptor error. `configuration` itself is read-only; attempting to set it is rejected.
- **Procedures:** `supported_procedures` identifies supported `run` targets. Cancellation policies describe support, not permission to infer that an already completed procedure can still be cancelled.
- **Frequency:** minimum, maximum, unit, grid resolution, and `nearest_ties_up` approximation, as defined below. Other hardware profiles define their own property characteristics; this document does not prescribe 1 kHz or GHz universally.
- **Firmware limits:** message size, framing deadline, pending-request admission, tuning, procedure execution, controlled stop, fixed scan count, and maximum dwell. Their units appear in their field names where needed. Client connection/response deadlines, reconnect pauses, polling, and Device caching are not firmware settings.
- **UTC capability:** whether trustworthy UTC is supported in principle, and which property acquisitions can supply `sampled_at`. Availability is assessed at runtime; declaration of support is not proof that the current clock is trusted. Boot identity, boot time, current faults, and activity belong to `status`, not this descriptor.

Read and validate the descriptor on initial connection and reconnection. Validate required fields, types, ranges, coherent access lists, declared limits, and expected identity before resuming operational writes. Merely opening TCP is not application readiness. An incompatible or malformed descriptor remains an observable compatibility/conformance problem, not a reason to pretend that the hardware has a different configuration.

### Hardware Authority, Local Profiles, and Device Configuration

Firmware is authoritative for its physical capabilities and must enforce them even if the Device also validates requests. Do not duplicate or override them casually in a Device file. Optional installation-specific operating restrictions may narrow what Synqaro permits, never enlarge hardware capability; the prototype does not require additional restrictions. An inconsistent restriction/profile is reported, not silently clipped or substituted.

For legacy hardware that explicitly reports `UNKNOWN_PROPERTY, parameter=name, value=configuration`, the Device may use an approved static profile matched to the expected apparatus/model/firmware using reliable deployment or identification information. If neither a usable descriptor nor a compatible approved profile is available, report the missing contract and disable affected operational writes; safe reads and diagnostics may remain available where their interface is known. A timeout, broken transport, malformed response, unknown identity, or incompatible protocol version does **not** trigger this fallback.

The hardware team supplies a reviewed specification from which an agent can implement firmware, descriptors, validation, and error catalogs. Validate that specification and its implementation against real hardware independently; generating both sides from the same mistaken input does not establish correctness.

Device-owned settings remain separate: connection target, client timeouts, polling, per-property cache policy, monitoring thresholds, and any optional operating restrictions. Temperature readings may be read-only while their monitoring thresholds are configurable. Supervisory thresholds do not replace hardware/PLC protections. Persistent configuration, live threshold changes, and historical reconstruction are requirements; file format, update interface, persistence/activation guarantees, and history storage remain explicit [open issues](#device-configuration-persistence-and-historical-reconstruction). No agent is required in the runtime control path.

### Setting the Frequency

For this example, the `frequency` property accepts:

- one numeric value, including integers and decimals;
- values between `1` and `10`, inclusive;
- the explicit unit `GHz`;
- a 1 kHz grid (`0.000001 GHz`), with approximation to the nearest grid value and ties to the higher frequency.

Strings, booleans, and lists are not valid frequency values. The receiver does not implicitly convert units.

The request is:

```text
#set <id=10>: name=frequency, value=5.5, unit=GHz\n
```

The receiver validates the entire request before changing the hardware. It returns `ok` only after the frequency has been applied. It does not return `accepted`: prolonged activities belong to procedures started through `run`.

#### Successful Setting

```text
REQUEST:
#set <id=10>: name=frequency, value=5.5, unit=GHz\n

RESPONSE:
#ok <id=10>: name=frequency, value=5.5, unit=GHz\n
```

The response identifies the property and confirms its verified applied value, not merely the requested text. First validate the original numeric value against the interval; then approximate to the declared grid. Never use rounding to bring an out-of-range request back inside the interval. Equivalent forms such as `005.50` and `5.5e0` represent the same requested value.

```text
REQUEST:
#set <id=21>: name=frequency, value=5.1234565, unit=GHz\n

RESPONSE:
#ok <id=21>: name=frequency, value=5.123457, unit=GHz\n
```

Rounding is explicit profile behavior, not truncation or a language-dependent floating-point side effect. The response always exposes the verified result. Applying and verifying one frequency must finish within `max_tuning_ms=1000`; failure returns `FREQUENCY_LOCK_FAILED` and does not establish what frequency remains applied.

Setting the current frequency again is valid and returns `ok`. It does not start a separate procedure.

Changing the operating frequency invalidates the calibration associated with the previous configuration. Setting the same effective grid frequency does not, by itself, invalidate calibration, even if the original numeric spelling or requested excess digits differ.

#### Value Outside the Allowed Range

```text
REQUEST:
#set <id=11>: name=frequency, value=100, unit=GHz\n

RESPONSE:
#error <id=11>: code=OUT_OF_RANGE, parameter=value, min=1, max=10, unit=GHz\n
```

The request is rejected. The previous frequency remains unchanged.

#### Invalid Value Type

```text
REQUEST:
#set <id=12>: name=frequency, value="5.5", unit=GHz\n

RESPONSE:
#error <id=12>: code=INVALID_TYPE, parameter=value, expected=number\n
```

`"5.5"` is a string, not a number. The firmware does not perform implicit type conversion. A boolean or list is rejected in the same way.

#### Missing Required Parameter

```text
REQUEST:
#set <id=13>: name=frequency, unit=GHz\n

RESPONSE:
#error <id=13>: code=MISSING_PARAMETER, parameter=value\n
```

Missing `name` or `unit` is handled using the same code and the corresponding parameter name. No hardware change occurs.

#### Unsupported Unit

```text
REQUEST:
#set <id=14>: name=frequency, value=5500, unit=MHz\n

RESPONSE:
#error <id=14>: code=UNSUPPORTED_UNIT, parameter=unit, expected=GHz\n
```

Although the requested quantity could be converted to GHz, this fictitious receiver requires the documented unit. The request is rejected without changing the frequency.

#### Unknown or Duplicate Parameter

An unknown parameter is rejected rather than ignored:

```text
REQUEST:
#set <id=15>: name=frequency, value=5.5, unit=GHz, gain=10\n

RESPONSE:
#error <id=15>: code=UNKNOWN_PARAMETER, parameter=gain\n
```

A repeated parameter is also rejected:

```text
REQUEST:
#set <id=16>: name=frequency, value=5.5, value=6, unit=GHz\n

RESPONSE:
#error <id=16>: code=DUPLICATE_PARAMETER, parameter=value\n
```

The receiver does not choose between duplicate values. Neither request changes the hardware.

#### Frequency Temporarily Unavailable for Modification

Frequency changes are prohibited while calibration controls the receiver's tuning.

```text
REQUEST:
#set <id=17>: name=frequency, value=6, unit=GHz\n

RESPONSE:
#error <id=17>: code=BUSY, description="Frequency changes are not allowed during calibration"\n
```

The request is rejected, not queued. Calibration continues unaffected.

The library interprets `BUSY`; the optional description supplies human-readable context.

#### Hardware Failure During Application

A valid request may fail after hardware execution has begun:

```text
REQUEST:
#set <id=18>: name=frequency, value=6, unit=GHz\n

RESPONSE:
#error <id=18>: code=FREQUENCY_LOCK_FAILED, description="Synthesizer did not lock within the allowed time"\n
```

Unlike a validation error, this failure does not guarantee that the previous frequency remains applied. The receiver must expose the resulting state truthfully through subsequent reads and status queries. It must not present the requested value, or the previous value, as valid without evidence.

#### Missing Response or Disconnection

```text
REQUEST:
#set <id=19>: name=frequency, value=6, unit=GHz\n

RESPONSE:
No complete response is received before the client timeout.
```

The timeout is detected locally by the communication library. It is not an `error` response from the receiver.

The client cannot infer whether the setting was applied. It follows staged recovery: one status probe before deciding whether to reconnect, then a fresh frequency read when permitted. It does not use a Device-cache hit to resolve an uncertain setting. A timeout alone must not be reported as a confirmed hardware execution failure.

#### Multiple Clients

```text
CLIENT A REQUEST:
#set <id=20>: name=frequency, value=5, unit=GHz\n

RESPONSE TO A:
#ok <id=20>: name=frequency, value=5, unit=GHz\n

CLIENT B REQUEST:
#set <id=20>: name=frequency, value=6, unit=GHz\n

RESPONSE TO B:
#ok <id=20>: name=frequency, value=6, unit=GHz\n
```

The identical identifiers are valid because A and B use different TCP connections.

The receiver serializes the changes. In the order shown, the final frequency is 6 GHz. A's response confirms that its setting was applied; it does not reserve that frequency or prevent B from changing it.

### Reading the Frequency

The `get` request reads the receiver's current operating frequency without modifying its configuration.

```text
#get <id=30>: name=frequency\n
```

For this receiver, successful responses return one numeric value in `GHz`. The request does not accept `value` or `unit`: unit conversion is outside this example's contract.

#### Successful Reading

```text
REQUEST:
#get <id=30>: name=frequency\n

RESPONSE:
#ok <id=30>: name=frequency, value=5.5, unit=GHz, sampled_at=2026-10-23T10:15:30.123456Z\n
```

The response reports the operating frequency acquired from the hardware. `sampled_at` identifies the acquisition time, not the response transmission time.

A successful reading confirms the value observed at acquisition. It does not guarantee that the frequency remains unchanged afterward.

#### Acquisition Timestamp Unavailable

```text
REQUEST:
#get <id=31>: name=frequency\n

RESPONSE:
#ok <id=31>: name=frequency, value=5.5, unit=GHz\n
```

The value is available, but no trustworthy acquisition timestamp is available. Omitting `sampled_at` does not, by itself, invalidate the reading. In this UTC-capable receiver, clock distrust is also visible through `CLOCK_UNTRUSTED` in general status and the Device's log/alarm state; timestamp omission must not hide the condition.

#### Device Cache Boundary

The fictitious firmware has no additional acquisition cache: each wire-level `get frequency` reads its current simulated hardware state. The Device may reuse its own previously acquired observation according to its per-property configuration. A Device cache hit is **not** another TCP exchange and allocates no request ID.

The default maximum reuse interval is 500 ms, overridable per property; zero disables reuse. Measure the local reuse interval with a monotonic clock from receipt of the fresh reply. This interval does not certify absolute hardware sample age or clock synchronization. Keep the original acquisition timestamp and quality, never relabel a cached sample with the current time. Polling cadence is a separate setting.

Invalidate a cached property on known changes, loss of the hardware connection, or conditions that make it unreliable. Invalidate frequency when a modifying attempt begins; do not seed an acquired-value cache merely from a requested `set`. During autonomous calibration/scan, uncertain-outcome recovery, or other known uncontrolled frequency changes, do not reuse frequency cache entries: acquire a new value when permitted or expose unavailability. A TTL is a reuse ceiling, not permission to hide a known fault or to guarantee that an external client has not changed the hardware meanwhile.

The cache policy is persistent **Device** configuration, not a firmware setting and not part of hardware `get configuration`. Retaining a setting does not make cached measurements valid after restart or reconnect. The Device's concrete configuration API and cache-bypass interface remain implementation work; clients that need fresh observations must be able to request them without confusing a cache hit with a new hardware acquisition.

#### Frequency Unavailable During Calibration

In this example, calibration takes control of tuning, so the operating frequency is temporarily unavailable.

```text
REQUEST:
#get <id=33>: name=frequency\n

RESPONSE:
#error <id=33>: code=VALUE_UNAVAILABLE, reason=CALIBRATING\n
```

This is an expected temporary condition, not evidence of a hardware fault. The receiver must not substitute the frequency used before calibration.

#### Hardware Read Failure

```text
REQUEST:
#get <id=34>: name=frequency\n

RESPONSE:
#error <id=34>: code=FREQUENCY_READ_FAILED, description="Unable to read the synthesizer frequency"\n
```

The firmware attempted the hardware read but could not obtain a valid value. It does not return a guessed frequency or silently substitute an invalid cached value.

This error is distinct from temporary unavailability during calibration. It also does not prove that the physical frequency changed: the failure concerns the ability to determine it.

#### Missing Property Name

```text
REQUEST:
#get <id=35>\n

RESPONSE:
#error <id=35>: code=MISSING_PARAMETER, parameter=name\n
```

The receiver rejects the request without performing a property read.

#### Unsupported Parameter

```text
REQUEST:
#get <id=36>: name=frequency, unit=MHz\n

RESPONSE:
#error <id=36>: code=UNKNOWN_PARAMETER, parameter=unit\n
```

The receiver does not silently ignore the requested unit or interpret it as a conversion request.

Duplicate parameters are rejected using `DUPLICATE_PARAMETER`, as defined for `set`.

#### Missing Response or Disconnection

```text
REQUEST:
#get <id=37>: name=frequency\n

RESPONSE:
No complete response is received before the client timeout.
```

The communication library reports a timeout or disconnection, not a receiver-generated error.

The client has no new frequency observation. A subsequent `get` obtains a new reading; it does not recover the value that would have been returned by the unanswered request.

#### Reading After Another Client Changes the Frequency

```text
CLIENT A REQUEST:
#set <id=38>: name=frequency, value=5, unit=GHz\n

RESPONSE TO A:
#ok <id=38>: name=frequency, value=5, unit=GHz\n

CLIENT B REQUEST:
#set <id=39>: name=frequency, value=6, unit=GHz\n

RESPONSE TO B:
#ok <id=39>: name=frequency, value=6, unit=GHz\n

CLIENT A REQUEST:
#get <id=40>: name=frequency\n

RESPONSE TO A:
#ok <id=40>: name=frequency, value=6, unit=GHz\n
```

The reading reflects the current hardware state, not the value last requested by client A. Request identifiers correlate exchanges; they do not reserve properties or associate a later reading with an earlier setting.

### General Receiver Status

The `status` request without `name` reads the receiver's general operating state:

```text
#status <id=50>\n
```

It does not modify the configuration, clear diagnostic information, or interrupt an activity. The response describes a coherent snapshot; the receiver may change state afterward.

#### Status Fields

| Field | Meaning |
|---|---|
| `health` | `ok`, `fault`, or `unknown`, according to the receiver's diagnostic checks |
| `activity` | `idle`, the current activity, or `unknown` if it cannot be determined |
| `calibrated` | Whether a calibration is valid for the current configuration |
| `boot_id` | Opaque identity of the current firmware execution; unchanged across reconnections, changed on every firmware restart |
| `booted_at` | UTC timestamp of the current firmware execution's startup, when trustworthy |
| `fault_codes` | Always-present flat list of active, confirmed fault codes; empty when none are confirmed |

`health=ok` does not imply that the receiver is calibrated or available for every operation. These are separate conditions.

`calibrated` is a boolean. If calibration validity cannot be determined, the field is omitted rather than reporting a guessed value. `booted_at` follows the general timestamp availability rules.

The operating frequency is read through `get`; this general status response does not duplicate it.

`boot_id` answers **which firmware execution**; `booted_at` answers **when it began**. For this profile use a fresh opaque 32-character lowercase hexadecimal token per firmware start, independent of UTC, and compare it as a string. Example tokens below are illustrative. A simulated reboot must generate a new token even if the host process is reused. No procedure execution identity is introduced, and a changed token does not prove which client, watchdog, or external action caused the restart.

General status determines health from synthesizer diagnostics, control/stop verification, and the declared UTC clock capability, not the last request result. Confirmed active faults take precedence (`fault`); with no confirmed fault, report `ok` only when required checks suffice, otherwise `unknown`. Validation errors, `BUSY`, `NOT_CANCELLABLE`, and lack of calibration are not faults by themselves. A calibration-reference failure need not make otherwise usable tuning faulty.

`fault_codes` replaces the singular `fault_code`. It is a list of **current confirmed conditions**, not incident history. `health=fault` requires at least one code; an empty list with `health=unknown` is not evidence of health. Remove an active code only after checks confirm resolution, never merely because another command succeeds. Preserve incident history in diagnostics even after a condition clears. Faults may coexist, for example `[SYNTHESIZER_FAILURE, CLOCK_UNTRUSTED]`. Fault-specific operating restrictions apply; `health=fault` does not automatically block every operation.

Activity describes the procedure lifecycle and verified stop state. Report `idle` only when no procedure is active and no stop remains unconfirmed. Report `calibrating` or `scanning` while that execution remains active, including during `cancelling`; the specific cancellation state belongs to the procedure status. Use `unknown` if actual activity cannot be established. An unconfirmed stop after its deadline adds `STOP_TIMEOUT`; keep the known activity if execution is confirmed continuing, otherwise report `unknown`. A stopped software task alone is not proof of a stopped apparatus. Short-command preconditions and transient tuning availability remain separate from the long-procedure activity field.

#### Available Receiver, Not Calibrated

```text
REQUEST:
#status <id=50>\n

RESPONSE:
#ok <id=50>: health=ok, activity=idle, calibrated=false, fault_codes=[], boot_id="11111111111111111111111111111111", booted_at=2026-10-23T09:00:00Z\n
```

The receiver reports no known fault and no activity in progress. It does not currently have a valid calibration.

`activity=idle` does not grant exclusive control or guarantee that every subsequent request will be accepted.

#### Activity in Progress

```text
REQUEST:
#status <id=51>\n

RESPONSE:
#ok <id=51>: health=ok, activity=calibrating, calibrated=false, fault_codes=[], boot_id="11111111111111111111111111111111", booted_at=2026-10-23T09:00:00Z\n
```

An activity is running, but this is not itself a fault. Restrictions on other requests depend on the activity's contract.

Detailed progress and outcome information belongs to the procedure-specific status query described with that procedure.

#### Receiver Fault

```text
REQUEST:
#status <id=52>\n

RESPONSE:
#ok <id=52>: health=fault, activity=idle, calibrated=false, fault_codes=[SYNTHESIZER_FAILURE], boot_id="11111111111111111111111111111111", booted_at=2026-10-23T09:00:00Z\n
```

`ok` means that the status query succeeded. `health=fault` means that the receiver reports a hardware fault.

A failure of an individual request does not automatically set `health=fault`; the receiver's diagnostic rules determine whether the condition affects its operating health.

#### Startup Timestamp Unavailable

```text
REQUEST:
#status <id=53>\n

RESPONSE:
#ok <id=53>: health=fault, activity=idle, calibrated=false, fault_codes=[CLOCK_UNTRUSTED], boot_id="22222222222222222222222222222222"\n
```

This execution began without trustworthy UTC, so `booted_at` is absent and `CLOCK_UNTRUSTED` is explicit. The receiver can still report its boot identity and operating state. If the clock instead becomes untrusted after a reliably timestamped boot, retain that historical `booted_at` while omitting unreliable new timestamps. The fault remains visible while clock trust is absent.

#### Status Cannot Be Determined

If some information is unavailable, the receiver reports uncertainty using the field rules above. It must not substitute a healthy or idle state.

If it cannot provide a usable general status response:

```text
REQUEST:
#status <id=54>\n

RESPONSE:
#error <id=54>: code=STATUS_UNAVAILABLE\n
```

This differs from successfully reporting a known fault.

If no complete response arrives, the communication library reports a timeout or disconnection. It must not interpret silence as `health=ok` or as a confirmed hardware fault.

This section describes general receiver status. Procedure-specific status queries, selected through `name`, are explained alongside the corresponding `run` procedures below.

### Running Calibration

The calibration procedure performs the receiver's calibration sequence. It is started through `run` and monitored through `status`.

For this fictitious receiver:

- only one calibration can execute at a time;
- starting calibration invalidates the previous calibration;
- calibration takes control of tuning;
- the starting operating frequency is saved and restored before success is declared;
- failure or cancellation leaves the receiver uncalibrated.

The receiver accepts no additional calibration parameters in this example. Normal simulated execution is approximately 10 seconds; the firmware deadline is 30 seconds from actual execution start, including final checks and restoration of the saved frequency. The normal duration is not a success criterion or a fabricated progress source. It remains independent of the client's two-second acceptance-response deadline.

Calibration accepts cancellation during its ordinary sequence but has a brief final coefficient-application/finalization phase that rejects client cancellation with `NOT_CANCELLABLE`. No stop timer starts for a rejected cancellation. The execution deadline still applies during that phase; a deadline-triggered stop is handled according to the controlled-stop rules, never hidden behind an indefinitely non-cancellable phase. Exact simulator phase scheduling is implementation detail to document with its tests.

#### Starting Calibration

```text
REQUEST:
#run <id=60>: name=calibrate\n

RESPONSE:
#accepted <id=60>\n
```

Before returning `accepted`, the firmware validates the request and registers the new attempt so that its state is immediately queryable.

`accepted` confirms that the procedure has been accepted for execution, not that calibration has succeeded. The receiver sends no subsequent notification for request `60`.

If calibration finishes before the client queries its status, that query returns the completed outcome.

#### Inspecting Execution

```text
REQUEST:
#status <id=61>: name=calibrate\n

RESPONSE:
#ok <id=61>: name=calibrate, state=running, started_at=2026-10-23T10:20:00Z, progress=40\n
```

`id=61` identifies the status query. It does not refer to the earlier request identifier.

`progress` is optional and is included only when meaningful advancement can be measured. The firmware must not invent percentages solely from elapsed time.

`started_at` records the actual execution start when a trustworthy timestamp is available.

#### Successful Completion

```text
REQUEST:
#status <id=62>: name=calibrate\n

RESPONSE:
#ok <id=62>: name=calibrate, state=succeeded, started_at=2026-10-23T10:20:00Z, finished_at=2026-10-23T10:20:10Z\n
```

Success requires completion of the calibration sequence, its final checks, and restoration of the saved operating frequency.

The general receiver status then reports `calibrated=true`. If frequency restoration fails, the procedure reports failure instead of success.

The completed state remains available until another calibration attempt starts. Reading it does not clear it.

#### Request Rejected Before Execution

If calibration is already running or cancellation is pending:

```text
REQUEST:
#run <id=63>: name=calibrate\n

RESPONSE:
#error <id=63>: code=BUSY, description="Calibration is already in progress"\n
```

No second attempt is created or queued. The current calibration or its cancellation continues.

If a known hardware fault prevents execution:

```text
REQUEST:
#run <id=64>: name=calibrate\n

RESPONSE:
#error <id=64>: code=HARDWARE_FAULT\n
```

A rejected request does not replace the state or outcome of the previous calibration attempt.

Missing, unknown, or duplicate parameters are rejected using the common validation rules before execution begins.

#### Failure After Acceptance

A procedure may fail after its initial acceptance:

```text
REQUEST:
#status <id=65>: name=calibrate\n

RESPONSE:
#ok <id=65>: name=calibrate, state=failed, started_at=2026-10-23T10:20:00Z, finished_at=2026-10-23T10:20:04Z, error_code=CALIBRATION_REFERENCE_UNAVAILABLE\n
```

The status query succeeded, so the response is `ok`. The procedure failed, so its state is `failed` and its diagnostic code appears in `error_code`.

An optional `description` may provide additional context. Software interprets the symbolic code, not the description.

The receiver remains uncalibrated. Its resulting frequency must be obtained through `get`; neither the saved nor requested frequency may be assumed valid without evidence.

A failed calibration does not automatically imply `health=fault`. General health depends on whether the underlying condition prevents normal receiver operation.

#### Other Requests During Calibration

While calibration controls tuning:

| Request | Behavior |
|---|---|
| General `status` | Remains available |
| Calibration-specific `status` | Remains available |
| `get` of `frequency` | Returns `VALUE_UNAVAILABLE` with `reason=CALIBRATING` |
| `set` of `frequency` | Returns `BUSY` |
| Another calibration or scan request | Returns `BUSY` |

The receiver must remain responsive to status queries while calibration executes.

#### Cancellation States

The cancellation request itself is described in [Cancelling a Procedure](#cancelling-a-procedure). Calibration exposes these states while interruption is handled:

```text
REQUEST:
#status <id=66>: name=calibrate\n

RESPONSE:
#ok <id=66>: name=calibrate, state=cancelling, started_at=2026-10-23T10:20:00Z\n
```

Once execution has actually stopped:

```text
REQUEST:
#status <id=67>: name=calibrate\n

RESPONSE:
#ok <id=67>: name=calibrate, state=cancelled, started_at=2026-10-23T10:20:00Z, finished_at=2026-10-23T10:20:05Z\n
```

`cancelled` must not be reported while calibration is still executing. The receiver remains uncalibrated; cancellation does not guarantee restoration of the starting frequency.

#### Excessive Execution Time

At 30 seconds without completion, the firmware initiates a controlled stop with an additional five-second deadline. The 30-second limit is not a claim that hardware is already stopped. Do not declare failure as a completed procedure until execution is confirmed stopped.

After execution has stopped, it records failure:

```text
REQUEST:
#status <id=68>: name=calibrate\n

RESPONSE:
#ok <id=68>: name=calibrate, state=failed, started_at=2026-10-23T10:20:00Z, finished_at=2026-10-23T10:20:32Z, error_code=CALIBRATION_TIMEOUT\n
```

Here execution was actually stopped two seconds after the execution deadline. If stop is still unconfirmed after five seconds, expose `STOP_TIMEOUT` through general status and preserve the known activity or report `unknown`, rather than declaring `idle`, `failed` as a completed execution, or `cancelled`. Prevent incompatible operations while stopping or uncertainty persists.

The communication library independently limits how long it waits. Its own timeout does not prove that calibration has failed or stopped.

#### Disconnection and Reconnection

Calibration continues if its client's TCP connection closes.

After reconnecting, any client can query:

```text
REQUEST:
#status <id=1>: name=calibrate\n
```

This returns the current attempt or the latest retained outcome, regardless of which client initiated it.

The same recovery applies if the initial `accepted` response was lost. The client must not automatically start another calibration merely because acceptance was not received.

There is no identifier for a particular attempt. If another client starts a new calibration, subsequent queries describe that newer attempt. Timestamps provide context but are not execution identifiers.

#### Unavailable Execution History

When the receiver knows that no calibration has started within its retained observation period:

```text
#ok <id=69>: name=calibrate, state=never_started\n
```

If execution history is unavailable, for example after a restart without retained state:

```text
#ok <id=70>: name=calibrate, state=unknown\n
```

Neither state includes invented execution timestamps. The receiver must not infer success or failure from missing history.

### Running a Frequency Scan

The `scan` procedure moves the receiver through a sequence of operating frequencies, holding each frequency for a specified duration.

This example performs tuning only. It does not acquire a spectrum or produce scientific measurement data. It does not guarantee association between externally acquired data and operating frequency. That remains an [open issue](#associating-scan-data-with-frequency); adding timestamps to individual `get` responses is not sufficient to resolve it.

#### Parameters

| Parameter | Meaning |
|---|---|
| `name` | Must be `scan` |
| `start` | Requested first frequency |
| `stop` | Requested last frequency, included after declared grid rounding |
| `unit` | Must be `GHz` |
| `dwell_ms` | Decimal integer from 1 through 1000 specifying holding time at each frequency |

This receiver always uses **10 distinct points**, including both endpoints. There is no `step` or variable point-count parameter. This replaces the earlier variable-step/1000-point proposal; the fixed count reduces prototype inputs while retaining tuning, holding, cancellation, and failure scenarios.

Validate the original endpoints within 1 through 10 GHz before rounding them to the 1 kHz grid using `nearest_ties_up`. Let the rounded endpoint grid indices be `a` and `b`. For `i` from 0 through 9, compute the nominal frequency at `a + i * (b - a) / 9` and round it to the nearest supported grid index, with ties to the higher frequency. Use exact rational/decimal or equivalent integer arithmetic, not accumulated floating-point increments. The first and last targets equal the rounded endpoints; direction may be ascending or descending. Effective adjacent steps may differ by one grid increment: exact equidistance is not promised.

Reject the request if the generated sequence is not strictly monotonic and distinct. This requires a rounded endpoint span of at least nine grid increments (9 kHz); equal or collapsed endpoints do not create a special one-point scan. There is no requirement that the span be exactly divisible by nine.

Before acceptance, validate the conservative duration budget `10 * (max_tuning_ms + dwell_ms) <= scan_timeout_ms`. With the declared limits this gives `dwell_ms <= 1000`. The budget uses the maximum allowed tuning and verification time, not its average; actual faster tuning does not add padding to reach 20 seconds. The 20-second execution deadline is still enforced if runtime delays or faults occur. It is an operational deadline, not a hard-real-time guarantee.

#### Starting a Scan

```text
REQUEST:
#run <id=100>: name=scan, start=5, stop=5.2, unit=GHz, dwell_ms=1000\n

RESPONSE:
#accepted <id=100>\n
```

The resulting target sequence in GHz is:

```text
5, 5.022222, 5.044444, 5.066667, 5.088889,
5.111111, 5.133333, 5.155556, 5.177778, 5.2
```

These are planned tuning targets, not scientific measurements or proof that every target was reached.

At each point, the receiver:

1. Applies and verifies the frequency.
2. Holds it for `dwell_ms`.
3. Advances to the next point, if any.

Holding time starts after the frequency has been successfully applied. It applies to every point, including the last. Total duration therefore includes both tuning and holding times.

The complete request is validated before tuning begins. Before returning `accepted`, the firmware registers the attempt so that its state is queryable.

#### Inspecting Execution

```text
REQUEST:
#status <id=101>: name=scan\n

RESPONSE:
#ok <id=101>: name=scan, state=running, started_at=2026-10-23T10:30:00Z, points_completed=1, points_total=10, progress=10\n
```

A point is completed only after its frequency has been applied and its holding time has elapsed.

`progress` is optional. If reported, it is based on completed points rather than an assumed execution duration.

Execution timestamps follow the general availability rules. No unsolicited notifications are sent.

#### Successful Completion

```text
REQUEST:
#status <id=102>: name=scan\n

RESPONSE:
#ok <id=102>: name=scan, state=succeeded, started_at=2026-10-23T10:30:00Z, finished_at=2026-10-23T10:30:11Z, points_completed=10, points_total=10\n
```

Success means every point was completed. The receiver remains at the rounded `stop` target; it does not automatically restore the frequency preceding the scan. The duration above is illustrative, not a required normal duration.

The outcome remains available until another scan starts. Reading status does not clear it.

Changing the operating frequency invalidates the calibration associated with the previous configuration. Scanning does not perform calibration.

#### Invalid Parameters

```text
REQUEST:
#run <id=103>: name=scan, start=5, stop=5.000001, unit=GHz, dwell_ms=1000\n

RESPONSE:
#error <id=103>: code=INVALID_PARAMETER, parameter=stop, reason=INSUFFICIENT_DISTINCT_POINTS\n
```

No scan starts and the frequency remains unchanged.

Missing parameters, invalid types, unsupported units, original endpoints outside the allowed interval, dwell outside 1 through 1000 ms, and insufficient distinct targets are rejected before execution. A supplied `step` or point-count parameter is rejected as `UNKNOWN_PARAMETER`. A rejected request does not replace a previous scan's retained outcome. `INVALID_PARAMETER` reasons for this profile include `INSUFFICIENT_DISTINCT_POINTS` and `EXECUTION_BUDGET_EXCEEDED`; numeric conversion beyond supported capacity uses `UNREPRESENTABLE_VALUE`. The earlier proposal to require exact, unrounded scan parameters is superseded by this fixed-point target-generation rule.

#### Conflicting Requests

Calibration and scanning both require control of tuning and cannot execute together.

```text
REQUEST:
#run <id=104>: name=scan, start=5, stop=6, unit=GHz, dwell_ms=1000\n

RESPONSE:
#error <id=104>: code=BUSY, description="Calibration currently controls receiver tuning"\n
```

While a scan is running or being cancelled:

| Request | Behavior |
|---|---|
| General or scan-specific `status` | Remains available |
| `get` of `frequency` | Returns the acquired operating frequency when valid |
| `set` of `frequency` | Returns `BUSY` |
| Another scan or calibration | Returns `BUSY` |

During a tuning transition, if no valid operating frequency is available, `get` returns `VALUE_UNAVAILABLE` with `reason=TUNING`. It must not report the next target as already applied. The query remains serviceable, but a numeric result cannot be guaranteed during transitions or hardware faults.

#### Hardware Failure During Scanning

```text
REQUEST:
#status <id=105>: name=scan\n

RESPONSE:
#ok <id=105>: name=scan, state=failed, started_at=2026-10-23T10:30:00Z, finished_at=2026-10-23T10:30:02.1Z, points_completed=1, points_total=10, error_code=FREQUENCY_LOCK_FAILED\n
```

The receiver stops advancing through the sequence. It does not silently skip the failed point.

No automatic frequency restoration is assumed. The resulting operating frequency must be determined through `get`; if it cannot be determined, the receiver reports its unavailability.

Each tuning/verification phase is limited to one second. If the overall execution exceeds 20 seconds, initiate controlled stop; once stopped, record `failed` with `error_code=SCAN_TIMEOUT`. The additional stop deadline is five seconds, and expiration without a verified stop produces an active `STOP_TIMEOUT` fault rather than a false terminal or idle state.

#### Cancelling a Scan

```text
REQUEST:
#cancel <id=106>: name=scan\n

RESPONSE:
#accepted <id=106>: name=scan\n
```

The client then queries the scan:

```text
REQUEST:
#status <id=107>: name=scan\n

RESPONSE:
#ok <id=107>: name=scan, state=cancelled, started_at=2026-10-23T10:30:00Z, finished_at=2026-10-23T10:30:01.5Z, points_completed=1, points_total=10\n
```

While interruption is pending, the state is `cancelling`. The receiver reports `cancelled` only after execution has stopped.

Cancellation does not restore the starting frequency. The receiver retains the last successfully applied frequency where it can verify that value; otherwise, its frequency is reported as unavailable.

The scan accepts cancellation throughout active execution, including tuning and holding. The [common cancellation rules](#cancelling-a-procedure) apply, including safe-stop confirmation, races with normal completion, and repeated cancellation requests. Support for cancellation is not a guarantee that malfunctioning hardware will actually stop.

#### Disconnection and Retained State

A scan continues if its client's connection closes. Any client may reconnect and inspect it using `status` with `name=scan`.

A lost acceptance response does not justify automatically starting another scan.

Queries describe the current scan or its latest retained outcome, not a specific client's execution. If execution history is lost after a restart, the receiver reports `unknown` rather than inferring an outcome.

### Cancelling a Procedure

The `cancel` request asks the receiver to stop an active procedure. It selects the procedure through `name`:

```text
#cancel <id=80>: name=calibrate\n
```

Cancellation targets the selected procedure currently executing when the receiver processes the request, regardless of which client started it. It does not identify a particular execution attempt.

`cancel` returns `accepted` or `error`. Acceptance confirms that the stop request has been accepted for processing; it does not confirm that execution has stopped.

Cancellation does not create a separate procedure. Its outcome is observed through the target procedure's status.

#### Cancellation Accepted

```text
REQUEST:
#cancel <id=80>: name=calibrate\n

RESPONSE:
#accepted <id=80>: name=calibrate\n
```

The receiver requests interruption of calibration and prevents a replacement calibration from starting while interruption is pending.

No subsequent notification is sent for request `80`.

#### Interruption in Progress

```text
REQUEST:
#status <id=81>: name=calibrate\n

RESPONSE:
#ok <id=81>: name=calibrate, state=cancelling, started_at=2026-10-23T10:20:00Z\n
```

`started_at` still refers to the calibration attempt, not to the cancellation request.

The receiver must not report `cancelled` until execution has actually stopped.

#### Cancellation Completed

```text
REQUEST:
#status <id=82>: name=calibrate\n

RESPONSE:
#ok <id=82>: name=calibrate, state=cancelled, started_at=2026-10-23T10:20:00Z, finished_at=2026-10-23T10:20:05Z\n
```

`finished_at` records when the procedure ended. The consequences for calibration validity and operating frequency follow the calibration contract.

Cancellation does not erase the procedure's retained state or diagnostic information.

#### Procedure Not Running

```text
REQUEST:
#cancel <id=83>: name=calibrate\n

RESPONSE:
#error <id=83>: code=NOT_RUNNING, name=calibrate\n
```

No cancellation occurs. The previous outcome remains unchanged.

If calibration completed successfully before the cancellation request was processed, it remains `succeeded`; the receiver must not rewrite its outcome as `cancelled`.

#### Cancellation Already Pending

```text
REQUEST:
#cancel <id=84>: name=calibrate\n

RESPONSE:
#accepted <id=84>: name=calibrate\n
```

Repeating the request while the procedure is already `cancelling` does not start another stop sequence, reset timestamps, or extend the cancellation deadline.

#### Cancellation Not Supported

```text
REQUEST:
#cancel <id=85>: name=calibrate\n

RESPONSE:
#error <id=85>: code=NOT_CANCELLABLE, name=calibrate\n
```

For this receiver, the response applies during calibration's final coefficient-application/finalization phase. No cancellation is registered and no five-second stop deadline begins; calibration and its execution deadline continue. Scan has no corresponding non-cancellable phase. Other hardware profiles declare their own procedure/phase policies.

An unknown procedure is rejected with `UNKNOWN_PROCEDURE`. Missing, unknown, or duplicate parameters follow the common validation rules.

#### Completion and Cancellation Race

Acceptance of cancellation does not guarantee that cancellation will win a race with normal completion.

If the procedure finishes successfully before interruption takes effect, its final state is `succeeded`. The receiver reports the actual outcome rather than manufacturing a cancelled result.

#### Stop Failure or Communication Loss

An accepted cancellation starts one controlled-stop attempt with a five-second deadline. The same limit applies to stops triggered by an execution deadline. Repeated requests while stopping do not restart it. If stop cannot be confirmed by the deadline, expose `health=fault` with `STOP_TIMEOUT`, retain a known active activity or report `unknown`, and prevent incompatible operations. Expiration alone never justifies reporting `cancelled`, completed `failed`, or `idle`. A later verified stop may establish the actual terminal outcome; recording the active fault must not erase diagnostic history.

A disconnection does not withdraw an accepted cancellation request. After reconnecting, the client queries the target procedure's status.

If the cancellation response was lost, the client checks status before deciding whether to send another request: without execution identifiers, a later request could target a newer execution of the same procedure.

### Rebooting the Receiver

The `reboot` command requests a restart of the receiver's firmware. It is a system lifecycle command, not a procedure started through `run`, and accepts no fields.

#### Request and Acceptance

```text
REQUEST:
#reboot <id=90>\n

RESPONSE:
#accepted <id=90>\n
```

The response confirms that the receiver has accepted the restart request. It does not confirm that restart has occurred or that startup will succeed.

If the request cannot be accepted, the receiver returns `error` instead. Unknown or unexpected fields are rejected using the common validation rules.

#### Required Execution Order

The firmware must perform these steps in order:

1. Validate the request and enter the reboot sequence, preventing new operations from starting.
2. Transmit the complete `accepted` response, including its terminating LF.
3. Wait for transmission completion according to the selected TCP stack's documented guarantees, within a bounded time.
4. Close the connection orderly where possible, then initiate restart.

A fixed sleep is not a transmission guarantee. The implementation must distinguish data merely queued for transmission from the completion conditions provided by its TCP stack.

Transmission completion does not prove that the client application has read the response. The protocol does not introduce an additional client acknowledgement. If communication fails, the client may be unable to determine whether the request was accepted or restart occurred.

No second response or unsolicited completion notification is sent for the reboot request.

#### Procedures and Retained State

This fictitious receiver permits reboot while calibration or scanning is active. Restart interrupts those activities; it must not rewrite an interrupted procedure's outcome as a successfully completed cancellation.

The prototype does not promise persistence of procedure outcomes across reboot: earlier outcomes become `unknown`, rather than being fabricated as cancelled, failed, or succeeded. A new execution must not claim a valid calibration merely because calibration had succeeded before restart. Startup checks determine the current operating state. Persistence of Device configuration is a separate requirement and does not imply firmware outcome persistence or automatic restoration of the last requested frequency.

Reboot is not monitored using `status` with `name=reboot`. Its verification concerns the receiver after startup.

#### Verification After Reconnection

After the original connection closes, the client follows continuous reconnection, reads the descriptor with ID 1, and queries general status with ID 2:

```text
REQUEST:
#status <id=2>\n

RESPONSE:
#ok <id=2>: health=ok, activity=idle, calibrated=false, fault_codes=[], boot_id="33333333333333333333333333333333", booted_at=2026-10-23T10:40:00Z\n
```

The request ID belongs to the new TCP connection. `booted_at` describes the current firmware startup time when known reliably. `boot_id` describes the firmware execution, whether started by this command, power-on, an external reset, or a watchdog, and does not change merely because TCP reconnects.

Compare `boot_id` with the value observed before the reboot request. A changed token establishes a new execution even without trustworthy UTC; an unchanged token establishes only restored communication, not a completed reboot. Without a prior token, do not invent proof of a transition. A changed token does not establish causation by this particular request. Clock distrust remains an explicit fault even though boot comparison still works.

#### Missing Response or Failed Reconnection

If `accepted` is not received, the reboot outcome is uncertain. The client attempts to reconnect and inspect status rather than automatically resending the command and risking another restart.

There is no fixed ten-second wait and no additional global startup-verification deadline in this prototype. Each TCP attempt is bounded by two seconds, failed attempts pause for five seconds, and attempts continue while requested. The Device reports unavailability and diagnostics during the outage and checks configuration/status as soon as a connection succeeds. A caller receives the initial `accepted`/`error` or communication failure within the ordinary response policy; it is not a blocking call that waits forever for startup. Once a usable connection exists, do not repeatedly tear it down solely because restart evidence is missing. Keep reachability, health, and verified new-execution evidence distinct; never automatically resend `reboot`.

A firmware that no longer processes requests cannot be recovered reliably by sending `reboot`. Watchdog and external-reset behavior belong to the protection and recovery design, not to a guarantee of this command.

## Initial Fault-injection and Conformance Matrix

The simulator replaces hardware and firmware, not the Synqaro Device. A small test client and conformance suite can exercise it before the framework is implemented. Fault control belongs to test tooling or simulator startup/configuration, **not** to extra production-protocol commands. The exact activation interface and scenario-file format are intentionally deferred.

For each case, tests must distinguish injected physical state, firmware-reported state, wire evidence, and the library's outcome. A well-formed reply is not proof that the hardware action succeeded, and a lost reply is not proof that it failed.

| Injected condition | Firmware / wire expectation | Client / state expectation |
|---|---|---|
| Partial frames or multiple frames per TCP read | Parse only complete LF-terminated frames | Preserve framing and match separate IDs |
| No LF within two seconds after first byte | Discard frame and close the receiving side's connection | Framing error/disconnection; no execution inferred from an incomplete request |
| More than 4096 bytes including required LF | Discard and close; no oversized request execution | Bounded receive memory; preserve diagnostics |
| Bad request fields, trustworthy ID | `MALFORMED_REQUEST`, no hardware effects, keep TCP | Complete only that rejection; preserve readable error context |
| Missing/invalid/ambiguous request ID | Uncorrelated `INVALID_ID`, no execution, keep TCP | Diagnostic only; no pending request completed |
| Repeated or decreasing request ID | `ID_NOT_INCREASING` plus rejected-target details; original unaffected | Reserved diagnostic path, not failure of original request |
| Fifth pending request from a faulty client | `TOO_MANY_PENDING_REQUESTS, limit=4`; no execution | Existing four continue; no implicit unbounded queue |
| Responses deliberately reordered | Echo each request's correct ID | Match individually; keep increasing send IDs and independent deadlines |
| Malformed complete reply with recoverable pending ID | Corrupt response is preserved as evidence | Local protocol error for that request, no state update, no automatic resend |
| Ordinary reply with never-sent or already-completed ID | Response anomaly | Log/discard without completing another request; keep TCP |
| Late reply after request timeout | Original operation may already have happened | Diagnostic only, not retroactive success or automatic state update |
| Apply frequency but lose its response | Hardware may hold the new value | Timeout, one status probe, fresh read before dependent work; never replay the setting automatically |
| Lose initial calibration/scan acceptance | Procedure remains current and queryable | Probe/reconnect as needed; query named status, do not start another attempt automatically |
| Lost reply but valid status probe | Firmware still serves status | Retain connection; separate reachability from health and command outcome |
| Silent probe or broken link | No usable reply | Reconnect with bounded attempts and pauses; Device stays reachable; no automatic reboot |
| Tuning fails or exceeds one second | `FREQUENCY_LOCK_FAILED`; no false verified frequency, scan does not advance | Observe resulting frequency/fault/uncertainty instead of assuming old or requested value |
| Frequency read cannot obtain a valid value | `FREQUENCY_READ_FAILED`, not a guessed value | Do not substitute an invalid cache or confuse it with expected `VALUE_UNAVAILABLE` |
| Calibration reference unavailable after acceptance | Procedure `failed` once stopped, `CALIBRATION_REFERENCE_UNAVAILABLE` | `calibrated=false`; health depends on actual affected capabilities |
| Client cancellation during calibration finalization | `NOT_CANCELLABLE`; no stop attempt registered | Execution continues; no cancellation timer is started |
| Accepted cancellation races with successful completion | Report actual terminal result, possibly `succeeded` | Do not manufacture `cancelled`; repeated cancel cannot extend a stop deadline |
| Calibration exceeds 30 s or scan exceeds 20 s | Initiate controlled stop; after verified stop report matching timeout failure | Separate execution deadline from the additional five-second stop budget |
| Controlled stop still unconfirmed after five seconds | `STOP_TIMEOUT` active; known continuing activity or `unknown`; incompatible work blocked | Do not report idle or confirmed terminal execution merely because a timer expired |
| Clock unavailable/untrusted on UTC-capable receiver | `CLOCK_UNTRUSTED`, omit unreliable new UTC timestamps | Visible log/alarm; valid UTC-independent readings and monotonic timers may continue |
| Simultaneous synthesizer and clock faults | Both appear in `fault_codes` | Preserve all active conditions; remove only after verified resolution |
| Successful reboot or spontaneous restart | New `boot_id`, old TCP closed; old outcomes not invented | Compare boot identity, reread descriptor/status, invalidate Device cache, never replay `reboot` |
| TCP reconnect without firmware restart | Same `boot_id` | Reachability restored, not evidence of reboot; keep usable TCP |
| Missing/incompatible/malformed descriptor | No invented capabilities; explicit unsupported legacy case may use matched profile | Otherwise affected writes stay disabled; no silent file fallback |
| Out-of-range or unrepresentable numeric input | Explicit validation error before hardware effects; no infinity/underflow coercion | Preserve type/range distinction and exact rounding-boundary behavior |
| Fixed scan endpoints collapse or budget exceeds limits | Validation rejection; previous scan outcome retained | No single-point substitution, silent skipped target, or started scan |
| Device cache expires, known modification begins, or link is lost | Subsequent wire `get` reads current simulated state | Invalidate/reacquire; cached sample time is never relabeled |

This is an acceptance matrix for implementation, not evidence that tests have already run. Include normal paths, ascending/descending scans, exact rounding ties, all frame-size/deadline boundaries, and fragmented/reordered responses in the future executable suite. Deadline tests should use controllable timing where possible rather than relying exclusively on slow wall-clock sleeps. Expected code names and fields must be checked against this contract.

## Open Issues and Deferred Scope

The following items are not resolved by this document. They must not be treated as guarantees already provided by the protocol. Some require completion of the prototype contract; others are separate capabilities to evaluate only when needed.

### Associating Scan Data with Frequency

An autonomous tuning scan and independent `get` requests do not guarantee which operating frequency belongs to an externally acquired datum. Frequency can change between acquisition and the query, and polling may miss intermediate frequency changes even when every response includes `sampled_at`.

Two approaches remain to be evaluated:

- **Coordinated acquisition:** hold each verified frequency until acquisition is confirmed complete, preventing incompatible changes during that interval.
- **Time-based association:** timestamp data at acquisition and retain a complete history of actual frequency validity intervals, including tuning transitions. Both timelines require a common clock or synchronization with a known, sufficiently small uncertainty. Data near uncertain boundaries or during transitions cannot be assigned a valid frequency by assumption.

If acquisition occurs inside the receiver, returning data with their verified acquisition frequency is another possible solution. No acquisition command, frequency-history format, retrieval mechanism, retention policy, or coordination handshake has been selected. Timestamp resolution alone does not establish synchronization or measurement accuracy.

### Bulk Data Transfer

No mechanism has been selected for transferring large datasets, arrays, spectra, or files. Flat list values do not define bulk transfer and remain subject to the message-size limit.

Transport, encoding, framing or chunking, integrity checks, flow control, resource limits, cancellation, and recovery from partial transfers remain to be specified. Whether transfers use a separate connection or another existing protocol is also undecided.

### Continuous Scientific Data Streams

Continuous acquisition is distinct from reading a property or transferring a completed dataset. Channel and sample formats, acquisition timestamps, sequence numbering, loss detection, buffering, overload behavior, and reconnection semantics have not been defined.

The control protocol could configure or start a stream, but it does not currently specify the stream's data transport. No stream notifications or data messages are implicitly added to the request/response connection.

### Fast Feedback and Deterministic Timing

This ASCII/TCP protocol provides no hard real-time deadline, bounded jitter, or synchronized actuation guarantee. It is not specified as the transport for fast feedback loops.

Suitable controllers, hardware timing, execution platforms, and communication technologies must be evaluated against concrete requirements. The present protocol may supervise those systems without carrying their real-time feedback signals.

### Interlocks and Immediate Protection

Interlock implementation, reaction times, safe states, watchdog behavior, and the required reliability of protective actions remain outside this contract. A successful control exchange does not establish a protection guarantee.

Any protection architecture must explicitly define its behavior when the control client, firmware communication task, or network is unavailable. Hardware, PLC, or dedicated protection technologies have not been selected.

### Reboot Implementation and Fault Recovery

Reboot syntax, continuous reconnect policy, lack of a global ten-second verification deadline, and verification independent of UTC using `boot_id` are specified above. Platform-specific TCP transmission-completion conditions and their bounded wait, actual restart/startup checks, production boot-token generation, and watchdog/external-reset integration remain implementation work. A future requirement for a boot-duration alarm must be stated explicitly rather than silently reintroducing the rejected verification timer.

A separate `recover` procedure remains conditional on defining a persistent fault that requires explicit recovery. It must verify recovery rather than merely clear diagnostic information. No recovery procedure is specified yet.

### Device Configuration, Persistence, and Historical Reconstruction

The approved requirements are persistent Device configuration, live modification of monitoring thresholds, configurable per-property cache reuse (500 ms default, zero to disable), and the ability to reconstruct which software, firmware, and effective configuration were in use at an incident time. These are not solved merely by returning hardware capabilities or keeping Git commits.

Record immutable effective-configuration revisions and their content, software deployment/build identity, firmware/hardware identity and descriptor/profile, Device boot/session, and requested/applied/saved change outcomes with activation evidence and timestamp provenance. Historical lookup must distinguish configuration present in a file from configuration actually active. Relate telemetry and diagnostic events to the effective revision; retain incidents even after faults clear. Version/hash references require retained content/artifacts to make reconstruction useful. Persisting settings does not require restoring stale measurement caches or automatically replaying hardware operations.

Still open are the concrete file/schema and update interface, atomic validation/application of related settings, hot-reload rules beyond the agreed threshold requirement, authorization/concurrent updates, persistence location, storage/activation failure semantics, audit retention, deployment manifests, and reliable retrieval of software/firmware artifacts. Also unresolved is the durability level: which crash/network/storage failures must preserve complete history, what local durable buffering is needed, and when explicitly incomplete reconstruction is acceptable. Do not infer lossless configuration audit from the existing asynchronous telemetry recorder or invent a new central runtime configuration service before these requirements justify one. The Device must not acquire shared PostgreSQL credentials to fill this gap.

### Simulator Fault Activation and Platform Timing

Fault injection is outside the operational wire protocol, and its initial acceptance matrix is defined above. Startup flags, scenario/configuration files, test-controlled runtime activation, trigger points, and exact simulator phase scheduling are still to be selected. Real hardware clock synchronization, trust/quality assessment, measurement uncertainty, and required acquisition timing accuracy must be specified for the chosen platform; the simulator host-clock assumption is not a production guarantee. Maximum supported connections and platform resource measurements also belong to implementation validation, not an implicit unlimited-capacity promise.

### Remaining Prototype Contract Details

The earlier open numeric, framing, request-ID, concurrency, timing, error-catalog, cache-ownership, cancellation, health/activity, discovery, and boot-identification choices are resolved in this revision. Do not treat superseded proposals (variable-step scans, a 1000-point maximum, firmware cache tuning, singular `fault_code`, non-monotonic IDs, unconditional disconnect on every response timeout, or a ten-second global reboot timer) as alternative current contracts.

The next development step is a standalone TCP hardware/firmware simulator plus a small client and executable conformance/fault tests. It does not depend on implementing the Synqaro framework, production Device configuration/history infrastructure, bulk data, or scientific acquisition. After validating that path, implement the communication library/adapter and use the evidence to refine the Device design. Detailed choices explicitly deferred above remain open; implementation must document them and must not silently change the approved behavior.
