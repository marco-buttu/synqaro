# Synqaro — AI Project Context and Handoff

**Document purpose:** preserve the project intent, settled decisions, reasoning, constraints, reversals, and open questions needed by an AI collaborator joining the Synqaro repository.

**Intended repository path:** `docs/ai_project_context.md`

**Status:** working handoff; not an implementation specification

**Related authoritative document:** [Synqaro Project Vision v0.9](project_vision.md)

**Current component architecture:** [Synqaro Component Architecture](component.md)

## 1. How to use this document

This document complements the Project Vision. The Project Vision describes what Synqaro is intended to become; this handoff preserves why the project took its present direction, which ideas are settled, which were revised, and which decisions remain open.

Project Vision v0.9 is present in this repository and is the primary source for its explicit requirements. This handoff records rationale and continuity, while focused architecture documents may refine prototype decisions that the vision deliberately left open. If the documents conflict, surface the conflict instead of silently choosing one; do not infer precedence from a version number alone.

The labels used here have precise meanings:

- **Settled principle:** accepted direction that should not be changed casually.
- **Working hypothesis:** direction to validate through prototypes before making permanent.
- **Open decision:** deliberately unresolved.
- **Rejected or reversed:** an earlier direction that should not be reintroduced without new evidence.

## 2. Project definition

Synqaro is an AI-native engineering and control platform for complex distributed scientific and industrial systems. It is not primarily a conventional control framework with a chatbot added on top. Its defining objective is to make the entire lifecycle accessible to, and increasingly executable by, AI agents:

- requirements and architecture;
- device and firmware integration;
- component and operational-layer development;
- simulator and test generation;
- deployment and configuration;
- operation and user assistance;
- monitoring and diagnosis;
- issue reproduction and correction;
- maintenance and long-term evolution.

Traditional control capabilities—distributed communication, commands, state, telemetry, alarms, history, sequencing, and supervision—are necessary, but they are not individually the innovation claim. The distinguishing hypothesis is that contracts, components, simulators, tests, telemetry, errors, source code, and operational knowledge can be connected coherently enough for agents to develop, understand, diagnose, and evolve the system reliably.

Synqaro must therefore be **AI-native without becoming AI-dependent**. Deterministic control must continue to function when the agentic environment is unavailable.

## 3. Motivation

The project originates in approximately two decades of experience with the ACS-based control software used by the Sardinia Radio Telescope (SRT) and related INAF radio-telescope systems.

The central problem is not merely that ACS and its dependencies are old. The operational experience is that framework complexity dominates many otherwise simple changes:

- specialist knowledge takes substantial time to acquire;
- documentation and technologies age together;
- even isolated component work may require a heavy environment and long startup path;
- testing and debugging are difficult to isolate;
- failures can be hard to locate across firmware, communication, framework, component code, and orchestration;
- automated tests, modern delivery workflows, and agentic development are harder to introduce;
- maintenance becomes concentrated in a small number of people;
- obsolescence propagates to clients and adjacent software.

A middleware previously reduced some of these effects by exposing modern APIs outside the legacy control system. That was a useful mitigation, not a solution to the underlying dependency.

Synqaro is intended to change the cost and method of developing, integrating, testing, diagnosing, and maintaining a control system that may remain operational for decades. The goal is not to reproduce ACS with newer technologies. It is to retain only the mechanisms that are actually necessary, make them independently testable, and make their behavior explicit enough for both machines and humans to verify.

Claims of lower cost, greater reliability, or faster maintenance are motivations and expected benefits until measured. Likewise, the absence of an equivalent system in an initial literature search does not establish uniqueness. Any novelty claim must be supported by a broader, systematic comparison with systems such as EPICS, TANGO, ACS, ELT control software, SKA practices, digital-twin work, and LIGO Guardian.

## 4. Settled architectural principles

### 4.1 A small, domain-neutral core

The Synqaro Core should provide a limited set of reusable mechanisms:

- component registration and discovery;
- command invocation and long-running operation tracking;
- states, events, alarms, and structured diagnostics;
- current and historical telemetry access;
- configuration and component-level operating limits;
- correlation and traceability across commands, events, failures, and tests;
- uniform, permission-aware machine access for clients and agents.

The core should understand components, capabilities, commands, states, parameters, events, and errors. It should not embed concepts such as astronomical observations, receivers, backends, interferometers, or production lines.

