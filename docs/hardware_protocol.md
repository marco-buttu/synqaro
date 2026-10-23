# Hardware Protocol

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

Metadata is mandatory. Fields are optional; when absent, the colon is omitted.

### Quick Examples

**Set a property:**

```text
REQUEST:
#set <id=10>: name=frequency, value=5.5, unit=GHz\n

RESPONSE:
#ok <id=10>\n
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
- is a decimal integer between `1` and `4294967295`;
- identifies a request within one TCP connection;
- must not be reused on the same connection, preventing ambiguity with delayed responses;
- does not identify a procedure execution across reconnections.

Different connections may use identical identifiers. There is no `operation_id`.

Multiple metadata fields are separated by commas. An optional `client_id` may provide attribution and diagnostic context. It does not change response correlation or grant ownership or exclusive control.

## Request Types

| Verb | Purpose |
|---|---|
| `get` | Read the current value of a property |
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

## Errors and Diagnostics

An `error` response includes a stable symbolic `code`. It may include structured diagnostic fields and an optional textual `description`.

Software uses codes and structured fields to make decisions. It must not interpret free text for control logic.

When `status` reports a failed procedure, its failure code appears in `error_code`. Failure to retrieve status itself produces an `error` response.

Unsupported functionality, unknown fields, invalid values, and duplicate fields are explicitly rejected. Request validation occurs before hardware side effects.

A failure during execution does not automatically guarantee that the previous hardware state remains unchanged.

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

## Concurrent Access

Multiple clients may communicate with the hardware. Firmware protects shared state and serializes incompatible changes.

A successful setting response confirms what was applied at that time. It does not prevent another client from changing it later.

Each hardware specification declares incompatibilities between properties and procedures. The protocol does not implicitly provide request queues, procedure ownership, or exclusive control.

## Worked Example: A Fictitious Receiver

This section illustrates the protocol through a fictitious receiver. Its purpose is to make requests, responses, state changes, and failure handling concrete; it does not describe real receiver hardware.

The receiver exposes a `frequency` property and supports procedures such as calibration and scanning. Their behavior is introduced separately.

In the exchanges below, `REQUEST` and `RESPONSE` are explanatory labels and are not transmitted. `\n` represents the message-terminating LF character.

### Setting the Frequency

For this example, the `frequency` property accepts:

- one numeric value, including integers and decimals;
- values between `1` and `10`, inclusive;
- the explicit unit `GHz`.

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

The response identifies the property and confirms its applied value. If the receiver cannot apply the requested value exactly according to the property's specification, it must not silently round it and report success.

Setting the current frequency again is valid and returns `ok`. It does not start a separate procedure.

Changing the operating frequency invalidates the calibration associated with the previous configuration. Setting the same frequency does not, by itself, invalidate calibration.

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

The client cannot infer whether the setting was applied. After communication is restored, it can read the current frequency and determine whether further action is necessary. A timeout alone must not be reported as a confirmed hardware execution failure.

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

The value is available, but no trustworthy acquisition timestamp is available. Omitting `sampled_at` does not, by itself, invalidate the reading.

#### Reading a Cached Value

If the firmware uses a cached acquisition, it preserves the original timestamp:

```text
REQUEST:
#get <id=32>: name=frequency\n

RESPONSE:
#ok <id=32>: name=frequency, value=5.5, unit=GHz, sampled_at=2026-10-23T10:15:25Z\n
```

The firmware may use the cached value only while it remains valid as a representation of the operating frequency. It must invalidate the cache when a configuration change or hardware condition makes that assumption unreliable.

In particular, the last requested frequency must not be presented as an acquired value merely because it was stored by a previous `set`.

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
| `booted_at` | UTC timestamp of the current firmware execution's startup, when trustworthy |
| `fault_code` | Symbolic diagnostic code when `health=fault` |

`health=ok` does not imply that the receiver is calibrated or available for every operation. These are separate conditions.

`calibrated` is a boolean. If calibration validity cannot be determined, the field is omitted rather than reporting a guessed value. `booted_at` follows the general timestamp availability rules.

The operating frequency is read through `get`; this general status response does not duplicate it.

#### Available Receiver, Not Calibrated

```text
REQUEST:
#status <id=50>\n

RESPONSE:
#ok <id=50>: health=ok, activity=idle, calibrated=false, booted_at=2026-10-23T09:00:00Z\n
```

The receiver reports no known fault and no activity in progress. It does not currently have a valid calibration.

`activity=idle` does not grant exclusive control or guarantee that every subsequent request will be accepted.

#### Activity in Progress

```text
REQUEST:
#status <id=51>\n

