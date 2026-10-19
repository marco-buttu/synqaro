# Synqaro–TANGO Architecture Benchmark

**Status:** architectural comparison

**Scope:** key architectural differences between Synqaro and established control-system frameworks, starting with TANGO Controls

## Introduction

This document summarizes the main architectural differences between Synqaro and TANGO Controls. Its purpose is to clarify design choices and trade-offs, not to claim that either approach is universally superior. The comparison is based on the Synqaro prototype architecture and on TANGO's documented device model. Synqaro decisions described here are prototype decisions or working hypotheses, not necessarily final production choices.

## 1. Device

### 1.1 What is a Device?

A **Device** is a software entity that represents and controls a physical instrument or a tightly coupled hardware subsystem. It translates hardware-specific protocols into an interface through which other software can issue commands, obtain state, and observe failures.

In **TANGO**, a Device is an object belonging to a TANGO Device class, exposed through standard framework concepts such as commands, attributes, and events. One operating-system process, called a *Device Server*, can host one or several Devices.

In **Synqaro**, a Device is an independently restartable operating-system process that owns the connection to its hardware endpoint, maintains authoritative current state in memory, and exposes typed commands, state, and diagnostics through public interfaces. The hardware may be replaced by a protocol-compatible simulator without changing the Device or its consumers.

### 1.2 Main differences

| Aspect | TANGO Controls | Synqaro |
|---|---|---|
| **Process isolation** | A Device Server process can host multiple Devices; deploying one Device per server is also possible. | The prototype requires one independently restartable operating-system process per Device. |
| **Software structure** | Devices follow the TANGO object model and framework base classes; tools such as Pogo support interface definition and code generation. | Small compositional library; separation of hardware adapter, Device model, communication adapters, and runtime concerns; no mandatory deep inheritance hierarchy or code-generation workflow. |
| **Commands and queries** | TANGO commands and attribute access use its established client/server API, traditionally based on CORBA. | Direct HTTP/JSON endpoints with FastAPI and Pydantic for typed commands, queries, health, and description. |
| **Live updates** | Framework-defined events, commonly distributed through ZeroMQ in modern TANGO deployments. | Core NATS publish/subscribe for internal live state; WebSocket at the Core/State Service boundary for UI and external clients. |
| **Interface description** | TANGO Device classes, attributes, commands, and their metadata, with framework conventions and tooling. | Explicit typed API models; OpenAPI and JSON Schema generated from code. |
| **Discovery** | TANGO naming and device-resolution infrastructure, normally backed by the TANGO database. | Stable logical names resolved by a lightweight registry with application-level leases; commands go directly to resolved Devices. Registry details remain open. |
| **Configuration and database** | Normally uses a central database for Device properties and discovery; database-free operation is also supported in particular configurations. | Devices use small deployment configurations and have no shared PostgreSQL credentials. PostgreSQL is reserved for selected history, managed through Core services. |
| **State and data model** | Standard commands, attributes, attribute quality, timestamps, alarm conventions, and predefined Device states. | Typed, versioned state groups with explicit timestamps, sequence/session identity, quality, and diagnostic context. The shared vocabulary and envelopes remain to be defined. |
| **Acquisition and polling** | Framework-managed polling, buffering, and integration with the event system are available. | Each owning Device acquires hardware state once and publishes it to subscribers; acquisition cadence is Device-specific. |
| **Concurrency** | Runtime facilities typically involve threads and framework-managed polling; implementations are available in several languages. | Python `asyncio` is the prototype baseline. Go is a possible measured alternative, not a committed migration. |
| **Fault reporting** | Standardized Device states, attribute quality, alarms, and exceptions. | Explicit separation of process reachability, hardware connectivity, invalid data, protocol errors, and recovery; common error semantics are still open. |
| **Long-running operations** | Commands and asynchronous client operations within the TANGO programming model. | Direct command submission with operation identity, progress, results, and correlation data; exact envelopes remain open. |
| **Administration and security** | Established administration, logging, and access-control facilities, with known limitations. | Health and diagnostics are required; authentication, authorization, deployment supervision, and audit details remain open. |

### 1.3 Architectural interpretation

The primary difference is **where the architecture imposes constraints**.

TANGO provides an integrated, mature Device model with shared behavior and operational facilities. This reduces the amount of infrastructure an application must invent, but also couples implementations to TANGO's abstractions and runtime conventions.

Synqaro aims to **standardize public interfaces and shared semantics without prescribing Device internals**. A Device should remain independently implementable, testable, deployable, and eventually replaceable in another language, provided it honors the same observable contracts. NATS, HTTP, and JSON Schema provide transport and representation mechanisms; they do not, by themselves, define all application-level semantics.

Synqaro should therefore keep shared contracts **small, explicit, and versioned** while leaving hardware handling, internal object organization, and implementation language to each Device. Necessary agreements about units, timestamps, validity, command outcomes, and message ordering support interoperability; they need not imply a large inheritance-based framework.

### 1.4 Trade-offs and open work

Synqaro's lighter runtime does not eliminate control-system requirements. In particular, consistent state quality, event meaning, command validation, security, discovery failure behavior, and recovery semantics still need precise definitions and conformance tests. Some capabilities are already included in the prototype architecture; others remain deliberately unresolved.

The goal is **not to reproduce TANGO feature for feature**. Each shared facility should be introduced only when needed by a concrete use case, preferably through a small contract or an established independent component rather than a mandatory Device framework. Conversely, removing a framework convention must not result in ambiguous or incompatible Device behavior.

### References

- Synqaro, `device.md` — *Synqaro Device Architecture* (prototype architecture decision).
- TANGO Controls documentation, [The Tango device server model](https://tango-controls.readthedocs.io/en/latest/Explanation/device-server-model.html).
- TANGO Controls documentation, [Tango Data Model](https://tango-controls.readthedocs.io/en/latest/Explanation/data-model.html).
- TANGO Controls documentation, [Device polling](https://tango-controls.readthedocs.io/en/latest/Explanation/polling.html).
- TANGO Controls documentation, [Guidelines for developing a Tango Device Server](https://tango-controls.readthedocs.io/en/latest/Tutorials/ds-guideline/device-server-guidelines.html).
