# Synqaro Component Architecture

**Status:** prototype architecture decision

**Scope:** component boundary, lifecycle, communication, live state, persistence boundary, configuration, safety, validation, and initial prototype topology

**Related documents:** [Project Vision](project_vision.md) and [AI Project Context and Handoff](ai_project_context.md)

## 1. Decision status and intent

This document defines the component architecture for the first Synqaro prototype. It turns the broad direction in the Project Vision into a small, measurable architecture for one receiver, one backend, and one mount/servomechanism.

The terms below distinguish what has and has not been decided:

- **Settled prototype decision:** the baseline to implement and test. Changing it requires an explicit architecture decision and evidence.
- **Working hypothesis:** the preferred starting point, deliberately subject to measurement.
- **Open question:** not decided by this document and must not be treated as an implicit requirement.

These decisions do not claim that the prototype stack is the final production stack. The public boundaries are designed so an implementation can be replaced without changing its consumers.

## 2. Component definition and boundary

### 2.1 Definition

A Synqaro component is an independently running software model/controller for one physical device or one tightly coupled hardware subsystem. It:

- owns the connection to that device or subsystem;
- translates its low-level protocol, often a socket byte stream, into typed commands and state;
- validates component-level syntax, ranges, current-state preconditions, approved operating limits, and applicable safety constraints;
- maintains the authoritative current component state in memory;
- exposes a versioned, discoverable public interface; and
- preserves device responses, protocol failures, timestamps, correlation data, and other diagnostic detail rather than collapsing them into generic failures.

The component is the only Synqaro process that communicates directly with its device endpoint. Other components and services use the component's public APIs and state publications.

### 2.2 Boundary and non-goals

A component is not:

- a hard-real-time controller;
- a facility-wide orchestration layer;
- an opaque framework container or mandatory inheritance runtime;
- a database-backed command queue;
- a bulk scientific-data transport; or
- a replacement for firmware, PLC, or dedicated-controller feedback loops and independent safety protections.

Hard real-time loops, hard limits, emergency stops, and other independent protections remain in firmware, PLCs, or dedicated controllers. Synqaro integrates with them and adds supervisory validation; it does not weaken or replace them. Bulk backend or scientific data uses a separate path optimized for its throughput and data model.

## 3. Lifecycle and deployment

### 3.1 Process model

**Settled prototype decision:** each component runs as a separate operating-system process. It is isolated from other components, can be started and inspected independently, and can be restarted without requiring unrelated components to restart.

A deployment container is optional and is not the definition of a component. A component may run directly under a process supervisor, in a virtual machine, or in a container while retaining the same process and API boundary.

This requirement refines the broader possibility left open in the Project Vision. It applies to the prototype architecture and creates an explicit failure boundary that can be measured.

### 3.2 Location independence and distributed failure

A component can begin on one host and later move to another without changing its logical name or public API. Only deployment configuration and endpoint resolution change.

Moving a component does not make distribution transparent. The design keeps the following conditions explicit:

- network failure and partition;
- connection timeout and retry;
- component process failure;
- stale or invalid state;
- registry lease expiry; and
- recovery after either the component or device restarts.

Consumers must not infer device health solely because a network connection or component process exists.

## 4. Small internal design

Synqaro is intentionally the opposite of ACS/TANGO-style framework complexity. A component is assembled from a small compositional library. It does not require an opaque hosting container, code generation ceremony, or a deep mandatory inheritance hierarchy.

The expected internal separation is:

1. **Device adapter and protocol library** — owns transport details, framing, encoding, timeouts, parsing, protocol conformance, reconnect behavior, and raw diagnostic evidence.
2. **Component model** — implements typed state and commands, component-level validation, state transitions, operating limits, and device-independent semantics.
3. **Communication adapters** — expose direct HTTP APIs through FastAPI and publish or consume live internal state through NATS. Transport details do not define the component model.
4. **Runtime, configuration, and diagnostics** — starts the process, resolves its logical device target, manages lifecycle and registration, exposes health, and emits structured logs and metrics.