The core provides mechanisms. Application-specific layers provide policies.

### 4.2 Domain-specific operational layers

Each facility may build an operational layer on top of the same core:

- SRT, Medicina, and Noto: observation setup, schedules, and coordination of antenna, receiver, and backend;
- Einstein Telescope (ET): subsystem supervision and operational sequences, without replacing specialized real-time controls;
- industrial systems: facility-specific production or machine-coordination policies.

Some orchestration mechanisms—timeouts, cancellation, prerequisites, completion conditions, recovery, and generic command sequencing—may prove reusable. They should be promoted into optional common services only after prototypes demonstrate that they are genuinely cross-domain. Do not move domain policies into the core merely to make the platform appear generic.

### 4.3 Operational and technical interaction are distinct

The astronomer/operator experience and the technical diagnostic experience have different goals and permissions, but they should use the same underlying contracts and data.

The technical interface is not automatically a second orchestration system. It may primarily access the core directly for diagnostics, state inspection, tests, and authorized low-level operations. The observing layer coordinates domain operations. Keep user interfaces separate from orchestration responsibilities.

### 4.4 Components must be independently understandable and testable

For the prototype, a Synqaro component is an independently running software model/controller for one physical device or tightly coupled hardware subsystem, and each component runs as a separate operating-system process. This is a deliberate failure and restart boundary. A component is still not defined by a deployment container: containers remain optional, and a component may move between hosts without changing its public API. The focused [component architecture](component.md) records this refinement of the broader process-mapping question left open in the Project Vision.

Each component should:

- expose an explicit, versioned contract;
- start and run without requiring the entire facility;
- have controlled dependencies;
- support simulation and automated verification;
- preserve precise diagnostic information;
- be replaceable without forcing unrelated components to change.

Legacy code is evidence of required behavior, not a design to translate line by line. Reconstruct the necessary behavior and remove historical framework complexity.

### 4.5 Structured operational data

Operational quantities must be machine-discoverable and consistently described. At minimum, a datum should carry identity, value, unit, timestamp, quality or validity, ownership, and semantic description. Current values and historical series are related but distinct access modes.

Storage rates and retention must be selected deliberately; not every value should be recorded indiscriminately. Numerical calculation, filtering, statistics, and plotting should be performed by deterministic tools. Agents select tools and interpret results; they do not invent measurements.

### 4.6 Diagnostics are an architectural concern

Errors must retain their identity and context across layers. The system should distinguish, where possible:

- physical-device or firmware failures;
- communication failures;
- protocol violations;
- timeouts and incomplete responses;
- invalid configuration;
- operating-limit violations;
- component software defects;
- orchestration or coordination failures.

The aim is to prevent a low-level failure from becoming an uninformative high-level error. Commands, events, logs, alarms, and issue records should carry correlation identifiers sufficient to reconstruct a causal chain.

## 5. The Smith agent layer

“Smith” is the provisional name for the agentic role or environment around Synqaro. It is not a specific product and must not become a mandatory dependency of the core.

Four boundaries must remain explicit and testable:

1. **Smith ↔ Synqaro:** stable, documented, permission-aware APIs and tools.
2. **Smith ↔ AI models:** replaceable local or remote models through adapters.
3. **Smith ↔ operators:** interaction channels independent of the Smith implementation.
4. **Smith internal capabilities:** memory, tool use, development, diagnosis, and conversation should evolve independently rather than forming an inseparable monolith.

Models, agent frameworks, and tool paradigms will change much faster than control infrastructure. Synqaro must therefore be vendor- and model-agnostic. Replacing a model may still be difficult because models differ in tool use and reliability; compatibility and safety tests are required. Architectural decoupling reduces replacement cost but does not make compatibility automatic.

Hermes Agent is only a candidate to investigate as an implementation of Smith or as a source of interface ideas. Its persistent memory, local execution, model flexibility, and tool integration may be useful. Synqaro must not be built around Hermes. Model Context Protocol (MCP) is also a candidate interoperability mechanism, not a settled core technology.

A persistent operational agent should answer routine questions by querying structured states, alarms, events, and diagnostic APIs. It should not need to reread source code to answer “Why is the antenna not moving?” Source analysis is appropriate for deeper development or fault investigation.

