# Synqaro Device Architecture

**Status:** prototype architecture decision

**Scope:** Device boundary, lifecycle, communication, live state, persistence boundary, configuration, safety, validation, and initial prototype topology

**Related documents:** [Project Vision](project_vision.md) and [AI Project Context and Handoff](ai_project_context.md)

## 1. Decision status and intent

This document defines the Device architecture for the first Synqaro prototype. It turns the broad direction in the Project Vision into a small, measurable architecture for one receiver, one backend, and one mount/servomechanism.

The terms below distinguish what has and has not been decided:

- **Settled prototype decision:** the baseline to implement and test. Changing it requires an explicit architecture decision and evidence.
- **Working hypothesis:** the preferred starting point, deliberately subject to measurement.
- **Open question:** not decided by this document and must not be treated as an implicit requirement.

These decisions do not claim that the prototype stack is the final production stack. The public boundaries are designed so an implementation can be replaced without changing its consumers.

## 2. Device definition and boundary

### 2.1 Definition

A Synqaro **Device** is the software representation and controller for one physical device or one tightly coupled hardware subsystem. It runs as an independently restartable operating-system process, communicates with the underlying hardware or its simulator, maintains authoritative current state, and exposes commands, state, and events to the rest of Synqaro. A Device:

- owns the connection to that physical device or subsystem;
- translates its low-level protocol, often a socket byte stream, into typed commands and state;
- validates Device-level syntax, ranges, current-state preconditions, approved operating limits, and applicable safety constraints;
- maintains its authoritative current state in memory;
- exposes a versioned, discoverable public interface; and
- preserves hardware responses, protocol failures, timestamps, correlation data, and other diagnostic detail rather than collapsing them into generic failures.

The Device is the only Synqaro process that communicates directly with its hardware endpoint. Other Devices and services use the Device's public APIs and state publications.

### 2.2 Boundary and non-goals

A Device is not:

- a hard-real-time controller;
- a facility-wide orchestration layer;
- an opaque framework container or mandatory inheritance runtime;
- a database-backed command queue;
- a bulk scientific-data transport; or
- a replacement for firmware, PLC, or dedicated-controller feedback loops and independent safety protections.

Hard real-time loops, hard limits, emergency stops, and other independent protections remain in firmware, PLCs, or dedicated controllers. Synqaro integrates with them and adds supervisory validation; it does not weaken or replace them. Bulk backend or scientific data uses a separate path optimized for its throughput and data model.

## 3. Lifecycle and deployment

### 3.1 Process model

**Settled prototype decision:** each Device runs as a separate operating-system process. It is isolated from other Devices, can be started and inspected independently, and can be restarted without requiring unrelated Devices to restart.

A deployment container is optional and is not the definition of a Device. A Device may run directly under a process supervisor, in a virtual machine, or in a container while retaining the same process and API boundary.

This requirement refines the broader possibility left open in the Project Vision. It applies to the prototype architecture and creates an explicit failure boundary that can be measured.

### 3.2 Location independence and distributed failure

A Device can begin on one host and later move to another without changing its logical name or public API. Only deployment configuration and endpoint resolution change.

Moving a Device does not make distribution transparent. The design keeps the following conditions explicit:

- network failure and partition;
- connection timeout and retry;
- Device process failure;
- stale or invalid state;
- registry lease expiry; and
- recovery after either the Device or hardware restarts.

Consumers must not infer hardware health solely because a network connection or Device process exists.

## 4. Small internal design

Synqaro is intentionally the opposite of ACS/TANGO-style framework complexity. A Device is assembled from a small compositional library. It does not require an opaque hosting container, code generation ceremony, or a deep mandatory inheritance hierarchy.

The expected internal separation is:

1. **device adapter and protocol library** — owns transport details, framing, encoding, timeouts, parsing, protocol conformance, reconnect behavior, and raw diagnostic evidence.
2. **Device model** — implements typed state and commands, Device-level validation, state transitions, operating limits, and hardware-independent semantics.
3. **Communication adapters** — expose direct HTTP APIs through FastAPI and publish or consume live internal state through NATS. Transport details do not define the Device model.
4. **Runtime, configuration, and diagnostics** — starts the process, resolves its logical hardware target, manages lifecycle and registration, exposes health, and emits structured logs and metrics.

This is a separation of responsibilities, not a required package layout or class hierarchy.

### 4.1 Hardware connection failure

The device adapter and Device handle loss of the hardware connection. Where the process itself remains healthy, the Device stays reachable for health, description, diagnostic, and permitted recovery operations.

