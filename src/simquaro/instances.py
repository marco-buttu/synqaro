"""The initial explicit inventory; model and runtime code receive its output."""

from simquaro.config import InstanceConfig, validate_inventory
from simquaro.models.fictitious_receiver.config import ReceiverConfig


def load_inventory() -> dict[str, InstanceConfig]:
    return validate_inventory({
        "receiver-a": InstanceConfig(
            name="receiver-a",
            model="fictitious_receiver",
            host="127.0.0.1",
            port=9001,
            settings=ReceiverConfig(),
        ),
    })