This is a separation of responsibilities, not a required package layout or class hierarchy.

### 4.1 Device connection failure

The device adapter and component handle loss of the hardware connection. Where the process itself remains healthy, the component stays reachable for health, description, diagnostic, and permitted recovery operations.

Its externally visible state must distinguish at least:

- component unreachable;
- component alive but device offline;
- protocol violation;
- invalid device data; and
- recovery or reconnection in progress.

The exact shared error and quality vocabulary is an open question, but these conditions must not be conflated.

## 5. Prototype technology baseline

The following are **settled prototype decisions** unless marked otherwise.

| Concern | Prototype decision | Rationale and boundary |
|---|---|---|
| Component language | Python | Minimizes implementation and toolchain complexity, supports code-first APIs and testing, and provides mature asynchronous I/O. Scientific Python libraries are not a reason to place Python in low-level components. |
| Device concurrency | `asyncio` | Supports device polling and pushed telemetry without a mandatory thread or framework model. |
| Direct component API | FastAPI with Pydantic models | Provides typed, code-first HTTP/JSON command, query, health, and description endpoints. |
| API/schema description | OpenAPI and JSON Schema generated from code | The prototype has no separate per-component gRPC/Protobuf IDL. Explicit Python types and exported endpoints remain the source. |
| HTTP runtime | An ASGI server such as Uvicorn | Expected runtime shape; versions are not pinned by this architecture document. |
| Internal live distribution | Core NATS publish/subscribe | Provides simple many-to-many distribution of live, superseded state. |
| External live distribution | WebSocket at the Core/State Service edge | Serves UIs and external clients without turning each component into a fan-out server or using WebSocket as the internal bus. |
| Historical storage | PostgreSQL | Stores selected historical telemetry, command/operation history, alarms, and diagnostic evidence. It is neither the live communication bus nor a command queue. |
| Initial payload representation | Inspectable JSON | **Working hypothesis:** use JSON until measurements justify a binary encoding. |

**Measured alternative:** Go remains the leading alternative for production device components if benchmarks demonstrate a need for compiled single binaries, stricter static typing, or lower runtime overhead. HTTP/JSON and NATS contracts must permit a Go implementation to replace a Python implementation without changing consumers.

## 6. Identity, discovery, and liveness

Components use stable logical names, for example `mount.srt.main`. A central registry acts as a directory:

1. a component registers its logical identity and current HTTP endpoint;
2. it renews an application-level liveness lease;
3. a client resolves the logical name;
4. the client caches the resolution for an appropriate bounded period; and
5. the client calls the component directly.

The registry is not a command proxy. It does not conceal direct component failures or become the data path for every command.

Registration and lease health are application-level concepts. A successful HTTP connection, TCP keepalive, NATS connection, or other transport check proves only that some transport path is present; it does not prove that the component is ready or that its device is connected and valid.

The registry implementation, lease rules, cache invalidation behavior, high availability, and failover semantics remain open.

## 7. Commands and operations

Commands are direct typed HTTP calls to the component that owns the target device. Before any request reaches the device, the receiver validates:

- request syntax and types;
- parameter ranges and units;
- current local state and command preconditions;
- caller permission; and
- applicable component-level and safety constraints.

Each component rechecks its own current state at command execution time. A caller may have made a decision using distributed state, but that state can become stale between decision and execution.

A short operation may complete in its HTTP response. A long operation returns an operation identity and subsequently publishes progress and the final result; query access may also be provided. Operation and correlation identities must preserve diagnostic causality across the direct request, device interaction, progress, result, alarm, and audit history.

The exact command, operation, result, and error envelopes remain open. PostgreSQL is not used as a command queue.

## 8. Live state distribution

### 8.1 Acquisition and ownership

If a device can push telemetry with suitable semantics, the component receives it. Otherwise, the component polls at the cadence required by its contract and the supervisory use case.

