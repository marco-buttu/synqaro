# AI-Native Control and Engineering Platform for Scientific Infrastructures

**Project vision, expected benefits, preliminary requirements, and research roadmap**  
**Version:** 0.5  
**Date:** October 15, 2026  
**Status:** Concept and requirements discussion draft; architecture and technologies are not yet selected  
**First reference facilities:** Sardinia Radio Telescope (SRT), Medicina Radio Telescope, and Noto Radio Telescope  
**Working scope:** Distributed scientific-infrastructure supervisory control and its full engineering lifecycle

> **Central proposition**  
> Design an open, lightweight, dependable platform through which scientific facilities can be designed, integrated, operated, diagnosed, tested, extended, and maintained with extensive assistance from autonomous AI agents. Use existing INAF radio telescopes as the first real-world proving ground, then evaluate whether the same core can serve future observatories and other scientific infrastructures without adding unnecessary complexity.

---

## 1. Executive vision

This project proposes a different approach to the **entire lifecycle of scientific-infrastructure control systems**, rather than a straightforward replacement for a legacy framework.

Large scientific installations may operate for decades. Their control software must accommodate new hardware, new observing modes, changing staff, evolving research needs, and technologies that become obsolete much faster than the instruments themselves. The ongoing cost is not limited to writing code: it includes onboarding engineers, integrating firmware, isolating faults, preparing environments, running tests, diagnosing field incidents, maintaining documentation, and evolving systems safely.

The project aims to reduce that burden through a combination of:

1. **An intentionally minimal distributed-control core**, independent of large legacy runtimes and of any AI model.
2. **Explicit device contracts**, reusable communication interfaces, independently runnable components, and simulator-based verification.
3. **Systematic fault injection and end-to-end diagnostics**, designed to reveal the origin of errors across device, firmware, software, and orchestration boundaries.
4. **AI-first engineering workflows**, spanning requirements, firmware integration, implementation, regression tests, code review support, issue triage, and long-term maintenance.
5. **AI-native operations**, allowing scientists and technicians to interact in natural language, obtain evidence-based guidance, inspect live and historical data, and create new analytical tools when justified.
6. **Controlled extensibility and progressive autonomy**, enabling agent capabilities to grow without making safety-critical operation dependent on their availability or reliability.

The first practical goal is to develop a dependable control solution for **SRT**, while taking advantage of the fact that the same current control software also serves **Medicina and Noto** through installation-specific configurations. These three facilities provide unusually valuable real-world cases for exercising a shared platform across different hardware configurations.

The broader strategic objective is a potentially reusable, open-source platform for **future scientific installations**. Candidate scenarios include new radio telescopes and selected supervisory subsystems of gravitational-wave observatories such as **Einstein Telescope (ET)**. Applicability to ET is a research hypothesis, not an existing partnership, an approved requirement, or a commitment to build interferometer real-time control.

A key strategic objective is to pursue **institutional, European, regional, and open-source research funding**. Grant-readiness will inform how demonstrators and deliverables are organized, but must not distort the engineering architecture.

## 2. Origin: a concrete problem at three radio telescopes

### 2.1 Current control system

The control software used at SRT was developed around **ALMA Common Software (ACS)**. The same software base is used at the Medicina and Noto radio telescopes, with the selected telescope configuration determining which devices, parameters, and operational facilities are available.

Over roughly twenty years of development, engineering experience suggests that a substantial share of the difficulty in creating and maintaining this system comes from the framework and its integration conventions rather than from the intrinsic complexity of many device-control components.

The project does not need a feature-by-feature comparison with earlier telescope frameworks. Its purpose is to replace unnecessary overhead with a simpler, independently verifiable approach.

### 2.2 The real testing burden

Testing a single ACS component **does not require starting the entire telescope control system**. However, the developer typically must prepare or start the relevant virtual machine/environment, start ACS, launch an **ACS container** (the hosting process in ACS terminology, not necessarily a Docker container), start the component, and then conduct the actual test.

This setup overhead recurs for small changes and fault investigations. A failure might originate in the firmware, communication layer, component code, ACS infrastructure, or interactions among them. Inadequate test automation and incomplete diagnostic context make the distinction difficult.

The intended replacement should allow an engineer or AI agent to run the smallest relevant test locally without starting unrelated framework infrastructure or accessing the physical telescope, unless the test specifically requires it.

### 2.3 Long-term organizational costs

The costs of a complex legacy system include:

- Months of specialized onboarding and knowledge transfer.
- Dependence on a small group of engineers who understand the framework.
- Substantial overhead for minor code changes and regression investigations.
- Manually repeated setup, integration, and verification procedures.
- Difficult diagnosis when errors propagate through multiple layers.
- Barriers to modern continuous integration, deployment, and agent-led development.
- A growing burden of unsupported or aging technologies over decades.
- Delays in implementing observing capabilities and integrating new hardware.