Project knowledge must not depend on an agent's conversational memory. The repository, contracts, tests, decisions, and telemetry are the verifiable memory of the system.

## 6. AI-native lifecycle

Synqaro should be developed from the beginning using the same agentic principles it is intended to support later.

The development environment should provide:

- an authoritative, versioned repository of vision, requirements, decisions, contracts, and procedures;
- persistent agent instructions, expected to include an `AGENTS.md` file;
- a reproducible environment that can run the system against simulated devices;
- automated tests and fault scenarios that agents can execute without physical hardware;
- traceability from requirements to contracts, code, tests, observed failures, and fixes;
- independent review and verification rather than trust in plausible generated code.

Start with one agent completing a full lifecycle successfully before introducing a complex multi-agent organization. Specialized roles for architecture, implementation, testing, review, operations, and diagnosis may emerge later if evidence justifies them.

A target maintenance loop is:

1. receive an operator report or issue;
2. collect correlated operational evidence;
3. reproduce the failure against simulators or recorded scenarios;
4. locate the affected layer;
5. propose or implement a correction;
6. add a regression test;
7. run conformance, integration, and safety checks;
8. prepare a reviewable change;
9. deploy only under the approval policy appropriate to the risk;
10. connect the deployed result back to the original report.

Agent autonomy should be able to increase over time without a redesign. The system must not assume either permanent human approval for every action or agent infallibility. Authority is granted by demonstrated capability, independent verification, and risk.

### 6.1 Agent-generated tools

If an operator asks for an analysis for which no tool exists, an agent may create one. Keep three levels distinct:

- **temporary analysis:** generated and executed in an isolated environment with read-only, controlled data access;
- **reusable tool:** versioned, documented, tested, permission-scoped, and added to a discoverable catalog;
- **permanent system extension:** changes operational software or APIs and therefore follows the full engineering and approval process.

Temporary tools must not acquire control permissions merely because they can read telemetry. Scientific validity requires explicit assumptions, units, timestamp handling, missing-data behavior, and domain validation; software tests alone are insufficient.

## 7. Contract-first device workflow

For each device or device family, use this working sequence:

1. **Define a verifiable contract.** Specify commands, parameters, responses, state transitions, timing constraints, operating limits, invalid inputs, loss of communication, partial responses, and error behavior.
2. **Implement the communication library and conformance tests.** Keep protocol behavior separate from the higher-level component.
3. **Build the simulator.** Derive it from the contract, not from an implicit shared interpretation in the component code.
4. **Add fault injection.** Simulate delays, timeouts, dropped connections, incomplete or incoherent responses, stuck states, out-of-range values, and faults observed in real firmware.
5. **Verify safe subsets against real hardware.** Run applicable conformance tests on the device and record deviations. Potentially dangerous tests require explicit authorization and controlled conditions.
6. **Build the control component.** Use the verified communication layer and add component-level behavior, state, limits, telemetry, and diagnostics.
7. **Add integration tests.** Verify coordination and error propagation in the simulated system before hardware validation.
8. **Continuously reconcile simulator and hardware.** Simulator success never proves real-hardware correctness. Every discovered mismatch should improve the contract, simulator, tests, or implementation.

Keep the normal simulator behavior conceptually separate from fault injection. The simulator should be as simple as the device permits while making new fault scenarios easy to add.

## 8. Initial SRT prototype plan

The first implementation target is intentionally small and empirical.

### Phase 1: three independent components

Build one representative instance of each:

- receiver;
- backend;
- servomechanism.

Do **not** introduce orchestration initially. For each component, define and validate:

- contract and naming conventions;
- commands and operation lifecycle;
- state and event publication;
- telemetry such as positions, temperatures, and other relevant parameters;
- current and historical data access;
- configuration and operating limits;
- diagnostics and error taxonomy;
- simulator, fault scenarios, and automated tests.

The purpose is to learn what the common core actually needs before designing a higher layer.

### Phase 2: integrated simulated system

Run the three components together against simulators. Demonstrate reproducible startup, state discovery, telemetry, command correlation, injected failures, diagnosis, and recovery without physical hardware.

### Phase 3: hardware conformance

Apply safe conformance tests to the real devices, compare observed behavior with the contracts and simulators, and revise any incorrect assumptions.

### Phase 4: operational and technical experiences

Introduce:

