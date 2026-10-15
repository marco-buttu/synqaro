# Synqaro

**An AI-native engineering and control platform for complex distributed systems**

**Project vision and preliminary design principles**  
**Version:** 0.6  
**Date:** October 15, 2026  
**Status:** Concept document for technical discussion, collaboration, and funding exploration. No architecture or technology stack has been approved.

---

## 1. Vision: one platform, an entire engineering lifecycle

Synqaro is a proposed open-source, AI-native platform for **developing, integrating, operating, testing, diagnosing, and maintaining complex distributed systems**. Its intended applications range from scientific research facilities to industrial installations. Instead of providing a large, prescriptive framework for one class of machinery, Synqaro aims to offer a small, dependable **control core** and a consistent **AI-assisted engineering environment**. Application-specific operational logic would be supplied by independently developed **operational layers**.

The central idea is simple: when devices, software services, firmware, configurations, telemetry, tests, and documentation are connected through clear, machine-readable contracts, both humans and AI agents can understand and work with the system far more effectively. An agent should be able to help design an interface with a firmware team, validate its behavior against a simulator and a real device, guide an operator through a procedure, investigate a failure, and prepare a tested software correction. These activities should form a coherent lifecycle rather than disconnected manual workflows.

Synqaro is intended to remain useful without AI. Its control functions, safety checks, and essential operator interfaces must behave deterministically and remain operable when AI services are unavailable. AI should enhance engineering and operations, not become a prerequisite for safe control.

The project's ambition is broad, but its implementation must be incremental: **build the smallest useful core, validate it in realistic environments, and generalize only where evidence justifies doing so.**

## 2. Why Synqaro matters: the main expected advantages

The distinctive promise is not an isolated feature. It is the **combination** of a minimal control architecture, contracts, systematic simulation, traceable diagnostics, and AI involvement throughout the lifecycle.

### Five principal strengths

1. **A substantially simpler control architecture.** Small components, clear APIs, few dependencies, and independent execution and testing should reduce infrastructure overhead. Each logical component need not be a separate process or container. Domain-specific workflows should not dictate the core's design.
2. **Reliability engineered from the device boundary upwards.** Versioned contracts, reusable communication libraries, simulators, fault injection, and tests shared with real hardware should expose faults early. Errors should remain traceable from firmware and communication layers to the user-facing diagnosis. This is a strategy for *verifiable robustness*, not a claim of proven superiority before validation.
3. **An AI-native lifecycle encompassing hardware and software teams.** Agents could assist with requirements, protocol design, firmware review, component development, test generation, cross-repository compatibility, issue diagnosis, fixes, documentation, and maintenance. This would reduce bottlenecks caused by fragmented knowledge and specialist-only workflows.
4. **Natural-language operations and on-demand capabilities.** Users could converse with an agent to configure a facility, plan operations, inspect live or historical measurements, ask why something failed, obtain graphical analyses, and request new tools. Where an appropriate tool does not exist, an agent could create and test it in an isolated environment and potentially publish a reusable version.
5. **Lower lifecycle effort and longer-term adaptability.** Reproducible tests, simpler startup, fewer unnecessary abstractions, reusable components, automated maintenance, and progressively greater agent autonomy could reduce development and operational costs over decades. Savings are a central motivation; their magnitude and the delivered reliability remain outcomes to establish in the demonstrators.

Additional expected strengths include faster onboarding, more consistent firmware integration, reduced reliance on undocumented knowledge, clear incident-to-fix traceability, external collaboration through open source, and applicability to multiple industries through separately designed operational layers.

Synqaro should not claim that none of its techniques exists elsewhere. Contracts, simulation, event systems, fault injection, and AI coding tools already exist. The research proposition is whether their **coherent, lightweight, AI-native integration** can yield a better lifecycle for real distributed-control installations.

## 3. Architectural concept: common core, replaceable operational layers

The leading architectural hypothesis is a deliberate separation between **generic mechanisms** and **domain-specific operations**.

### Common control core

The Synqaro core should know about components and their declared capabilities, commands, parameters, measurements, states, events, errors, and permissions. It should not need to understand telescopes, interferometers, industrial production, receivers, or scientific observing schedules.

Candidate common capabilities are:

- Component discovery and interface/contract descriptions.
- Invocation and tracking of commands, including long-running operations.
- Current-state and event access, with consistent timestamps and validity information.
- Structured telemetry and access to historical data through interchangeable services.
- Error identity, correlation, provenance, and diagnostic reporting across boundaries.
- Configuration validation, component-level operating limits, and suitable common safety mechanisms.
- Authorization hooks and auditable actions, including actions initiated by agents.
- Straightforward local execution, simulation, testing, and deployment.