These observed burdens motivate the project without requiring a cost study before initial development. Later measurements will still be useful to demonstrate actual gains, reveal unexpected costs, and support scientific reporting or funding decisions.

## 3. Strategic positioning and priorities

### 3.1 A platform for the lifecycle, not merely a framework replacement

**The proposed product is an AI-native engineering and operational platform for distributed scientific facilities.** Its control core is only one part of the proposition. The platform also includes testable device integration, simulation, diagnostics, data access, development workflows, and optional intelligent interfaces.

The term *AI-native* refers to the way the platform is designed to be understood and used by agents: explicit contracts, discoverable capabilities, structured telemetry, reproducible test environments, traceable changes, and controlled tool access. It does **not** mean that an AI model executes low-level control loops or makes independent safety decisions.

### 3.2 Immediate engineering priority: useful results at SRT

The general vision must not become an excuse for speculative abstraction. The initial requirements and prototypes must come from real SRT devices and operating procedures. Medicina and Noto provide additional validation opportunities because they use the same present-day control software with different configurations.

The intended outcomes include:

- An independently testable control stack without an ACS dependency.
- A realistic offline environment with device simulators and fault scenarios.
- A path to configure, operate, and diagnose representative telescope subsystems.
- A migration strategy that does not compromise operations.
- Eventually, a practically usable replacement for the current system.

The prospective timeline of approximately one year for a substantially working implementation is an **aspiration to test**, not a validated delivery estimate. A fully operational replacement and certification against physical operating constraints may require additional time.

### 3.3 Conditional wider applicability

Only after representative prototypes, or later when justified, should the team test whether generic control primitives can support another class of scientific facility. The platform should become reusable through **demonstrated common requirements**, not through a universal abstraction designed in advance.

In particular, ET-related experimentation would focus on suitable **supervisory functions** such as auxiliary equipment, environmental monitoring, or cryogenic-system coordination. High-rate feedback, interferometer stabilization, hard real-time acquisition, and independent physical interlocks are outside the proposed core's scope.

### 3.4 Potential open-source community

Subject to institutional approval and intellectual-property review, the project may become open source and invite contributions from other research institutes, observatories, universities, and technical groups. Public software, contracts, simulators, and test suites could let adopters share improvements and avoid rebuilding common capabilities independently.

Open-source licensing, contributor governance, release policies, security disclosure, and the handling of site-specific or proprietary code remain open decisions.

## 4. Principal strengths and expected advantages

The following are **design advantages and hypotheses to validate**, not yet demonstrated performance claims. Their combination is the project's principal proposition.

### 4.1 Architecture, reliability, and safety

**1. Minimal architecture and reduced operational overhead.** Small, independently runnable components, explicit boundaries, and only the infrastructure justified by actual requirements should make the system easier to start, change, and deploy.

**2. Reliability engineered from the device boundary upward.** Agreed device contracts, isolated communication libraries, protocol conformance checks, and independently testable components make low-level behavior verifiable before it is embedded in a larger system.

**3. Systematic fault injection.** Device simulators must model not just successful responses but also timeouts, network failures, malformed data, stuck states, intermittent firmware problems, and recovery behavior. The focus is not merely proving that a device works, but discovering how the system behaves when it does not.

**4. Traceable root causes.** Consistent error information and operation correlation should preserve the source of failures through multiple layers, reducing the likelihood that an original device error becomes an opaque generic supervisory failure.

**5. Layered operational protection.** Independent hardware and PLC protections, local component limits, and global supervisory safeguards form separate lines of defense. AI assistance must never bypass them.

### 4.2 AI-led engineering across the full lifecycle

**6. Agent-led software implementation.** Agents can interpret agreed requirements, implement functions, write tests, review changes, refactor code, update documentation, and prepare validated contributions. Human effort can shift toward goals, architecture, evidence, and operational accountability.

**7. Automated incident investigation and regression repair.** When observatory staff report a problem, agents can inspect logs, reproduce behavior against simulators, propose a fix, and retain a regression test. This could shorten the issue-to-resolution cycle substantially.

**8. Coordinated hardware, firmware, and software development.** With permitted access to the relevant repositories and contracts, agents can help device teams design compatible protocols, review firmware, assess proposed changes, and keep control components and simulators aligned.

**9. Reduced dependence on individual experts.** Versioned specifications, accessible code, explicit tests, and shared diagnostic history help preserve institutional knowledge beyond any single framework specialist or departmental boundary.

**10. Progressive autonomy.** Agent permissions and automated approval paths can expand where evidence supports them. The architecture should not need major revision whenever agent capabilities improve.

### 4.3 AI-assisted scientific operations

**11. Natural-language interaction.** Observers, operators, and engineers may interact by typed or spoken requests rather than by navigating complex control screens, while traditional interfaces and APIs remain available.

