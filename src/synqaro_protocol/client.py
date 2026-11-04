"""Managed hardware client: correlation, bounded evidence, and uncertain-outcome recovery."""

import asyncio
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from functools import partial

from synqaro_protocol.clock import SystemClock, bounded
from synqaro_protocol.errors import ProtocolError, render_error
from synqaro_protocol.codec import NumericToken, Request, Response, Value, encode_request, parse_response, recover_request_id
from synqaro_protocol.transport import TcpConnection

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


@dataclass(frozen=True)
class ClientLimits:
    max_message_bytes: int = 4096
    incomplete_timeout: float = 2.0
    response_timeout: float = 2.0
    connect_timeout: float = 2.0
    reconnect_pause: float = 5.0
    max_pending: int = 4

    def __post_init__(self):
        if (self.max_message_bytes != 4096 or self.max_pending != 4
                or any(type(n) not in (int, float) or not 0 < n <= 60
                       for n in (self.incomplete_timeout, self.response_timeout,
                                 self.connect_timeout, self.reconnect_pause))):
            raise ValueError("Unsupported wire limits or invalid client deadlines")


@dataclass(frozen=True)
class ClientContract:
    validate_descriptor: object
    validate_status: object
    refresh_usable: object
    error_catalog: Mapping
    limits: ClientLimits = ClientLimits()