The owning component performs each physical acquisition once, updates its authoritative in-memory state, and publishes a self-contained state group on NATS. Other components do not independently poll the same device and do not poll PostgreSQL for current state.

### 8.2 Mount position example

If consumers need mount position every 50 ms:

1. the mount component performs one 20 Hz acquisition from the mount device;
2. it updates the authoritative position state in memory;
3. it publishes a self-contained position state group on NATS;
4. every interested component subscribes to that publication once; and
5. each consumer retains the latest accepted value locally and checks its timestamp, quality, sequence, and freshness before use.

Adding consumers must not add mount-device polls or database queries.

A 50 ms publication period is supervisory near-real-time behavior. It is not a hard-real-time guarantee, feedback loop, or safety control.

### 8.3 Delivery and state shape

Core NATS has at-most-once delivery. That is acceptable for continuously superseded current-state samples provided the publication includes sequence information so consumers can observe missed updates. A consumer must explicitly mark state stale or invalid; it must never silently continue to present an old value as current.

Alarms, command results, audit records, and other non-lossy events require a durable path. The exact division between NATS JetStream and PostgreSQL remains open.

**Working hypothesis:** for small, moderate-rate state, publish complete self-contained snapshots or coherent groups rather than requiring consumers to reconstruct state from deltas. Measurements may justify another representation.

Each state publication must preserve:

- component identity;
- component boot/session identity;
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

- subscribes to component state on NATS;
- materializes the latest accepted state in memory;
- rejects or marks out-of-order updates and detects stale data;
- provides aggregate HTTP queries;
- serves filtered live updates to external WebSocket clients; and
- asynchronously or in batches records selected telemetry and history in PostgreSQL, potentially through a separately identifiable recorder role.

When an external client subscribes, the service should deliver an ordered snapshot followed by updates with later revisions, so the client cannot confuse subscription timing with a complete initial state.

Components neither query nor write shared PostgreSQL tables and do not receive shared database credentials. A database outage must not stop device communication or the live component-to-NATS path. Recording failures remain observable and recover according to the eventually selected durability policy.

After a State Service restart, any values loaded from PostgreSQL are historical and stale until refreshed by the current boot/session of the owning component. Stored values must not silently become authoritative current state.

**Working hypothesis:** for prototype simplicity, registry, materialized-state, aggregate HTTP/WebSocket gateway, and recorder roles can share one small Synqaro Core process. Split them only when failure isolation, scaling, security, or operational measurements justify it.

## 10. Configuration and simulator parity

The simulator replaces the hardware, not the component. It implements the real device protocol and supports reproducible fault injection.

The paths are deliberately the same:

```text
development: component -> device protocol -> simulator
production:  component -> device protocol -> physical device
```

Deployment environments resolve a stable logical device name such as `receiver-device` to either a simulator endpoint or a physical-device endpoint. Only the owning component sees that endpoint. Other components continue to use the owner's stable public identity and API.

Avoid separate, duplicated full configurations for test and production. Keep one configuration shape and vary environment-specific endpoint resolution and approved values.

A component configuration remains small:

- logical component identity;
- logical device target or resolver;
- HTTP listen address;
- registry address;
- NATS address;
- device timeouts and polling settings; and
- approved operating limits.

Component configuration contains no PostgreSQL address or database credentials.

## 11. Health, safety, and timing semantics

Health reporting must keep these dimensions distinct:

- process reachability;
- component application readiness;
- device connectivity;
- device data validity;
- state freshness; and
- registry lease status.

FastAPI health endpoints expose application-level status. Transport keepalives expose only connection status.

The component's deterministic command and safety boundaries apply equally to human users, conventional clients, operational services, and AI agents. AI cannot bypass permissions, parameter validation, state preconditions, operating limits, or independent safety systems.

Supervisory publication cadences, including the representative 50 ms mount interval, must be described and measured in terms of latency, jitter, loss, and freshness. They must not be described as hard real-time guarantees.