These are **candidate responsibilities**, not a decision to implement all of them inside one runtime. Optional services and libraries may be preferable to a larger mandatory core. The design must distinguish logical components from processes, containers, services, and physical devices.

### Domain-specific operational layers

Each installation defines its own operational layer on top of the core. This layer interprets facility-specific concepts and coordinates devices, for example:

- **Radio telescopes:** receiver/backend configuration, antenna positioning and tracking, observation scheduling, and observatory-specific workflows.
- **Gravitational-wave facilities:** supervisory coordination of selected subsystems, operational sequencing, health monitoring, and maintenance workflows.
- **Industrial installations:** production sequences, equipment coordination, process monitoring, and plant-specific operating procedures.

The operational layer defines *what the installation does*; the core offers reusable ways to communicate with, observe, test, and manage its components. Generic sequence execution, cancellation, timeouts, retries, and state-machine mechanisms might be shared as **optional building blocks** where they demonstrably remove duplication. Synqaro must not force every application into one universal orchestration model.

Device adapters and hardware-facing components sit beneath this distinction. Their software interfaces should be stable and explicit, while individual devices and firmware implementations remain replaceable. One interface may have several implementations selected by installation configuration.

### Safety is not an AI feature

Safety requires multiple layers. Independent hardware protections and PLC interlocks must remain independent. Components should validate configured operating ranges and enforce local constraints. Facility-specific supervisory logic must address global situations such as unsafe weather, loss of vital telemetry, or the need to stop operations and move equipment to safe states. Such logic may take precedence over ordinary commands.

Generic mechanisms may support alarms, command rejection, priorities, and interlocks, but **the concrete safety rules belong to the installation and its validated protective systems**. Agents may recommend and request actions only through authorized interfaces; they must not bypass protection logic. Real-time deterministic feedback controllers, where required, remain dedicated systems rather than assumed responsibilities of the general-purpose core.

## 4. Device contracts, simulation, and fault diagnosis

Reliable integration begins with a contract jointly agreed upon by the device/firmware team and the control-system team. A contract describes, as applicable, commands, data formats, replies, error conditions, states, transitions, timing constraints, operating limits, and recovery behavior. It is versioned and is the reference for implementations and conformance tests.

A typical development loop is:

1. Review and agree on the device contract with the responsible engineers.
2. Implement a reusable communication library where appropriate, plus contract-driven tests.
3. Implement a simulator representing nominal behavior and controllable fault scenarios.
4. Run applicable tests against the simulator and then, subject to hardware safety constraints, against the real device.
5. Resolve discrepancies without presuming that a failure necessarily proves a firmware bug: the contract, implementation, simulator, or test may be wrong.
6. Develop the control component against the verified interface and add component and cross-component integration tests.
7. Retain conformance and regression tests for future firmware and software updates.

Simulation must deliberately include **failure modes**, not merely successful responses: dropped and delayed messages, timeouts, malformed replies, stuck states, intermittent disconnections, invalid measurements, and known firmware defects. Scenarios should be reproducible, with fault injection separate from nominal simulation where practical.

The platform should make a full simulated installation feasible to the extent permitted by available models. This allows agents to reproduce incidents offline and verify fixes without repeatedly using real equipment. Simulator success is **not** proof of physical correctness: safe hardware-in-the-loop and real-system validation remain necessary.

Every operation should be traceable across layers. When a device fails, the upper layers must preserve the originating error, affected component, command or operation identifier, timestamps, and relevant evidence, rather than reducing the result to an uninformative generic failure. Clear fault attribution is a core reliability requirement.

## 5. AI-native engineering across departments

Synqaro's engineering environment should include not just its core repository but, whenever access is possible, related firmware repositories, protocols, simulators, tests, configuration definitions, and technical documentation. These may live in a shared GitHub organization or across independently owned repositories with suitable access controls. **Shared access and versioned contracts matter more than forcing a monorepo or centralized ownership.**

For example, a team developing a new receiver, sensor, or industrial controller could ask an agent which existing interface to preserve. The agent could examine current contracts, compare firmware implementations, propose compatible changes, create simulator and test updates, and identify corresponding changes needed in the control component. A firmware pull request could trigger compatibility checks against the control stack and associated test suites.

For proprietary devices, the system must still work from published protocols, observed behavior, and conformance tests without access to source firmware. AI review of firmware cannot replace appropriate physical tests, device-owner responsibilities, or controlled deployment procedures.

