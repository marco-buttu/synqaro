"""Shared symbolic errors and bounded human-readable diagnostic rendering."""

from collections.abc import Mapping
from dataclasses import dataclass
from itertools import islice
from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from simquaro.protocol import Value


@dataclass(frozen=True)
class ErrorDefinition:
    code: str
    message: str
    parameters: tuple[str, ...]
    action: str


_DEFINITIONS = (
    ErrorDefinition("INVALID_ID", "No valid, unambiguous request ID", (), "Supply one decimal ID from 1 through 4294967295."),
    ErrorDefinition("ID_NOT_INCREASING", "Request ID was reused or decreased", ("last_id", "rejected_verb", "rejected_name", "received_at"), "Use a new ID greater than last_id on this connection."),
    ErrorDefinition("MALFORMED_REQUEST", "Request syntax is invalid", (), "Correct the request syntax and send it with a new ID."),
    ErrorDefinition("TOO_MANY_PENDING_REQUESTS", "Connection admission limit exceeded", ("limit",), "Wait for a pending response before submitting another request."),
    ErrorDefinition("UNKNOWN_VERB", "Verb is unsupported", ("verb",), "Use a verb supported by the receiver contract."),
    ErrorDefinition("UNKNOWN_PROPERTY", "Property is unsupported", ("parameter", "value"), "Select a property supported by the receiver contract."),
    ErrorDefinition("UNKNOWN_PROCEDURE", "Procedure is unsupported", ("name",), "Select a supported procedure."),
    ErrorDefinition("READ_ONLY_PROPERTY", "Property is read-only", ("name",), "Read this property with get; select a writable property for set."),
    ErrorDefinition("MISSING_PARAMETER", "Required parameter is absent", ("parameter",), "Supply the required parameter."),
    ErrorDefinition("UNKNOWN_PARAMETER", "Parameter is unsupported", ("parameter",), "Remove the unsupported parameter."),
    ErrorDefinition("DUPLICATE_PARAMETER", "Parameter occurs more than once", ("parameter",), "Supply the parameter only once within its section."),
    ErrorDefinition("INVALID_TYPE", "Parameter has the wrong type", ("parameter", "expected"), "Supply the declared type without implicit conversion."),
    ErrorDefinition("OUT_OF_RANGE", "Value is outside the allowed interval", ("parameter", "min", "max", "unit"), "Choose an original value within the declared interval."),
    ErrorDefinition("UNSUPPORTED_UNIT", "Unit is unsupported", ("parameter", "expected"), "Supply the declared unit explicitly."),
    ErrorDefinition("INVALID_PARAMETER", "Parameter constraint is violated", ("parameter", "reason"), "Correct the parameter according to the symbolic reason and receiver contract."),
    ErrorDefinition("BUSY", "Current activity prevents this operation", (), "Inspect status and wait for the conflicting activity to finish."),
    ErrorDefinition("VALUE_UNAVAILABLE", "Property cannot currently provide a valid value", ("reason",), "Inspect status and resolve the reported condition before reading again."),
    ErrorDefinition("STATUS_UNAVAILABLE", "Usable receiver status is unavailable", (), "Check receiver diagnostics and communication before relying on its state."),
    ErrorDefinition("HARDWARE_FAULT", "An active hardware fault prevents this operation", (), "Inspect general status and resolve the active fault."),
    ErrorDefinition("NOT_RUNNING", "Selected procedure is not active", ("name",), "Inspect the selected procedure's retained status."),
    ErrorDefinition("NOT_CANCELLABLE", "Procedure or phase cannot accept cancellation", ("name",), "Inspect procedure status and wait for a cancellable phase or completion."),
    ErrorDefinition("STOP_TIMEOUT", "Controlled stop was not confirmed within its deadline", (), "Inspect actual hardware activity and resolve the unconfirmed stop before incompatible work."),
    ErrorDefinition("CLOCK_UNTRUSTED", "UTC clock is unavailable or untrusted; new UTC timestamps are omitted", (), "Restore host clock trust before operations requiring trustworthy UTC."),
)

ERROR_CATALOG: Mapping[str, ErrorDefinition] = MappingProxyType(
    {definition.code: definition for definition in _DEFINITIONS})


def _safe(text: str, limit: int) -> str:
    return "".join(character if " " <= character <= "~" else "?"
                   for character in text[:limit])


def _render_value(value: "Value") -> str:
    if isinstance(value, list):
        text = "[" + ", ".join(_render_value(item) for item in value[:8])
        return text + (", ...]" if len(value) > 8 else "]")
    if isinstance(value, bool):
        return "true" if value else "false"
    return _safe(str(value), 96)


def render_error(code: str, fields: Mapping[str, "Value"], *,
                 catalog: Mapping[str, ErrorDefinition] = ERROR_CATALOG) -> str:
    """Render known or future errors without unbounded or control-bearing logs."""
    definition = catalog.get(code)
    message = definition.message if definition else "Unrecognized hardware error code"
    action = definition.action if definition else "Inspect the supplied context and receiver contract."
    # Both the number and size of rendered values are bounded independently of callers.
    context = []
    for key, value in islice(fields.items(), 16):
        context.append(f"{_safe(str(key), 48)}={_render_value(value)}")
    suffix = "; " + ", ".join(context) if context else ""
    prefix = f"{_safe(code, 64)}: {message}. {action}"
    return (prefix + suffix)[:1024]


class ProtocolError(Exception):
    """A symbolic validation error, with context and optional safe correlation."""

    def __init__(self, code: str, fields: Mapping[str, "Value"], request_id: int | None = None):
        self.code = code
        self.fields = dict(fields)
        self.request_id = request_id
        super().__init__(render_error(code, self.fields))
