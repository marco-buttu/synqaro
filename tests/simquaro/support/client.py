"""Construction-only fixture; production owns all communication behavior."""

from synqaro_protocol.client import LocalFailure, ProtocolClient
from synqaro_protocol.profiles.fictitious_receiver import (
    FICTITIOUS_RECEIVER_CONTRACT, _descriptor, _refresh_usable)


def ConformanceClient(host, port, *, clock=None, expected_hardware_id="example-receiver-01"):
    return ProtocolClient(host, port, clock=clock,
                          expected_hardware_id=expected_hardware_id,
                          contract=FICTITIOUS_RECEIVER_CONTRACT)