The intended issue workflow is similarly connected: a user reports an anomaly; an agent asks for relevant details, correlates telemetry and logs, tries to reproduce the fault in a simulator, identifies a probable cause, produces a fix and regression tests, and prepares a reviewable change. Automated release and deployment permissions should be **risk-based**. Development agents may gain greater autonomy as verification capabilities mature, but safety-critical firmware, controller changes, and production deployments require separately defined safeguards.

The aim is to make cross-team engineering knowledge available through living contracts, source repositories, diagnostics, and tests, rather than relying on a handful of individuals to remember the entire system.

## 6. AI-native use: a conversational operator and engineering assistant

Users should be able to interact with Synqaro through normal interfaces and, optionally, through text or speech. An agent would act as a **first-class client of structured APIs**, not as a screen-clicking substitute for a documented client. An adapter such as an MCP server may be useful at the agent boundary; it need not be the internal communication protocol.

Examples of possible conversations include:

- A new observer or operator asks for a short introduction and is guided through an initial configuration.
- An experienced user describes an intended observation or process. The agent checks device compatibility, prerequisites, weather or environmental conditions, planning constraints, and available alternatives, then asks for clarification when necessary.
- A user requests the current temperature of a device, or a plot of an antenna's commanded and actual positions for the last five minutes. The agent retrieves and visualizes real measurements through approved tools.
- An operator reports unexpected behavior. The agent investigates, distinguishes an actual fault from a configuration or procedural problem when evidence permits, and asks whether to prepare or submit an issue.
- An engineer asks an agent to compare a proposed firmware interface with existing contracts or to diagnose a failing test.

Numerical calculations, telemetry queries, scheduling checks, physical limits, and safety validation should be performed by deterministic services. The language model interprets the request, selects tools, integrates evidence, and explains results, with uncertainty when conclusions are not established.

Telemetry access therefore needs discoverable measurement names, units, timestamps, validity/quality indicators, descriptions, and support for present and historical readings. Data retention and sampling must be configurable; recording every signal indiscriminately is not a goal. The same services should support conventional interfaces, independent of AI availability.

### Agents that develop tools when needed

If the system lacks an analysis tool requested during a conversation, an authorized agent could construct and execute one **in a restricted, reproducible environment** with controlled data access and no direct hardware-control authority. The user gets the result; the tool may later be tested, reviewed, versioned, and published in a reusable catalogue with its dependencies, input/output contracts, permissions, limitations, and provenance.

A one-off script must not silently become trusted production software. An analysis can be programmatically correct while scientifically wrong because of units, clock alignment, missing samples, filtering, or inappropriate statistical assumptions. Verification must address the meaning of results, not just the absence of exceptions.

### Progressive autonomy

Synqaro should not hardcode today's AI limitations into its architecture. The long-term goal is extensive autonomy in engineering, support, diagnosis, and appropriate operations. Permissions and validation gates should be adjustable by task and risk, allowing responsibility to increase when evidence supports it. This is **not** a premise that future models will be infallible, nor a reason to make the control core dependent on them.

## 7. A credible path from concept to demonstrations

Synqaro must be evaluated through small, representative experiments before committing to an extensive framework design. The initial process is:

**Stage 1 — General requirements.** Define functional responsibilities, safety boundaries, observability, reliability, operational needs, AI capabilities, and the distinction between core and domain logic.

**Stage 2 — Architecture and tools.** Compare modest technical options. Build a minimal vertical slice: a real or realistically simulated device contract, communication library, component, telemetry access, fault injection, and a small domain-specific operational workflow. Test usability by human clients and agents; reject unnecessary abstraction.

**Stage 3 — Delivery plan.** Select a limited group of real components, define acceptance criteria, CI and regression suites, staging and hardware validation, security policies, and a safe migration strategy. Expand by measured capability rather than promised feature count.

A crucial architectural test is whether **a second application domain can implement its operational layer without forcing domain concepts into the core**. A simulated industrial process or a narrowly scoped scientific subsystem may be enough for this experiment.

Useful evaluation criteria include component startup complexity, deployment effort, time to reproduce and diagnose faults, contract conformance, failure containment, integration effort, regression coverage, reliability under injected faults, and the proportion of engineering tasks agents can complete under defined verification criteria. These are proposed measurements, not benefits already proven.

## 8. Open source, collaboration, and funding

Synqaro is intended to be evaluated as an **open-source** platform capable of attracting external users, contributors, and institutional partners. Governance, licensing, contribution rules, interface stability, release practices, and ownership of firmware or third-party IP require decisions before publication.

