"""Receiver-specific diagnostic definitions and bounded rendering."""

from functools import partial
from types import MappingProxyType

from synqaro_protocol.errors import ErrorDefinition, ERROR_CATALOG as COMMON_ERRORS
from synqaro_protocol.errors import render_error as _render_error


_DEFINITIONS = (
    ErrorDefinition("FREQUENCY_LOCK_FAILED", "The synthesizer did not reach and verify the requested frequency within its allowed time", (), "Read frequency and general status before deciding the next operation."),
    ErrorDefinition("FREQUENCY_READ_FAILED", "The synthesizer frequency could not be read reliably", (), "Inspect synthesizer diagnostics before relying on a frequency value."),
    ErrorDefinition("CALIBRATION_REFERENCE_UNAVAILABLE", "The calibration reference is unavailable", (), "Restore the calibration reference and inspect the retained procedure outcome."),
    ErrorDefinition("CALIBRATION_TIMEOUT", "Calibration exceeded its execution deadline", (), "Inspect procedure and stop status before starting further work."),
    ErrorDefinition("SCAN_TIMEOUT", "The scan exceeded its execution deadline", (), "Inspect procedure and stop status before starting further work."),
    ErrorDefinition("SYNTHESIZER_FAILURE", "Diagnostics confirm a synthesizer fault", (), "Resolve the synthesizer fault and verify its diagnostics."),
)
ERROR_CATALOG = MappingProxyType({
    **COMMON_ERRORS, **{definition.code: definition for definition in _DEFINITIONS}})
render_error = partial(_render_error, catalog=ERROR_CATALOG)
