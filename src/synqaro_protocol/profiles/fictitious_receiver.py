"""Explicit fictitious-v1 client contract and shared receiver diagnostics."""

from datetime import datetime
from decimal import Context, Decimal, InvalidOperation, localcontext
import re
from synqaro_protocol.codec import NumericToken
from synqaro_protocol.client import LocalFailure, ClientContract

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

def _descriptor(response, expected_id):
    """Validate only the supported fixed receiver contract, with no fallback."""
    fields = response.fields
    literals = {
        "name": "configuration", "hardware_id": expected_id, "hardware_model": "fictitious_receiver",
        "frequency_unit": "GHz", "frequency_rounding": "nearest_ties_up",
        "calibrate_cancellation": "except_finalization", "scan_cancellation": "always",
        "utc_clock_supported": True,
    }
    integers = {
        "protocol_version": "1", "max_message_bytes": "4096", "incomplete_message_timeout_ms": "2000",
        "max_pending_requests": "4", "max_tuning_ms": "1000", "calibrate_timeout_ms": "30000",
        "scan_timeout_ms": "20000", "procedure_stop_timeout_ms": "5000", "scan_points": "10",
        "scan_max_dwell_ms": "1000",
    }
    numbers = {"frequency_min": "1", "frequency_max": "10", "frequency_resolution": "0.000001"}
    lists = {"readonly_properties": ["configuration"], "readwrite_properties": ["frequency"],
             "supported_procedures": ["calibrate", "scan"], "sampled_at_properties": ["frequency"]}
    valid = response.verb == "ok"
    valid &= all(type(fields.get(key)) is type(value) and fields.get(key) == value for key, value in literals.items())
    valid &= all(isinstance(fields.get(key), NumericToken) and len(fields[key].text) <= 64
                 and re.fullmatch(r"[0-9]+", fields[key].text) is not None
                 and int(fields[key].text) == int(value)
                 for key, value in integers.items())
    for key, expected in numbers.items():
        value = fields.get(key)
        # Bounded spelling/capacity before Decimal prevents giant exponent work.
        try:
            valid &= (isinstance(value, NumericToken) and len(value.text) <= 64
                      and abs(Decimal(value.text).adjusted()) <= 20 and Decimal(value.text) == Decimal(expected))
        except InvalidOperation:
            valid = False
    valid &= all(isinstance(fields.get(key), list) and len(fields[key]) == len(value)
                 and all(isinstance(item, str) for item in fields[key])
                 and sorted(fields[key]) == sorted(value) for key, value in lists.items())
    valid &= all(isinstance(fields.get(key), str) and bool(fields[key]) for key in ("firmware_version", "firmware_build"))
    if not valid:
        raise LocalFailure("INCOMPATIBLE_DESCRIPTOR", response.request_id)


def _general(response):
    fields = response.fields
    faults = fields.get("fault_codes")
    valid = (response.verb == "ok" and fields.get("health") in ("ok", "fault", "unknown")
             and fields.get("activity") in ("idle", "calibrating", "scanning", "unknown")
             and isinstance(fields.get("boot_id"), str)
             and re.fullmatch(r"[a-f0-9]{32}", fields["boot_id"]) is not None
             and isinstance(faults, list) and all(isinstance(code, str) and re.fullmatch(r"[A-Z][A-Z0-9_]*", code) for code in faults)
             and ("calibrated" not in fields or type(fields["calibrated"]) is bool))
    if not valid or (fields["health"] == "fault" and not faults) or (faults and fields["health"] != "fault"):
        raise LocalFailure("UNUSABLE_STATUS", response.request_id)
    if "booted_at" in fields:
        timestamp = fields["booted_at"]
        try:
            if not isinstance(timestamp, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?Z", timestamp) is None:
                raise ValueError
            datetime.strptime(timestamp[:19], "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            raise LocalFailure("UNUSABLE_STATUS", response.request_id) from None


def _refresh_usable(target, response):
    fields = response.fields
    valid = response.verb == "ok" and fields.get("name") == target[1]
    if target[0] == "get":
        value = fields.get("value")
        try:
            number = Decimal(value.text) if isinstance(value, NumericToken) and len(value.text) <= 64 else None
            # At most 64 input characters; range-check before scaled arithmetic.
            # Trailing zeroes are spelling, not evidence of off-grid precision.
            with localcontext(Context(prec=80)):
                valid &= (number is not None and 1 <= number <= 10
                          and number * 1000000 == (number * 1000000).to_integral_value()
                          and fields.get("unit") == "GHz")
        except InvalidOperation:
            valid = False
    else:
        valid &= fields.get("state") in ("unknown", "never_started", "running", "cancelling", "succeeded", "failed", "cancelled")
    if not valid:
        raise LocalFailure("UNUSABLE_REFRESH", response.request_id)
    return True

FICTITIOUS_RECEIVER_CONTRACT = ClientContract(_descriptor, _general, _refresh_usable, ERROR_CATALOG)