class ProtocolClient:
    def __init__(self, host, port, *, contract, expected_hardware_id,
                 clock=None, read_only=False, observe=None):
        self.host, self.port = host, port
        self.clock = clock or SystemClock()
        self.contract, self.limits = contract, contract.limits
        self.read_only, self.observe = read_only, observe
        self._render_error = partial(render_error, catalog=contract.error_catalog)
        if not isinstance(expected_hardware_id, str) or not expected_hardware_id:
            raise ValueError("Supply an independently configured expected hardware identity")
        self.expected_hardware_id = expected_hardware_id
        self.descriptor = self.general = None
        self.evidence = deque(maxlen=256)
        self.uncertainties = deque(maxlen=256)
        self.refreshed = {}
        self._writer = None
        self._connection = None
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
        return (not self.read_only and self._ready and self._session_live()
                and not self._affected and not self._recovering)

    @property
    def ready(self):
        return self._ready and self._session_live()

    def _session_live(self, session=None):
        return (not self._closed and not self._broken
                and (session is None or session == self._session)
                and self._writer is not None and not self._writer.is_closing()
                and self._reader_task is not None and not self._reader_task.done())

    def _require_live(self, session):
        if not self._session_live(session):
            raise LocalFailure("DISCONNECTED")

    @property
    def _recovering(self):
        return self._recovery is not None and not self._recovery.done()

    async def _bounded(self, awaitable, seconds=None):
        seconds = self.limits.response_timeout if seconds is None else seconds
        try:
            return await bounded(awaitable, self.clock, self.clock.monotonic() + max(0, seconds))
        except TimeoutError:
            raise _Deadline from None

    def _record(self, kind, request_id=None, pending=None, *, wire=b"", message=""):
        event = Evidence(kind, request_id, pending.verb if pending else None,
                         pending.fields.get("name") if pending else None,
                         self.expected_hardware_id, self.clock.utcnow().isoformat(), "client_receipt_utc",
                         "".join(ch if " " <= ch <= "~" else "?" for ch in message[:1024]), wire[:4096])
        self.evidence.append(event)
        if self.observe is not None:
            try:
                self.observe(event)
            except Exception:
                pass  # Diagnostics cannot affect transaction correctness.
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
        try:
            self._connection = await TcpConnection.open(
                self.host, self.port, clock=self.clock, timeout=self.limits.connect_timeout)
            self._writer = self._connection.writer
        except TimeoutError:
            raise LocalFailure("CONNECT_TIMEOUT") from None
        except OSError:
            raise LocalFailure("DISCONNECTED") from None
        self._next_id = 1
        self._session += 1
        session = self._session
        self._retired.clear()
        self._broken = False
        self._reader_task = asyncio.create_task(self._read(self._connection))
        response = await self._exchange("get", {"name": "configuration"}, recover=False)
        try:
            self.contract.validate_descriptor(response, self.expected_hardware_id)
        except LocalFailure:
            self._record("incompatible_descriptor", response.request_id, wire=b"", message="Unsupported descriptor; writes disabled")
            raise
        general = await self._exchange("status", {}, recover=False)
        self.contract.validate_status(general)
        self._require_live(session)
        self.descriptor = response
        self.general = general
        self._ready = True

    async def request(self, verb: str, fields: Mapping[str, Value] | None = None) -> Response:
        fields = dict(fields or {})
        if self._closed:
            raise LocalFailure("CLOSED")
        modifying = verb in ("set", "run", "cancel", "reboot")
        if modifying and self.read_only:
            raise LocalFailure("READ_ONLY_CLIENT")
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
        session = self._session
        response = await self._exchange(verb, fields)
        target = (verb, fields.get("name"))
        if isinstance(fields.get("name"), str) and target in self._affected and self._session_live(session):
            try:
                self.contract.refresh_usable(target, response)
            except LocalFailure:
                pass
            else:
                self.refreshed[target] = response
                self._affected.discard(target)
        return response

    async def _exchange(self, verb, fields, *, recover=True):
        if self.read_only and verb in ("set", "run", "cancel", "reboot"):
            raise LocalFailure("READ_ONLY_CLIENT")
        if verb not in ("get", "set", "run", "status", "cancel", "reboot"):
            raise ValueError("Unsupported verb; use a diagnostic console for invalid requests")
        if self._slots >= self.limits.max_pending:
            raise LocalFailure("TOO_MANY_PENDING_REQUESTS")
        self._slots += 1
        pending = _Pending(verb, dict(fields), asyncio.get_running_loop().create_future(), self._session, recover)
        request_id = None
        try:
            async with self._send_lock:
                if recover and verb in ("set", "run", "cancel", "reboot") and not self.writes_enabled:
                    raise LocalFailure("RECOVERY_IN_PROGRESS" if self._recovering else "WRITES_DISABLED")
                if len(self._pending) >= self.limits.max_pending:
                    raise LocalFailure("TOO_MANY_PENDING_REQUESTS")
                if self._writer is None or self._writer.is_closing() or self._next_id > 4294967295:
                    raise LocalFailure("DISCONNECTED")
                request_id = self._next_id
                pending.session = self._session
                frame = encode_request(Request(verb, request_id, {}, fields))
                self._next_id += 1
                self._pending[request_id] = pending
                self._record("tx", request_id, pending, wire=frame)
                await self._bounded(self._connection.send(frame))
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

    async def _read(self, connection):
        buffer = bytearray()
        first_byte = None
        try:
            while not self._closed:
                remaining = (None if first_byte is None else
                             self.limits.incomplete_timeout - (self.clock.monotonic() - first_byte))
                read = connection.receive(self.limits.max_message_bytes - len(buffer))
                chunk = await read if remaining is None else await self._bounded(read, remaining)
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
                if len(buffer) >= self.limits.max_message_bytes:
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
        self._record("rx", request_id, pending, wire=frame)
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
                         pending, wire=frame, message=self._render_error(code, response.fields))
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
            self._record("hardware_error", request_id, pending, wire=frame, message=self._render_error(code, response.fields))
        if response.verb == "ok":
            active_codes = response.fields.get("fault_codes", [])
            if isinstance(active_codes, list):
                for active_code in active_codes[:16]:
                    if isinstance(active_code, str):
                        self._record("active_fault", request_id, pending, wire=frame,
                                     message=self._render_error(active_code, {"code": active_code}))
            error_code = response.fields.get("error_code")
            if isinstance(error_code, str):
                self._record("procedure_failure", request_id, pending, wire=frame,
                             message=self._render_error(error_code, response.fields))
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
                    session = self._session
                    response = await self._exchange("status", {}, recover=False)
                    self.contract.validate_status(response)
                    self._require_live(session)
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
                        await self.clock.sleep(self.limits.reconnect_pause)
                        continue
                try:
                    for target in tuple(self._affected):
                        session = self._session
                        response = await self._exchange(target[0], {"name": target[1]}, recover=False)
                        self._require_live(session)
                        self.contract.refresh_usable(target, response)
                        self.refreshed[target] = response
                        self._affected.discard(target)
                    self._require_live(self._session)
                    if self._affected:
                        continue
                    return
                except LocalFailure as exc:
                    if not self._session_live():
                        self._broken = True
                        continue
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
        connection, self._connection = self._connection, None
        self._writer = None
        if connection is not None:
            await connection.close()

    async def close(self):
        self._closed = True
        if self._recovering:
            self._recovery.cancel()
            await asyncio.gather(self._recovery, return_exceptions=True)
        await self._disconnect()
        for request_id, pending in tuple(self._pending.items()):
            if not pending.future.done():
                pending.future.set_exception(LocalFailure("CLOSED", request_id, uncertain=True))
