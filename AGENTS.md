# Repository instructions

## Hardware development and integration

When asked to develop or integrate hardware, or change its contract or externally
visible behavior, first read and follow
[the hardware integration workflow](docs/hardware_integration_workflow.md).
Read its required references and the applicable hardware specifications before
asking specification questions, proposing a contract or implementing changes.
Do not rely on conversation history or remembered instructions.

Use the approved hardware contract as the reference for implementation, tests,
documentation and GUI operations. Keep unknowns and proposals distinct from
approved requirements. Follow the workflow's completeness and approval gates;
do not silently change a contract to match existing code.

Distinguish the team's operational needs from its proposed solutions. Preserve
Synqaro's simplicity and maintainability. Hardware-contract approval does not
authorize changes to the framework or shared protocol: those require a separate
proposal and maintainer approval as described in the workflow.

## Device development

Before designing, implementing or changing a Device public interface, read
[Device architecture](docs/device.md) and the agreed
[Device public interface](docs/device_public_interface.md), especially the agent
instructions and open questions. Read the applicable system conventions,
approved hardware contract, selected protocol and verification evidence. Propose
missing system conventions (including domain-specific UCUM units) for maintainer
approval. Do not promote illustrative schemas or unresolved questions to approved
requirements, change shared interfaces without approval, or invent hardware
capabilities. Keep the common interface minimal and model-specific behavior typed
and discoverable; verify it with independent tests.

## Development tests

From the repository root, run `bash install.sh --dev` to prepare the local
`.venv` without installing the application. Use `.venv/bin/pytest` for the full
suite or pass test paths to select a subset. The full suite includes real-browser
tests, which require installed Google Chrome; report any unavailable prerequisites
and do not treat skipped or unrun tests as successful verification. Existing
unittest test cases remain supported by pytest.
