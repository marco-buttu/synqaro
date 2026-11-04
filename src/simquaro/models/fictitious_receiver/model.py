"""Shared physical receiver evidence and its firmware request interface.

The model owns firmware tasks, independently of client session lifetimes. Wire
delivery and the response_ready hook belong to the caller after handle returns.
"""

import asyncio
from dataclasses import fields
from decimal import Context, Decimal, localcontext
import logging
import re
import secrets

from synqaro_protocol.clock import Clock, SystemClock
from synqaro_protocol.errors import ProtocolError
from simquaro.faults import FaultContext, FaultController
from simquaro.model import ModelReply
from synqaro_protocol.codec import MAX_REQUEST_ID, NumericToken, Request, Response, encode_response
from .config import ReceiverConfig
from synqaro_protocol.profiles.fictitious_receiver import render_error
from .faults import receiver_faults
from .procedures import Procedures
from .validation import parse_frequency


_LOGGER = logging.getLogger(__name__)
_DIAGNOSTIC_CAUSES = (("synthesizer_failure", "SYNTHESIZER_FAILURE"),
                      ("frequency_read_failure", "FREQUENCY_READ_FAILED"),
                      ("clock_untrusted", "CLOCK_UNTRUSTED"))


def _text(value: Decimal) -> str:
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _number(value: Decimal | int | float) -> NumericToken:
    return NumericToken(_text(value if isinstance(value, Decimal) else Decimal(str(value))))


def _context_text(value: str) -> str | None:
    return "".join(c if " " <= c <= "~" else "?" for c in value[:64]) or None


def _json_fields(values):
    return {key: str(value) if isinstance(value, NumericToken) else value
            for key, value in values.items()}