**12. Intelligent observation preparation.** Agents can assist with receiver and backend selection, frequency settings, schedule creation, source visibility, solar proximity, weather context, and equipment readiness. Decisions must be backed by authoritative tools and system data.

**13. Adaptive onboarding and operator assistance.** New users may receive concise explanations and guided setup; experienced users may proceed directly to technical diagnostics and advanced requests.

**14. Conversational data exploration and diagnostics.** Users may request the current temperature of a receiver, a chart of commanded and measured antenna positions over the last five minutes, or a time-aligned comparison of tracking error and wind speed.

**15. On-demand analytical tool creation.** When standard tools cannot answer a legitimate question, an agent may generate and execute analysis code in a sandbox and, after suitable verification, propose its reuse.

**16. Continuous path from user feedback to engineering action.** An observer can report an issue conversationally; the agent gathers supporting evidence and prepares a ticket; engineering agents attempt reproducible fixes; results can be communicated back to the observer.

### 4.4 Sustainability, integration, and scientific reach

**17. Lower expected lifetime engineering costs.** Less framework overhead and more automated development, testing, and maintenance may reduce the amount of specialized manual work required over decades.

**18. Faster device introduction.** Shared contracts, libraries, simulators, and conformance checks can reduce duplicated effort when integrating new receivers, backends, sensors, or other equipment.

**19. Better long-term technological adaptability.** Replaceable components, restrained dependencies, and stable interface contracts should make later platform evolution less disruptive.

**20. Collaborative open-source development.** If released openly, validated components and tools could be reused and improved by facilities beyond the original INAF installations.

**21. Transferability across scientific domains.** A carefully bounded supervisory-control core might also serve prototypes for non-radioastronomy infrastructures, including selected ET-related systems, without attempting universal real-time control.

**22. Validation against real instruments.** SRT, Medicina, and Noto provide actual configurations and operational experience, avoiding the weaknesses of a platform demonstrated only with artificial examples.

**23. Relevance to research and innovation funding.** The platform connects advanced instrumentation, software sustainability, AI, open source, verification, and cross-facility collaboration in a form that can produce concrete, assessable research deliverables.

### 4.5 What may genuinely distinguish the project

Device simulators, automated testing, machine-readable APIs, distributed controllers, and AI coding tools already exist individually. It would not be credible to claim that none of these techniques has precedents, or that this proposal is already more robust than every current system.

The potentially distinguishing contribution is **their deliberate integration across the entire lifecycle**: a device contract supports firmware development, simulated operation, system integration, field diagnostics, agent-generated fixes, and regression verification; operational users can interact with the same structured knowledge; and additional tools can be created and evaluated without compromising the control core.

The actual novelty and benefits must be assessed through a targeted review of prior work and evidence from prototypes. That review should support research claims; it need not become a feature-by-feature contest with legacy frameworks.

## 5. Core engineering principles

### 5.1 Simplicity is a technical requirement

Do not add a service, abstraction, runtime, configuration language, or dependency without a clear purpose. The software should remain compact enough that a component's behavior and dependencies can be understood and tested in isolation, by human engineers or AI agents.

### 5.2 Control, interfaces, and agent capabilities are separate

The **deterministic control core** must operate without an AI service. GUIs, command-line applications, third-party software, conversational agents, and future clients should use authorized, documented interfaces to the same underlying capabilities. No agent should be required to imitate mouse clicks through the GUI.

An **optional AI integration layer** may expose discoverable tools, documentation, states, events, and telemetry to models using an appropriate protocol, potentially an MCP adapter or equivalent. It is an interface to the core, not a new mandatory control runtime.

### 5.3 Logical functions are not containers

A component, controller, service, process, and deployment container are separate concepts. The existing installation has on the order of tens of processes or components; that scale does not by itself justify complex microservice infrastructure. One logical controller does not necessarily need one operating-system or orchestration container.

### 5.4 Contracts and tests guide implementations

Where device teams provide protocol descriptions, these should be reviewed, clarified, and converted into agreed, testable contracts. Communication code, simulator behavior, and conformance tests should derive from them. The contract is not simply a document: it is the shared reference across teams.

### 5.5 Errors retain their meaning

Structured errors, correlation identifiers, timestamps, and diagnostic contexts should allow operators and agents to trace a failure from an outward symptom back toward its original source. Avoid replacing specific causes with generic exceptions at subsystem boundaries.

### 5.6 Risk-based autonomy, not unrestricted autonomy

Agents may increasingly automate analysis, code creation, documentation, and low-risk changes. For firmware, actuator control, safety parameters, or deployment into live observing systems, independent validation and suitable authorization remain required. These safeguards are tied to physical and operational risk, not to an assumption that humans are infallible or AI agents are incapable.

### 5.7 Evidence rather than promises