Its externally visible state must distinguish at least:

- Device unreachable;
- Device alive but hardware offline;
- protocol violation;
- invalid hardware data; and
- recovery or reconnection in progress.

The exact shared error and quality vocabulary is an open question, but these conditions must not be conflated.

## 5. Prototype technology baseline

The following are **settled prototype decisions** unless marked otherwise.

| Concern | Prototype decision | Rationale and boundary |
|---|---|---|
| Device language | Python | Minimizes implementation and toolchain complexity, supports code-first APIs and testing, and provides mature asynchronous I/O. Scientific Python libraries are not a reason to place Python in low-level Devices. |
| Device concurrency | `asyncio` | Supports hardware polling and pushed telemetry without a mandatory thread or framework model. |
| Direct Device API | FastAPI with Pydantic models | Provides typed, code-first HTTP/JSON command, query, health, and description endpoints. |
| API/schema description | OpenAPI and JSON Schema generated from code | The prototype has no separate per-Device gRPC/Protobuf IDL. Explicit Python types and exported endpoints remain the source. |
| HTTP runtime | An ASGI server such as Uvicorn | Expected runtime shape; versions are not pinned by this architecture document. |
| Internal live distribution | Core NATS publish/subscribe | Provides simple many-to-many distribution of live, superseded state. |
| External live distribution | WebSocket at the Core/State Service edge | Serves UIs and external clients without turning each Device into a fan-out server or using WebSocket as the internal bus. |
| Historical storage | PostgreSQL | Stores selected historical telemetry, command/operation history, alarms, and diagnostic evidence. It is neither the live communication bus nor a command queue. |
| Initial payload representation | Inspectable JSON | **Working hypothesis:** use JSON until measurements justify a binary encoding. |

**Measured alternative:** Go remains the leading alternative for production Devices if benchmarks demonstrate a need for compiled single binaries, stricter static typing, or lower runtime overhead. HTTP/JSON and NATS contracts must permit a Go implementation to replace a Python implementation without changing consumers.

## 6. Identity, discovery, and liveness

Devices use stable logical names, for example `mount.srt.main`. A central registry acts as a directory:

1. a Device registers its logical identity and current HTTP endpoint;
2. it renews an application-level liveness lease;
3. a client resolves the logical name;
4. the client caches the resolution for an appropriate bounded period; and
5. the client calls the Device directly.

The registry is not a command proxy. It does not conceal direct Device failures or become the data path for every command.

Registration and lease health are application-level concepts. A successful HTTP connection, TCP keepalive, NATS connection, or other transport check proves only that some transport path is present; it does not prove that the Device is ready or that its hardware is connected and valid.

The registry implementation, lease rules, cache invalidation behavior, high availability, and failover semantics remain open.

## 7. Commands and operations

Commands are direct typed HTTP calls to the Device that owns the target hardware. Before any request reaches the hardware, the Device validates:

- request syntax and types;
- parameter ranges and units;
- current local state and command preconditions;
- caller permission; and
- applicable Device-level and safety constraints.

Each Device rechecks its own current state at command execution time. A caller may have made a decision using distributed state, but that state can become stale between decision and execution.

A short operation may complete in its HTTP response. A long operation returns an operation identity and subsequently publishes progress and the final result; query access may also be provided. Operation and correlation identities must preserve diagnostic causality across the direct request, hardware interaction, progress, result, alarm, and audit history.

The exact command, operation, result, and error envelopes remain open. PostgreSQL is not used as a command queue.

## 8. Live state distribution

### 8.1 Acquisition and ownership

If the hardware can push telemetry with suitable semantics, the Device receives it. Otherwise, the Device polls at the cadence required by its contract and the supervisory use case.

The owning Device performs each physical acquisition once, updates its authoritative in-memory state, and publishes a self-contained state group on NATS. Other Devices do not independently poll the same hardware and do not poll PostgreSQL for current state.

### 8.2 Mount position example

If consumers need mount position every 50 ms:

1. the mount Device performs one 20 Hz acquisition from the mount hardware;
2. it updates the authoritative position state in memory;
3. it publishes a self-contained position state group on NATS;
4. every interested Device or service subscribes to that publication once; and
5. each consumer retains the latest accepted value locally and checks its timestamp, quality, sequence, and freshness before use.

Adding consumers must not add mount-hardware polls or database queries.

A 50 ms publication period is supervisory near-real-time behavior. It is not a hard-real-time guarantee, feedback loop, or safety control.