## 12. Proportional validation

The prototype must validate architecture claims with tests and measurements proportional to risk:

- device protocol and contract-conformance tests;
- simulator tests and reproducible fault injection for timeouts, disconnections, malformed responses, invalid values, and recovery;
- FastAPI request/response, health, description, OpenAPI, and JSON Schema tests;
- NATS state-distribution tests, including multiple consumers, sequence gaps, stale data, out-of-order data, and component restarts;
- independent process restart and recovery tests for each component, Core, NATS, and PostgreSQL where applicable;
- fan-out, end-to-end latency, jitter, loss, and recovery measurements at representative rates; and
- explicitly authorized, safe real-hardware checks that reconcile the simulator, protocol contract, component, and observed device behavior.

Simulator success does not prove hardware correctness. A mismatch improves the contract, simulator, test, component, or device implementation rather than being hidden.

## 13. Alternatives and reversals

| Considered direction | Prototype decision | Rationale or condition for revisit |
|---|---|---|
| gRPC/Protobuf for every component | Use FastAPI/Pydantic with generated OpenAPI and JSON Schema | A separate per-component IDL adds prototype complexity. Revisit with measured performance evidence or a concrete multi-language requirement. |
| Infer interfaces from arbitrary component implementation details | Require explicit Python types and exported endpoints | Discovery must be deliberate, testable, and versionable rather than magical. |
| Direct per-component WebSocket fan-out or a custom FastAPI broker | Use NATS internally and WebSocket only at the external edge | NATS supplies the many-to-many distribution role without making every component a broker. |
| PostgreSQL as current-state or command bus | Keep current state in memory/NATS and use PostgreSQL for selected history | Database latency and availability must not sit in the live device or command path. |
| Add Redis Pub/Sub | Do not introduce Redis without another demonstrated Redis requirement | Core NATS already fills the selected prototype pub/sub role. |
| Use ZeroMQ | Do not select it for the prototype | Synqaro would still need to own more topology, discovery, reconnect, and fan-out policy. |
| Select Python because of scientific libraries | Select Python for prototype simplicity, typed code-first APIs, testing, and asynchronous I/O | Scientific processing does not belong in low-level components merely because Python can host it. |
| Introduce Go immediately | Retain Go as a measured replacement option | Revisit when binary distribution, type guarantees, or runtime overhead have benchmarked value. |

## 14. Initial prototype topology

The first measurable slice contains separate component processes and matching simulator processes:

```text
receiver component ---- receiver device protocol ---- receiver simulator
backend component  ---- backend device protocol  ---- backend simulator
mount component    ---- mount device protocol    ---- mount simulator
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

Direct commands resolve a component through the registry and then call that component's HTTP endpoint; they do not flow through the diagram's state-distribution line or through PostgreSQL.

## 15. Prototype acceptance criteria

The architecture slice is accepted only when evidence demonstrates that:

1. the same component implementation runs against a simulator or real-device endpoint selected only through deployment configuration;
2. receiver, backend, and mount components run as separate processes and each can restart independently;
3. clients resolve stable logical names through the registry and then issue direct typed HTTP commands;
4. command validation rejects invalid syntax, ranges, state/preconditions, permissions, or safety conditions before device transmission;
5. the mount path acquires and publishes representative position state at 20 Hz, with measured latency and jitter;
6. multiple consumers receive mount state without independently polling the mount device or PostgreSQL;
7. consumers and the State Service detect stale state, boot/session changes, missed sequence data, and out-of-order updates;
8. PostgreSQL unavailability does not stop device communication or live state distribution;
9. a device failure is observably different from a component process failure, protocol violation, invalid data, and recovery in progress; and
10. reproducible fault injection exercises timeouts, dropped connections, malformed responses, invalid values, and recovery.

Safe real-hardware conformance is a distinct acceptance step and requires the authorization appropriate to the device and risk.

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
