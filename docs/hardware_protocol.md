# Hardware Protocol

## Purpose

This protocol provides a common text-based interface for controlling different types of hardware over TCP.

It supports:

- reading and setting properties;
- starting procedures and inspecting their state and outcome;
- distinguishing invalid requests, hardware failures, and communication problems;
- straightforward implementation and testing of firmware, communication libraries, and simulators.

Message structure and general behavior are shared across hardware types. Each hardware specification defines its supported properties, procedures, parameters, and specific error codes.

The protocol is intended for control and diagnostics, not bulk data transfer.

### Why Generic Verbs

The protocol uses a fixed set of verbs instead of a separate verb for every hardware capability. Properties are selected through `name`, assigned through `value`, and accessed through `get` and `set`. Procedures are selected through `name`, started through `run`, and inspected through `status`.

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

`get`, `set`, and `run` select a property or procedure through `name`. `set` also requires `value`. Additional fields depend on the selected functionality.

Without `name`, `status` describes the hardware. With `name`, it describes the selected procedure.

A `set` must complete the setting before confirming success. Work requiring prolonged execution is modeled as a procedure started through `run`.

## Responses

Every valid request receives exactly one response:

| Response | Meaning |
|---|---|
| `ok` | The read, setting, or status query has completed |
| `accepted` | The procedure has been accepted; its outcome must be obtained through `status` |
| `error` | The request was rejected, or its short execution failed |

`get`, `set`, and `status` return `ok` or `error`. `run` returns `accepted` or `error`.

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

`started_at` records when an attempt began. `finished_at` records when it ended, including failure or cancellation. Timestamps use UTC:

```text
YYYY-MM-DDTHH:MM:SS.sssZ
```

Timestamps require a trustworthy clock. Unavailable or nonexistent timestamps must not be replaced with fabricated dates.

`progress` is optional. When provided, it represents a percentage between `0` and `100`.

Reading status does not modify or clear it. State and outcomes remain available across disconnections according to the procedure's declared retention rules. Retention across a hardware restart requires an explicit guarantee.

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