Funding is strategic because the research contribution is wider than one installation: it includes an integrated lifecycle model, reusable control mechanisms, simulation and fault-diagnosis methodology, AI-assisted cross-repository engineering, and controlled agent-based operations.

Funding routes to investigate include:

- **INAF and other research institutions:** engineering R&D and modernization of research facilities.
- **Horizon Europe Research Infrastructures — INFRATECH:** technology development and innovative digital solutions for research infrastructures, subject to the requirements of each call.
- **Horizon Europe Research Infrastructures — INFRADEV and related topics:** collaboration and infrastructure development where the actual call scope is relevant.
- **Regional and national R&I programmes**, including Sardinia's ERDF/FESR initiatives and programmes connected to scientific and industrial infrastructure ecosystems.
- **Open-source and digital-commons funding** for well-defined reusable modules, where eligibility and objectives align.
- **Consortia and applied research partnerships** with observatories, research institutes, universities, and industrial organizations.

These are **candidate programme families, not confirmed currently open or eligible calls**. For each application, the team must check the current official call, beneficiaries, consortium rules, expected impacts, technology readiness, eligible costs, deadlines, and required deliverables. Grant applications should shape demonstrators and reporting, **not inflate or distort the core architecture**.

Proposed fundable outcomes include a reproducible software demonstrator; a validated device contract and fault-injection suite; an independently testable control component; a facility-specific operational layer; an agent-assisted issue-to-fix workflow; and evidence of reuse in a second domain. Demonstrators should expose measurable engineering outcomes rather than promising universal applicability.

## 9. Initial validation environments and future applications

### First proving ground: three INAF radio telescopes

The **Sardinia Radio Telescope (SRT)**, the **Medicina Radio Telescope**, and the **Noto Radio Telescope** are three Italian radioastronomy facilities operated by the **Istituto Nazionale di Astrofisica (INAF)**. They provide a concrete opportunity to evaluate Synqaro against real operational needs, rather than creating an abstract framework without users or hardware.

Their current control software shares a common architecture and interfaces while using **different site configurations and, for some devices, different component implementations behind the same interface**. This makes them a useful first test of Synqaro's distinction between reusable core mechanisms, replaceable device implementations, and installation-specific operational configurations.

The experimental programme could develop a radioastronomy operational layer while progressively replacing selected existing components, reusing their behavioral knowledge but not mechanically copying legacy architecture. SRT, Medicina, and Noto would serve as development and validation environments, and successful outcomes could support an eventual operational migration. The specific migration scope, authorization, staffing, and timetable are not yet established.

### Additional experimental domain: Einstein Telescope

**Einstein Telescope (ET)** is a proposed next-generation gravitational-wave observatory. It could be a valuable second domain in which to **test the transferability of the same core principles and AI-native engineering lifecycle**: device contracts, simulator-first integration, fault diagnosis, cross-team firmware/software coordination, supervisory monitoring, operator assistance, and extensible domain-specific workflows.

A scoped prototype could use a simulated or partnered supervisory subsystem—for example monitoring, environmental instrumentation, or a cryogenic-support workflow—without assuming that Synqaro should implement high-frequency interferometer feedback control. Any use in ET would require engagement with its engineering teams, concrete subsystem requirements, and appropriate validation. **No ET partnership or adoption is implied.**

Such a demonstrator could be scientifically useful even without deployment in the operational detector: it would test whether a common control core and AI-native lifecycle transfer beyond radioastronomy without significant architectural burden.

### Other scientific and industrial systems

The same hypothesis may apply to laboratories, distributed test facilities, industrial automation, and other installations that integrate heterogeneous devices and require monitoring, coordinated operations, fault diagnosis, and long-term maintenance. Applicability must be demonstrated, not presumed. Where specialized real-time or certified safety controls exist, Synqaro should integrate with them rather than replacing them indiscriminately.

## 10. Technical case note: why the INAF radio telescopes need a new approach

*This section is deliberately application-specific. It explains the operational motivation for using Synqaro as a replacement path for existing radio-telescope control software; it is not the rationale for limiting Synqaro to radioastronomy.*

### Current situation

SRT, Medicina, and Noto currently use a radio-telescope control system built on **ALMA Common Software (ACS)**. The principal difficulty is not merely that ACS is old. It is that the existing engineering model imposes substantial framework-specific complexity on components whose device-facing logic can be relatively simple.

Even to run tests for one component, a developer may need to start the necessary virtual-machine environment, initialize ACS, start an ACS **container** (the framework process hosting the component), start the component, and only then execute the test. This is **not** a requirement to start the entire telescope control system: the burden is the framework runtime and its setup. ACS's use of the word *container* should not be confused with a modern deployment container such as Docker.

