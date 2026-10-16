# Synqaro

**An AI-native platform for engineering and controlling complex distributed systems**

**Project vision and preliminary engineering principles**  
**Version:** 0.9  
**Date:** October 16, 2026  
**Status:** Concept and research proposal. The architecture, technology stack, partnerships, and deployment plans are not yet approved.

---

## 1. What Synqaro is

**Synqaro is a proposed AI-native engineering and control platform designed for a world in which autonomous AI agents become primary participants in developing, operating, diagnosing, and evolving complex distributed systems.** Rather than adding an AI assistant to a conventional control framework, Synqaro aims to make **the entire system lifecycle accessible to agents by design**: from device and firmware specifications through software implementation, simulation, integration, operations, incident analysis, corrective changes, and subsequent verification.

Its defining proposition is **a continuous, verifiable connection between what a system is supposed to do, what has been implemented, what can be simulated and tested, and what actually happens in operation**. Agents should be able to navigate that connection and act on it, subject to explicit permissions and independent safety and acceptance mechanisms. A fault reported by an operator should be traceable to evidence, reproducible where possible, and actionable as a tested change rather than disappearing into disconnected logs, repositories, teams, and undocumented assumptions.

Synqaro is intended for scientific facilities, industrial plants, and other installations composed of heterogeneous devices and software. A **small, domain-independent control core** would expose shared mechanisms; each installation would supply its own **operational layer**. The agentic engineering environment, contracts, simulation methods, diagnostic mechanisms, and development practices would remain common across applications. **Synqaro must be AI-native without depending on any particular agent framework, model, or inference provider:** the entire agentic environment must be replaceable without redesigning the control platform.

The innovations Synqaro aims to demonstrate are therefore not basic device communication or telemetry, which established systems already provide, but the following combination:

1. **Agents as first-class engineers and operators.** Agents receive structured, permissioned access to components, contracts, repositories, test environments, system state, historical evidence, and operational tools. They can propose and, where authorized, execute work across the lifecycle instead of merely generating isolated code snippets or answering questions.
2. **A closed engineering-to-operations loop.** Requirements, device protocols, implementations, simulators, tests, deployments, telemetry, incidents, and fixes remain linked and traceable. Findings from operations can feed directly into reproducible tests and improvements.
3. **Agent-ready verification rather than trust in generated code.** Explicit contracts, simulator-first development, fault injection, conformance checks against real devices, regression tests, and controlled delivery make autonomous engineering testable and progressively extensible.
4. **One generic foundation, many application-specific operating models.** A common control core and agentic lifecycle can support distinct operational layers, avoiding the assumption that a radio telescope, a gravitational-wave observatory, and an industrial plant must share the same operational procedures.
5. **Replaceable agents and models, by architectural contract.** The agentic layer (provisionally called **Smith**) is separate from the control core and operational layers. Its interfaces to control services, models, and operator-facing applications must be defined, versioned, and testable, supporting local or remote models and future replacement of Smith itself.
6. **Progressively increasing autonomy without surrendering deterministic control.** More engineering and appropriate operational work can be delegated to agents as their performance and verification improve, while essential control, hard limits, interlocks, and safe fallback behavior remain independent of probabilistic AI services.

**The ambition is not simply to write a new control framework faster using AI. It is to build a control and engineering platform that AI agents can understand, extend, test, repair, and help operate throughout its lifetime.** This is a research and engineering objective, not an already demonstrated advantage or a claim that no related projects exist.

## 2. Why a new approach is timely

Conventional control frameworks were largely designed for engineering organizations in which people write and maintain application code, manually interpret distributed failures, and integrate devices through specialized knowledge of the runtime and its tooling. Some of these frameworks are mature, reliable, and well supported; their fundamental capabilities are not obsolete. **What may be becoming outdated is the assumption that humans must be the principal integrators of every software change and every diagnostic investigation.**

