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
The [fictitious receiver contract](../contracts/models/fictitious_receiver.yaml),
revision 0.2, is approved; implementation migration remains tracked in
[issue #38](https://github.com/marco-buttu/synqaro/issues/38).
See the [first application and verification record](fictitious_receiver_contract_application.md).
The receiver-specific generator projects structured data; behavioral implementation
and independent test oracles remain explicit. This is not a generic generator for
other hardware models.

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
draft. On resuming work, check whether they have changed and revisit affected
decisions. A future agent integration must load the required instructions, guidance,
applicable schema and specifications before interviewing the team or proposing a
contract. If mandatory sources are missing, unreadable or conflicting, report the
problem and block the affected work until it is resolved. Do not substitute memory
for the current sources. `AGENTS.md` and a reading record alone do not enforce this
behavior.

## Interview the team

Start with the operational purpose: what the hardware must accomplish, what can be
measured or controlled, and whether the hardware and firmware already exist. Extract
known answers from the supplied material before asking questions.

Determine the required protocol independently of firmware release versions. If
firmware does not yet exist or compatibility has not been verified, leave the
contract's firmware version list empty rather than inventing a release or assuming
unrestricted compatibility. When compatible firmware already exists, prefer reuse
where identity, requirements and conformance evidence justify it. If the team
rejects reuse, ask for the reasons and assess whether they justify a replacement
(e.g. unmet requirements, reliability, licensing or maintainability); do not assume
that a new implementation is necessary. Record the decision and evidence. Add
verified compatible releases later through a reviewed contract revision. Contract
approval does not itself certify a firmware build or authorize production writes
to unverified hardware.

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

## Explore and verify existing hardware

For existing hardware, alternate the interview with early, targeted tests on the
real instrument. Do not wait for a supposedly final contract before gathering
evidence. Use this same cycle when a prototype becomes available. The cycle is:
read and ask, form a hypothesis, agree a test, observe, discuss and revise the draft.

### Prepare access and agree the test scope

Guide the team in making the selected instrument reachable from the agent's actual
execution environment through an authorized network path or local interface. Obtain
the endpoint/connection settings, protocol, hardware identity and firmware version.
Clarify availability, current configuration/state, other clients and any required
local operator. Keep credentials out of the contract and test logs. Reachability
alone does not identify the instrument or authorize commands.

Before sending traffic, agree and record the target and test scope with the team:
permitted operations, parameter ranges, rate/duration limits, relevant side effects,
stop conditions and how the team can interrupt work. Include connection/bootstrap
traffic generated by the chosen library, not just the commands in the test script.
Do not assume a read is harmless: some instruments clear counters, consume samples
or change state when read. Start with the least invasive agreed probes.

Writes, movement, calibration, reboot, fault injection and other disruptive work
must be explicitly covered by that scope and any required operating conditions.
Reuse authorization for tests within the agreed scope; ask again only when the
target, scope or relevant conditions change. Unexpected effects or uncertain
outcomes require stopping the affected probes and agreeing recovery with the team,
not blindly retrying commands or guessing a reset sequence.

This authorization permits preparation and execution of exploratory scripts/probes
before contract approval. It does not approve the draft or authorize production
firmware, simulator, library or GUI changes. Prefer existing tools; keep any new
probe code separate from production behavior, versioned and linked to its evidence.
Framework or shared-protocol extensions still need separate maintainer approval.

### Probe, compare and refine

1. Select a question or suspected discrepancy. State the expected behavior and its
   source as a hypothesis, together with what the probe can and cannot establish.
2. Execute a bounded probe within the agreed scope. Record the target and firmware,
   initial configuration/state, concurrent activity, tool/script revision, exact
   requests and responses, timing provenance, observed effects and errors. A reply
   reporting success is not by itself proof of a physical effect; use independent
   measurements or operator observations where that distinction matters.
3. Compare the result with the documentation and the team's explanation. Discuss
   mismatches instead of automatically changing the expected result. A mismatch may
   be a firmware defect, a misunderstood requirement, an undocumented behavior or
   a problem in the probe/environment.
4. Update the draft and source evidence, record the team's decisions and outstanding
   questions, then choose the next targeted probe. Expand to further scenarios or a
   full test suite only when its actions and prerequisites fit the authorized scope.

For each investigated behavior, keep these distinctions in the evidence record:

| Kind | Meaning |
| --- | --- |
| Declared | What a versioned specification or the team says should happen. |
| Observed | What a particular probe demonstrated on identified hardware/firmware under recorded conditions. |
| Agreed | What the team decides the contract should require after reviewing the evidence. |

An observed quirk is not automatically a requirement or a guarantee across firmware
versions, configurations or repeated runs. Record unresolved discrepancies and
untested assumptions explicitly. Link versioned evidence through the contract's
`sources` and requirement references; these distinctions describe the evidence,
not new schema fields or additional approval states. Never convert observations
directly into test expectations without reviewing their intended meaning.

If access is unavailable or the agent cannot execute probes, explain the limitation
and guide the team through the agreed local test procedure. Team-run results must
be identified as such. Mark untested claims as unverified; simulator results do not
substitute for real-hardware evidence. The fictitious receiver has no real instrument
to probe, so record that fact rather than claiming physical verification.

The approved contract is a versioned reference, not an immutable first attempt.
Further evidence can reopen a question and produce a proposed revision. Keep the
currently approved revision distinct from that draft and apply the approval process
below before changing production behavior. Exploration is also possible against
an existing approved baseline; new observations do not silently supersede it.

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
- For existing hardware, exploratory results and their conditions are linked;
  discrepancies, access limitations and untested behavior are explicit. Decide
  with the team which gaps block approval and which are accepted limitations or
  exclusions; do not claim verification that has not occurred.
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
remain deferred. Hardware-team approval covers the exact contract revision and scope;
maintainer approval covers the separate framework or shared-protocol proposal. Neither
substitutes for the other, even when the same person holds both roles. Do not adapt
production implementation, behavioral tests or GUI before the applicable approvals.
Separately authorized [exploratory probes and scripts](#explore-and-verify-existing-hardware)
may precede contract approval to gather evidence; their results are not themselves
approval.

The future agent integration must enforce these gates at its action boundaries:
check the approver's authority, revision, scope and evidence; reject missing, stale
or out-of-scope approvals; and keep independent authorized work possible. Tests must
exercise actual context loading and attempted approval bypasses, including resumed
sessions and separately authorized exploratory work. Implementation and testing are
follow-up work from [issue #38, section 6](https://github.com/marco-buttu/synqaro/issues/38#6-specify-requirements-for-future-agent-integration),
not capabilities provided by this workflow or the schema validator.

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

For the current fictitious receiver, the [approved contract](../contracts/models/fictitious_receiver.yaml)
revision 0.2 is the receiver-specific behavioral reference, together with the shared
rules in [Hardware Protocol](hardware_protocol.md). Its approval is recorded in
[the review](fictitious_receiver_contract_review.md#formal-approval). Implementation and GUI/test adaptation are tracked in section 5 of issue #38;
see the [application record](fictitious_receiver_contract_application.md) for
actual verification results and remaining limitations. Approval does not establish
implementation conformance.