The first prototypes should show concrete results: how quickly a component can be tested, whether injected faults are detected and attributed correctly, whether multiple telescope configurations work, and whether agents can diagnose and repair a deliberately introduced problem. No improvement in cost, safety, or scientific quality should be stated as proven before validation.

## 6. Preliminary operational architecture

No final hierarchy, API, language, or transport technology has been selected. The responsibilities below are candidates to validate through a working vertical slice.

### 6.1 Observer and technical experiences

**Observer interface:** a simple configuration and monitoring experience, potentially assisted by a wizard or a conversational agent. It should support observation preparation, permitted commands, status, alerts, and progress without exposing irrelevant infrastructure details.

**Technical interface:** a separate view for engineers and operators, providing detailed component states, command histories, faults, logs, configuration inspection, and authorized technical actions.

Both should use the same core service capabilities with different roles and presentation needs.

### 6.2 Command, state, and event interfaces

The control API should support:

- Discoverable and documented commands, parameters, preconditions, and outcomes.
- Submission and tracking of long-running operations.
- Current device and subsystem states.
- Events, status changes, warnings, and diagnostic evidence.
- Safe cancellation or interruption semantics where applicable.
- Configuration access and authorized changes.
- Versioned contracts and relevant capability metadata.

Command initiation, execution progress, telemetry, and event delivery need not use the same communication pattern. Protocol and transport choices must follow requirements and simple representative experiments.

### 6.3 Orchestration: reconsider the legacy Boss model

The current SRT system uses a top-level coordinator (informally the **Boss of Bosses**), subsystem **Bosses**, and low-level **Components**. A configuration such as `KKG` is forwarded to appropriate subsystem Bosses; they coordinate receiver positioning, receiver configuration, backend preparation, and other relevant local actions according to the telescope configuration.

This captures real coordination requirements but **does not dictate the future architecture**. Alternatives may include simple coordinators, explicit workflows, declarative setups, or state-driven controllers. Their complexity, fault behavior, observability, and agent-readiness should be compared through prototypes, not chosen by analogy. Terminology such as *controller*, *orchestrator*, or *device adapter* remains provisional.

### 6.4 Device-facing components

A device adapter or low-level component mediates between an agreed protocol and the wider control system. It validates requests, reports states and faults, enforces locally configured operating limits, and uses a communication layer that can be tested separately where appropriate.

Devices in the same class, such as receivers, should share common interfaces when useful, while exposing their legitimate differences without awkward workarounds. Avoid imposing a universal device-state machine on equipment with very different behavior.

### 6.5 Multi-facility configuration

The design must allow SRT, Medicina, and Noto to use appropriate site-specific devices, operating limits, capabilities, and observing setups. Configuration should be validated, versioned, traceable, and kept separate from generic logic where practicable. Safety-relevant changes need stronger controls than ordinary operational settings.

### 6.6 Safety supervision

Safety has three distinct responsibilities:

1. **Independent physical safeguards:** PLCs, limit switches, interlocks, and other device protections continue to work without this platform.
2. **Component protections:** command bounds, operating ranges, temperature limits, legal-state constraints, and local alarms are enforced close to the equipment.
3. **Global supervision:** system-level logic can interrupt an observation, inhibit commands, stop operations, or trigger an approved safe-state procedure when conditions require it.

Examples include excessive wind and unavailable weather information during an unattended remote observation. Parking an antenna is not automatically the appropriate response to every fault; safe responses, priorities, recovery rules, and degraded operating modes must be defined for the relevant installation.

An AI agent may report, explain, or propose actions, but cannot override these deterministic protections.

### 6.7 User messaging and alert priorities

Observers should not be overwhelmed by internal logs. Provide operator-facing messages distinguished by severity and operational relevance: for example, critical alarms, errors, warnings, and informational notices. Design should consider visibility, grouping, acknowledgement, history, and escalation. Critical protection actions must not depend on message presentation or user acknowledgement.

### 6.8 Authentication and data services

Authentication and authorization must be supported for operational use; external identity-provider integrations may remain optional for development or offline test installations. Access to configuration, historical telemetry, diagnostic logs, and scientific observation products need not depend on a single database or monolithic service.

Keep **current operational status**, **historical operational data**, and **scientific acquisition data** conceptually distinct. Decide persistence and retention policies according to actual usage and required timing; do not store every signal indiscriminately.

## 7. Contracts, firmware, simulation, and fault tolerance

### 7.1 End-to-end development contract

For each new device, its team supplies a protocol and functional specification. Control-system and device engineers review it together, resolve ambiguities, and agree on a testable contract covering, where relevant:

- Operations, parameters, response formats, and status semantics.
- State transitions, initialization, shutdown, and recovery.
- Timing requirements, timeouts, and retries.
- Operating ranges, rejected commands, and safety-related limits.
- Expected responses to connection failures, malformed requests, firmware faults, and invalid device states.
- Compatibility and versioning rules for later firmware changes.