- an SRT-specific observing layer for astronomers and operators;
- a separate technical diagnostic interface that can inspect the core and authorized low-level behavior.

The observing layer should be built for SRT first. Do not attempt to make it generically suitable for all facilities before evidence exists.

### Phase 5: orchestration

Only after the components and diagnostic model are stable, explore orchestration. The current SRT “boss of bosses → subsystem bosses → components” hierarchy is reference behavior, not a required future architecture. Prototype the simplest mechanism that can coordinate configuration, prerequisites, asynchronous work, timeouts, cancellation, completion, recovery, and safety priority.

### Phase 6: agentic lifecycle demonstration

Demonstrate at least one end-to-end case in which an agent:

- understands a requirement or issue from repository context;
- modifies a component, simulator, or operational layer;
- adds or updates tests;
- injects or reproduces a failure;
- produces a diagnosis and a reviewable correction;
- updates the relevant documentation.

This is a more meaningful proof of the Synqaro hypothesis than a large feature list.

SRT should become a documented reference implementation: not merely a deployment, but an example showing how to integrate devices, customize operations, test faults, and adapt the platform.

## 9. Validation with Medicina, Noto, and Einstein Telescope

### 9.1 Medicina and Noto

Medicina and Noto should be considered while SRT is developed, but the project should not attempt to build three full systems simultaneously.

They are valuable because the three INAF radio telescopes share a control-system lineage and common interfaces while using different configurations and, in some cases, different component implementations. Use those differences to test whether:

- the same core and contracts support multiple configurations;
- alternative implementations can preserve a shared interface;
- SRT-specific assumptions have leaked into the core;
- operational-layer customization remains understandable and contained.

This is a same-domain test. It does not by itself prove general applicability.

### 9.2 Einstein Telescope

ET is a possible second-domain validation context. Apply the same contract, simulation, testing, diagnostic, and agentic-development principles to a carefully selected subsystem.

Do not assume that the SRT-derived core already satisfies ET timing, reliability, or safety needs. Specialized real-time controls should remain separate. The ET prototype should test whether the core can support supervision and integration without absorbing real-time responsibilities it is not designed to meet.

Before designing an ET operational layer, study existing work such as LIGO Guardian and the relevant ET real-time-control research. Select a small subsystem with well-understood boundaries and measurable success criteria.

An ET or industrial prototype is strategically important because it can show whether operational policies can change without modifying the core.

## 10. Safety and authority

Safety is layered and must never depend solely on an AI model.

1. **Hardware and PLC protections** remain independent of Synqaro and continue to operate if the entire software system fails.
2. **Component protections** validate command parameters and enforce configured operating limits and monitored thresholds.
3. **System-level safety services** observe global conditions and may interrupt normal operations, reject commands, or trigger protective actions such as parking an antenna. Their authority must take precedence over ordinary orchestration.
4. **Domain safety policy** defines facility-specific decisions, such as weather thresholds or loss-of-communications procedures.
5. **Agent permissions** restrict which data and tools an agent may access. Safety checks remain in deterministic services even when an agent proposes an operation.

Use the principle: **agents may interpret and propose; deterministic services validate and execute**.

Risk determines approval. Read-only diagnosis and temporary analysis can be highly autonomous. Changes to permanent software, configuration, or control behavior require stronger evidence and authorization. Dangerous hardware tests require explicit approval. Generated tools run in isolation and do not gain command authority by default.

Remote or unattended operation requires conservative behavior when critical information is unavailable—for example, loss of reliable weather data. Exact policies remain domain decisions.

## 11. Important decisions and reversals

The following history prevents old assumptions from returning as if they were unresolved:

