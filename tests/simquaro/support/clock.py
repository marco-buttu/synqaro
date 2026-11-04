"""A manually advanced clock: moving UTC never advances monotonic deadlines."""

import asyncio
from datetime import datetime, timedelta, timezone
import heapq
import math


class VirtualClock:
    def __init__(self, *, utc: datetime | None = None) -> None:
        self._monotonic = 0.0
        self._utc = datetime(2026, 1, 1, tzinfo=timezone.utc)
        if utc is not None:
            self.set_utc(utc)
        self._sleepers: list[tuple[float, int, asyncio.Future[None]]] = []
        self._sequence = 0

    def monotonic(self) -> float:
        return self._monotonic

    def utcnow(self) -> datetime:
        return self._utc

    def set_utc(self, value: datetime) -> None:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("UTC must be timezone-aware; supply an aware datetime")
        self._utc = value.astimezone(timezone.utc)

    @staticmethod
    def _check_seconds(seconds: float) -> None:
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("elapsed seconds must be finite and nonnegative")

    def advance(self, seconds: float) -> None:
        self._check_seconds(seconds)
        self._monotonic += seconds
        self._utc += timedelta(seconds=seconds)
        while self._sleepers and self._sleepers[0][0] <= self._monotonic:
            _, _, future = heapq.heappop(self._sleepers)
            if not future.done():
                future.set_result(None)

    async def sleep(self, seconds: float) -> None:
        self._check_seconds(seconds)
        if seconds == 0:
            await asyncio.sleep(0)
            return
        future = asyncio.get_running_loop().create_future()
        self._sequence += 1
        heapq.heappush(self._sleepers, (self._monotonic + seconds, self._sequence, future))
        await future
