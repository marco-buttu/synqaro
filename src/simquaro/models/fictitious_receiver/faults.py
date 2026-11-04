"""Receiver fault causes and phase hooks; scheduling stays generic."""

from simquaro.faults import FaultController, FaultDefinition, Scenario


RECEIVER_DEFINITIONS = tuple(FaultDefinition(name, True, effect) for name, effect in (
    ("calibration_reference_unavailable", "The physical calibration reference is unavailable; normal diagnostics and calibration fail accordingly."),
    ("frequency_lock_failure", "The synthesizer cannot verify the requested frequency lock; tuning must report FREQUENCY_LOCK_FAILED."),
    ("synthesizer_failure", "The physical synthesizer fails; normal diagnostics report SYNTHESIZER_FAILURE."),
    ("frequency_read_failure", "Reading the physical frequency fails; firmware reports FREQUENCY_READ_FAILED without inventing a value."),
    ("clock_untrusted", "UTC is untrusted; firmware reports CLOCK_UNTRUSTED and omits new UTC timestamps."),
    ("procedure_stall", "Firmware procedure advancement stalls without blocking the event loop; normal deadlines still apply."),
    ("stop_unconfirmed", "Physical activity continues despite a stop request; firmware cannot confirm a controlled stop."),
))


def receiver_faults(scenario: Scenario = Scenario()) -> FaultController:
    return FaultController(
        scenario, definitions=RECEIVER_DEFINITIONS,
        events=("response_ready", "frequency_set_verified", "calibrate_reference_measurement"),
        delivery_events=("response_ready", "frequency_set_verified"))