| Earlier direction | Current direction | Reason |
|---|---|---|
| Present the project mainly as an ACS replacement for SRT | Present Synqaro as a cross-domain AI-native engineering and control platform, with SRT as the first concrete validation case | The architectural contribution is broader than legacy replacement |
| Lead with distributed-control features as innovations | Treat them as baseline capabilities; emphasize the integrated agentic lifecycle and verifiability | Comparable frameworks already provide many traditional features |
| Generalize the system and observing layer from the outset | Generalize only proven common mechanisms; build the SRT observing layer first | Premature abstraction would recreate unwanted complexity |
| Treat the technical layer as a second orchestrator | Treat it primarily as a diagnostic and authorized low-level interface unless evidence demands more | User interface and orchestration are separate responsibilities |
| Assume the current Boss hierarchy should be retained | Use it only as reference behavior; prototype alternatives after component work | The hierarchy may be unnecessarily rigid |
| Consider an agent's persistent memory as project knowledge | Store authoritative knowledge in versioned documents, contracts, tests, code, and telemetry | Models and sessions are replaceable and context is finite |
| Build around Hermes Agent | Treat Hermes only as a candidate Smith implementation or interface reference | Smith and models must remain interchangeable |
| Make the AI layer part of the critical control path | Keep control deterministic and functional without Smith | Reliability, safety, and technology independence |
| Permanently integrate every agent-generated tool | Separate temporary analysis, verified reusable tools, and permanent extensions | Prevent uncontrolled complexity and unsafe privilege growth |
| Let funding opportunities determine the roadmap | Develop Synqaro independently; pursue a call only when genuinely aligned | Architecture and timing should serve the project, not a call |
| Claim that humans will no longer program or that Synqaro is unique | Design for extensive delegation while retaining verification; make only evidence-supported novelty claims | Strategic ambition must not become an unsupported assertion |
| Keep component/process mapping open for the prototype | Run each component as a separate operating-system process; keep containers optional | Creates an independently restartable, measurable failure boundary without defining components as containers |
| Choose component technology from access to scientific libraries | Use Python with `asyncio` for prototype simplicity, code-first APIs, testing, and asynchronous device I/O; retain Go as a measured production alternative | Low-level components should not absorb scientific processing, and language replacement must remain possible behind stable APIs |
| Define a separate gRPC/Protobuf IDL for every component | Use FastAPI/Pydantic HTTP APIs with generated OpenAPI and JSON Schema in the prototype | Avoids a second per-component contract representation until performance or multi-language evidence justifies it |
| Infer a component interface from arbitrary implementation details | Require explicit Python types and deliberately exported endpoints | Discovery and schemas must be inspectable, testable, and versionable |
| Use direct WebSocket fan-out or a custom FastAPI broker for internal state | Use Core NATS publish/subscribe internally and WebSocket at the external Core/State Service edge | Separates many-to-many internal distribution from UI/client delivery and avoids building a broker |
| Use PostgreSQL as the live-state or command path | Keep authoritative live state in component/Core memory, distribute it through NATS, and use PostgreSQL for selected history | Database availability must not block device communication, live state, or commands |
| Add Redis Pub/Sub or ZeroMQ to the initial stack | Do not add either without demonstrated need beyond the selected NATS baseline | Avoids overlapping infrastructure and additional topology, discovery, reconnect, and fan-out policy |
| Optimize state payloads before measuring them | Start with inspectable JSON and adopt binary encoding only if benchmarks justify it | Simplicity and diagnosis take priority until payload cost is demonstrated |

## 12. Constraints and non-goals

- Do not select technologies merely because they are fashionable. Interfaces and verification matter more than current tool popularity.
- Do not require Smith, a particular model, or an external network for deterministic control.
- Do not put domain concepts into the core without cross-domain evidence.
- Do not make every component a separate container by definition.
- Do not require the complete system to develop or test an individual component.
- Do not treat simulator success as proof of hardware correctness.
- Do not permit AI-generated numerical results to bypass deterministic computation.
- Do not replace independent hardware safety with software or AI controls.
- Do not promise a full production replacement of the legacy system within one year; that remains unvalidated.
- Do not confuse a conversational interface with the deeper AI-native engineering objective.
- Do not build a complex multi-agent architecture before one agent can complete a verified lifecycle.

## 13. Open questions

These decisions should be resolved through focused prototypes, measurements, and explicit approval:

### Core and communication

- What exact command, state, long-running operation, result, and error envelopes work for the three prototype components?
- What quality vocabulary, timestamp/unit policy, and schema-compatibility rules apply to the generated OpenAPI/JSON Schema APIs and NATS publications?
- What NATS subject conventions, authorization boundaries, and recovery rules are required for missed ephemeral state?
- When do state publications use complete snapshots/groups rather than deltas?
- Which orchestration mechanisms belong in optional common services, and which remain in domain layers?
- How should registry leases, cached resolution, high availability, process supervision, packaging, and deployment be implemented?
- What benchmark result would justify Go components, gRPC/Protobuf, or binary payload encoding instead of the prototype baseline?