The system is costly to understand and change. Framework-specific code, aging dependencies, limited or outdated documentation, and manual integration procedures make onboarding slow and concentrate maintenance knowledge in a small group. Troubleshooting is especially difficult when a failure could originate in device firmware, communications, framework behavior, or application code built above it. Inadequate fault isolation and limited automatic regression coverage can allow incidents to recur or remain unresolved for long periods.

Crucially, the concern is **operational reliability**, not simply developer convenience. According to experience with these installations, shortcomings in the present design and testing process contribute to unreliable behavior and make it unnecessarily difficult to locate the cause of faults. The project should not portray the existing software as reliably controlling the telescopes simply because it is in use. At the same time, this document does not invent downtime statistics, incidents, or quantified defect rates that have not yet been provided.

### Why replacing the approach is worthwhile

For INAF, Synqaro could offer a different maintenance and assurance model:

- Components can be launched and tested independently, without the ACS-specific runtime sequence.
- Firmware and communication interfaces are treated as explicit, versioned contracts, shared with device-development groups.
- Simulators exercise both nominal operation and failure modes before changes touch telescope hardware.
- The same safe conformance tests can reveal regressions after firmware updates.
- Structured errors and correlated telemetry support fault localization through all layers.
- Automated build, integration, regression testing, and agent-assisted issue resolution become ordinary development practice rather than exceptional projects.
- Different telescopes can reuse interfaces and core mechanisms while retaining their own configurations, hardware adapters, and operational differences.
- Conversational assistance can help operators configure observing sessions, diagnose problems, inspect telemetry, and report incidents.

These changes target **reliability, maintainability, incident response, engineering effort, and the ability to evolve the software for decades**. They are not justified solely by replacing old technologies with newer ones.

### A controlled migration, not an uncontrolled replacement

The existing installation cannot simply be switched off while a replacement is developed. A credible plan would establish tested component contracts, validated simulation, isolated subsystem pilots, comparisons with real device behavior, hardware-in-the-loop testing where applicable, operational acceptance criteria, and appropriately staged deployment. Protective systems and observatory-specific safety procedures remain authoritative throughout.

For managers and technical teams, the value proposition is not a speculative software rewrite. It is **an opportunity to resolve persistent reliability and diagnosability problems while creating a reusable, testable engineering capability** whose benefits can extend to new devices, new staff, and potentially other facilities. The first prototypes should provide enough operational evidence to decide whether a broader migration is justified.

## 11. Decisions still open

Synqaro's architecture should not be treated as settled. Decisions to investigate include the internal communication protocol, programming languages, component lifecycle, event delivery, telemetry storage and retention, deployment topology, access control, domain orchestration primitives, detailed safety boundaries, configuration formats, simulator APIs, testing infrastructure, agent integration protocol, agent tool sandbox, repository governance, open-source licensing, and policies for automated code changes and deployment.

Especially important questions are **how small the core can remain**, which capabilities should be optional, how cross-domain portability can be demonstrated, and what evidence is required before granting agents more autonomy. These should be answered with prototypes and explicit technical trade-offs rather than assumptions.

## 12. Guidance for future AI reviewers and contributors

Treat this document as a **vision and preliminary requirements brief**, not an implementation specification. When evaluating Synqaro:

- Prioritize simplicity, independent testability, failure diagnosis, and verifiable safety.
- Challenge claims of universal applicability, automatic reliability, or assured AI superiority; propose practical demonstrations instead.
- Keep the generic core separate from domain-specific operational logic and specialized real-time systems.
- Do not reproduce ACS's architecture merely because legacy source code is available; recover required behaviors and interfaces.
- Prefer versioned contracts, simulator-backed conformance tests, and explicit error provenance over implicit coupling.
- Design AI as a capable, replaceable client and engineering participant, never as the sole safety authority.
- Treat firmware, control software, simulations, documentation, and tests as connected but separately governed assets.
- Do not write production code or commit to a stack before requirements and a small prototype justify the choice.
- Use the INAF telescopes as concrete validation opportunities, and ET or industrial scenarios as later portability experiments, without claiming partnerships or approvals.
- Identify both technical benefits and credible failure modes. Proposed advantages are hypotheses until demonstrated.

**Ultimate objective:** a small, robust, reusable control foundation plus an AI-native engineering and operational ecosystem that lets complex installations be developed, understood, extended, and maintained far more effectively across their lifetimes.
