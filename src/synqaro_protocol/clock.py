"""Monotonic deadlines and UTC observations are separate clock operations."""

import asyncio
from datetime import datetime, timezone
import time
from typing import Protocol


class Clock(Protocol):
    def monotonic(self) -> float: ...

    def utcnow(self) -> datetime: ...

    async def sleep(self, seconds: float) -> None: ...


class SystemClock:
    def monotonic(self) -> float:
        return time.monotonic()

    def utcnow(self) -> datetime:
        return datetime.now(timezone.utc)

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


async def bounded(awaitable, clock, deadline):
    """Await one operation against an absolute deadline and join owned tasks."""
    operation = asyncio.ensure_future(awaitable)
    timer = asyncio.create_task(clock.sleep(max(0, deadline - clock.monotonic())))
    try:
        done, _ = await asyncio.wait((operation, timer), return_when=asyncio.FIRST_COMPLETED)
        if operation in done and clock.monotonic() <= deadline:
            return operation.result()
        raise TimeoutError
    finally:
        for task in (operation, timer):
            if not task.done():
                task.cancel()
        await asyncio.gather(operation, timer, return_exceptions=True)
