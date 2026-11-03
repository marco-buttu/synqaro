"""Private procedure lifecycle: advancement, independent deadlines and stop proof."""

import asyncio
from dataclasses import dataclass, field
from decimal import Decimal

from simquaro.errors import ProtocolError
from simquaro.protocol import NumericToken
from .validation import parse_frequency


@dataclass
class _Attempt:
    name: str
    state: str = "unknown"
    phase: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    error_code: str | None = None
    targets: tuple[Decimal, ...] = ()
    points_completed: int = 0
    saved_frequency: Decimal | None = None
    reference_verified: bool = False
    restoration_verified: bool = False
    stop_deadline: float | None = None
    execution_deadline: float | None = None
    stop_error: str | None = None
    execution_task: asyncio.Task | None = field(default=None, repr=False)
    watchdog_task: asyncio.Task | None = field(default=None, repr=False)
    stop_task: asyncio.Task | None = field(default=None, repr=False)
    stop_watchdog_task: asyncio.Task | None = field(default=None, repr=False)


class Procedures:
    def __init__(self, model):
        self.model = model
        self.attempts = {name: _Attempt(name) for name in ("calibrate", "scan")}
        self.active: _Attempt | None = None

    def status(self, name):
        attempt = self.attempts[name]
        result = {"name": name, "state": attempt.state}
        for key in ("started_at", "finished_at", "error_code"):
            value = getattr(attempt, key)
            if value is not None:
                result[key] = value
        if name == "scan" and attempt.state not in ("unknown", "never_started"):
            result.update(points_completed=NumericToken(str(attempt.points_completed)),
                          points_total=NumericToken("10"), progress=NumericToken(str(attempt.points_completed * 10)))
        return result

    def start(self, name, request, session_id, targets, dwell_ms):
        model = self.model
        attempt = _Attempt(name, state="running", phase="preparation" if name == "calibrate" else "tuning",
                           started_at=model.utc_timestamp(), targets=targets, saved_frequency=model._frequency)
        self.attempts[name] = self.active = attempt
        if name == "calibrate":
            model._calibrated = False
        deadline = model.clock.monotonic() + (model.config.calibrate_timeout_ms if name == "calibrate"
                                              else model.config.scan_timeout_ms) / 1000
        attempt.execution_deadline = deadline
        attempt.execution_task = model._spawn(self._execute(attempt, request, session_id, dwell_ms))
        attempt.watchdog_task = model._spawn(self._watchdog(attempt, deadline))

    async def _advance_ready(self):
        while self.model.faults.is_active("procedure_stall"):
            await self.model.clock.sleep(.05)

    async def _phase_wait(self, deadline):
        remaining = deadline - self.model.clock.monotonic()
        if remaining > 0:
            await self.model.clock.sleep(remaining)
        await self._advance_ready()

    async def _execute(self, attempt, request, session_id, dwell_ms):
        try:
            await self._advance_ready()
            if attempt.name == "calibrate":
                await self._calibrate(attempt, request, session_id)
            else:
                await self._scan(attempt, dwell_ms)
            error = attempt.stop_error
            if self.model.clock.monotonic() > attempt.execution_deadline:
                error = "CALIBRATION_TIMEOUT" if attempt.name == "calibrate" else "SCAN_TIMEOUT"
            self._finish(attempt, "failed" if error else "succeeded", error)
        except ProtocolError as error:
            self._finish(attempt, "failed", error.code)

    def _check_reference(self):
        self.model._diagnose()
        if self.model.faults.is_active("calibration_reference_unavailable"):
            raise ProtocolError("CALIBRATION_REFERENCE_UNAVAILABLE", {})
        if not self.model._frequency_verified:
            raise ProtocolError("FREQUENCY_LOCK_FAILED", {})

    async def _calibrate(self, attempt, request, session_id):
        model = self.model
        preparation_end = model.clock.monotonic() + model.config.calibrate_preparation_ms / 1000
        reference = parse_frequency(NumericToken("6"), model.config)
        await model._tune(reference)
        await self._phase_wait(preparation_end)
        attempt.phase = "reference_measurement"
        model._emit("calibrate_reference_measurement", request, session_id)
        self._check_reference()
        await self._phase_wait(model.clock.monotonic() + model.config.calibrate_measurement_ms / 1000)
        self._check_reference()
        attempt.reference_verified = True
        attempt.phase = "finalization"
        finalization_end = model.clock.monotonic() + model.config.calibrate_finalization_ms / 1000
        await model._tune(attempt.saved_frequency)
        await self._phase_wait(finalization_end)
        self._check_reference()
        if not model._frequency_verified or model._frequency != attempt.saved_frequency:
            raise ProtocolError("FREQUENCY_LOCK_FAILED", {})
        attempt.restoration_verified = True
        model._calibrated = attempt.reference_verified

    async def _scan(self, attempt, dwell_ms):
        for target in attempt.targets:
            await self._advance_ready()
            attempt.phase = "tuning"
            await self.model._tune(target)
            await self._advance_ready()
            attempt.phase = "holding"
            await self.model.clock.sleep(dwell_ms / 1000)
            await self._advance_ready()
            self.model._diagnose()
            if not self.model._frequency_verified or self.model._frequency != target:
                raise ProtocolError("FREQUENCY_LOCK_FAILED", {})
            attempt.points_completed += 1

    async def _watchdog(self, attempt, deadline):
        await self.model.clock.sleep(max(0, deadline - self.model.clock.monotonic()))
        if self.active is attempt and attempt.stop_deadline is None:
            self._begin_stop(attempt, "CALIBRATION_TIMEOUT" if attempt.name == "calibrate" else "SCAN_TIMEOUT")

    def cancel(self, name):
        attempt = self.active
        if attempt is None or attempt.name != name:
            raise ProtocolError("NOT_RUNNING", {"name": name})
        if attempt.state == "cancelling":
            return
        if name == "calibrate" and attempt.phase == "finalization":
            raise ProtocolError("NOT_CANCELLABLE", {"name": name})
        self._begin_stop(attempt)

    def _begin_stop(self, attempt, error=None):
        attempt.state = "cancelling"
        attempt.stop_error = error
        attempt.stop_deadline = self.model.clock.monotonic() + self.model.config.procedure_stop_timeout_ms / 1000
        if error is not None:
            self.model._incident(error)
        attempt.stop_task = self.model._spawn(self._stop(attempt))
        attempt.stop_watchdog_task = self.model._spawn(self._stop_watchdog(attempt))

    async def _stop_watchdog(self, attempt):
        model = self.model
        await model.clock.sleep(max(0, attempt.stop_deadline - model.clock.monotonic()))
        if self.active is attempt:
            model._stop_timeout = True
            model._incident("STOP_TIMEOUT")

    async def _stop(self, attempt):
        model = self.model
        while True:
            while model.faults.is_active("stop_unconfirmed"):
                await model.clock.sleep(.05)
            # A fresh modeled stop action is required after the cause is removed.
            await model.clock.sleep(model.config.stop_duration_ms / 1000)
            if not model.faults.is_active("stop_unconfirmed"):
                break
        if self.active is attempt:
            attempt.execution_task.cancel()
            await asyncio.gather(attempt.execution_task, return_exceptions=True)
            self._finish(attempt, "failed" if attempt.stop_error else "cancelled", attempt.stop_error)

    def _finish(self, attempt, state, error=None):
        if self.active is not attempt:
            return
        attempt.state = state
        if attempt.name == "calibrate" and state != "succeeded":
            self.model._calibrated = False
        attempt.finished_at = self.model.utc_timestamp()
        attempt.error_code = error
        if error is not None:
            self.model._incident(error)
        self.active = None
        self.model._stop_timeout = False
        current = asyncio.current_task()
        for task in (attempt.watchdog_task, attempt.stop_task, attempt.stop_watchdog_task):
            if task is not None and task is not current:
                task.cancel()