Software engineering is changing rapidly. AI assistants have evolved from code completion to agents that can inspect repositories, edit multiple files, run tests, and prepare pull requests. The peer-reviewed **SWE-agent** work (NeurIPS 2024) established the importance of interfaces designed specifically for software-engineering agents. The **2025 DORA report**, based on responses from nearly 5,000 technology professionals, found widespread AI adoption and emphasized that high-quality platforms, loosely coupled systems, and rapid feedback loops matter more than simply supplying AI tools. A **2026 empirical study of GitHub projects** documented rapidly growing adoption of coding agents, extending beyond simple autocomplete. [1–3]

These findings do **not** establish that agents already outperform expert engineers on every task, or that human coding will disappear on a particular schedule. Productivity effects depend on the task and environment, and evidence remains mixed; a 2026 METR update explicitly warned against overinterpreting its productivity estimates. [4] Nevertheless, it is reasonable to design a long-lived platform for a future in which agents undertake **most routine implementation and a growing share of complex engineering work**, with humans increasingly focused on objectives, requirements, review, acceptance, and accountability.

This transition exposes weaknesses that are especially costly in long-lived control systems: opaque dependencies, device behavior known only to a few specialists, poor isolation of failures, incomplete simulations, tests that require a large runtime or physical equipment, and fragmented evidence between firmware and application software. Such weaknesses also limit agent effectiveness: a capable agent cannot reliably diagnose what the system does not describe or safely validate what the system cannot test.

Synqaro's response is to **design for agentic engineering and verifiable operation from the beginning**. Simplicity, observable behavior, explicit interfaces, simulations, and failure provenance are not secondary conveniences. They are the prerequisites for reliable delegation to agents and for more maintainable systems regardless of whether AI is currently available.