class FictitiousReceiverSimulator:
    def __init__(self, config: ReceiverConfig, *, faults: FaultController | None = None,
                 clock: Clock | None = None):
        if not isinstance(config, ReceiverConfig):
            raise ValueError("invalid receiver configuration; provide a validated ReceiverConfig")
        self.config = config
        self.faults = faults if faults is not None else receiver_faults()
        self.clock = clock if clock is not None else SystemClock()
        self._tasks: set[asyncio.Task] = set()
        self._incidents: list[dict] = []
        try:
            encode_response(Response("ok", MAX_REQUEST_ID, self._descriptor()))
        except ProtocolError:
            raise ValueError("configuration descriptor exceeds 4096 bytes; shorten hardware_id, firmware_version or firmware_build") from None
        self._reset()

    def _reset(self):
        self.boot_id = secrets.token_hex(16)
        self.booted_at = self.utc_timestamp()
        self._frequency = Decimal(str(self.config.initial_frequency))
        self._frequency_verified = not self.faults.is_active("synthesizer_failure")
        self._target: Decimal | None = None
        self._tuning = False
        self._short_change = False
        self._calibrated = False
        self._reboot_pending = False
        self._closed = False
        self._stop_timeout = False
        self._known_faults: set[str] = set()
        self._synthesizer_activation = self.faults.activation_token("synthesizer_failure")
        self._procedures = Procedures(self)
        self._diagnose()

    def _spawn(self, coroutine):
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def utc_timestamp(self):
        if self.faults.is_active("clock_untrusted"):
            return None
        return self.clock.utcnow().isoformat().replace("+00:00", "Z")

    def _incident(self, code):
        entry = {"code": code, "boot_id": self.boot_id,
                 "monotonic": self.clock.monotonic()}
        utc = self.utc_timestamp()
        if utc is not None:
            entry["utc"] = utc
        self._incidents.append(entry)
        del self._incidents[:-32]
        _LOGGER.info("receiver incident %s; %s", entry, render_error(code, {}))

    def _emit(self, event, request, session_id):
        target = request.fields.get("name")
        return self.faults.emit(FaultContext(
            event, _context_text(session_id), request.request_id,
            _context_text(request.verb), _context_text(target) if isinstance(target, str) else None))

    def _busy(self):
        return (self._short_change or self._procedures.active is not None
                or self._reboot_pending or self._closed)

    def _diagnose(self):
        # Fault removal cannot recreate evidence destroyed by physical failure.
        activation = self.faults.activation_token("synthesizer_failure")
        invalidated = activation is not self._synthesizer_activation
        self._synthesizer_activation = activation
        if invalidated or self.faults.is_active("synthesizer_failure"):
            self._frequency_verified = False
            self._calibrated = False
        current = {code for cause, code in _DIAGNOSTIC_CAUSES if self.faults.is_active(cause)}
        detected = current | ({"SYNTHESIZER_FAILURE"} if invalidated else set())
        for code in sorted(detected - self._known_faults):
            self._incident(code)
        self._known_faults = current

    @staticmethod
    def _allowed(request, allowed):
        for key in request.metadata:
            if key not in ("id", "client_id"):
                raise ProtocolError("UNKNOWN_PARAMETER", {"parameter": key})
        for key in request.fields:
            if key not in allowed:
                raise ProtocolError("UNKNOWN_PARAMETER", {"parameter": key})

    @staticmethod
    def _required(request, name):
        if name not in request.fields:
            raise ProtocolError("MISSING_PARAMETER", {"parameter": name})
        return request.fields[name]

    def _name(self, request, *, procedure=False):
        name = self._required(request, "name")
        if not isinstance(name, str):
            raise ProtocolError("INVALID_TYPE", {"parameter": "name", "expected": "string"})
        supported = ("calibrate", "scan") if procedure else ("configuration", "frequency")
        if name not in supported:
            context = {"name": name} if procedure else {"parameter": "name", "value": name}
            raise ProtocolError("UNKNOWN_PROCEDURE" if procedure else "UNKNOWN_PROPERTY", context)
        return name

    def _unit(self, request):
        if self._required(request, "unit") != "GHz":
            raise ProtocolError("UNSUPPORTED_UNIT", {"parameter": "unit", "expected": "GHz"})

    def _frequency_parameter(self, request, parameter):
        try:
            return parse_frequency(self._required(request, parameter), self.config)
        except ProtocolError as error:
            error.fields["parameter"] = parameter
            raise

    def _scan_parameters(self, request):
        start = self._frequency_parameter(request, "start")
        stop = self._frequency_parameter(request, "stop")
        self._unit(request)
        dwell = self._required(request, "dwell_ms")
        if not isinstance(dwell, NumericToken) or re.fullmatch(r"[0-9]+", dwell.text) is None:
            raise ProtocolError("INVALID_TYPE", {"parameter": "dwell_ms", "expected": "integer"})
        digits = dwell.text.lstrip("0")
        if not digits or len(digits) > 4 or int(digits) > 1000:
            raise ProtocolError("OUT_OF_RANGE", {"parameter": "dwell_ms", "min": _number(1), "max": _number(1000)})
        dwell_ms = int(digits)
        if 10 * (self.config.max_tuning_ms + dwell_ms) > self.config.scan_timeout_ms:
            raise ProtocolError("INVALID_PARAMETER", {"parameter": "dwell_ms", "reason": "EXECUTION_BUDGET_EXCEEDED"})
        # Integer nearest rounding with ties toward the higher (positive) grid index.
        with localcontext(Context(prec=32)):
            a, b = int(start * 1000000), int(stop * 1000000)
            indices = [(2 * (9 * a + i * (b - a)) + 9) // 18 for i in range(10)]
        if abs(b - a) < 9 or len(set(indices)) != 10:
            raise ProtocolError("INVALID_PARAMETER", {"parameter": "stop", "reason": "INSUFFICIENT_DISTINCT_POINTS"})
        with localcontext(Context(prec=32)):
            return tuple(Decimal(index) / Decimal(1000000) for index in indices), dwell_ms

    def _descriptor(self):
        names = {"protocol_version", "hardware_id", "hardware_model", "firmware_version", "firmware_build",
                 "frequency_min", "frequency_max", "frequency_unit", "frequency_resolution", "frequency_rounding",
                 "max_message_bytes", "incomplete_message_timeout_ms", "max_pending_requests", "max_tuning_ms",
                 "calibrate_timeout_ms", "scan_timeout_ms", "procedure_stop_timeout_ms", "scan_points",
                 "scan_max_dwell_ms", "utc_clock_supported"}
        result = {"name": "configuration"}
        for field in fields(self.config):
            if field.name in names:
                value = getattr(self.config, field.name)
                result[field.name] = _number(value) if type(value) in (int, float) else value
        result.update(readonly_properties=["configuration"], readwrite_properties=["frequency"],
                      supported_procedures=["calibrate", "scan"], calibrate_cancellation="except_finalization",
                      scan_cancellation="always", sampled_at_properties=["frequency"])
        return result

    def _general(self):
        codes = []
        for cause, code in _DIAGNOSTIC_CAUSES:
            if self.faults.is_active(cause):
                codes.append(code)
        if self._stop_timeout:
            codes.append("STOP_TIMEOUT")
        active = self._procedures.active
        result = {"health": "fault" if codes else "ok" if self._frequency_verified or self._tuning else "unknown",
                  "activity": {"calibrate": "calibrating", "scan": "scanning"}.get(active.name, "idle") if active else "idle",
                  "calibrated": self._calibrated, "fault_codes": codes, "boot_id": self.boot_id}
        if self.booted_at is not None:
            result["booted_at"] = self.booted_at
        return result

    def _read_frequency(self):
        active = self._procedures.active
        if active is not None and active.name == "calibrate":
            raise ProtocolError("VALUE_UNAVAILABLE", {"reason": "CALIBRATING"})
        if self._tuning:
            raise ProtocolError("VALUE_UNAVAILABLE", {"reason": "TUNING"})
        if self.faults.is_active("frequency_read_failure") or self.faults.is_active("synthesizer_failure"):
            raise ProtocolError("FREQUENCY_READ_FAILED", {})
        if not self._frequency_verified:
            raise ProtocolError("VALUE_UNAVAILABLE", {"reason": "UNVERIFIED"})
        result = {"name": "frequency", "value": _number(self._frequency), "unit": "GHz"}
        timestamp = self.utc_timestamp()
        if timestamp is not None:
            result["sampled_at"] = timestamp
        return result

    async def _tune(self, target):
        self._diagnose()
        activation = self.faults.activation_token("synthesizer_failure")
        deadline = self.clock.monotonic() + self.config.max_tuning_ms / 1000
        self._target = target
        if self._frequency != target:
            self._calibrated = False
        self._frequency = target  # Applied physical target, not yet verified evidence.
        self._frequency_verified = False
        self._tuning = True
        duration = (self.config.max_tuning_ms if self.faults.is_active("frequency_lock_failure")
                    else self.config.tuning_duration_ms) / 1000
        try:
            await self.clock.sleep(duration)
            self._diagnose()
            if (self.clock.monotonic() > deadline or self.faults.is_active("frequency_lock_failure")
                    or self.faults.is_active("synthesizer_failure")
                    or activation is not self.faults.activation_token("synthesizer_failure")):
                self._incident("FREQUENCY_LOCK_FAILED")
                raise ProtocolError("FREQUENCY_LOCK_FAILED", {})
            self._frequency_verified = True
            _LOGGER.info("frequency verified boot=%s monotonic=%s value=%s", self.boot_id,
                         self.clock.monotonic(), target)
        finally:
            self._tuning = False

    async def _external_set(self, request, target, session_id):
        try:
            await self._tune(target)
            effects = self._emit("frequency_set_verified", request, session_id)
            return ModelReply(Response("ok", request.request_id,
                                      {"name": "frequency", "value": _number(self._frequency), "unit": "GHz"}), effects,
                              delivery_events=("frequency_set_verified",))
        except ProtocolError as error:
            return self._error(request, error)
        finally:
            self._short_change = False

    @staticmethod
    def _error(request, error):
        # Unknown legal tokens can occupy virtually an entire input frame. Echo
        # bounded diagnostic context so adding the response envelope still fits.
        context = {key: value[:128] if isinstance(value, str) else value
                   for key, value in error.fields.items()}
        return ModelReply(Response("error", request.request_id, {"code": error.code, **context}))

    async def handle(self, request: Request, *, session_id: str) -> ModelReply:
        self._diagnose()
        try:
            verb = request.verb
            if verb not in ("get", "set", "status", "run", "cancel", "reboot"):
                raise ProtocolError("UNKNOWN_VERB", {"verb": verb})
            if verb == "get":
                self._allowed(request, {"name"})
                name = self._name(request)
                values = self._descriptor() if name == "configuration" else self._read_frequency()
            elif verb == "status":
                self._allowed(request, {"name"})
                values = self._procedures.status(self._name(request, procedure=True)) if "name" in request.fields else self._general()
            elif verb == "set":
                self._allowed(request, {"name", "value", "unit"})
                name = self._name(request)
                if name == "configuration":
                    raise ProtocolError("READ_ONLY_PROPERTY", {"name": name})
                target = self._frequency_parameter(request, "value")
                self._unit(request)
                if self._busy():
                    raise ProtocolError("BUSY", {})
                if self.faults.is_active("synthesizer_failure"):
                    raise ProtocolError("HARDWARE_FAULT", {})
                self._short_change = True
                return await asyncio.shield(self._spawn(self._external_set(request, target, session_id)))
            elif verb == "run":
                name = self._name(request, procedure=True)
                self._allowed(request, {"name", "start", "stop", "unit", "dwell_ms"} if name == "scan" else {"name"})
                targets, dwell = self._scan_parameters(request) if name == "scan" else ((), 0)
                if self._busy():
                    raise ProtocolError("BUSY", {})
                if self.faults.is_active("synthesizer_failure") or (name == "calibrate" and self.faults.is_active("calibration_reference_unavailable")):
                    raise ProtocolError("HARDWARE_FAULT", {})
                self._procedures.start(name, request, session_id, targets, dwell)
                return ModelReply(Response("accepted", request.request_id, {}))
            elif verb == "cancel":
                self._allowed(request, {"name"})
                name = self._name(request, procedure=True)
                self._procedures.cancel(name)
                return ModelReply(Response("accepted", request.request_id, {"name": name}))
            else:
                self._allowed(request, set())
                if self._reboot_pending or self._closed:
                    raise ProtocolError("BUSY", {})
                self._reboot_pending = True
                return ModelReply(Response("accepted", request.request_id, {}), reboot_requested=True)
            return ModelReply(Response("ok", request.request_id, values))
        except ProtocolError as error:
            return self._error(request, error)

    def snapshot(self):
        self._diagnose()
        active = self._procedures.active
        return {"actual": {"frequency": _text(self._frequency), "frequency_verified": self._frequency_verified,
                           "requested_target": _text(self._target) if self._target is not None else None,
                           "tuning": self._tuning, "procedure_active": active is not None,
                           "procedure": active.name if active else None,
                           "phase": active.phase if active else None,
                           "stop_deadline": active.stop_deadline if active else None,
                           "scan_targets": [_text(value) for value in active.targets] if active else [],
                           "reference_verified": active.reference_verified if active else False,
                           "procedures": {name: {"reference_verified": attempt.reference_verified,
                                                 "restoration_verified": attempt.restoration_verified,
                                                 "points_completed": attempt.points_completed,
                                                 "targets": [_text(value) for value in attempt.targets]}
                                          for name, attempt in self._procedures.attempts.items()},
                           "reboot_pending": self._reboot_pending},
                "reported": {"general": _json_fields(self._general()),
                             "procedures": {name: _json_fields(self._procedures.status(name))
                                            for name in ("calibrate", "scan")}},
                "incidents": [dict(entry) for entry in self._incidents]}

    async def close(self):
        self._closed = True
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def reboot(self):
        await self.close()
        self._reset()
