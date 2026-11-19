# Hardware integration workflow

This guide tells a development agent how to turn a team's hardware requirements
into an approved contract. Use it for hardware to be built, existing hardware to
integrate, and changes to an existing contract or externally visible behavior.

The team should not need to understand Synqaro's implementation or write a contract
file. The agent reads the available evidence, asks focused questions, records the
answers and presents a readable proposal for approval.

## Contract-driven development

The approved contract defines what the hardware must do and how software can
interact with it. Firmware, simulator, communication library, tests, documentation
and GUI operations must follow that contract. Existing code is evidence of current
behavior, not authority to redefine the expected behavior.

Keep three complementary parts in the contract:

| Part | Content | Intended use |
| --- | --- | --- |
| Structured definitions | Properties, types, units, access permissions, procedure parameters, constraints and error identifiers | Drive standard GUI controls, validation and applicable generated checks |
| Behavioral requirements | Preconditions, effects, state transitions, timing, concurrency and failure behavior | Guide implementation and define what correctness means |
| Verification scenarios | Initial conditions, requests or injected faults, expected responses and observable final state | Guide conformance and regression tests |

Give requirements stable references so implementations, tests and explanatory
documentation can point to them. Reference the chosen protocol rather than copying
its rules. Keep the reasons for important choices alongside the requirements.

A GUI should not discover public operations by guessing from internal Python
methods. Tests should not derive expected outcomes from the implementation they
are testing. Generated checks can verify shared definitions; independent behavioral
tests must still detect mistakes in generators or shared interpretations. Complex
behavior can be described in precise prose and scenarios rather than encoded in a
new programming language.

An unsuccessful test may reveal an implementation defect, an incorrect test or an
ambiguous, incomplete or wrong contract. Investigate the disagreement; do not simply
change the expected result to match the code.

## Current status and required reading

