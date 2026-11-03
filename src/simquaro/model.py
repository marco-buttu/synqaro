"""Small hardware-independent contract consumed by simulator infrastructure."""

from dataclasses import dataclass
from typing import Protocol

from synqaro_protocol.clock import Clock
from simquaro.faults import FaultController, FaultEffect
from synqaro_protocol.codec import Request, Response


@dataclass(frozen=True)
class ModelReply:
    response: Response
    delivery_effects: tuple[FaultEffect, ...] = ()
    reboot_requested: bool = False
    delivery_events: tuple[str, ...] = ()


class SimulatorModel(Protocol):
    clock: Clock
    boot_id: str
    faults: FaultController

    def utc_timestamp(self) -> str | None: ...
    async def handle(self, request: Request, *, session_id: str) -> ModelReply: ...
    def snapshot(self) -> dict: ...
    async def reboot(self) -> None: ...
    async def close(self) -> None: ...