This reference should serve firmware, communication libraries, simulators, conformance tests, control adapters, and documentation.

### 7.2 Simulator-first verification with fault injection

A simulator should be independently executable and reproduce normal and abnormal behavior. Fault cases may include lost or malformed messages, delayed replies, disconnected networks, unexpected errors, stuck state transitions, invalid sensor values, intermittent faults, and recovery failures.

Tests should deliberately challenge the control system's handling of these cases. Additional scenarios should be added when operational incidents reveal previously unseen failure modes. Full simulation of every physical anomaly is neither possible nor claimed.

### 7.3 Verify real devices against the same contract

A shared conformance suite should run against both the simulator and the actual hardware wherever safe and meaningful. Differences require investigation; they could indicate firmware defects, incorrect contract interpretation, simulator mistakes, library errors, or undocumented device behavior.

Potentially disruptive or dangerous tests must never be launched unattended against physical equipment merely because they run safely in simulation.

### 7.4 Preserve regression evidence

Applicable conformance tests remain available after integration. When device teams update firmware, automated checks should identify changed behavior and possible incompatibilities with the rest of the system. Version the contract and record which firmware, simulator, library, and control versions were validated together.

### 7.5 Build a simulated observatory

An offline assembly of simulated devices and controllers should allow meaningful whole-system tests: telescope configuration, multiple subsystem coordination, operator messaging, protective responses, degraded modes, and fault propagation. AI coding agents should be able to start, inspect, break, and test this environment without contacting live hardware.

Success in the simulator is essential engineering evidence, **not a substitute for real-hardware qualification**.

## 8. Integrated cross-team engineering ecosystem

### 8.1 Shared access, not necessarily a monorepo

The project should strive to make all relevant, accessible software and specifications available to authorized agents: control-system code, device firmware, hardware-interface documentation, libraries, simulators, conformance suites, and issue histories.

A common GitHub organization or an equivalent shared repository space could simplify navigation and administration. A single repository is not necessary. Different groups may retain ownership of their code, and some vendors or teams may allow access only to protocol specifications, not firmware sources.

### 8.2 An agent as a collaborator across departments

When a receiver team plans new firmware or a revised interface, an agent could find existing receiver contracts, identify compatible commands, propose a revised protocol, create tests, inspect allowed firmware changes, and coordinate necessary updates to the simulator and control adapter.

When a firmware pull request changes a protocol, automated cross-repository checks could determine which consumers are affected and propose aligned changes or flag broken compatibility. This could detect integration problems before the device is installed at the telescope.

### 8.3 Contracts as active coordination assets

Maintain explicit relationships among device contracts, firmware versions, communication libraries, simulators, conformance tests, and control components. This does not require a complicated central platform initially; versioned files, reproducible tests, and repository automation may be enough.

### 8.4 Governance and security boundaries

Agents should have the smallest repository, infrastructure, and equipment permissions appropriate to their task. Read access and code-proposal permissions are different from approval rights, firmware flashing, and deployment rights.

Repositories may contain credentials, operational parameters, sensitive details, or third-party intellectual property. Access, retention, publication, and audit policies must reflect institutional requirements. A closed-source device must still be integrable through its agreed interface without forcing source-code disclosure.

## 9. AI-native interactions and an extensible operational assistant

### 9.1 The conversational operator

The long-term user experience may be that of speaking with a knowledgeable observatory operator. A new astronomer might request a short introduction and guided setup; an experienced scientist could describe a complete observation goal and ask the assistant to prepare a proposed configuration.

Examples:

- "Configure the K-band receiver and prepare the appropriate backend settings for this observation."
- "Build a schedule for these sources and tell me if the trajectory gets too close to the Sun."
- "The forecast seems unfavorable. Should I change observing time or frequency?"
- "Why is the telescope not ready?"
- "What is the temperature of receiver X?"
- "Plot commanded and actual antenna elevation over the last five minutes."
- "Compare pointing error with wind speed during the last twenty minutes."

The agent should identify missing information, explain trade-offs, and offer useful alternatives. Astronomy, meteorology, numerical analysis, hardware compatibility, and safety checks must be carried out using reliable data and deterministic tools, not unsupported model guesses.

### 9.2 Interaction is not just another graphical UI

The agent should discover and call the same documented operations that ordinary clients use. It should not require GUI automation to operate the telescope. Conversational interfaces, voice recognition, model choice, and an MCP-compatible adapter (if adopted) belong outside the mandatory deterministic control core.

### 9.3 Structured telemetry and analysis

Expose current operational measurements and relevant historical time series through authorized tools. Each measurement should have machine-readable identity, units, timestamp, meaning, provenance, and quality/validity markers where appropriate. Queries should support time windows and handle time synchronization, missing samples, rate differences, and data retention limitations.