This workflow is a repository instruction, not an implemented agent platform.
The [versioned schema and authoring validator](../contracts/README.md) are available.
Migration of the fictitious receiver remains later work in
[issue #38](https://github.com/marco-buttu/synqaro/issues/38).
Do not claim that current code, tests or GUI are already generated from one contract.

At the start of an integration, read:

1. This workflow and the applicable repository instructions in `AGENTS.md`.
2. [The hardware-contract introduction](hardware_contract.md) and
   [the README overview](../README.md#overview), for the user's workflow and the
   distinction between hardware, Devices and orchestration.
3. The [contract format and validation instructions](../contracts/README.md) and
   [schema version 1](../contracts/schema-v1.json), or the applicable later schema
   when introduced. If a required version is unavailable, record that limitation;
   do not substitute another version silently or claim validation against a missing file.
4. The hardware team's specifications, existing approved contract and amendments,
   model/firmware identities, interface documentation and relevant issue decisions.
   Record the version or revision of each source used. For an existing model, review
   its implementation and test evidence to identify discrepancies, not to invent
   requirements from code.
5. The selected protocol specification. For new hardware, propose Synqaro's
   [default hardware protocol](hardware_protocol.md) and assess its suitability.
   For existing firmware, read its actual protocol; adoption of the default protocol
   is not a prerequisite for integration.

Read relevant architecture documents when a requirement crosses an architectural
boundary. [Project Vision](project_vision.md) provides rationale, but is explicitly
a proposal; do not treat its unapproved technology choices as implemented guarantees.
When sources disagree, record the conflict and obtain a decision rather than
silently choosing whichever source matches the code.

Record the documents and revisions actually consulted in the integration issue or
draft. On resuming work, check whether they have changed. A future agent integration
must implement and test loading these instructions at workflow entry; `AGENTS.md`
and this reading record alone do not enforce that behavior.

## Interview the team

Start with the operational purpose: what the hardware must accomplish, what can be
measured or controlled, and whether the hardware and firmware already exist. Extract
known answers from the supplied material before asking questions.

Use the following topics as a completeness checklist, not a questionnaire to send
all at once. Ask one focused question at a time, explain why it matters when needed,
and follow the relevant branches. Accept a documented, justified “not applicable”.

| Topic | Questions and conditional follow-ups |
| --- | --- |
| Identity and scope | Which hardware model and firmware versions are covered? Which variations are instance configuration, and which change the behavior or compatibility? |
| Physical interface and firmware | For hardware to be built, which board, interfaces and resources must the firmware use? For existing hardware, what is documented, observed or unavailable? |
| Communication | Which transport, framing and protocol apply? How are requests correlated? What happens on invalid, incomplete or oversized input, timeout and loss of connection? Reuse protocol rules already defined. |
| Properties | What can be read, and what can also be written? What are the type, unit, range, resolution and approximation policy? When is a value unavailable or invalid? Does a successful write mean it has actually been applied? |
| Measurements and time | When was a value sampled? Can it be cached or stale? How is clock reliability reported? If values must be associated with acquired data, what guarantees that association? |
| Procedures | What are the parameters, preconditions, effects and observable states? If execution is long, how are acceptance, completion, failure and progress distinguished? What are the maximum durations? |
| Cancellation | If cancellation is supported, in which phases? What remains after cancellation? How are completion races and failure to stop reported? |
| Concurrency | Which operations may overlap? What happens when clients request conflicting changes? Who can inspect or cancel work, and what survives disconnection? |
| Startup and persistence | What are the initial state and readiness criteria? What happens on reboot, power loss or firmware change? Which settings and procedure outcomes survive, and how is a new boot identified? |
| Errors and recovery | How are invalid requests, communication failures and hardware failures distinguished? What remains usable after a failure? When is an outcome unknown, and when is retry safe or forbidden? |
| Configuration | Which capabilities and limits come from the hardware, and which require a local fallback? Which settings may change live, persist or require restart? How is the effective configuration traced? |
| Protection and access | What can damage equipment or interrupt work? Which protections must be independent of Synqaro? Who may modify settings or run disruptive procedures, including during verification? |
| Verification | What demonstrates success, boundary behavior and failure handling? Which faults can be simulated, and which checks require real hardware or special authorization? |

For example, “calibration can be cancelled” is incomplete. Ask whether every phase
can be interrupted, what state and readable values remain afterwards, and what is
reported if stopping fails. Each answer should become a requirement or an explicit
open question, not remain only in the conversation.

If a new topic is discovered, propose an update to this guide and the applicable
checks so future integrations benefit. A checklist cannot anticipate every hardware
detail; it must not be used to dismiss a relevant requirement outside its headings.

## Assess fit before accepting a solution

Perform this assessment during the interview and before including a requirement in
the contract proposed for approval. Revisit it when the requirement or its evidence
changes. Record the result in the integration issue or draft, rather than leaving it
only in the conversation. Keep routine assessments short; a supported requirement
does not need a separate architecture proposal.

### Establish the need and locate the limitation

1. State the operational outcome independently of the team's proposed solution.
   Include measurable acceptance conditions where relevant, such as timing,
   accuracy or failure behavior. If these are unknown, ask rather than inventing them.
2. Check existing capabilities, supported configuration and model-specific adapters
   against that outcome. Cite the relevant specification revision and implementation
   or test evidence. Distinguish documented guarantees, observed behavior and
   unverified assumptions: an implemented feature is not proof of every guarantee.
3. If there is a gap, identify its source using the table below. More than one source
   may apply. If the cause is uncertain, record the missing evidence and how to obtain
   it; do not present an architectural extension as the established solution.

| Source of limitation | What to establish | Consequence |
| --- | --- | --- |
| Hardware | Does the physical design or existing firmware support the required capability? | Software cannot promise a physical capability that the hardware lacks. Clarify hardware changes or a feasible alternative with the team. |
| Communication protocol | Does the selected protocol express the operation and provide the required guarantees? | Consider an existing suitable interface or a proposal to extend the protocol; do not invent wire behavior silently. |
| Current implementation | Does an approved contract already require behavior that the code lacks or implements incorrectly? | Treat it as an implementation gap or defect. A correction within the approved scope does not require a new contract; any necessary framework change still follows maintainer approval. |
| Deliberate architectural constraint | Which approved decision establishes the boundary, and why? | Assess the rationale and alternatives. A constraint is neither automatically negotiable nor immutable; changing it requires an explicit maintainer decision. |

Do not mistake an unapproved vision document or an implementation detail for a
deliberate architectural constraint. Do not weaken the operational requirement
silently to make it fit an existing implementation.

### Compare alternatives and make a recommendation

Consider reuse of existing capabilities first, then a model-specific implementation
within existing interfaces, then changes to shared mechanisms where justified.
Compare the viable alternatives, not a fixed number of artificial options. Include
deferring or declining the unsupported requirement when no acceptable solution exists.

For each viable option, explain:

- Whether it meets the operational need and which limitations remain.
- Which contracts, hardware models, clients and existing deployments it affects,
  including compatibility and migration consequences.
- What complexity it adds: dependencies, configuration, duplicated behavior,
  abstractions, failure modes and operational steps.
- How a user would operate and diagnose it, and how developers and agents would
  understand, test and maintain it over time.
- Which verification scenarios and resources would establish its guarantees.

Recommend the smallest sufficient solution and explain the trade-off. Challenge a
request whose maintenance or usability cost is disproportionate to its benefit,
even when the team asks for it explicitly. Being able to generate the code quickly
is not evidence that the resulting system will be simple to maintain. Conversely,
do not reject a justified extension merely because the current system lacks it.

### Record the decision and control dependencies

Use a short assessment record containing: requirement reference, operational need,
proposed solution, evidence and gaps, limitation source, alternatives and impacts,
recommendation, decision status and rationale. Link it from the draft rather than
duplicating it in several documents. Record who decided, when and the exact scope;
until the appropriate person decides, the recommendation remains a proposal.

For a framework or shared-protocol change, create a separate linked proposal for
maintainers before implementation. Include benefits, costs, alternatives, affected
contracts, compatibility consequences and the verification plan. Record explicit
maintainer approval of its revision and scope. Hardware-team contract approval does
not replace this decision, even if the same person performs both roles. If no
maintainer decision is available, pause the dependent work and continue independent
work within the approved scope.

Mark each affected draft requirement as depending on that proposal. Distinguish
**awaiting approval**, **approved but not implemented/verified**, **available with
evidence**, and **rejected or deferred**. Approval alone does not make a capability
available. Unapproved dependencies block the affected implementation scope; an
approved extension may be developed within its authorized scope, but must be
implemented and verified before the dependent capability is advertised as available.
If the extension is rejected or deferred, agree an alternative or explicit scope
exclusion with the team; do not quietly remove its need or claim it is satisfied.

For example, a team may propose more timestamp digits to associate scientific data
with frequency during a scan. First establish the required association accuracy.
The [current protocol's open issues](hardware_protocol.md#associating-scan-data-with-frequency)
explain why finer timestamp resolution alone does not guarantee that association.
Assess synchronization or coordinated acquisition against the actual need; neither
is implicitly approved or supplied by the current receiver. Record any proposed
extension and its approval dependency before promising the capability.

## Draft, review and approve

Maintain a versioned draft in the repository and link it from the integration issue.
Use the applicable schema and label the draft's revision and validation limits.
For each requirement or decision, retain its source, rationale where significant,
and status: proposed, confirmed by the team, not applicable with a reason, or open.
Confirmed answers contribute to the draft; they are not approval of the whole contract.

For each open item record the question or conflict, its impact, who must resolve it
and which work depends on it. Do not substitute defaults or assumptions for missing
hardware specifications. Technical proposals must be visibly labeled as proposals.

Before presenting the contract for approval, check:

- All applicable interview topics have been addressed; exclusions have reasons.
- Properties and procedures have observable outcomes, failure behavior and timing
  where relevant, not only names and parameter types.
- Scenarios cover normal use, boundaries, malformed input, hardware faults,
  conflicting operations and interruption/reconnection where applicable.
- Contradictory sources and unapproved architectural dependencies are resolved or
  explicitly excluded from the proposed implementation scope.
- Available schema and consistency checks pass, and their results are recorded.
  If checks cannot be run, record the reason and resolve it before declaring the
  contract validated; manual review alone is not automated validation.
- A semantic review checks whether the requirements are meaningful and complete.
  Passing a schema validator cannot replace this review.

Present a readable summary of behavior, important choices and their reasons,
limitations, exclusions and verification scenarios. Link the exact draft revision
and request explicit team approval. Record who approved it, when, the approved
revision/scope and the approval evidence in the issue or review. Do not infer
approval from silence or from passing tests.

Approval authorizes implementation against that scope. Unresolved requirements
affecting it block implementation; unrelated, explicitly excluded capabilities may
remain deferred. Hardware-team approval and maintainer approval of framework or
shared-protocol changes are separate decisions, even when the same person holds
both roles. Do not adapt implementation, behavioral tests or GUI to a new contract
before the applicable approvals.

## Implement and manage changes

After approval, implement against the contract and link test scenarios and generated
artifacts to its revision and requirement references. Derive standard GUI operations,
applicable validations and checks from the structured definitions as that support is
implemented. Document any remaining manually maintained parts and check them for drift.

If development or verification reveals a substantive change, describe the difference
from the approved contract, its reason, compatibility impact and affected scenarios.
Update the draft and obtain approval of that change before implementing the changed
behavior. Reuse unchanged approvals; corrections that restore already specified
behavior do not require approval of a new contract. Keep the contract, implementation,
tests and reference documentation consistent in the delivered change.

Record verification results and limitations. Simulator conformance does not prove
physical-hardware behavior; identify the checks still needed on real equipment.

For the current fictitious receiver, the approved behavioral specification remains
in [Hardware Protocol](hardware_protocol.md). The structured-contract migration and
GUI/test adaptation are later steps of issue #38 and require the agreed contract
review; this workflow does not approve a replacement contract.