### Data and diagnosis

- How should durability be divided between NATS JetStream and PostgreSQL for alarms, command results, audit records, and other non-lossy events?
- Which telemetry sampling, downsampling, retention, and query policies are appropriate for PostgreSQL history?
- What correlation and provenance model connects commands, events, alarms, tests, issues, and deployments?
- How will error taxonomies remain consistent across device families and sites?

### Security and safety

- What authentication, authorization, audit, and role model is required?
- Which operations may agents perform autonomously at each risk level?
- How are safety policies specified, tested, independently reviewed, and overridden?
- What isolation technology is required for agent-generated code and tools?

### Smith and agent interoperability

- What is the minimal stable interface between Synqaro and Smith?
- Is MCP suitable for some tools, or should another mechanism be used?
- How will compatibility and reliability be measured across Smith implementations and AI models?
- Which operational context should persist, where should it be stored, and how is it validated?

### Prototypes and migration

- Which concrete receiver, backend, and servomechanism should be selected first?
- What are the success criteria for each phase and for an end-to-end agentic demonstration?
- How will the new system coexist with ACS during incremental validation and migration?
- Which differences among SRT, Medicina, and Noto provide the strongest portability tests?
- Which ET subsystem offers a safe, bounded, and meaningful second-domain prototype?

### Project governance

- Will the project become open source, under which license, and with what contribution and review policy?
- What evidence is required before an expected benefit is presented as a demonstrated result?
- How will architectural decisions and reversals be recorded—such as through ADRs—so agents do not repeatedly reopen settled questions?

## 14. Collaboration rules for AI agents

The project owner expects the following working style:

1. **Be concise and answer the actual question.** Do not overwhelm the user with unrequested chapters, background, or tangents.
2. **Be candid, not agreeable.** Challenge assumptions with specific technical reasoning. Do not endorse an idea merely because the user proposed it.
3. **Proceed incrementally.** Discuss and approve material architectural choices before implementation. Do not implement unless explicitly authorized.
4. **Ask when ambiguity is material.** If uncertainty could change architecture, scope, safety, or the meaning of a document, ask one focused question rather than inventing an answer.
5. **Separate facts, decisions, hypotheses, and proposals.** Never convert a plausible idea into a settled requirement without acknowledgment.
6. **Preserve rationale and reversals.** When a decision changes, record both the new direction and why the previous one was rejected.
7. **Prefer small empirical prototypes to abstract debate.** For APIs, orchestration, and technology choices, build the smallest representative example, measure it, and then decide.
8. **Do not generalize prematurely.** SRT is the first concrete problem. Promote only demonstrated commonality into the reusable core.
9. **Verify rather than assume.** Use contracts, simulators, tests, telemetry, and real-hardware checks appropriate to the risk.
10. **Protect the architecture from current AI fashions.** Models, frameworks, and agent runtimes are replaceable. Stable contracts and evidence are the long-lived assets.
11. **Keep humans responsible for goals and risk.** Extensive agent autonomy is desired, but safety-critical authority must follow explicit policy and independent verification.
12. **Keep the document set coherent.** Before changing the system, read the Project Vision, this handoff, relevant ADRs, contracts, and agent instructions. Update the affected documentation with the code.

## 15. Recommended next step

Use the [Synqaro Component Architecture](component.md) to build the first measurable architecture slice: separate receiver, backend, and mount component processes; their protocol-compatible simulators; NATS; one small Core process; and PostgreSQL only when history is introduced.

The slice should prove the documented acceptance criteria, especially independent restart, logical-name resolution, direct validated commands, representative 20 Hz mount state fan-out, stale/restart/out-of-order detection, live operation during database failure, distinct device/process failures, and reproducible fault injection. Only after that evidence exists should Synqaro expand orchestration or split the initial Core roles.

## 16. Architecture document index

- [Synqaro Project Vision v0.9](project_vision.md) — authoritative project intent, scope, principles, and validation strategy.
- [Synqaro Component Architecture](component.md) — prototype component boundary, process model, communication, state, persistence, configuration, validation, and open questions.
- [AI Project Context and Handoff](ai_project_context.md) — rationale, decision history, collaboration rules, and open project-wide questions.
