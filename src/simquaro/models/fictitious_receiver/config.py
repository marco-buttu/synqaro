"""Validated settings for the fictitious receiver."""

from dataclasses import dataclass
from decimal import Context, Decimal, localcontext

from synqaro_protocol.profiles._receiver_contract_data import DATA

_DESCRIPTOR = DATA["descriptor"]


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

    protocol_version: int = _DESCRIPTOR["protocol_version"]
    hardware_id: str = "example-receiver-01"
    hardware_model: str = _DESCRIPTOR["hardware_model"]
    firmware_version: str = "0.1.0"
    firmware_build: str = "example-build"
    frequency_min: float = _DESCRIPTOR["frequency_min"]
    frequency_max: float = _DESCRIPTOR["frequency_max"]
    frequency_unit: str = _DESCRIPTOR["frequency_unit"]
    frequency_resolution: float = _DESCRIPTOR["frequency_resolution"]
    frequency_rounding: str = _DESCRIPTOR["frequency_rounding"]
    max_message_bytes: int = _DESCRIPTOR["max_message_bytes"]
    incomplete_message_timeout_ms: int = _DESCRIPTOR["incomplete_message_timeout_ms"]
    max_pending_requests: int = _DESCRIPTOR["max_pending_requests"]
    max_tuning_ms: int = _DESCRIPTOR["max_tuning_ms"]
    calibrate_timeout_ms: int = _DESCRIPTOR["calibrate_timeout_ms"]
    scan_timeout_ms: int = _DESCRIPTOR["scan_timeout_ms"]
    procedure_stop_timeout_ms: int = _DESCRIPTOR["procedure_stop_timeout_ms"]
    scan_points: int = _DESCRIPTOR["scan_points"]
    scan_max_dwell_ms: int = _DESCRIPTOR["scan_max_dwell_ms"]
    utc_clock_supported: bool = _DESCRIPTOR["utc_clock_supported"]
    initial_frequency: float = 5
    tuning_duration_ms: int = 100
    stop_duration_ms: int = 100
    calibrate_preparation_ms: int = 1000
    calibrate_measurement_ms: int = 8000
    calibrate_finalization_ms: int = 1000

    def __post_init__(self) -> None:
        for name in ("hardware_id", "firmware_version", "firmware_build"):
            _identity(getattr(self, name), name)

        fixed = {name: expected for name, expected in _DESCRIPTOR.items()
                 if name in self.__dataclass_fields__}
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
        if not initial.is_finite() or not Decimal(str(self.frequency_min)) <= initial <= Decimal(str(self.frequency_max)):
            raise ValueError(f"initial_frequency is out of range; choose {self.frequency_min} through {self.frequency_max} {self.frequency_unit}")
        # In-range int/float decimal spellings fit exactly within 32 digits.
        # The caller's precision, exponent limits, and traps cannot change validation.
        with localcontext(Context(prec=32)):
            off_grid = initial % Decimal(str(self.frequency_resolution)) != 0
        if off_grid:
            raise ValueError(f"initial_frequency is off grid; choose an exact {self.frequency_resolution:.6f} {self.frequency_unit} step")

        for name in ("tuning_duration_ms", "stop_duration_ms", "calibrate_preparation_ms",
                     "calibrate_measurement_ms", "calibrate_finalization_ms"):
            _positive_integer(getattr(self, name), name)
        if self.tuning_duration_ms > self.max_tuning_ms:
            raise ValueError(f"tuning_duration_ms exceeds its deadline; use at most {self.max_tuning_ms} ms")
        if self.stop_duration_ms > self.procedure_stop_timeout_ms:
            raise ValueError(f"stop_duration_ms exceeds its deadline; use at most {self.procedure_stop_timeout_ms} ms")
        calibration_ms = (self.calibrate_preparation_ms + self.calibrate_measurement_ms
                          + self.calibrate_finalization_ms)
        if calibration_ms > self.calibrate_timeout_ms:
            raise ValueError(f"calibration exceeds its deadline; reduce its phase durations to total at most {self.calibrate_timeout_ms} ms")
        if self.calibrate_finalization_ms < self.tuning_duration_ms:
            raise ValueError("calibration cannot restore frequency; allow at least tuning_duration_ms for finalization")