Plots, correlations, statistics, filtering, and astronomical calculations should use reproducible numerical tools. Agents can select analyses and explain results while keeping numerical evidence inspectable.

### 9.4 Conversation-driven issue reporting

When a user reports an unexpected behavior, an agent can ask clarifying questions, inspect state and logs, determine whether there is evidence of a genuine defect or simply a configuration misunderstanding, and propose filing an issue.

A useful ticket should contain the affected device, timeline, command or observation identifiers, relevant versions, events, logs, and reproducible steps or simulator scenarios, while respecting data access controls. Engineering agents can then investigate and prepare a fix, with links between the reported incident, tests, pull request, and release.

### 9.5 Agents that create their own tools

Not every scientific or diagnostic request can be anticipated. When no existing tool is appropriate, an agent may write an ad hoc script and execute it inside an **isolated, permission-restricted environment**. If the resulting capability is useful beyond one session, it can be reviewed, tested, versioned, and entered into a reusable catalog.

Maintain a strict distinction among:

1. **Temporary analysis code** for one bounded question.
2. **Verified reusable tools** with contracts, tests, versions, dependency information, permissions, and documented scientific assumptions.
3. **Permanent modifications to control software**, which require the appropriate software validation, release process, and operational safeguards.

Generated code should not gain direct hardware-control rights by virtue of being useful for data analysis. Successful execution does not guarantee scientific correctness: calibration, units, time alignment, and methodology must be evaluated.

### 9.6 Increasing autonomy over time

The architecture should allow progressively broader agent responsibilities as tools, evaluation methods, and models improve. A low-risk graph-generation task might run automatically; a repository change might pass automated gates; a safety-policy change or deployment to a live telescope would require a more stringent independent authorization path.

Do not assume any particular AI model will be available, nor that future agents will be infallible. The objective is **high autonomy with explicit evidence and bounded authority**, rather than permanent human intervention for every routine step or unrestricted autonomous modification of the observatory.

## 10. Proposed engineering workflow

### 10.1 Device integration

1. Receive and jointly refine the device and firmware specification.
2. Agree on the versioned, testable interface contract.
3. Create conformance tests including negative and failure cases.
4. Build or reuse a communication library and a fault-injectable simulator.
5. Verify the protocol against simulation.
6. Run applicable safe tests against the actual device.
7. Analyze discrepancies and revise implementations or the contract when justified.
8. Build the control component using the verified communication layer.
9. Perform component, integration, and simulated-system testing.
10. Retain tests for later firmware and software changes.

These steps may iterate rather than occur in an inflexible sequence.

### 10.2 From incident to released fix

1. User describes an incident, optionally through natural-language interaction.
2. Agent gathers logs, telemetry, versions, and clarifications.
3. An issue is created with the user's consent or under an established reporting policy.
4. Engineering agent reproduces the fault offline and identifies a likely cause.
5. Agent creates a focused fix and regression tests.
6. Automated suites validate the change against device and system simulators.
7. Review, hardware testing, and deployment authorization follow risk-based policy.
8. The issue and operational record are updated with traceable outcomes.

### 10.3 AI-first work does not dictate a multi-agent bureaucracy

An agent may have several tools and roles without requiring a swarm of autonomous services. Prefer small, transparent workflows, straightforward source control, and reproducible test commands. Introduce multiple specialized agents or elaborate orchestration only when experiments show a material benefit.

## 11. Funding strategy and scientific deliverables

### 11.1 Why funding matters to the vision

The project has two complementary outcomes: a practical modernization of existing INAF installations and a research program exploring a new AI-native lifecycle for scientific-control infrastructure. That second outcome can support collaborative projects, demonstrators, publications, and broader adoption.

Funding should be considered when identifying work packages, evidence, collaborations, dissemination, open-source outputs, and evaluation criteria. **Do not add product complexity merely to match a particular call.**

### 11.2 Funding routes to evaluate

