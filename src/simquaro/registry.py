"""Explicit composition table: add a model here, not in protocol or runtime."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from synqaro_protocol.errors import ErrorDefinition
from simquaro.faults import FaultController, Scenario
from simquaro.model import SimulatorModel
from simquaro.models.fictitious_receiver.config import ReceiverConfig
from synqaro_protocol.profiles.fictitious_receiver import ERROR_CATALOG
from simquaro.models.fictitious_receiver.faults import receiver_faults
from simquaro.models.fictitious_receiver.model import FictitiousReceiverSimulator
from simquaro.models.fictitious_receiver.checks import CHECKS, client_factory


@dataclass(frozen=True)
class ModelDefinition:
    config_type: type
    factory: Callable[..., SimulatorModel]
    fault_factory: Callable[[Scenario], FaultController]
    error_catalog: Mapping[str, ErrorDefinition]
    config_key: str
    client_factory: Callable | None = None
    checks: tuple = ()
    editable_settings: tuple[str, ...] = ()


MODELS = {
    "fictitious_receiver": ModelDefinition(
        ReceiverConfig, FictitiousReceiverSimulator, receiver_faults,
        ERROR_CATALOG, "receiver", client_factory, CHECKS,
        ("hardware_id", "firmware_version", "firmware_build", "initial_frequency",
         "tuning_duration_ms", "stop_duration_ms", "calibrate_preparation_ms",
         "calibrate_measurement_ms", "calibrate_finalization_ms")),
}


def get_model(name: str) -> ModelDefinition:
    if not isinstance(name, str) or name not in MODELS:
        raise ValueError("unsupported model; select a name from the explicit model registry")
    return MODELS[name]