RESPONSE:
#ok <id=51>: health=ok, activity=calibrating, calibrated=false, booted_at=2026-10-23T09:00:00Z\n
```

An activity is running, but this is not itself a fault. Restrictions on other requests depend on the activity's contract.

Detailed progress and outcome information belongs to the procedure-specific status query described with that procedure.

#### Receiver Fault

```text
REQUEST:
#status <id=52>\n

RESPONSE:
#ok <id=52>: health=fault, activity=idle, calibrated=false, fault_code=SYNTHESIZER_FAILURE, booted_at=2026-10-23T09:00:00Z\n
```

`ok` means that the status query succeeded. `health=fault` means that the receiver reports a hardware fault.

A failure of an individual request does not automatically set `health=fault`; the receiver's diagnostic rules determine whether the condition affects its operating health.

#### Startup Timestamp Unavailable

```text
REQUEST:
#status <id=53>\n

RESPONSE:
#ok <id=53>: health=ok, activity=idle, calibrated=false\n
```

The receiver can report its state but cannot provide a trustworthy startup timestamp. The missing timestamp does not invalidate the other fields.

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

The receiver accepts no additional calibration parameters in this example.

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

The procedure has a documented maximum execution time. If that limit is exceeded, the firmware attempts a controlled stop.

After execution has stopped, it records failure:

```text
REQUEST:
#status <id=68>: name=calibrate\n

RESPONSE:
#ok <id=68>: name=calibrate, state=failed, started_at=2026-10-23T10:20:00Z, finished_at=2026-10-23T10:20:30Z, error_code=CALIBRATION_TIMEOUT\n
```

If the hardware cannot be stopped or its condition cannot be determined, the firmware must expose the fault or uncertainty rather than declare the receiver idle.

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
| `start` | First frequency |
| `stop` | Last frequency, included in the sequence |
| `step` | Positive frequency increment magnitude |
| `unit` | Must be `GHz` |
| `dwell_ms` | Positive integer specifying the holding time at each frequency |

Both endpoints must lie within the receiver's allowed frequency range. Direction follows the endpoints: ascending when `stop > start`, descending when `stop < start`.

The distance between endpoints must be an exact multiple of `step`. The receiver rejects incompatible parameters rather than silently changing the step or endpoint. Decimal arithmetic must not introduce extra or missing points through floating-point rounding.

Equal endpoints produce a single-point scan.

The number of points and total execution time must remain within the receiver's documented limits.

#### Starting a Scan

```text
REQUEST:
#run <id=100>: name=scan, start=5, stop=5.2, step=0.1, unit=GHz, dwell_ms=1000\n

RESPONSE:
#accepted <id=100>\n
```

The resulting sequence is:

```text
5 GHz -> 5.1 GHz -> 5.2 GHz
```

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
#ok <id=101>: name=scan, state=running, started_at=2026-10-23T10:30:00Z, points_completed=1, points_total=3, progress=33\n
```

A point is completed only after its frequency has been applied and its holding time has elapsed.

`progress` is optional. If reported, it is based on completed points rather than an assumed execution duration.

Execution timestamps follow the general availability rules. No unsolicited notifications are sent.

#### Successful Completion

```text
REQUEST:
#status <id=102>: name=scan\n

RESPONSE:
#ok <id=102>: name=scan, state=succeeded, started_at=2026-10-23T10:30:00Z, finished_at=2026-10-23T10:30:03.2Z, points_completed=3, points_total=3\n
```

Success means every point was completed. The receiver remains at `stop`; it does not automatically restore the frequency preceding the scan.

The outcome remains available until another scan starts. Reading status does not clear it.

Changing the operating frequency invalidates the calibration associated with the previous configuration. Scanning does not perform calibration.

#### Invalid Parameters

```text
REQUEST:
#run <id=103>: name=scan, start=5, stop=5.25, step=0.1, unit=GHz, dwell_ms=1000\n

RESPONSE:
#error <id=103>: code=INVALID_PARAMETER, parameter=step, reason=ENDPOINT_NOT_REACHABLE\n
```

No scan starts and the frequency remains unchanged.

Missing parameters, invalid types, unsupported units, nonpositive steps or holding times, and exceeded limits are rejected before execution. A rejected request does not replace a previous scan's retained outcome.

#### Conflicting Requests

Calibration and scanning both require control of tuning and cannot execute together.

