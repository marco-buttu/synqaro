"""Validated startup configuration, independent of its inventory source."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
import re


def _identity(value: str, name: str) -> None:
    if (not isinstance(value, str) or not value or not value.isascii()
            or not value.isprintable() or not value.strip()):
        raise ValueError(f"{name} must be nonempty printable ASCII; provide a valid identity")


def _positive_integer(value: int, name: str) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive integer; choose a duration in milliseconds")


@dataclass(frozen=True)
class ReceiverConfig:
    """The supported protocol-v1 receiver profile and nominal simulator timing.

    Descriptor limits are fixed for this implemented profile. Identity and the
    grid-aligned startup value may vary. Nominal timings may vary within the
    advertised deadlines; they never define completion or progress by themselves.
    """

    protocol_version: int = 1
    hardware_id: str = "example-receiver-01"
    hardware_model: str = "fictitious_receiver"
    firmware_version: str = "0.1.0"
    firmware_build: str = "example-build"
    frequency_min: float = 1
    frequency_max: float = 10
    frequency_unit: str = "GHz"
    frequency_resolution: float = 0.000001
    frequency_rounding: str = "nearest_ties_up"
    max_message_bytes: int = 4096
    incomplete_message_timeout_ms: int = 2000
    max_pending_requests: int = 4
    max_tuning_ms: int = 1000
    calibrate_timeout_ms: int = 30000
    scan_timeout_ms: int = 20000
    procedure_stop_timeout_ms: int = 5000
    scan_points: int = 10
    scan_max_dwell_ms: int = 1000
    utc_clock_supported: bool = True
    initial_frequency: float = 5
    tuning_duration_ms: int = 100
    stop_duration_ms: int = 100
    calibrate_preparation_ms: int = 1000
    calibrate_measurement_ms: int = 8000
    calibrate_finalization_ms: int = 1000

    def __post_init__(self) -> None:
        for name in ("hardware_id", "firmware_version", "firmware_build"):
            _identity(getattr(self, name), name)

        fixed = {
            "protocol_version": 1,
            "hardware_model": "fictitious_receiver",
            "frequency_min": 1,
            "frequency_max": 10,
            "frequency_unit": "GHz",
            "frequency_resolution": 0.000001,
            "frequency_rounding": "nearest_ties_up",
            "max_message_bytes": 4096,
            "incomplete_message_timeout_ms": 2000,
            "max_pending_requests": 4,
            "max_tuning_ms": 1000,
            "calibrate_timeout_ms": 30000,
            "scan_timeout_ms": 20000,
            "procedure_stop_timeout_ms": 5000,
            "scan_points": 10,
            "scan_max_dwell_ms": 1000,
            "utc_clock_supported": True,
        }
        for name, expected in fixed.items():
            actual = getattr(self, name)
            if isinstance(expected, bool):
                valid = actual is expected
            elif isinstance(expected, int) and not name.startswith("frequency_"):
                valid = type(actual) is int and actual == expected
            elif isinstance(expected, (int, float)):
                valid = type(actual) in (int, float) and actual == expected
            else:
                valid = isinstance(actual, str) and actual == expected
            if not valid:
                raise ValueError(f"{name} is unsupported; use {expected!r} for this receiver profile")

        if type(self.initial_frequency) not in (int, float):
            raise ValueError("initial_frequency must be numeric; supply a frequency in GHz")
        initial = Decimal(str(self.initial_frequency))
        if not initial.is_finite() or not Decimal("1") <= initial <= Decimal("10"):
            raise ValueError("initial_frequency is out of range; choose 1 through 10 GHz")
        if initial % Decimal("0.000001") != 0:
            raise ValueError("initial_frequency is off grid; choose an exact 0.000001 GHz step")

        for name in ("tuning_duration_ms", "stop_duration_ms", "calibrate_preparation_ms",
                     "calibrate_measurement_ms", "calibrate_finalization_ms"):
            _positive_integer(getattr(self, name), name)
        if self.tuning_duration_ms > self.max_tuning_ms:
            raise ValueError("tuning_duration_ms exceeds its deadline; use at most 1000 ms")
        if self.stop_duration_ms > self.procedure_stop_timeout_ms:
            raise ValueError("stop_duration_ms exceeds its deadline; use at most 5000 ms")
        calibration_ms = (self.calibrate_preparation_ms + self.calibrate_measurement_ms
                          + self.calibrate_finalization_ms)
        if calibration_ms > self.calibrate_timeout_ms:
            raise ValueError("calibration exceeds its deadline; reduce its phase durations to total at most 30000 ms")
        if self.calibrate_finalization_ms < self.tuning_duration_ms:
            raise ValueError("calibration cannot restore frequency; allow at least tuning_duration_ms for finalization")


@dataclass(frozen=True)
class InstanceConfig:
    """One instance; port zero is reserved for direct test/server construction."""

    name: str
    model: str
    host: str
    port: int
    receiver: ReceiverConfig = field(default_factory=ReceiverConfig)

    def __post_init__(self) -> None:
        if (not isinstance(self.name, str)
                or re.fullmatch(r"[a-z][a-z0-9_-]{0,47}", self.name) is None
                or self.name == "all"):
            raise ValueError("invalid instance name; use 1–48 lowercase letters, digits, '_' or '-', starting with a letter, except 'all'")
        if self.model != "fictitious_receiver":
            raise ValueError("unsupported model; select 'fictitious_receiver'")
        if (not isinstance(self.host, str) or not self.host or not self.host.isascii()
                or any(character.isspace() or not character.isprintable()
                       for character in self.host)):
            raise ValueError("invalid host; provide an ASCII address or hostname without whitespace")
        if type(self.port) is not int or not 0 <= self.port <= 65535:
            raise ValueError("invalid port; choose an integer from 1 through 65535, or 0 for a direct test server")
        if not isinstance(self.receiver, ReceiverConfig):
            raise ValueError("invalid receiver configuration; provide a validated ReceiverConfig")


def validate_inventory(configs: Mapping[str, InstanceConfig]) -> dict[str, InstanceConfig]:
    """Return an independent mapping after validating inventory-wide constraints."""
    result = dict(configs)
    endpoints = set()
    for name, config in result.items():
        if not isinstance(config, InstanceConfig) or name != config.name:
            raise ValueError("inventory key does not match its instance; use the InstanceConfig.name as the key")
        if config.port == 0:
            raise ValueError("inventory port cannot be zero; choose a fixed port from 1 through 65535")
        endpoint = (config.host, config.port)
        if endpoint in endpoints:
            raise ValueError(f"duplicate endpoint {endpoint!r}; give each instance a unique host and port")
        endpoints.add(endpoint)
    return result