*Research context:* [1] [SWE-agent, NeurIPS 2024](https://proceedings.neurips.cc/paper_files/paper/2024/hash/5a7c947568c1b1328ccc5230172e1e7c-Abstract-Conference.html); [2] [DORA State of AI-assisted Software Development, 2025](https://dora.dev/research/2025/dora-report/); [3] [Robbes et al., "Agentic Much? Adoption of Coding Agents on GitHub," ACM TOSEM, 2026](https://doi.org/10.1145/3822180); [4] [METR, developer-productivity research update, February 2026](https://metr.org/blog/2026-02-24-uplift-update/).

## 3. The platform boundary: core, operational layers, and devices

The central architectural hypothesis is to separate **generic control mechanisms** from **application-specific operational behavior**.

**The core** should expose an intelligible and uniform model of components and their declared capabilities, commands, parameters, states, measurements, events, errors, and permissions. It should support communication, command tracking, monitoring of current state, access to historical telemetry, structured diagnostics, configuration, and authorization through simple, documented interfaces. These are expected foundations of a modern control system, **not Synqaro's claimed innovations by themselves**. We should improve their simplicity, observability, fault isolation, and independent testability where possible rather than merely reimplementing features found in existing frameworks.

The core must not know what an astronomical observation, interferometer lock acquisition, or industrial production cycle means. Nor should the core become a single mandatory monolith: the design should favor a minimal runtime with optional common services and libraries where that reduces dependencies. A logical component is not necessarily a separate process, service, deployment container, or physical device. Components should be straightforward to start, inspect, simulate, and test independently.

**Operational layers** implement domain-specific coordination above these common capabilities. A radioastronomy layer might manage receiver/backend setup, antenna tracking, and observation schedules. Another layer could coordinate an industrial process or supervise suitable subsystems of a gravitational-wave facility. Each can be implemented or extended with agent assistance because its underlying components, capabilities, contracts, and tests are discoverable. Different sites may reuse one operational layer with different configurations and different implementations of the same device interface.

The boundary should not force each operational layer to reinvent generic mechanisms. Shared optional tools for asynchronous commands, sequencing, cancellation, timeouts, state machines, and recovery may prove valuable; **their mechanism belongs in reusable services, while domain-specific sequencing rules remain in the operational layer**. The right boundary is an empirical design decision for the prototypes, not a fixed inheritance hierarchy.

**Device-facing components and adapters** connect declared interfaces to actual firmware, controllers, PLCs, sensors, actuators, or external systems. A stable contract may be implemented by several different devices. Where source code is available, the agentic environment may also examine firmware and related tests; otherwise it must work from approved protocols and observed conformance.

Finally, agents should be **first-class clients** of the same documented, permissioned capabilities used by conventional applications. Machine-readable metadata and discoverable tools are essential. An agent-facing adapter such as MCP may be useful, but should not dictate the core's internal transport or require AI to be online for the installation to function.

### AI layer boundary and replaceability (Smith)

**Smith is a provisional name for an architectural role, not a selected product or required implementation.** It is an agentic environment that can use authorized control and engineering capabilities to assist operators and engineers. Its replacement must not require rewriting Synqaro's device components, core, operational layers, or operator applications.

Three distinct interfaces must remain explicit and versioned:

- **Smith ↔ Synqaro:** a domain-independent, authenticated and permissioned interface to discover capabilities, issue validated commands, retrieve live and historical state, investigate incidents, and access approved engineering assets. Its semantics, error schemas, audit trail, and safety boundaries belong to Synqaro, not to an agent vendor.
- **Smith ↔ AI models and tools:** adapters for interchangeable local and remote inference endpoints and tool runtimes, with capability discovery and compatibility tests. A different model may require different prompts, tool formats, context handling, or evaluation thresholds; interchangeability is an engineering objective, not a claim of behaviorally identical models.
- **Smith ↔ operators:** a stable application-facing interface for requests, responses, progress, explanations, evidence, approvals, and handoffs, independent of any particular chat application, voice frontend, or agent implementation.

Keep long-lived engineering knowledge in versioned contracts, documentation, source control, test results, telemetry, and incident records, rather than relying on one agent's conversational memory. Agents may maintain useful persistent context, but must be able to retrieve authoritative current state on demand. **Safety-critical operation must continue if Smith, its model, or its connectivity is unavailable.**

**Hermes Agent (Nous Research) is one candidate implementation to investigate, not a dependency or an adopted technology.** Its documented support for MCP tool servers, multiple inference providers (including compatible local endpoints), and agent interoperability is relevant. An evaluation should examine whether its boundaries and protocols are open, widely interoperable, stable under version changes, and suitable for authorization, observability, operational latency, and deployment isolation. Standard interfaces such as MCP may inform Synqaro's integration adapters where appropriate; Synqaro should not adopt a Hermes-specific interface merely because Hermes currently provides it. [5–6]

## 4. The engineering method: contracts, simulators, and verified components

**The development process is a fundamental part of Synqaro, not just a recommended coding style.** Components should enter the system through a reproducible, contract-driven process that agents can help execute and verify.

A **versioned device contract**, negotiated with the responsible firmware or hardware team, describes commands, formats, responses, parameter units, device states and transitions, timing and timeout behavior, error codes, operating constraints, and recovery behavior as appropriate. Contracts must be understandable by engineers and machines and be linked to implementations, tests, and documentation. An agent should be able to determine what a device promises, which versions are compatible, and what a proposed firmware change affects.

A preferred integration cycle is:

1. **Define the contract.** Hardware, firmware, and control engineers agree on intended behavior and constraints; an agent can draft, compare, or check the specification.
2. **Build testable boundaries.** Develop a reusable protocol/communication library where appropriate, conformance tests, and a simulator implementing the contract. A physical device is not required for initial component development.
3. **Model failures deliberately.** Use reproducible fault injection for lost or late responses, malformed messages, disconnections, invalid values, stuck states, partial failures, and relevant firmware anomalies—not only ideal behavior.
4. **Verify the real interface.** Run applicable tests against real firmware and hardware under safe conditions. Resolve inconsistencies in the contract, simulator, tests, or firmware instead of automatically assuming that one side is correct.
5. **Develop and integrate components.** Agents can implement device components and tests against the verified interface, then exercise them independently and within a simulated installation and its operational layer.
6. **Preserve evidence.** Retain conformance tests, regression scenarios, firmware compatibility results, and links to requirements so future changes are checked against known behavior.

Digital twins or richer physical simulations are valuable where their fidelity justifies the effort. **Synqaro should not require a high-fidelity digital twin for every device.** A protocol-level simulator may be sufficient for a communications component; physical, timing, or system-level models may be necessary for other tests. A progressively complete simulated installation would let agents reproduce incidents, exercise operational workflows, and test fixes without repeatedly disturbing the real plant. Simulation does not remove the need for safe hardware-in-the-loop and acceptance tests on actual equipment.

Failures must retain their identity across the system. Commands and operations should carry correlation identifiers; errors should preserve their originating component and layer, relevant timestamps, device responses, and supporting telemetry. Instead of merely reporting that a high-level operation failed, the system should make it possible to distinguish a malformed firmware response, a timeout in communication, a component-level defect, an invalid configuration, and a mistake in the operational layer. **Diagnosability is an architectural requirement because autonomous repair is impossible without usable evidence.**

## 5. An agentic lifecycle that connects engineering and operation

Synqaro should give authorized agents a **coherent view of the installation and its engineering assets**: interface contracts, device descriptions, software repositories, accessible firmware repositories, build results, simulations, test reports, configuration, telemetry, logs, incidents, documentation, and deployed versions. These assets need not be in a monorepo or controlled by one organization. Access controls, traceable versions, machine-readable links, and trustworthy provenance matter more than repository layout.

**During development**, agents could translate approved requirements into interface proposals, implement device drivers and operational-layer features, generate simulators and regression tests, review firmware compatibility across repositories, run CI jobs, explain failures, update documentation, and prepare reviewable changes. The goal is to delegate increasing amounts of actual implementation, not merely to ask an LLM for coding advice. Proprietary or unavailable firmware is not an obstacle to the general method if its externally visible contract can be tested.

**During operations**, agents could guide inexperienced users, assemble an observing or production setup, check prerequisites, answer questions about present and historical states, identify an unavailable device, and explain operational alternatives. Text or voice may be used, but voice is only an interaction modality. Conventional displays and command tools must remain usable. The system should expose semantic descriptions, units, timestamps, sample validity, and telemetry retention rules so an agent can request meaningful data and present a trustworthy chart rather than guessing what a measurement means.

**During incident response**, the intended loop is concrete:

> Report or detect an anomaly -> identify the affected operation and components -> retrieve correlated telemetry and errors -> propose hypotheses -> reproduce relevant conditions in a simulator or test environment -> investigate source, firmware, configuration, and operational logic -> create a correction and regression test -> verify it -> prepare a controlled deployment -> confirm the outcome in operation.

An agent may ask clarifying questions, create an issue, propose a patch, or coordinate across teams. Every step should record the evidence, changes, validation, and permissions involved. Failed hypotheses and unresolved uncertainties must remain visible; an attractive explanation is not a demonstrated root cause.

**During analysis**, if no suitable tool exists, an agent may generate a new diagnostic script or visualization in a restricted execution environment, test it against representative data, and return its result. A reusable tool can subsequently be reviewed, versioned, documented, and published with clear interfaces and permissions. Generated analytical code must be checked for correct units, clocks, missing samples, calibration, filtering, and statistical assumptions, not just successful execution.

Autonomy should be **progressive and risk-based**. Low-risk analytical and development tasks may be completed automatically when tests and permissions allow. Changes to operating firmware, protective logic, motion limits, and production deployment require stronger independent validation and appropriate authorization. The architecture should accommodate more capable future agents without rewriting the control system, but must not assume that future models are infallible.

## 6. Reliability, safety, and the role of deterministic systems

Synqaro's reliability objective has two sides: **reduce the introduction of defects** through contracts, simulation, and regression testing, and **reduce the time needed to understand and recover from failures** through traceability and structured diagnostics. Neither improvement should be asserted as achieved before measurement.

AI agents must not be the sole authority for physical safety. Hard limits, emergency stops, and independent hardware or PLC interlocks must remain effective even if Synqaro or an AI service fails. Components should enforce appropriate local constraints. Validated facility-specific supervisory logic should handle hazards involving multiple components—for instance dangerous weather, critical telemetry loss, or an unsafe plant condition—and take precedence over ordinary work requests.

Deterministic numerical routines and dedicated real-time controllers should remain responsible for feedback loops, physical limits, timing-critical behavior, and quantitative checks when required. Synqaro should integrate with such systems rather than assuming one generic distributed runtime can replace them. Agent requests must pass through authorization, validation, and audit mechanisms; agents must not bypass the ordinary command and safety boundaries.

The normal system, including essential user interfaces, should remain operational when AI is disconnected or unavailable. AI is an increasingly autonomous engineering and interaction layer, **not a runtime dependency for safe physical control**.

## 7. Initial development and validation strategy

The first prototype will be developed for the **Sardinia Radio Telescope (SRT)**, but it is intended to test the generic Synqaro architecture rather than define that architecture around radioastronomy. The scope is intentionally small: **one receiver, one backend, and one antenna servomechanism**, represented by **three independently usable device components**. The first milestone does **not** require an observational orchestration layer. Each component must be understandable, executable, observable, simulated, and testable on its own.

**Stage 1 — Establish the component foundation without orchestration.** Define explicit device contracts, coherent naming conventions, commands, state models, parameters, capabilities, units, timestamps, errors, and telemetry. Expose live state and relevant historical information, such as antenna position and receiver temperatures, through consistent core interfaces. Develop device simulators (and progressively more faithful digital twins where useful), including fault injection, protocol and timing errors, and repeatable tests. The three components should exercise realistic differences in behavior without requiring a telescope-wide runtime. Agents working through a provisional Smith-compatible interface should be able to inspect specifications, implement or revise components and tests, and investigate simulated faults. Real hardware integration and its safety restrictions remain separate acceptance steps.

**Stage 2 — Discover, rather than assume, the orchestration boundary.** Once the individual components and their interfaces are stable enough to exercise, implement a limited **SRT observational layer** that coordinates receiver, backend, and servomechanism for representative tasks. This domain-specific orchestration should be built on generic core capabilities; any reusable sequencing, tracking, cancellation, prerequisite, or recovery mechanisms should be evaluated individually rather than automatically absorbed into a growing core. The initial observational layer is an example implementation, not a prescribed operating model for other facilities.

**Stage 3 — Provide distinct observational and technical experiences.** Astronomers and operators need an observation-oriented interface that expresses their tasks and presents meaningful status. Engineers and technicians need a technical diagnostic interface exposing component-level behavior, telemetry, events, error provenance, and relevant history. **These are separate user experiences, not necessarily separate orchestration engines**: technical diagnostics should be able to query the core directly when appropriate. Agentic interaction may serve both audiences through explicitly scoped permissions and tools; normal operation and safety must not depend on the availability of an AI agent.

**Stage 4 — Test reuse as development proceeds.** While developing the SRT prototype, continuously examine how the same core, contracts, development workflow, and agentic interfaces could serve the **Medicina and Noto** radio telescopes. In particular, compare their different configurations and the cases where components share an interface but require different implementations. Determine which SRT observational workflows, interface patterns, and orchestration mechanisms can be reused unchanged, adapted, or replaced. Record cases where making a mechanism generic introduces avoidable complexity; prefer site-specific operational extensions over weakening a simple domain-independent core. This is a design-validation activity alongside SRT development, **not a commitment to implement all three observatories at once**.

The SRT implementation should also become a **worked example for future Synqaro adopters**: how to specify devices, develop components and simulators, validate behavior, add orchestration, and create operator and diagnostic interfaces. Others may reuse its structure or replace its operational layer without changing the core. The project must make that distinction explicit in both documentation and software boundaries.

**Stage 5 — Validate the agentic lifecycle and broader transferability.** Exercise end-to-end cycles in which an agent uses accessible contracts, code, simulations, tests, telemetry, and incident records to diagnose a failure, propose a change, and validate it under appropriate controls. Test Smith replacement or an alternative model early enough to expose accidental dependencies. Subsequently, select a bounded non-radioastronomy case—potentially a suitable Einstein Telescope supervisory prototype or an industrial simulation—to assess whether the core's reuse is real and whether any optional extension remains justified.

Evidence should include component startup and test effort, fault-injection coverage, time to reproduce and localize faults, interoperability across different component implementations, quality of regression detection, effort to build or customize operational layers, and **the fraction and complexity of lifecycle tasks completed correctly by agents under specified supervision**. These benefits remain hypotheses until measured. Design decisions and technology choices should follow prototype evidence, not precede it unnecessarily.

## 8. Open development, collaboration, and funding

An open-source distribution is a proposed direction, not a licensing decision already made. Synqaro should enable independent contributions and reusable components while respecting institutional policies, proprietary firmware, cybersecurity needs, and deployment responsibilities. Governance, licensing, version compatibility, security disclosure, release practices, and contribution rules remain to be designed.

A realistic funding proposition is broader than replacement of a single control framework. It combines a reusable control foundation, a contract-and-simulation-based development method, a verifiable agentic engineering lifecycle, and experimental evidence from demanding installations. Potential funding avenues to evaluate include INAF and other research institutions; relevant Horizon Europe Research Infrastructures calls, including suitable INFRATECH or INFRADEV topics; regional and national research-and-innovation programmes, including Sardinian ERDF/FESR initiatives; open-source funding; and scientific or industrial partnerships. **These are possibilities, not verified currently open calls or confirmed eligible projects.**

Useful deliverables would be a repeatable core demonstrator, reusable interface-contract tools, a simulator and fault-injection suite, cross-device conformance tests, a complete traceable issue-to-fix agent workflow, a small operational layer, and evidence of reuse in another domain. Funding requirements should not lead to unnecessary architectural complexity.

## 9. Concrete proving grounds and transferability

**Sardinia Radio Telescope (SRT), Medicina, and Noto.** These are three radioastronomy facilities of the Italian National Institute for Astrophysics (**INAF**, *Istituto Nazionale di Astrofisica*). **SRT is the initial implementation and experimental site**, beginning with one receiver, one backend, and one servomechanism as independent components. Medicina and Noto provide contemporaneous architectural comparison cases: the present control system shares interfaces and architectural concepts while accommodating different configurations and, for some components, **different implementations behind the same interface**. Studying those differences during the SRT work will test whether Synqaro truly separates the reusable core from site-specific orchestration and user experiences, without undertaking three simultaneous implementations. A sufficiently successful prototype could support a carefully managed operational migration, subject to institutional decisions and safety acceptance.

**Einstein Telescope (ET).** This proposed next-generation gravitational-wave observatory offers a possible second, scientifically demanding context in which to test the **same design and development principles**, the reusable core where suitable, and the same agentic methods of integration, diagnosis, and extension. A prototype could focus on an appropriate supervisory subsystem, environmental instrumentation, infrastructure monitoring, or another clearly bounded application. ET-specific capabilities could be added through optional extensions and its own operational layer, while dedicated high-frequency control and protective systems retain their established responsibilities. Requirements, interfaces, timing, and safety must be assessed with the relevant experts; no collaboration with ET or adoption by the project is implied.

**Industry and other research facilities.** Manufacturing, experimental laboratories, distributed plants, and test facilities may benefit from the same reusable foundation and agentic workflow, with independently developed operational layers. This is a **transferability hypothesis**, not a claim that one unmodified core will automatically satisfy all regulatory, real-time, or operational requirements. A second-domain prototype should test exactly where extensions are necessary and whether those extensions preserve simplicity.

---

## 10. Technical case note — Modernizing the INAF radio-telescope control systems

*This application-specific section addresses the engineers and managers responsible for SRT, Medicina, and Noto. It is a possible adoption case for Synqaro, not the definition or primary rationale of the platform.*

### The engineering and operational problem

The three telescopes currently use **DISCoS**, a radio-telescope control system built on **ALMA Common Software (ACS)**. ACS provides legitimate distributed-component services, but its runtime and programming model introduce considerable framework-specific infrastructure around device-facing behavior that can itself be quite simple. This complexity affects the cost of understanding components, testing them, integrating changes, and investigating anomalies.

For example, to exercise one ACS component, a developer must first have the required ACS environment available, start the framework services and an ACS **container** (an ACS hosting process), launch the component, and only then run component tests. Depending on the existing setup, this may involve a virtual machine. **The entire telescope control system does not need to be started.** The distinction matters: the criticism concerns avoidable framework and environment overhead, not a false claim that all telescope services must be running. An ACS container is not a Docker-style deployment container.

More seriously, **the motivation is operational unreliability and inadequate fault diagnosability**, not just age or developer inconvenience. When a commanded operation misbehaves, it may be difficult to establish whether the cause lies in the device firmware, the communications protocol, ACS infrastructure, device-component code, or higher-level orchestration. Failure evidence can be fragmented or lose specificity while moving between layers; realistic negative-path tests and reproducible device simulation may be insufficient. This can leave the origin of a fault unresolved and make the same behavior difficult to prevent from recurring.

These concerns are based on firsthand engineering experience with the installations, not on downtime statistics or a quantitative comparison supplied in this document. An adoption proposal should gather representative incidents, reproducibility data, and evidence of engineering effort. **The fact that a system is deployed does not, by itself, establish acceptable reliability**, but neither should its replacement be justified by unsupported defect-rate claims.

### What changes with Synqaro

The proposed replacement is **not a mechanical rewrite of DISCoS on a different middleware**. It is a different way to specify, develop, verify, operate, and continuously improve the control software:

- **Independent components and simpler infrastructure.** Device-facing services can be started, simulated, tested, and diagnosed without the ACS-specific runtime sequence; their implementation focuses on device behavior rather than framework ceremony.
- **Contracts shared with firmware teams.** Interface versions, commands, states, timing, limits, and error conditions become explicit engineering assets, with conformance and regression tests that can be retained when firmware or devices change.
- **Simulator-first reliability engineering.** Expected behavior and failure modes are exercised before deployment. Delays, missing replies, invalid packets, interrupted connections, and other faults become reproducible tests rather than surprises first seen at the telescope.
- **Traceable faults, rather than generic failures.** Correlated operations, structured errors, and historical telemetry help identify whether the problem is in hardware, firmware, communications, component software, configuration, or operational logic.
- **Agent-driven engineering and maintenance.** An agent can work across accessible contracts, code, simulators, logs, and tests to develop new components, investigate incidents, propose a correction, add regression coverage, and prepare reviewable changes. This capability is the principal strategic difference from a conventional framework migration.
- **Site-specific flexibility with common foundations.** The three facilities can share a core and radioastronomy operational concepts while retaining different hardware interfaces, component implementations, configurations, and site-dependent procedures.
- **Operator assistance grounded in real state.** An agent may help configure observations, check prerequisites, explain warnings, retrieve historical measurements, and initiate a documented diagnostic workflow without bypassing validated operational or safety procedures.

The expected institutional benefits are fewer opaque failures, shorter diagnosis and integration cycles, lower dependence on scarce framework-specific knowledge, easier training, safer upgrades, and greater long-term maintainability. **These outcomes must be measured; they are not guarantees.** The additional value is that such an investment would contribute to a reusable platform for other scientific and industrial infrastructures rather than only producing a replacement for three telescopes.

### A migration credible to the observatories

Operational reliability must take precedence over speed of replacement. Start at SRT with appropriately isolated implementations of one receiver, one backend, and one servomechanism, initially without orchestration. Recover the actual required behavior from existing software and operational experience; establish contracts, consistent telemetry, simulators, and tests for each component independently; compare with real devices when safe; and only then introduce a limited observational orchestration layer and separate operator and diagnostic interfaces. Use staged deployment, regression suites, hardware-in-the-loop where feasible, monitored trials, and explicit acceptance criteria. Existing protective interlocks and observatory safety procedures remain authoritative.

A crucial criterion is whether Synqaro can **diagnose and prevent classes of failures that the present development model leaves opaque**. A pilot that demonstrates only modern code structure or a conversational interface would not be sufficient justification for migration. Conversely, measurable improvement in fault isolation, regression detection, and incident resolution would make a substantially stronger case to operational stakeholders.

The project should therefore be assessed as a **controlled engineering experiment with potential operational payoff**, not as a commitment to retire the existing software before a better alternative has been demonstrated.


*Agent interoperability references:* [5] [Hermes Agent: MCP integration](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp/); [6] [Hermes Agent: integrations and model providers](https://hermes-agent.nousresearch.com/docs/integrations). These sources document candidate capabilities, not production suitability or interoperability guarantees.