```text
REQUEST:
#run <id=104>: name=scan, start=5, stop=6, step=0.1, unit=GHz, dwell_ms=1000\n

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
#ok <id=105>: name=scan, state=failed, started_at=2026-10-23T10:30:00Z, finished_at=2026-10-23T10:30:01.4Z, points_completed=1, points_total=3, error_code=FREQUENCY_LOCK_FAILED\n
```

The receiver stops advancing through the sequence. It does not silently skip the failed point.

No automatic frequency restoration is assumed. The resulting operating frequency must be determined through `get`; if it cannot be determined, the receiver reports its unavailability.

Execution deadlines and controlled-stop requirements follow the common procedure rules.

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
#ok <id=107>: name=scan, state=cancelled, started_at=2026-10-23T10:30:00Z, finished_at=2026-10-23T10:30:01.5Z, points_completed=1, points_total=3\n
```

While interruption is pending, the state is `cancelling`. The receiver reports `cancelled` only after execution has stopped.

Cancellation does not restore the starting frequency. The receiver retains the last successfully applied frequency where it can verify that value; otherwise, its frequency is reported as unavailable.

The [common cancellation rules](#cancelling-a-procedure) apply, including races with normal completion and repeated cancellation requests.

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

This response applies when the selected procedure, or its current execution phase, cannot be interrupted. Each procedure specification declares its cancellation rules.

An unknown procedure is rejected with `UNKNOWN_PROCEDURE`. Missing, unknown, or duplicate parameters follow the common validation rules.

#### Completion and Cancellation Race

Acceptance of cancellation does not guarantee that cancellation will win a race with normal completion.

If the procedure finishes successfully before interruption takes effect, its final state is `succeeded`. The receiver reports the actual outcome rather than manufacturing a cancelled result.

#### Stop Failure or Communication Loss

The firmware must bound the interruption attempt. If it cannot stop the hardware, it must expose the resulting fault or uncertainty and prevent incompatible operations. Expiration of a timer alone does not justify reporting `cancelled` or `idle`.

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

Without explicitly specified persistence, execution outcomes from before restart become `unknown`. A new execution must not claim a valid calibration merely because calibration had succeeded before restart. Startup checks and the receiver's declared persistence rules determine what can be reported reliably.

Reboot is not monitored using `status` with `name=reboot`. Its verification concerns the receiver after startup.

#### Verification After Reconnection

After the original connection closes, the client reconnects and reads general status:

```text
REQUEST:
#status <id=1>\n

RESPONSE:
#ok <id=1>: health=ok, activity=idle, calibrated=false, booted_at=2026-10-23T10:40:00Z\n
```

The identifier belongs to the new connection. `booted_at` describes startup of the current firmware execution, whether caused by this command, power-on, an external reset, or a watchdog.

A changed, trustworthy `booted_at` provides evidence of a new execution. If the timestamp is unavailable or unreliable, successful reconnection alone establishes reachability, not proof that the reboot occurred. The client must not invent a completion result.

#### Missing Response or Failed Reconnection

If `accepted` is not received, the reboot outcome is uncertain. The client attempts to reconnect and inspect status rather than automatically resending the command and risking another restart.

If the receiver does not become reachable within the client's startup deadline, the library reports that restart could not be verified. It must not assume whether the cause is firmware startup failure, power loss, or a network problem.

A firmware that no longer processes requests cannot be recovered reliably by sending `reboot`. Watchdog and external-reset behavior belong to the protection and recovery design, not to a guarantee of this command.

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

Reboot syntax and general behavior are specified in [Rebooting the Receiver](#rebooting-the-receiver). Platform-specific TCP transmission-completion conditions, shutdown and startup deadlines, startup checks, persistence, and verification when `booted_at` is unavailable remain to be defined for the implementation.

A separate `recover` procedure remains conditional on defining a persistent fault that requires explicit recovery. It must verify recovery rather than merely clear diagnostic information. No recovery procedure is specified yet.

### Remaining Prototype Contract Details

Before firmware and library implementation, the prototype still needs concrete definitions for:

- exact numeric syntax, representable frequency resolution, and the handling of values that cannot be represented as requested;
- message-size limits, incomplete-message and response timeouts, procedure and cancellation deadlines, scan point limits, and default polling behavior;
- supported numbers of pending requests per connection, response ordering, and handling of duplicate request IDs, delayed responses, and unexpected identifiers;
- the common error-code registry and the behavior for malformed messages beyond the framing violations already specified;
- how cached values remain valid, how hardware health and activity are established, and which phases of each procedure can reject cancellation;
- clock synchronization, clock-quality assessment, and availability rules on the selected hardware;
- a fault-injection matrix linking simulated failures to the expected firmware response, reported state, and communication-library outcome.
