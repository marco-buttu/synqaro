"""One public-client functional suite for the simulator or matching firmware."""

from decimal import Decimal, InvalidOperation

from simquaro.checks import Check, CheckFailure, CheckSkipped
from synqaro_protocol.client import ProtocolClient
from synqaro_protocol.codec import NumericToken as N
from synqaro_protocol.errors import render_error
from synqaro_protocol.profiles.fictitious_receiver import FICTITIOUS_RECEIVER_CONTRACT


def client_factory(host, port, settings, *, read_only=False):
    return ProtocolClient(host, port, contract=FICTITIOUS_RECEIVER_CONTRACT,
                          expected_hardware_id=settings.hardware_id, read_only=read_only)


async def _call(client, verb, fields=None):
    response = await client.request(verb, fields)
    if response.verb == "error":
        raise CheckFailure(render_error(response.fields["code"], response.fields,
                                        catalog=client.contract.error_catalog))
    expected = "accepted" if verb in ("run", "cancel", "reboot") else "ok"
    if response.verb != expected:
        raise CheckFailure(f"Expected {expected}, received {response.verb}")
    return response


async def configuration(client):
    response = await _call(client, "get", {"name": "configuration"})
    client.contract.validate_descriptor(response, client.expected_hardware_id)


async def general_status(client):
    response = await _call(client, "status")
    client.contract.validate_status(response)
    client.general = response
    if response.fields["health"] != "ok":
        codes = response.fields.get("fault_codes", [])
        raise CheckFailure("Hardware health is not ok: " + ", ".join(codes))


async def frequency(client):
    response = await _call(client, "get", {"name": "frequency"})
    client.contract.refresh_usable(("get", "frequency"), response)
    return response


async def _status(client, name):
    response = await _call(client, "status", {"name": name})
    client.contract.refresh_usable(("status", name), response)
    return response


async def calibrate_status(client): await _status(client, "calibrate")
async def scan_status(client): await _status(client, "scan")


async def _idle(client):
    response = await _call(client, "status")
    client.contract.validate_status(response)
    client.general = response
    if response.fields["health"] != "ok" or response.fields["activity"] != "idle":
        raise CheckSkipped("Modifying check requires healthy idle hardware and an isolated test context")


async def _wait(client, name, timeout_ms):
    deadline = client.clock.monotonic() + timeout_ms / 1000 + 2
    while client.clock.monotonic() <= deadline:
        response = await _status(client, name)
        if response.fields["state"] not in ("running", "cancelling"):
            return response
        await client.clock.sleep(.5)
    raise CheckFailure(f"{name} did not terminate within its advertised observation budget")


def _state(response, expected):
    if response.fields.get("state") != expected:
        raise CheckFailure(f"Expected {expected}, received {response.fields.get('state')}; "
                           f"error={response.fields.get('error_code', 'none')}")


async def set_frequency_rounding(client):
    await _idle(client)
    response = await _call(client, "set", {"name": "frequency", "value": N("5.1234565"), "unit": "GHz"})
    client.contract.refresh_usable(("get", "frequency"), response)
    if not _equals(response.fields.get("value"), "5.123457"):
        raise CheckFailure("Rounding must apply 5.1234565 GHz as 5.123457 GHz")
    actual = await frequency(client)
    if not _equals(actual.fields.get("value"), "5.123457"):
        raise CheckFailure("Frequency readback does not match the applied rounded value")


def _equals(value, expected):
    try:
        return isinstance(value, N) and len(value.text) <= 64 and Decimal(value.text) == Decimal(expected)
    except InvalidOperation:
        return False


async def calibrate(client):
    await _idle(client)
    await _call(client, "run", {"name": "calibrate"})
    terminal = await _wait(client, "calibrate", int(str(client.descriptor.fields["calibrate_timeout_ms"])))
    _state(terminal, "succeeded")
    await general_status(client)
    if client.general.fields.get("calibrated") is not True:
        raise CheckFailure("Completed calibration is not reflected in general status")


async def _scan(client, dwell):
    await _idle(client)
    await _call(client, "run", {"name": "scan", "start": N("5"), "stop": N("5.2"),
                                "unit": "GHz", "dwell_ms": N(str(dwell))})


async def scan(client):
    await _scan(client, 1)
    terminal = await _wait(client, "scan", int(str(client.descriptor.fields["scan_timeout_ms"])))
    _state(terminal, "succeeded")
    if terminal.fields.get("points_completed") != N("10"):
        raise CheckFailure("Successful scan did not report ten completed points")
    actual = await frequency(client)
    if not _equals(actual.fields.get("value"), "5.2"):
        raise CheckFailure("Successful scan did not end at 5.2 GHz")


async def scan_cancel(client):
    await _scan(client, 1000)
    await _call(client, "cancel", {"name": "scan"})
    terminal = await _wait(client, "scan", int(str(client.descriptor.fields["procedure_stop_timeout_ms"])))
    _state(terminal, "cancelled")  # Completion in a cancellation race is not cancellation proof.


async def reboot(client):
    await _idle(client)
    previous = client.general.fields["boot_id"]
    await _call(client, "reboot")  # Once only; never replay after a lost acceptance.
    deadline = client.clock.monotonic() + 30
    while client.clock.monotonic() <= deadline:
        if client.ready and client.general.fields["boot_id"] != previous:
            return
        await client.clock.sleep(.5)
    raise CheckFailure("No validated new firmware boot identity observed within 30 seconds")


CHECKS = tuple(Check(name, mutating, function) for name, mutating, function in (
    ("configuration", False, configuration), ("general_status", False, general_status),
    ("frequency", False, frequency), ("calibrate_status", False, calibrate_status),
    ("scan_status", False, scan_status), ("set_frequency_rounding", True, set_frequency_rounding),
    ("calibrate", True, calibrate), ("scan", True, scan),
    ("scan_cancel", True, scan_cancel), ("reboot", True, reboot)))