### 8.3 Delivery and state shape

Core NATS has at-most-once delivery. That is acceptable for continuously superseded current-state samples provided the publication includes sequence information so consumers can observe missed updates. A consumer must explicitly mark state stale or invalid; it must never silently continue to present an old value as current.

Alarms, command results, audit records, and other non-lossy events require a durable path. The exact division between NATS JetStream and PostgreSQL remains open.

**Working hypothesis:** for small, moderate-rate state, publish complete self-contained snapshots or coherent groups rather than requiring consumers to reconstruct state from deltas. Measurements may justify another representation.

Each state publication must preserve:

- Device identity;
- Device boot/session identity;
- schema version;
- monotonically usable sequence information within the boot/session;
- observation timestamp and publication timestamp;
- typed property identity and value;
- unit and semantic metadata, carried in the sample or available from a versioned discoverable schema;
- quality or validity; and
- relevant error or alarm context.

Exact NATS subject names are open. Illustrative names such as `state.mount.srt.main.position` may be used in prototypes or discussion, but are not final conventions.

## 9. State Service, external edge, and persistence

A domain-neutral **State Service** role within Synqaro Core:

- subscribes to Device state on NATS;
- materializes the latest accepted state in memory;
- rejects or marks out-of-order updates and detects stale data;
- provides aggregate HTTP queries;
- serves filtered live updates to external WebSocket clients; and
- asynchronously or in batches records selected telemetry and history in PostgreSQL, potentially through a separately identifiable recorder role.

When an external client subscribes, the service should deliver an ordered snapshot followed by updates with later revisions, so the client cannot confuse subscription timing with a complete initial state.

Devices neither query nor write shared PostgreSQL tables and do not receive shared database credentials. A database outage must not stop hardware communication or the live Device-to-NATS path. Recording failures remain observable and recover according to the eventually selected durability policy.

After a State Service restart, any values loaded from PostgreSQL are historical and stale until refreshed by the current boot/session of the owning Device. Stored values must not silently become authoritative current state.

**Working hypothesis:** for prototype simplicity, registry, materialized-state, aggregate HTTP/WebSocket gateway, and recorder roles can share one small Synqaro Core process. Split them only when failure isolation, scaling, security, or operational measurements justify it.

## 10. Configuration and simulator parity

The simulator replaces the hardware, not the Device. It implements the real hardware protocol and supports reproducible fault injection.

The paths are deliberately the same:

```text
development: Device -> hardware protocol -> simulator
production:  Device -> hardware protocol -> physical hardware
```

Deployment environments resolve a stable logical hardware name such as `receiver-hardware` to either a simulator endpoint or a physical-hardware endpoint. Only the owning Device sees that endpoint. Other Devices continue to use the owner's stable public identity and API.

Avoid separate, duplicated full configurations for test and production. Keep one configuration shape and vary environment-specific endpoint resolution and approved values.

A Device configuration remains small:

- logical Device identity;
- logical hardware target or resolver;
- HTTP listen address;
- registry address;
- NATS address;
- hardware timeouts and polling settings; and
- approved operating limits.

Device configuration contains no PostgreSQL address or database credentials.

## 11. Health, safety, and timing semantics

Health reporting must keep these dimensions distinct:

- process reachability;
- Device application readiness;
- hardware connectivity;
- hardware data validity;
- state freshness; and
- registry lease status.

FastAPI health endpoints expose application-level status. Transport keepalives expose only connection status.

The Device's deterministic command and safety boundaries apply equally to human users, conventional clients, operational services, and AI agents. AI cannot bypass permissions, parameter validation, state preconditions, operating limits, or independent safety systems.

Supervisory publication cadences, including the representative 50 ms mount interval, must be described and measured in terms of latency, jitter, loss, and freshness. They must not be described as hard real-time guarantees.

## 12. Proportional validation

The prototype must validate architecture claims with tests and measurements proportional to risk:

- hardware protocol and contract-conformance tests;
- simulator tests and reproducible fault injection for timeouts, disconnections, malformed responses, invalid values, and recovery;
- FastAPI request/response, health, description, OpenAPI, and JSON Schema tests;
- NATS state-distribution tests, including multiple consumers, sequence gaps, stale data, out-of-order data, and Device restarts;
- independent process restart and recovery tests for each Device, Core, NATS, and PostgreSQL where applicable;
- fan-out, end-to-end latency, jitter, loss, and recovery measurements at representative rates; and
- explicitly authorized, safe real-hardware checks that reconcile the simulator, protocol contract, Device, and observed hardware behavior.

