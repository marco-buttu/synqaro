"""Small fictitious-v1 acceptance client, deliberately confined to test support.

There is no Device/cache, operation replay, arbitrary schema interpreter, or
faulty-request mode here. Diagnostics and uncertainty are bounded test evidence,
not a durable deployment/incident history.
"""

import asyncio
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
import re

from simquaro.clock import SystemClock
from simquaro.errors import ProtocolError, render_error
from simquaro.protocol import NumericToken, Response, Value, parse_response, recover_request_id


class LocalFailure(Exception):
    """A local communication/admission failure, never a firmware execution error."""

    def __init__(self, code, request_id=None, *, uncertain=False):
        self.code = code
        self.request_id = request_id
        self.uncertain = uncertain
        super().__init__(f"{code}: inspect client evidence and fresh receiver state before further work")


@dataclass(frozen=True)
class Evidence:
    kind: str
    request_id: int | None
    verb: str | None
    target: str | None
    hardware_id: str
    received_at: str
    time_provenance: str
    message: str
    wire: bytes


@dataclass
class _Pending:
    verb: str
    fields: dict[str, Value]
    future: asyncio.Future
    session: int
    recover: bool
    uncertainty_recorded: bool = False


class _Deadline(TimeoutError):
    pass


def _value(value):
    if isinstance(value, NumericToken):
        return value.text
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str) and all(" " <= ch <= "~" for ch in value):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(value, list) and not any(isinstance(item, list) for item in value):
        return "[" + ", ".join(_value(item) for item in value) + "]"
    raise ValueError("Supply a protocol scalar or flat list; use a raw client for invalid wire tests")


