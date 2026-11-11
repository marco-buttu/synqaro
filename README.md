# synqaro
Synqaro is a framework for controlling and monitoring complex systems, with AI agents helping develop, test, and maintain the control system.

## Overview

Synqaro represents each hardware unit through a software component called a **Device**. A Device communicates with its hardware and exposes its commands, measurements, and current state through a documented interface.

Devices can be coordinated to operate a subsystem—for example, several servomechanisms working together to position a receiver. Higher-level orchestrations can then coordinate multiple subsystems to prepare and operate the complete installation.

These coordination layers are added where needed: a Device can also be used independently, without requiring a hierarchy of managers.

Synqaro’s development approach is **bottom-up and AI-driven**: it starts with integrating individual hardware units, then builds the coordination and user interfaces needed to operate the system. AI agents carry out development work at the user’s request, against agreed specifications and explicit acceptance criteria.

### Development workflow

1. **Define the hardware contract.** Hardware developers work with Synqaro’s development agent to define the specifications for hardware to be built, or clarify the behavior of existing hardware. The contract covers commands, measurements, states, timing, errors, and operating constraints.

2. **Implement and verify hardware communication.** At the user’s request, the agent develops the firmware where applicable, a hardware simulator, reusable communication libraries, and automated tests. The user explores the simulator through a GUI, while automated tests systematically exercise the specified behavior and failure scenarios. Tests are checked against the agreed contract; real firmware and hardware are also verified when available and safe to test.

3. **Implement the Device.** The agent builds the Device using the communication libraries and verifies its commands, state handling, and error reporting. The Device can be exercised independently against the simulator and, subsequently, the real hardware.

4. **Add coordination where needed.** The agent implements or extends the software that coordinates the Device with other Devices and subsystems, according to the user’s operational requirements.

5. **Create or extend user interfaces.** The agent develops the graphical interfaces requested by the user, supporting both operational tasks and technical diagnostics.

Existing firmware does not have to adopt Synqaro’s proposed hardware protocol. When it uses another protocol, a dedicated adapter handles communication, and the simulator reproduces that existing interface. The Device still exposes a consistent interface to the rest of Synqaro, keeping hardware-specific protocols out of higher-level coordination logic.

## Installation

### Download and install

1. [Download Synqaro](https://github.com/marco-buttu/synqaro/archive/refs/heads/main.zip).
2. Extract the ZIP archive, open a terminal in the extracted folder, and run:

   ```sh
   bash install.sh
   ```

### Remove

Open a terminal in the same extracted folder and run:

```sh
bash uninstall.sh
```

Your configuration is preserved. To remove it as well, run:

```sh
bash uninstall.sh --purge
```

The script asks for confirmation before deleting configuration files.

## Documentation

### Project

- [Project Vision](docs/project_vision.md)
- [AI Project Context](docs/ai_project_context.md)

### Architecture

- [Hardware Protocol](docs/hardware_protocol.md)
- [Device Architecture](docs/device.md)

### Development and testing

Inside the repository's Python 3.12+ virtual environment:

```sh
.venv/bin/python -m pip install -e '.[web]'
.venv/bin/simquaro gui
```

First-time setup and browser walkthrough:

- [Getting started](docs/getting_started.md)
- [Simquaro operator guide](docs/simquaro.md)
