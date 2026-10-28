"""The initial explicit inventory; model and runtime code receive its output."""

from simquaro.config import InstanceConfig, ReceiverConfig, validate_inventory


def load_inventory() -> dict[str, InstanceConfig]:
    return validate_inventory({
        "receiver-a": InstanceConfig(
            name="receiver-a",
            model="fictitious_receiver",
            host="127.0.0.1",
            port=9001,
            receiver=ReceiverConfig(),
        ),
    })