| Route or program | Possible project role | Notes |
| --- | --- | --- |
| **INAF institutional and internal technology funding** | Feasibility, early prototypes, migration work, and validation across SRT, Medicina, and Noto | Requires an internal sponsor, governance, and identification of eligible budgets or calls. |
| **[Horizon Europe Research Infrastructures - INFRATECH](https://research-and-innovation.ec.europa.eu/funding/funding-opportunities/funding-programmes-and-open-calls/horizon-europe/research-infrastructures_en)** | New technologies and digital capabilities for research infrastructures | Topic-specific scope, consortium, expected impact, and eligibility must be verified. |
| **[Horizon Europe Research Infrastructures - INFRADEV](https://research-and-innovation.ec.europa.eu/funding/funding-opportunities/funding-programmes-and-open-calls/horizon-europe/research-infrastructures_en)** | Collaborative infrastructure development where a relevant topic exists | Not every INFRADEV call is suitable for a software platform. |
| **[Sardinia ERDF/FESR](https://www.regione.sardegna.it/)** and regional research initiatives | Technological innovation and local research-infrastructure collaborations | Calls may be restricted by beneficiary type and geographic or partnership conditions. |
| **ET-related research and technology collaborations** | A bounded cross-domain supervisory-control or simulation demonstrator | A research direction, **not a confirmed open funding call**; technical partners must validate relevance. |
| **[NLnet/NGI](https://nlnet.nl/funding.html)** and other open-source schemes | Small, reusable modules such as tooling, simulation, and standards-compatible interfaces | Specific scheme objectives and grant limits may exclude the full platform. |

This list is a **prospect map, not a list of currently open or guaranteed grants**. For each actual application, consult official documents to confirm deadline, topic language, beneficiary and consortium eligibility, funding rates, project duration, deliverables, licensing restrictions, and budget rules. For EU calls, use the official [Funding & Tenders Portal](https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/home).

### 11.3 Candidate research outputs

Potential verifiable deliverables include:

- A reproducible reference implementation of lightweight distributed supervisory control.
- A formalized contract and conformance-test approach for device integration.
- Fault-injectable simulators and a simulated multi-subsystem observatory.
- End-to-end diagnostic and operator-alert demonstrations.
- A documented AI agent workflow that reproduces and repairs a seeded defect.
- A conversational observer assistant using validated scheduling, telemetry, and configuration tools.
- An agent-generated analysis tool promoted through controlled verification.
- A cross-repository firmware-to-control compatibility demonstration.
- A pilot across distinct telescope configurations.
- Optionally, a partner-defined non-radioastronomy demonstrator to test transferability.

### 11.4 Evaluation without unnecessary bureaucracy

A preliminary financial study is not a prerequisite. Nevertheless, credible evaluation should eventually examine such observable properties as:

- Time and steps needed to launch and test an isolated component.
- Automated test coverage of agreed behavior and selected failure classes.
- Detection and attribution of deliberately injected faults.
- Recovery behavior following communication interruption or stuck devices.
- Repeatability of the same test suite across simulated and real hardware.
- Time needed to integrate a representative new device or firmware revision.
- Agent success rates for bounded issue reproduction and repair tasks.
- Performance and behavior across SRT, Medicina, and Noto configurations.
- Reliability of authorization, safety, and deployment safeguards.

Such evidence can substantiate benefits and inform proposals without burdening the first experimental steps with an elaborate benchmarking program.

## 12. Research and implementation roadmap

The first planning framework has three stages. They establish order, not a prematurely fixed schedule.

### Phase 1 - General requirements

Document the actual needs of SRT, including interfaces, observing operations, device classes, state and error behavior, safety boundaries, relevant telemetry, and user roles. Identify how Medicina and Noto differ by configuration. Capture AI-led engineering and AI-assisted operation as explicit capabilities, while distinguishing core requirements from optional later functions.

**Exit criterion:** an agreed requirements baseline and a small representative control scenario suitable for a technical prototype.

### Phase 2 - Architecture and tools

Evaluate several simple architectures, then implement a **small vertical slice**: a real device contract, communication library, simulator with fault injection, control adapter, one coordinating operation, state/diagnostic exposure, and tests. Evaluate usability by AI coding agents. If straightforward, trial a read-only conversational tool and historical telemetry query, but do not allow this experiment to delay the basic control prototype.

**Exit criterion:** runnable evidence supporting the architectural choice, known trade-offs, reproducible tests, and a decision on whether to extend or revise the approach.

### Phase 3 - Detailed work plan and staged deployment

Inventory legacy behavior and integrations; plan components, priorities, milestones, coexistence and migration from ACS, test acceptance criteria, real-hardware verification, release controls, and long-term maintenance. Define discrete research and funding packages and determine whether a second telescope configuration or a cross-domain demonstrator can be added without distorting the core.

**Exit criterion:** a risk-aware, incrementally deliverable roadmap with technical milestones and appropriate ownership.

### Subsequent development priorities

Build and validate operational control capability first. Expand simulation, hardware qualification, diagnostic tooling, cross-repository automation, and the optional AI operator experience in independently useful increments. Investigate ET or other non-radioastronomy reuse only when there is sufficient working evidence and a concrete partner-defined use case.

## 13. Open decisions and risks

### 13.1 Design choices still to be made

- Programming language(s), package structure, and build/test tools.
- Communication transport, API schema, event mechanisms, and versioning.
- Synchronous versus asynchronous commands, operation tracking, and cancellation.
- Orchestration model: hierarchical coordinators, workflows, state machines, or alternatives.
- Logical component boundaries, processes, and deployment packaging.
- Configuration representation and safe multi-telescope variation.
- Detailed hardware and global safety-supervision behavior.
- Test framework, simulator representation, and fault-injection mechanism.
- Telemetry transport, time synchronization, storage, retention, and quality metadata.
- Observer UI, technical UI, alerts, acknowledgement, and message priorities.
- Authentication, authorization, identity integration, and auditing.
- Agent integration protocols, models, sandbox, reusable tool registry, and permissions.
- Source-control organization, firmware access, cross-repository testing, and governance.
- AI autonomy levels, evidence thresholds, and change/deployment approval rules.
- Open-source licensing and intellectual-property restrictions.
- Funding collaborators, eligible programs, deliverables, and submission strategy.
- Migration, coexistence, operations, and hardware qualification plan.
- Criteria and timing for evaluating other scientific facilities, including ET.

### 13.2 Risks that must be treated directly

**Simulation gap.** A simulator may omit firmware bugs, timing behavior, or physics. Mitigation: real-device conformance tests, incident-driven scenario updates, and separate hardware acceptance.

**Generated code passing inadequate tests.** Automated success can conceal incorrect requirements or missing edge cases. Mitigation: independently reviewed contracts, negative tests, traceable assumptions, and targeted real-world verification.

**Scientific misinterpretation.** An analysis may run correctly but misuse timebases, units, calibration, or statistics. Mitigation: deterministic computation, explicit data provenance, scientific validation, and visible assumptions.

**Agent overreach.** A useful coding or analytical agent might otherwise gain inappropriate equipment or deployment permissions. Mitigation: sandboxing, role-based authorization, isolated environments, and independent safety enforcement.

**Uncontrolled generalization.** A platform meant for every facility could recreate the complexity the project seeks to remove. Mitigation: SRT-led prototypes and cross-domain experiments only when justified.

**Uncontrolled tool growth.** Dynamically generated scripts may accumulate and conflict. Mitigation: temporary-by-default tools, versioned catalog, deduplication, testing, and retirement policies.

**Long-term funding and governance.** An open platform requires ownership of releases, security, documentation, and coordination. Mitigation: explicit stewardship and staged deliverables independent of any one grant.

## 14. Guidance for AI reviewers and future development agents

This document is intended to let a technically capable AI evaluate the proposal without reading the originating conversation.

1. **Treat stated priorities as binding unless the project owner revises them:** build from real telescope needs, preserve simplicity, and keep operational safety independent from AI.
2. **Treat candidate architectures and technologies as undecided.** Do not infer that existing Boss hierarchies, MCP, containers, state machines, or any particular language have been selected.
3. **Do not copy ACS's internal structure merely because it is the legacy implementation.** Use legacy code as evidence of actual device behavior and operating requirements.
4. **Consider SRT, Medicina, and Noto as real validation cases**, with existing telescope-specific configuration, but do not claim the new platform has already been deployed at any of them.
5. **Keep ET and other facilities as possible research extensions.** Never silently add interferometer hard real-time requirements to the supervisory platform.
6. **Design for independent testing:** start with a device contract, a fault-injectable simulator, a communication layer, and a thin control component.
7. **Preserve error provenance** and support deterministic, reproducible diagnosis at every layer.
8. **Keep agents outside the trusted safety boundary.** Agent-assisted operations must obey the same command validation, permissions, and protective controls as all other clients.
9. **Treat AI models as replaceable collaborators.** Their capabilities may improve, but future reliability or autonomy must not be assumed as established fact.
10. **Allow agent-created analysis tools only through scoped, isolated execution**; require additional verification before shared reuse or modification of production control software.
11. **Do not require every firmware repository to be public or centrally owned.** Respect access rights while aiming for shared, versioned interfaces and automated compatibility testing.
12. **Separate expected benefits from demonstrated results.** Challenge claims of uniqueness or exceptional robustness until sufficient evidence exists.
13. **Make funding relevance visible, but verify each current call.** A program name in this document is not evidence of an open grant or guaranteed eligibility.
14. **Prefer concrete alternatives, trade-offs, and experiments over agreement without analysis.** Identify unnecessary complexity and propose how to test assumptions.
15. **Do not begin implementation, choose permanent technologies, or modify the project architecture autonomously without an explicit request or agreed workflow.** Keep specifications, code, tests, and documentation synchronized once development begins.

## 15. Closing statement

The central ambition is a **new engineering and operational model for scientific-control infrastructure**: lightweight deterministic control, explicit contracts, testable device integration, failure-aware simulation, evidence-rich diagnostics, and AI agents participating throughout software and firmware development, facility operation, user assistance, and continuous improvement.

The first evidence must come from an actual, useful implementation for SRT, informed by the shared software and differing configurations of Medicina and Noto. This establishes a credible practical foundation and potential migration benefits, rather than merely a conceptual AI demonstration.

If the platform proves reliable and genuinely simpler in practice, its reusable elements may support future observatories, open-source collaboration, and funded research programs. A later ET-related supervisory-control prototype could test that transferability even without production deployment. The broader ambition should **increase the value of the initial telescope work, not make it harder**.
