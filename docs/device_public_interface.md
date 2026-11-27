# Device public interface

**Status:** agreed prototype decisions, recorded for review in [issue #45](https://github.com/marco-buttu/synqaro/issues/45), 2026-11-27. JSON examples illustrate the intended interface; they are not an implemented schema or a new hardware protocol.

Read with [Device architecture](device.md). This document specifies the public boundary of a Device, not a mandatory base class, generic execution framework, registry, recorder, orchestration layer or external UI API. Existing architecture decisions remain in force. The first application is the fictitious receiver; see section 9. Implement and test it in a subsequent issue.

## 1. Identity, discovery and boundaries

Each Device owns its hardware connection, maintains current state in memory and provides a direct typed HTTP/JSON API (FastAPI/Pydantic for the prototype). Clients resolve its logical name to an endpoint through the registry and call that endpoint directly. Device paths do not repeat the category or logical name. Use explicit hardware-specific endpoints, not a generic command-name dispatcher or a second capability catalog. Generate OpenAPI and JSON Schema from the public types and routes. Use the same definitions for validation, documentation and discoverable semantics wherever possible.

| Common interface | Responsibility |
| --- | --- |
| `GET /description` | Logical identity, category, hardware model, Device software and public API versions, execution session ID and OpenAPI reference |
| `GET /health` | Lightweight passive Device and hardware health |
| `GET /state` | Passive current-state snapshot |
| `GET /configuration` | Effective public configuration and revision |
| `PATCH /configuration` | Validated, persistent, atomic change to writable public settings |
| `GET /operations/{id}` | Inspect a recorded operation |
| `POST /operations/{id}/cancel` | Request cancellation of a cancellable asynchronous operation |

Hardware-specific endpoints expose actual properties and procedures, e.g. `GET /frequency`, `PUT /frequency`, `POST /calibrate`, `POST /scan`. The available endpoints, inputs, outputs, ranges, units, constraints, errors and meaning are explicit in the generated schema and descriptions. They need not be present on unrelated Devices. The underlying hardware descriptor and wire protocol are not the Device API. Do not expose internal adapter methods or simulator fault controls as production capabilities. Keep hardware capabilities separate from writable Device policy (architecture section 10.1).

Logical names are unique within an installation, independent of category. Category and each individual name token (Device, property, group) use lowercase ASCII letters, digits, hyphens and underscores; dots are reserved as NATS separators. Use consistent names across APIs, configuration, registry and subjects, without alias conversion. Synqaro suggests categories such as `receiver`, `mount` and `backend`; an installation may extend or replace them. The Core does not hardcode categories. `session_id` is a fresh UUID on each Device process start, distinct from the logical identity and from a hardware boot identifier.

Illustrative description:

```json
{
  "name": "pippo",
  "category": "receiver",
  "hardware_model": "fictitious_receiver",
  "device_version": "0.1.0",
  "api_version": "1",
  "session_id": "811a8295-ad76-40e5-9d66-553867304ec0",
  "openapi": "/openapi.json"
}
```

Version values and exact schema field layouts in examples are illustrative, not released version declarations. The versioned schema must describe constraints and semantics, including those that cannot be expressed as simple numeric bounds.

## 2. Properties, state, quality and clocks

`GET /state` reads the authoritative in-memory snapshot without contacting hardware. Include relevant operating conditions (e.g. frequency, calibration validity, activity, connectivity and active faults), not static descriptor fields, configuration, history or large scientific data. A snapshot need not mean that all properties were physically observed simultaneously. Each datum retains its own provenance and quality.

A property endpoint such as `GET /frequency` can return the same observation when reusable, or perform a fresh acquisition when not reusable. `GET /frequency?fresh=true` bypasses reuse and requests a new observation, subject to hardware permissions, validity and operating conditions; it does not override preconditions. Both periodic and successful on-demand acquisitions update the same authoritative in-memory observation; there is no separate duplicate property cache. Hardware is acquired once per sample, not once per subscribing client. A read request must not silently return a cached value after a known invalidating event.

Four distinct configurable intervals per property or coherent group (milliseconds):

| Setting | Meaning |
| --- | --- |
| `acquisition_period_ms` | Scheduled hardware observation cadence, independent of requests |
| `publication_period_ms` | Scheduled publication cadence, even for unchanged observations |
| `cache_ttl_ms` | Maximum local age for reuse by a property read; default 500 ms; zero disables reuse |
| `stale_after_ms` | Age beyond which a previously valid observation is stale |

The cache TTL is not a quality threshold. An observation can be too old to reuse for a property request while still valid for monitoring. Conversely, an immediate invalidating event overrides both intervals. Do not reacquire just to publish; publish the latest observation with its original timestamps and current quality. Hardware-pushed observations are also supported where the contract permits them; no invented polling or hard-real-time guarantee. Exact scheduling under delay and per-model interval defaults other than cache TTL are implementation questions.

Use the same quality vocabulary in HTTP and NATS:

| Quality | Meaning | Value |
| --- | --- | --- |
| `valid` | Verified observation within its freshness policy, no known invalidation | Observed value |
| `stale` | Previously valid observation exceeds its freshness threshold | Last verified value with original time |
| `invalid` | Evidence makes the observation untrustworthy | `null` |
| `unavailable` | No usable observation is available | `null` |

Preserve the reason and diagnostic context; invalid/unavailable must not masquerade as zero or a guessed prior value. Local freshness uses a monotonic clock, with known invalidations applied immediately. A client may require stricter freshness and must not treat a silent publisher as indefinitely current. The Device provides the necessary information; no common client-specific silence timeout is imposed.

Time semantics (UTC ISO 8601 where available): `acquired_at` is the actual hardware acquisition instant, or `null` if unknown/untrustworthy; `received_at` is when the Device received the observation; `published_at` is the NATS publication instant. A repeated publication or cache hit never updates acquisition or reception time. Never substitute reception time for unknown hardware time. Preserve trustworthy historical timestamps when clock trust is lost. Clock accuracy and synchronization guarantees must be stated, not inferred. Use monotonic time for cache reuse, local freshness, timeouts, operation durations and scheduling; monotonic readings have no transferable UTC epoch and are not compared between hosts.

For physical quantities, choose one public unit per quantity, consistent across HTTP and NATS. Declare it with OpenAPI `x-unit` using case-sensitive [UCUM](https://ucum.org/ucum), e.g. `GHz`, `deg`, `deg/s`, `K`, `Cel`, `ms`. Use the schema's type, bounds and descriptions to convey resolution, rounding and scientific semantics; do not constrain accepted original inputs to a grid when the contract specifies rounding. The system's agent proposes domain-appropriate default units for maintainer approval; Devices follow those conventions or obtain approval for exceptions. Synqaro imposes no global list of units, no alternate units per public property and no mandatory conversion library. Client display conversions are outside the Device interface. The adapter supplies any units required by the hardware protocol.

Illustrative property read:

```json
{
  "value": 5.123457,
  "quality": "valid",
  "acquired_at": "2026-11-27T10:00:00.100Z",
  "received_at": "2026-11-27T10:00:00.120Z"
}
```

The schema identifies this value as frequency in GHz. On a cache hit the same timestamps are returned. A publication may additionally carry publication metadata. A state snapshot carries observations for multiple properties and relevant operating conditions; the snapshot is not a new acquisition.

Illustrative passive receiver snapshot while calibration is active (the exact state schema is not yet frozen):

```json
{
  "frequency": {
    "value": null,
    "quality": "unavailable",
    "acquired_at": null,
    "received_at": null,
    "reason": "CALIBRATING"
  },
  "calibrated": false,
  "activity": "calibrating",
  "hardware_connected": true,
  "fault_codes": []
}
```

This snapshot reports known operating conditions and unavailable frequency without a new hardware request. If calibration status is indeterminate, do not assert a boolean value from old evidence.

## 3. Health and diagnostics

`GET /health` is passive and lightweight; it must not trigger hardware I/O. Report Device software health and readiness separately from hardware connectivity and health when known. Example:

```json
{
  "device": {"health": "healthy", "ready": false},
  "hardware": {"connected": true, "health": "fault"}
}
```

A healthy process can be not ready for normal work. A successful HTTP response or hardware connection is not proof of healthy hardware; an unreachable process cannot report its own unreachability. Detailed property qualities, activity and faults belong in state. Keep registry lease status distinct. Exact health enums and lease integration remain open. Unknown hardware conditions must not be fabricated.

Use structured errors with a machine-readable `category` and `code`, readable `message`, timestamp, correlation ID and contextual details, preserving original hardware/protocol diagnostic codes and evidence without disclosing credentials. Initial categories: `VALIDATION`, `HARDWARE`, `COMMUNICATION`, `PROTOCOL`, `STATE`, `AUTHORIZATION`, `INTERNAL`. Distinguish rejected requests, failed execution, data unavailability and unknown outcome; do not reduce faults to a generic error. Correlate requests, operation identities, wire interactions and logs; exact mappings and disclosure policy are to be verified with the first Device. Authorization and independent safety constraints remain mandatory design boundaries; authentication/permission implementation is deferred, not authorization to bypass them.

## 4. Commands and operation lifecycle

Use direct typed HTTP calls. Validate inputs, constraints, permissions, state preconditions and safety before hardware effects. Recheck relevant state at execution time. No implicit command queue or automatic replay of modifying commands. Short synchronous commands return the verified outcome in their response; asynchronous starts return HTTP `202 Accepted` and an operation identity. Acceptance is not completion.

The client generates a fresh UUID for each intended hardware-modifying execution, synchronous or asynchronous. No operation UUID is required for simple reads. The Device records the ID before sending the command to hardware. Check registration atomically so concurrent duplicates cannot both execute. Any already registered ID is rejected with HTTP `409 Conflict`, code `DUPLICATE_OPERATION_ID`, regardless of parameters or prior state. It does not return the prior success as if it were a new execution. The client may inspect the old operation with `GET /operations/{id}`. The exact ID placement in request schemas is illustrative below.

The in-memory operation register retains the ID, command, parameters, status, available timestamps, result, and error evidence. The same query API works for short modifying commands. Publish operation updates when state changes. The common lifecycle vocabulary includes `accepted`, `running`, `cancelling`, `succeeded`, `failed`, `cancelled`, `unknown`. Progress is optional and meaningful only if supported by evidence; do not derive fake percentages from elapsed time. Distinguish known active work from unknown outcome. `unknown` is not an assertion of failure, success or stopped hardware, and can be reconciled with fresh evidence. Do not infer an operation identity from a hardware wire request ID or from an unrelated later state. Reconnection can recover evidence only when it can be attributed to that operation. Keep incompatible work blocked until safe state is established; do not automatically replay. Disconnection of a client does not cancel hardware work.

For completed operations, retain up to 24 hours and at most 1,000 records by default (both configurable); evict oldest terminated records when either limit requires it. Never evict active work because of those limits. No operation-register persistence across process restarts. Unknown outcomes with unconfirmed activity must not be treated as terminated for eviction. Retention after verified cessation with an irrecoverable outcome remains an explicit open detail. Missing records return `404 Not Found`; this does not prove non-execution. Duplicate protection is bounded by retained registration; an expired or restarted register may accept the same ID as a new request. Do not blindly retry an uncertain execution. Long-term history belongs to a separate durable path, not Device PostgreSQL access.

Illustrative calibration sequence (full UUID):

```http
POST /calibrate
Content-Type: application/json

{"operation_id":"550e8400-e29b-41d4-a716-446655440000"}
```

`202 Accepted`:

```json
{"operation_id":"550e8400-e29b-41d4-a716-446655440000","name":"calibrate","status":"accepted","accepted_at":"2026-11-27T10:00:00Z"}
```

`GET /operations/550e8400-e29b-41d4-a716-446655440000`, `200 OK` during execution:

```json
{"operation_id":"550e8400-e29b-41d4-a716-446655440000","name":"calibrate","status":"running","cancellable":true,"accepted_at":"2026-11-27T10:00:00Z","started_at":"2026-11-27T10:00:01Z","completed_at":null,"error":null}
```

The same GET after verified successful completion returns:

```json
{"operation_id":"550e8400-e29b-41d4-a716-446655440000","name":"calibrate","status":"succeeded","cancellable":false,"accepted_at":"2026-11-27T10:00:00Z","started_at":"2026-11-27T10:00:01Z","completed_at":"2026-11-27T10:00:11Z","error":null}
```

Repeating the original POST while this ID is retained returns `409 Conflict`:

```json
{
  "operation_id": "550e8400-e29b-41d4-a716-446655440000",
  "error": {
    "category": "STATE",
    "code": "DUPLICATE_OPERATION_ID",
    "message": "Operation ID already registered. No new operation was started.",
    "timestamp": "2026-11-27T11:00:00Z",
    "correlation_id": "18bc9c98-21fb-4f6f-8cb5-c1b83851462b"
  }
}
```

If communication with hardware is lost during the original execution, the GET may instead report `status: "unknown"` with error category `COMMUNICATION`, code `CONNECTION_LOST` and evidence. Later verified evidence may establish `running` or a terminal outcome. HTTP success for the query does not assert success of the operation.

### Cancellation

`POST /operations/{id}/cancel` requests cancellation of that existing operation; the ID in the path refers to the target, not a new calibration. `202 Accepted` means the cancellation request was accepted, not that stopping succeeded. `409 Conflict` means the operation is not cancellable or already terminated; `404 Not Found` means the ID is unknown. Once cancellation is accepted, report `cancelling` while stopping is unresolved. Actual confirmed cancellation yields `cancelled`; verified normal completion winning the race yields `succeeded`; actual failure yields `failed`; lack of reliable evidence may yield `unknown` or continued known stopping activity. A timeout alone does not establish a terminal state. Repeated cancellation must follow the model-specific contract (receiver: no resetting the stop deadline). No new execution is created by cancellation. The exact request identity/correlation treatment for cancellation retries remains to be specified separately from start UUIDs.

## 5. Core NATS publication

The Device publishes live state, not commands, on subjects:

| Subject | Content |
| --- | --- |
| `state.<category>.<device_name>.<property_or_group>` | Self-contained latest observation or coherent group |
| `health.<category>.<device_name>` | Health information (cadence/details not yet fixed) |
| `operations.<category>.<device_name>` | Operation updates on changes |
| `configuration.<category>.<device_name>` | Full public configuration on successful effective change |

Examples: `state.receiver.pippo.frequency`, `state.receiver.baudo.frequency`, `state.mount.antenna-1.position`. The last can group azimuth/elevation coherently when the actual hardware acquisition supports it. Wildcards such as `state.receiver.*.frequency` or `state.receiver.pippo.>` permit subscriptions without a bespoke routing protocol.

Each subject has its own sequence counter starting at 1 in a fresh Device session, increasing on every publication even when values are unchanged. Counters are not persisted. Messages identify the Device, session, schema version, sequence, observation times where applicable, publication time, quality, and applicable diagnostic context; state messages also include `configuration_revision`. Types, units and semantic metadata are present or discoverable in the versioned schema. Example on `state.receiver.pippo.frequency`:

```json
{
  "device_name": "pippo",
  "category": "receiver",
  "session_id": "811a8295-ad76-40e5-9d66-553867304ec0",
  "schema_version": "1",
  "sequence": 15,
  "configuration_revision": 43,
  "value": 8.0,
  "quality": "valid",
  "acquired_at": "2026-11-27T10:00:00.100Z",
  "received_at": "2026-11-27T10:00:00.120Z",
  "published_at": "2026-11-27T10:00:00.150Z"
}
```

Core NATS is at-most-once, not a durable message log. A consumer seeing sequences 10, 11, 15 for one session/subject can detect a gap. If monitoring the latest frequency, message 15 supersedes missing samples. If message 12 instead reported operation A's completion and message 15 is about B, a consumer interested in A can query `GET /operations/A` (A stands for its UUID) while the record is retained. `GET /state` permits passive resynchronization after a gap or restart. Sequence values are comparable only for the same subject and session; UUIDs are not chronological ordering tokens. Consumers need to establish which session is current; detailed race-free snapshot/subscription synchronization is open. No Device-side replay buffer, retransmission or delivery acknowledgement protocol is added.

Publication continues periodically for unchanged values, preserving observation timestamps. The periodic publication itself acts as a liveness signal; no additional per-property heartbeat. Clients can use the advertised publication period and their own silence policy, and must distinguish stale data, interrupted publication and actual hardware fault. No fixed three-period rule. Reliable delivery for every alarm, audit record, operation transition or scientific datum is a separate requirement; Core NATS and the RAM register alone do not satisfy it. JetStream/PostgreSQL durability and selected recording remain open as described in the architecture.

## 6. Device configuration

Persist each instance's configuration in JSON, at a configurable path such as `~/.config/synqaro/devices/pippo.json`, outside the Git checkout. Schemas, defaults and examples can be versioned in Git; live instance values are not source changes. Keep hardware capabilities/limits in the approved descriptor/profile, not duplicated writable settings. The Device has no shared database credentials or access. No central configuration service or file watcher is required.

`GET /configuration` returns the effective public configuration. Only explicitly public fields may appear in HTTP, OpenAPI or NATS configuration notifications. Describe read-only vs writable fields. Infrastructure addresses are private by default unless explicitly needed; credentials and secrets never appear in public configuration. Other diagnostic/error payloads must not leak them either. Internal storage of secrets and auth implementation are separate open decisions.

Hot settings include acquisition/publication intervals, cache TTL, freshness thresholds and applicable warning/alarm thresholds; apply to subsequent cycles. Identity, hardware endpoint and infrastructure address changes require restart. A PATCH is all-or-nothing: reject the entire request if any setting is invalid or not hot-editable. No independent partial commits. Serialize revision check, validation and update against concurrent writes. Validate the resulting complete configuration, atomically save the new configuration on disk, activate it in memory, then acknowledge success. A failure before committing the save (e.g. disk full) leaves the previous effective configuration in use. If the process stops after save but before activation, the next start reads the saved configuration; lost responses are not proof that a change was not applied. Do not promise stronger crash/power-loss guarantees than verified by the storage implementation. Failure after commit but before successful activation must not be reported as a confirmed rollback; detailed recovery semantics remain open.

`configuration_revision` is a persistent increasing integer initially 1. Each effective successful change increments it by one; rejected and no-op changes do not. Store revision and `configuration_hash` with the JSON. SHA-256 covers a deterministic representation of the effective configuration parameters, excluding revision and hash metadata. On valid manual edits while stopped, recompute the hash at startup and increment/save only if the effective values changed. Unchanged restart or whitespace/key-order changes do not create revisions. Validate before activation, reject invalid configuration, and do not expose the internal hash as a public secret-derived value. The precise canonical representation, recovery from damaged metadata, restored old files and crash durability are open; no universal monotonicity across manual rollback or loss of the file is promised.

Illustrative `GET /configuration` response (periods other than the agreed cache TTL are example values, not defaults):

```json
{
  "configuration_revision": 43,
  "frequency": {
    "acquisition_period_ms": 1000,
    "publication_period_ms": 1000,
    "cache_ttl_ms": 500,
    "stale_after_ms": 3000
  }
}
```

`PATCH /configuration` includes the expected revision. A mismatch rejects the whole change with `409 Conflict`, `CONFIGURATION_REVISION_MISMATCH`. Example:

```http
PATCH /configuration
Content-Type: application/json

{"configuration_revision":42,"frequency":{"publication_period_ms":2000}}
```

```json
{
  "error": {
    "category": "STATE",
    "code": "CONFIGURATION_REVISION_MISMATCH",
    "message": "The configuration has changed since it was retrieved. No changes were applied.",
    "timestamp": "2026-11-27T10:00:00Z",
    "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
    "details": {"requested_revision": 42, "current_revision": 43}
  }
}
```

Publish the full public effective configuration on `configuration.receiver.pippo` (for example) after successful effective changes, not periodically. Include the revision in GET, notifications and periodic state messages. Monitoring clients must subscribe to the configuration subject as well as their chosen state subjects, and refresh through GET if a later state publication exposes a different revision. This is an interface-use requirement for keeping monitoring configuration current, not a prescribed client timeout/retry implementation. Because notifications can be lost, they are not an audit guarantee. For incident reconstruction retain actual configuration content and activation evidence in future history, not just a revision or hash; distinguish requested, saved and effective configuration. The Device's file retains only the current configuration, not its historical versions.

## 7. Instructions for Device development agents

Before proposing a Device, read the architecture, this specification, the applicable system conventions, the approved hardware contract and selected protocol, and the integration/verification evidence. Record the consulted revisions. If the system conventions do not yet exist, propose them (including categories and domain-appropriate UCUM units) for approval; do not invent a different convention for each Device. If mandatory sources conflict or are unavailable, report the gap. Use the approved hardware behavior as authority, not simulator implementation quirks or remembered conversations. An extension to a shared interface or hardware contract requires separate approval.

Design explicit typed model-specific properties and commands and the small common interface above. Document constraints, units, provenance, quality, preconditions, side effects, timing, cancellation, recovery, and diagnostics so agents and clients can discover them without reading internal source. Use code-first schemas, not another parallel manually synchronized capability catalog. Keep deployment policy, hardware capability and simulator administration separate. Write independent behavior tests against the approved contract; include admission, negative and uncertainty cases. Do not build a generic framework before concrete Devices justify reuse. Expose no controls that bypass authorization, validation or independent safety. Preserve the separation of monitoring, orchestration, durable history and hardware communication.

## 8. Representative fit assessment (not additional Device contracts)

| Representative need | How the interface fits | What must be specified later |
| --- | --- | --- |
| Antenna mount | Typed position observations, coherent azimuth/elevation group if acquired together, e.g. `state.mount.antenna-1.position`; common health, configuration and long-motion operation status | Coordinate frame, units and time semantics, tracking commands and motion/stop constraints, applicable safety protections, measured acquisition/publication latency and jitter |
| Spectrometer/backend | Typed operating configuration and status, async preparation/acquisition control, small supervisory metrics on NATS | Bulk sample transfer, timing association, durable data path, data formats, acquisition rates and loss guarantees; no bulk scientific data through the common interface |

These are conceptual checks, not implementations or commitments to model-specific commands, rates or capabilities. Neither requires the common interface to know radioastronomy concepts. The existing 20 Hz mount example is a measurement target, not a universal Device period. A second concrete Device must validate the design before reuse claims or a generic framework.

## 9. Fictitious receiver application

Authority: [approved receiver contract, revision 0.2](../contracts/models/fictitious_receiver.yaml), [hardware protocol v1](hardware_protocol.md), [contract application and verification](fictitious_receiver_contract_application.md). The simulator is a tuning-only model with no verified physical firmware; an empty firmware-version list is not a wildcard. No operational writes to unverified physical firmware. Keep wire request IDs, hardware boot identity and public Device operation UUIDs separate. The interface must not alter wire grammar or contract behavior.

| Public endpoint or state | Contract mapping |
| --- | --- |
| `GET /frequency` (optional `fresh=true`) | Verified frequency; map to hardware get frequency when needed; use one authoritative observation and invalidate on uncertain tuning, calibration or failed read as required |
| `PUT /frequency` | Short verified set, client operation UUID; accepted original numeric bounds 1–10 GHz inclusive, nearest 0.000001 GHz grid, ties toward higher frequency; return verified applied value only on success |
| `POST /calibrate` | No hardware parameters; public request carries UUID; async procedure with actual verified completion and restored starting frequency |
| `POST /scan` | Async; UUID, `start` and `stop` in GHz and integer `dwell_ms` in ms; wire adapter supplies fixed `unit=GHz` |
| `GET /operations/{id}` and `POST /operations/{id}/cancel` | Device register; query/cancel hardware procedure by contract semantics with verified association to the Device operation |
| `GET /state`, `GET /health` | Passive frequency observation, calibration validity, activity, connectivity and relevant active faults based on hardware general status and acquired evidence |
| `GET /description`, configuration endpoints | Device identity/schema and Device-owned policy; not the hardware read-only configuration descriptor |

Read and validate the hardware descriptor on connect/reconnect, preserve hardware identity, firmware release/build and protocol version in diagnostics, and block incompatible/unverified operational writes. This receiver has no fallback profile on failed descriptor discovery. The descriptor, wire `status` and procedure status remain adapter inputs, not copied wholesale into writable Device configuration. Hardware reboot exists in the contract as a dedicated lifecycle verb; its public exposure, permission and lifecycle API shape are not yet agreed. Do not expose it implicitly through an unrelated route or replay it automatically.

Example synchronous request, with the public schema fixing the unit:

```http
PUT /frequency
Content-Type: application/json

{"operation_id":"06e595d9-d3f3-4f47-9665-895fd26df193","value":5.1234565}
```

Illustrative successful `200 OK` response:

```json
{
  "operation_id": "06e595d9-d3f3-4f47-9665-895fd26df193",
  "status": "succeeded",
  "result": {"value": 5.123457, "quality": "valid", "acquired_at": null, "received_at": "2026-11-27T10:00:00Z"}
}
```

Map the trustworthy wire `sampled_at` to `acquired_at`, preserving fractional precision. Absence of a trustworthy hardware timestamp does not by itself invalidate a verified value; report clock distrust separately. The actual set response may require fresh observation to establish acquisition time; no timestamp is fabricated. The schema describes accepted original numeric values (not just grid-aligned values), and the verified result is on grid. Validation before rounding rejects out-of-range original input. Successful same-effective-frequency set preserves existing valid calibration; a changed frequency or failed setting that loses verification invalidates calibration, even if the requested effective frequency was unchanged. Reacquiring the same value does not restore invalidated calibration; only successful recalibration can. Overlapping incompatible starts/sets, including short set overlap, are rejected with preserved `BUSY`, not queued.

Example scan request:

```http
POST /scan
Content-Type: application/json

{"operation_id":"e25b3dbf-f8d0-4370-bbf8-14d3c7a7cab6","start":5.0,"stop":5.2,"dwell_ms":100}
```

The contract requires original endpoint validation, then rounding and ten distinct strictly monotonic points including endpoints (minimum nine grid increments); dwell is 1–1000 ms and the conservative budget must fit the 20 s execution deadline. Verify each tuned target and hold it for the required dwell including the last. Progress, if exposed, reflects completed holds. No configurable point count/step and no scientific acquisition. Success leaves the rounded stop frequency; cancellation/failure does not promise restoration. The schema must explain compound constraints and code must enforce them before effects.

Calibration has a 30 s execution deadline, scan 20 s, tuning up to 1000 ms and controlled stopping an additional 5000 ms. These are hardware contract values, not general Synqaro defaults. Calibration invalidates previous calibration at start; success requires final checks and verified restoration; failure/cancellation leaves it invalid. Reject cancellation in calibration finalization with the original `NOT_CANCELLABLE`; scan permits cancellation throughout active execution. Repeated accepted cancellation cannot extend the stop deadline. If completion wins a cancellation race, report actual success. If stopping is unconfirmed, expose `STOP_TIMEOUT`, retain unresolved activity and block incompatible work, never fabricate terminal failure or idle. Report actual terminal timeout failure only after confirmed stop. On connection loss follow staged recovery (status probe where appropriate, bootstrap descriptor/status on reconnect, reacquire affected state, suspend writes until evidence, no replay). Hardware history is current/last retained attempt by name, not by public UUID. Reboot makes previous procedure outcomes unknown; a verified hardware boot change proves new execution but not causation. A new Device process does not inherit the old operation register.

When frequency is unavailable during calibration or unverified tuning, return no value and preserve `CALIBRATING`/`TUNING` evidence from `VALUE_UNAVAILABLE`; after lost verification use `UNVERIFIED` when no specific acquisition failure applies. A failed read preserves `FREQUENCY_READ_FAILED`; known loss of verification invalidates an existing observation. When no observation exists, mark it unavailable. During autonomous tuning or uncertain recovery, do not reuse cached frequency merely because TTL has not expired. A confirmed hardware fault is distinct from unavailability and communication uncertainty. Preserve all concurrent fault codes and clock trust evidence; a successful unrelated command does not clear faults. LNA temperature in the architecture is a hypothetical property example, not part of this receiver contract.

### Verification requirements for implementation

Use the approved 19 hardware scenarios and existing independent hardware tests as a reference, not as proof that the Device API works. Add Device-level tests for common endpoints/schema, no-hardware-I/O passive reads, cache vs stale thresholds, fresh acquisitions, coherent publications, multiple subscribers, monotonic timing/UTC trust, explicit errors, concurrent duplicate UUIDs and expired/restarted registers, unknown outcomes and cancellation races, configuration revision conflicts, no-op and manual-edit hash behavior, failed save, public-field filtering, configuration notifications, missed publications and session changes. Cover receiver validation/rounding, calibration validity, scan timing and progress, BUSY, stop timeout and recovery against the simulator. Do not claim physical conformance. Exact status-code mappings beyond the agreed cases, response field shapes and scheduling policies must be documented and tested in implementation.

## 10. Remaining open questions and issue #45 review

The agreed common semantics above are the baseline. The following are not silently resolved by illustrative JSON:

- Exact request/response schemas and version compatibility, health enum details, timestamp precision/synchronization and representation of unknown local clock trust; exact mappings of wire errors to HTTP status and quality for all cases, error disclosure policy and typed result/progress fields.
- Admission and retention of rejected/irrecoverably unknown operations, cancel request identity, restart/old-session and snapshot-subscription race handling; exact supported reboot/recovery public commands and permission policy. Bounded duplicate detection is not an exactly-once guarantee.
- Per-model acquisition/publication/stale defaults, scheduling under delay, health cadence and measured snapshot/group size limits; subject authorization and schema compatibility. No imposed client-specific silence threshold.
- Deterministic JSON canonicalization, invalid/missing revision/hash, restored older configuration files, power-loss durability, save/activation recovery and consistent notification order; exact config schema and handling of restart-only settings. Revision and hash are not audit history.
- Registry/leases, TLS/authentication/authorization/secret management, process supervision, deployment, historical retention and non-lossy JetStream/PostgreSQL path, bulk scientific data, and eventual orchestration. The current interface does not implement any of these.

Acceptance review (documentation only): common versus model-specific boundaries are explicit (sections 1–6); identities, units, quality, timing, state, health, commands, errors and diagnostics are discoverable (sections 1–5); receiver mapping preserves contract behavior (section 9); representative mount/backend assessment avoids extra abstractions (section 8); instructions for agents are explicit (section 7); unresolved details are recorded here. The specification is a basis for the next implementation issue, not evidence of an implemented API, successful Device tests or approval to change the hardware contract. Confirm the remaining model-specific schema choices during implementation review before advertising stable compatibility.

### Source record

Repository baseline: `main`, checked against GitHub on 2026-11-27. The previous architecture was refined by decisions approved by the project owner in the issue #45 design discussion. Repository source blobs consulted: `docs/device.md` `ae8b6a29cbf0d079870dd4ab16ba0db57a8d4c6e`; `docs/ai_project_context.md` `8fdcc3ebf1cb5327db93422c38dc3e443e60fe06`; `docs/project_vision.md` `1e5fdc6f4b3d504f553fcf2f3d0f6b5d6c1110b8`; `AGENTS.md` `ccfe4f6fa143c60c570533f9bd54d0242a3aebdf`; `README.md` `a82d0c9a356a9689a33f49350cf116adfcb5d1fd`; `docs/hardware_integration_workflow.md` `cd70eed48f7f9c2bc7a1f5398ed543b07efcdd04`; `contracts/models/fictitious_receiver.yaml` `fe8cc157058c53c01fe353d37055979655704628`; `docs/hardware_protocol.md` `ce04fb587cacd6c3a9df7336442e9d2d9fcfa635`; `docs/fictitious_receiver_contract_application.md` `0b710fd77f81bdda09b392909a2c18e1d7bc8ac5`; `docs/hardware_contract.md` `5afe45a2a900415989c71be2a1d07de994ada2e0`; `contracts/README.md` `5aaa437b5f04b14e2a6ab29a95ba286908feac38`; `contracts/schema-v1.json` `b11eb1ff8eda606335903077a6423e064c78daa3`. No hardware contract amendments.