Simulator success does not prove hardware correctness. A mismatch improves the contract, simulator, test, Device, or hardware implementation rather than being hidden.

## 13. Alternatives and reversals

| Considered direction | Prototype decision | Rationale or condition for revisit |
|---|---|---|
| gRPC/Protobuf for every Device | Use FastAPI/Pydantic with generated OpenAPI and JSON Schema | A separate per-Device IDL adds prototype complexity. Revisit with measured performance evidence or a concrete multi-language requirement. |
| Infer interfaces from arbitrary Device implementation details | Require explicit Python types and exported endpoints | Discovery must be deliberate, testable, and versionable rather than magical. |
| Direct per-Device WebSocket fan-out or a custom FastAPI broker | Use NATS internally and WebSocket only at the external edge | NATS supplies the many-to-many distribution role without making every Device a broker. |
| PostgreSQL as current-state or command bus | Keep current state in memory/NATS and use PostgreSQL for selected history | Database latency and availability must not sit in the live hardware or command path. |
| Add Redis Pub/Sub | Do not introduce Redis without another demonstrated Redis requirement | Core NATS already fills the selected prototype pub/sub role. |
| Use ZeroMQ | Do not select it for the prototype | Synqaro would still need to own more topology, discovery, reconnect, and fan-out policy. |
| Select Python because of scientific libraries | Select Python for prototype simplicity, typed code-first APIs, testing, and asynchronous I/O | Scientific processing does not belong in low-level Devices merely because Python can host it. |
| Introduce Go immediately | Retain Go as a measured replacement option | Revisit when binary distribution, type guarantees, or runtime overhead have benchmarked value. |

## 14. Initial prototype topology

The first measurable slice contains separate Device processes and matching simulator processes:

```text
receiver Device ---- receiver hardware protocol ---- receiver simulator
backend Device  ---- backend hardware protocol  ---- backend simulator
mount Device    ---- mount hardware protocol    ---- mount simulator
       |                         |                         |
       +-------------------------+-------------------------+
                                 |
                            Core NATS
                                 |
                  small Synqaro Core process
       registry + latest state + HTTP/WebSocket + recorder
                                 |
                    PostgreSQL when history is introduced
```

Direct commands resolve a Device through the registry and then call that Device's HTTP endpoint; they do not flow through the diagram's state-distribution line or through PostgreSQL.

## 15. Prototype acceptance criteria

The architecture slice is accepted only when evidence demonstrates that:

1. the same Device implementation runs against a simulator or physical-hardware endpoint selected only through deployment configuration;
2. receiver, backend, and mount Devices run as separate processes and each can restart independently;
3. clients resolve stable logical names through the registry and then issue direct typed HTTP commands;
4. command validation rejects invalid syntax, ranges, state/preconditions, permissions, or safety conditions before hardware transmission;
5. the mount path acquires and publishes representative position state at 20 Hz, with measured latency and jitter;
6. multiple consumers receive mount state without independently polling the mount hardware or PostgreSQL;
7. consumers and the State Service detect stale state, boot/session changes, missed sequence data, and out-of-order updates;
8. PostgreSQL unavailability does not stop hardware communication or live state distribution;
9. a hardware failure is observably different from a Device process failure, protocol violation, invalid data, and recovery in progress; and
10. reproducible fault injection exercises timeouts, dropped connections, malformed responses, invalid values, and recovery.

Safe real-hardware conformance is a distinct acceptance step and requires the authorization appropriate to the hardware and risk.

## 16. Open questions

The following are deliberately unresolved:

- exact command, state, operation, result, and error envelopes;
- the shared quality/validity vocabulary;
- timestamp clock, precision, synchronization, and unit policy;
- NATS subject naming, account boundaries, and authorization;
- schema evolution and compatibility rules;
- snapshot/group versus delta thresholds and representation;
- recovery after missed ephemeral state messages;
- the durability split between JetStream and PostgreSQL;
- telemetry selection, downsampling, retention, and query policy;
- registry implementation, lease timing, cache behavior, and high availability;
- TLS, authentication, authorization, audit, and secret management;
- process supervision, packaging, deployment, and upgrade strategy; and
- benchmark thresholds that would justify Go or binary payload encoding.

These questions should be answered through the smallest representative prototype, measurements, fault tests, and explicit architecture decisions. They are not license to leave the observable behavior undefined during implementation.
