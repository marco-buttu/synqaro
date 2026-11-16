# Define the hardware contract

Provide Synqaro’s development agent with a description of your hardware: what it must do, what can be controlled or measured, and any operating limits. Include existing technical documentation when available.

**If the hardware has not been developed yet**, the agent will introduce Synqaro’s [proposed communication protocol](hardware_protocol.md) and help you define how to use it for your hardware. Once its behavior, electronic platform, and physical interfaces are specified, the agent will write the firmware needed to command and monitor it through that protocol. The firmware must then be verified on the real hardware.

**If the hardware already exists**, provide its documentation and communication protocol. Integration can use the existing firmware without requiring it to adopt Synqaro’s protocol.

The agent will ask for missing information and prepare a specification for you to review and approve. This specification becomes the reference for firmware, simulator, communication library, and tests.

Instructions for interacting with the agent will be added when that interface is available.

Next: [implement and verify hardware communication](getting_started.md), using a fictitious receiver as an example.