def _request(verb, request_id, fields):
    if verb not in ("get", "set", "run", "status", "cancel", "reboot"):
        raise ValueError("Use a supported verb; invalid request generation belongs to a raw client")
    if any(not isinstance(key, str) or re.fullmatch(r"[a-z][a-z0-9_]*", key) is None for key in fields):
        raise ValueError("Supply valid field names; use a raw client for malformed requests")
    payload = ", ".join(f"{key}={_value(value)}" for key, value in fields.items())
    frame = (f"#{verb} <id={request_id}>" + (": " + payload if payload else "") + "\n").encode("ascii")
    if len(frame) > 4096:
        raise ValueError("Request exceeds the 4096-byte contract; shorten it")
    return frame


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
    valid &= all(isinstance(fields.get(key), NumericToken) and fields[key].text == value
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
            valid &= (number is not None and 1 <= number <= 10 and number.as_tuple().exponent >= -6
                      and fields.get("unit") == "GHz")
        except InvalidOperation:
            valid = False
    else:
        valid &= fields.get("state") in ("unknown", "never_started", "running", "cancelling", "succeeded", "failed", "cancelled")
    if not valid:
        raise LocalFailure("UNUSABLE_REFRESH", response.request_id)


class ConformanceClient:
    def __init__(self, host, port, *, clock=None, expected_hardware_id="example-receiver-01"):
        self.host, self.port = host, port
        self.clock = clock or SystemClock()
        if not isinstance(expected_hardware_id, str) or not expected_hardware_id:
            raise ValueError("Supply an independently configured expected hardware identity")
        self.expected_hardware_id = expected_hardware_id
        self.descriptor = self.general = None
        self.evidence = deque(maxlen=256)
        self.uncertainties = deque(maxlen=256)
        self.refreshed = {}
        self._writer = None
        self._reader_task = self._recovery = None
        self._pending = {}
        self._retired = {}
        self._affected = set()
        self._next_id = 1
        self._session = 0
        self._slots = 0
        self._closed = False
        self._ready = False
        self._broken = False
        self._send_lock = asyncio.Lock()
        self._connect_lock = asyncio.Lock()

    @property
    def writes_enabled(self):
        return self._ready and not self._closed and not self._affected and not self._recovering

    @property
    def _recovering(self):
        return self._recovery is not None and not self._recovery.done()

    async def _bounded(self, awaitable, seconds=2):
        deadline = self.clock.monotonic() + max(0, seconds)
        async def expire():
            await self.clock.sleep(max(0, deadline - self.clock.monotonic()))
        operation = asyncio.ensure_future(awaitable)
        timer = asyncio.create_task(expire())
        try:
            done, _ = await asyncio.wait((operation, timer), return_when=asyncio.FIRST_COMPLETED)
            if operation in done and self.clock.monotonic() <= deadline:
                return operation.result()
            raise _Deadline
        finally:
            for task in (operation, timer):
                if not task.done():
                    task.cancel()
            await asyncio.gather(operation, timer, return_exceptions=True)

    def _record(self, kind, request_id=None, pending=None, *, wire=b"", message=""):
        event = Evidence(kind, request_id, pending.verb if pending else None,
                         pending.fields.get("name") if pending else None,
                         self.expected_hardware_id, self.clock.utcnow().isoformat(), "client_receipt_utc",
                         "".join(ch if " " <= ch <= "~" else "?" for ch in message[:1024]), wire[:4096])
        self.evidence.append(event)
        return event

    def _retire(self, request_id, kind):
        self._retired[request_id] = kind
        if len(self._retired) > 256:
            del self._retired[next(iter(self._retired))]

    def _uncertain(self, pending, failure):
        failure.uncertain = True
        if pending.uncertainty_recorded:
            return
        pending.uncertainty_recorded = True
        event = self._record("uncertain", failure.request_id, pending, message=str(failure))
        self.uncertainties.append(event)
        if pending.verb == "set" and isinstance(pending.fields.get("name"), str):
            self._affected.add(("get", pending.fields["name"]))
        elif pending.verb in ("run", "cancel") and isinstance(pending.fields.get("name"), str):
            self._affected.add(("status", pending.fields["name"]))
        self._start_recovery()

    async def connect(self):
        async with self._connect_lock:
            if self._closed:
                raise LocalFailure("CLOSED")
            if self._ready:
                return
            if self._writer is not None:
                await self._disconnect()
            await self._establish()

    async def _establish(self):
        self._ready = False
        opening = asyncio.create_task(asyncio.open_connection(self.host, self.port, limit=4096))
        try:
            reader, self._writer = await self._bounded(opening)
        except _Deadline:
            # A scheduler stall may complete TCP after its absolute deadline.
            if not opening.cancelled() and opening.done() and opening.exception() is None:
                _, late_writer = opening.result()
                late_writer.close()
                await asyncio.wait_for(late_writer.wait_closed(), 2)
            raise LocalFailure("CONNECT_TIMEOUT") from None
        except OSError:
            raise LocalFailure("DISCONNECTED") from None
        self._next_id = 1
        self._session += 1
        self._retired.clear()
        self._broken = False
        self._reader_task = asyncio.create_task(self._read(reader))
        response = await self._exchange("get", {"name": "configuration"}, recover=False)
        try:
            _descriptor(response, self.expected_hardware_id)
        except LocalFailure:
            self._record("incompatible_descriptor", response.request_id, wire=b"", message="Unsupported descriptor; writes disabled")
            raise
        self.descriptor = response
        self.general = await self._exchange("status", {}, recover=False)
        _general(self.general)
        self._ready = True

    async def request(self, verb: str, fields: Mapping[str, Value] | None = None) -> Response:
        fields = dict(fields or {})
        if self._closed:
            raise LocalFailure("CLOSED")
        modifying = verb in ("set", "run", "cancel", "reboot")
        if modifying and self._recovering:
            raise LocalFailure("RECOVERY_IN_PROGRESS")
        if modifying and not self.writes_enabled:
            raise LocalFailure("WRITES_DISABLED")
        if self._next_id > 4294967295:
            # No wrapping or impossible probe: drain admitted requests, then rotate.
            if self._pending:
                await asyncio.gather(*(asyncio.shield(p.future) for p in tuple(self._pending.values())), return_exceptions=True)
            if self._recovering:
                await asyncio.shield(self._recovery)
            else:
                self._start_recovery(direct=True)
                await asyncio.shield(self._recovery)
            if modifying and not self.writes_enabled:
                raise LocalFailure("WRITES_DISABLED")
        response = await self._exchange(verb, fields)
        target = (verb, fields.get("name"))
        if target in self._affected:
            try:
                _refresh_usable(target, response)
            except LocalFailure:
                pass
            else:
                self.refreshed[target] = response
                self._affected.discard(target)
        return response

    async def _exchange(self, verb, fields, *, recover=True):
        if self._slots >= 4:
            raise LocalFailure("TOO_MANY_PENDING_REQUESTS")
        self._slots += 1
        pending = _Pending(verb, dict(fields), asyncio.get_running_loop().create_future(), self._session, recover)
        request_id = None
        try:
            async with self._send_lock:
                if recover and verb in ("set", "run", "cancel", "reboot") and not self.writes_enabled:
                    raise LocalFailure("RECOVERY_IN_PROGRESS" if self._recovering else "WRITES_DISABLED")
                if len(self._pending) >= 4:
                    raise LocalFailure("TOO_MANY_PENDING_REQUESTS")
                if self._writer is None or self._writer.is_closing() or self._next_id > 4294967295:
                    raise LocalFailure("DISCONNECTED")
                request_id = self._next_id
                pending.session = self._session
                frame = _request(verb, request_id, fields)
                self._next_id += 1
                self._pending[request_id] = pending
                self._writer.write(frame)
                await self._bounded(self._writer.drain())
            # The response deadline starts after complete request transmission.
            response = await self._bounded(asyncio.shield(pending.future))
            if pending.session == self._session:
                self._retire(request_id, "duplicate")
            return response
        except _Deadline:
            failure = LocalFailure("RESPONSE_TIMEOUT", request_id, uncertain=request_id is not None)
            if pending.session == self._session:
                self._retire(request_id, "late")
            if recover and request_id is not None:
                self._uncertain(pending, failure)
            raise failure from None
        except (ConnectionError, LocalFailure) as exc:
            failure = exc if isinstance(exc, LocalFailure) else LocalFailure("DISCONNECTED", request_id)
            if recover and request_id is not None and failure.code != "MALFORMED_RESPONSE":
                if pending.session == self._session:
                    self._retire(request_id, "late")
                self._uncertain(pending, failure)
            elif recover and request_id is not None and verb in ("set", "run", "cancel", "reboot"):
                self._uncertain(pending, failure)
            raise failure from None
        except asyncio.CancelledError:
            # Caller cancellation cannot withdraw an already transmitted command.
            if request_id is not None and not self._closed:
                if pending.session == self._session:
                    self._retire(request_id, "late")
                self._uncertain(pending, LocalFailure("CALLER_CANCELLED", request_id, uncertain=True))
            raise
        finally:
            self._slots -= 1
            if request_id is not None and self._pending.get(request_id) is pending:
                self._pending.pop(request_id, None)
            if not pending.future.done():
                pending.future.cancel()
            elif not pending.future.cancelled():
                pending.future.exception()

    async def _read(self, reader):
        buffer = bytearray()
        first_byte = None
        try:
            while not self._closed:
                remaining = None if first_byte is None else 2 - (self.clock.monotonic() - first_byte)
                chunk = (await reader.read(4096 - len(buffer)) if remaining is None else
                         await self._bounded(reader.read(4096 - len(buffer)), remaining))
                if not chunk:
                    raise LocalFailure("DISCONNECTED")
                if first_byte is None:
                    first_byte = self.clock.monotonic()
                buffer.extend(chunk)
                while b"\n" in buffer:
                    end = buffer.index(b"\n") + 1
                    frame = bytes(buffer[:end])
                    del buffer[:end]
                    self._receive(frame)
                    # Any partial tail begins with this read, not its predecessor.
                    first_byte = self.clock.monotonic() if buffer else None
                if len(buffer) >= 4096:
                    raise LocalFailure("OVERSIZED_RESPONSE")
        except asyncio.CancelledError:
            raise
        except (_Deadline, LocalFailure, ConnectionError) as exc:
            framing = isinstance(exc, _Deadline) or (isinstance(exc, LocalFailure) and exc.code == "OVERSIZED_RESPONSE")
            code = "INCOMPLETE_RESPONSE" if isinstance(exc, _Deadline) else getattr(exc, "code", "DISCONNECTED")
            self._record("framing" if framing else "disconnected", wire=bytes(buffer), message=code)
            self._broken = True
            self._ready = False
            self.refreshed.clear()
            if self._writer:
                self._writer.close()
            self._lose_pending(code)
            self._start_recovery(direct=True)

    def _lose_pending(self, code):
        for request_id, pending in tuple(self._pending.items()):
            if not pending.future.done():
                failure = LocalFailure(code, request_id, uncertain=True)
                if pending.recover and not self._closed:
                    self._uncertain(pending, failure)
                pending.future.set_exception(failure)
        self._pending.clear()

    def _receive(self, frame):
        request_id = recover_request_id(frame)
        pending = self._pending.get(request_id)
        try:
            response = parse_response(frame)
        except ProtocolError:
            self._record("malformed" if pending else "unattributed_malformed", request_id, pending, wire=frame,
                         message="Malformed response; no receiver-confirmed execution failure")
            if pending and not pending.future.done():
                pending.future.set_exception(LocalFailure("MALFORMED_RESPONSE", request_id, uncertain=True))
            return
        code = response.fields.get("code") if response.verb == "error" else None
        if response.request_id is None or code == "ID_NOT_INCREASING":
            self._record("uncorrelated" if response.request_id is None else "id_rejection", response.request_id,
                         pending, wire=frame, message=render_error(code, response.fields))
            return
        if pending is None or pending.future.done():
            kind = self._retired.get(request_id, "duplicate" if pending else "foreign")
            self._record(kind, request_id, wire=frame, message="Discarded response anomaly")
            return
        expected = ("accepted", "error") if pending.verb in ("run", "cancel", "reboot") else ("ok", "error")
        if response.verb not in expected:
            self._record("malformed", request_id, pending, wire=frame, message="Unexpected response verb")
            pending.future.set_exception(LocalFailure("MALFORMED_RESPONSE", request_id, uncertain=True))
            return
        if code:
            self._record("hardware_error", request_id, pending, wire=frame, message=render_error(code, response.fields))
        if response.verb == "ok":
            active_codes = response.fields.get("fault_codes", [])
            if isinstance(active_codes, list):
                for active_code in active_codes[:16]:
                    if isinstance(active_code, str):
                        self._record("active_fault", request_id, pending, wire=frame,
                                     message=render_error(active_code, {"code": active_code}))
            error_code = response.fields.get("error_code")
            if isinstance(error_code, str):
                self._record("procedure_failure", request_id, pending, wire=frame,
                             message=render_error(error_code, response.fields))
        pending.future.set_result(response)

    def _start_recovery(self, *, direct=False):
        self._broken |= direct
        if not self._closed and not self._recovering:
            self._recovery = asyncio.create_task(self._recover())

    async def _recover(self):
        # Let all failures from this loop turn contribute to the same probe.
        await asyncio.sleep(0)
        try:
            if not self._broken and self._next_id <= 4294967295:
                try:
                    response = await self._exchange("status", {}, recover=False)
                    _general(response)
                    self.general = response
                except LocalFailure:
                    self._broken = True
            else:
                self._broken = True
            while not self._closed:
                if self._broken:
                    await self._disconnect()
                    try:
                        await self._establish()
                    except LocalFailure as exc:
                        self._record("reconnect_failed", message=str(exc))
                        if exc.code == "INCOMPATIBLE_DESCRIPTOR":
                            # Visible incompatible endpoint, never a profile fallback/retry loop.
                            return
                        self._broken = True
                        await self._disconnect()
                        await self.clock.sleep(5)
                        continue
                try:
                    for target in tuple(self._affected):
                        response = await self._exchange(target[0], {"name": target[1]}, recover=False)
                        _refresh_usable(target, response)
                        self.refreshed[target] = response
                        self._affected.discard(target)
                    return
                except LocalFailure as exc:
                    if exc.code in ("UNUSABLE_REFRESH", "MALFORMED_RESPONSE"):
                        self._record("unusable_refresh", exc.request_id, message=str(exc))
                        return
                    self._broken = True
        except asyncio.CancelledError:
            raise

    async def _disconnect(self):
        self._ready = False
        self.refreshed.clear()
        self._lose_pending("DISCONNECTED")
        reader_task, self._reader_task = self._reader_task, None
        if reader_task is not None and reader_task is not asyncio.current_task():
            reader_task.cancel()
            await asyncio.gather(reader_task, return_exceptions=True)
        writer, self._writer = self._writer, None
        if writer is not None:
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), 2)
            except (ConnectionError, TimeoutError):
                writer.transport.abort()

    async def close(self):
        self._closed = True
        if self._recovering:
            self._recovery.cancel()
            await asyncio.gather(self._recovery, return_exceptions=True)
        await self._disconnect()
        for request_id, pending in tuple(self._pending.items()):
            if not pending.future.done():
                pending.future.set_exception(LocalFailure("CLOSED", request_id, uncertain=True))
