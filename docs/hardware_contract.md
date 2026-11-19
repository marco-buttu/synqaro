# Define the hardware contract

Provide Synqaro’s development agent with a description of your hardware: what it must do, what can be controlled or measured, and any operating limits. Include existing technical documentation when available.

**If the hardware has not been developed yet**, the agent will introduce Synqaro’s [proposed communication protocol](hardware_protocol.md) and help you define how to use it for your hardware. Once its behavior, electronic platform, and physical interfaces are specified, the agent will write the firmware needed to command and monitor it through that protocol. The firmware must then be verified on the real hardware.

**If the hardware already exists**, provide its documentation and communication protocol. Integration can use the existing firmware without requiring it to adopt Synqaro’s protocol.

The agent will help you make the instrument reachable and agree which tests it may
perform. Early probes on the real hardware help clarify misunderstandings while the
contract is still a draft: the agent compares results with your explanations and the
documentation, discusses discrepancies with you and refines the contract. Permission
to run these exploratory tests is separate from contract approval; disruptive
operations must be explicitly included in the agreed test scope. If real-hardware
tests cannot be performed, the missing evidence remains visible.

What was documented, what was observed and what you agree the instrument should do
remain distinct. An observed behavior may be a firmware defect, not a requirement.
The approved contract is a versioned reference that can be revised as new evidence
emerges, rather than a document assumed to be final after the first conversation.

The agent reads the available specifications, asks for missing information and prepares a contract for you to review and approve. The approved contract is the reference for firmware, simulator, communication library, tests, documentation and GUI operations. Changes to that behavior must be reflected in the contract and approved before implementation.

The [hardware integration workflow](hardware_integration_workflow.md) defines the agent's required reading, questions, completeness review and approval process. It also explains how to handle requirements that would change Synqaro itself. Such changes require separate maintainer approval; they are not automatically authorized by approving a hardware contract.

The [contract format and authoring checks](../contracts/README.md) are available now. They validate structure and selected consistency rules, not semantic completeness or approval. The receiver contract and contract-driven GUI remain subsequent steps tracked in [issue #38](https://github.com/marco-buttu/synqaro/issues/38).

Instructions for interacting with the agent will be added when that interface is available.

Next: [implement and verify hardware communication](getting_started.md), using a fictitious receiver as an example.
