"""Per-tab TCP ownership, snapshot binding, and bounded wire evidence."""

import asyncio
from collections import deque
from dataclasses import dataclass, field
import json
import secrets

from simquaro.configuration import configuration_io, ConfigurationService
from simquaro.console import render_bytes, submission
from simquaro.registry import get_model
from simquaro.web import ServiceError
from synqaro_protocol.client import LocalFailure
from synqaro_protocol.clock import SystemClock
from synqaro_protocol.codec import NumericToken
from synqaro_protocol.transport import TcpConnection


def protocol_value(value, *, item=False):
    """JSON numbers must be explicit tagged decimal tokens, never floats."""
    if type(value) in (str, bool): return value
    if type(value) is dict and set(value) == {"number"}:
        text = value["number"]
        if type(text) is not str or len(text) > 64:
            raise ValueError("Use a decimal spelling of at most 64 characters")
        return NumericToken(text)
    if type(value) is list and not item:
        return [protocol_value(v, item=True) for v in value]
    raise ValueError('Use strings, booleans, flat lists, or {"number":"5.1"}')


def json_value(value):
    if isinstance(value, NumericToken): return {"number": value.text}
    if isinstance(value, dict): return {k: json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [json_value(v) for v in value]
    return value


@dataclass
class _Session:
    id: str
    target: str
    mode: str
    config: object
    revision: str
    source: str
    deadline: float
    state: str = "connecting"
    client: object = None
    connection: object = None
    reader: object = None
    notice: object = None
    closer: object = None
    opener: object = None
    events: deque = field(default_factory=deque)
    sizes: deque = field(default_factory=deque)
    total_bytes: int = 0
    sequence: int = 0
    received: int = 0
    sending: bool = False


class SessionManager:
    def __init__(self, store, *, clock=None, busy=None):
        self.store, self.clock = store, clock or SystemClock()
        self.busy = busy or (lambda target: False)
        self._sessions = {}
        self._sweeper = None
        self._closed = False

    def _get(self, sid):
        if sid not in self._sessions:
            raise ServiceError("UNKNOWN_SESSION", "Session expired or closed; reconnect explicitly")
        return self._sessions[sid]

    def _event(self, session, kind, **values):
        session.sequence += 1
        event = {"cursor": session.sequence, "kind": kind,
                 "observed_at": self.clock.utcnow().isoformat(),
                 "time_provenance": "client_receipt_utc", **values}
        size = len(json.dumps(event, ensure_ascii=True).encode())
        if size > 1048576:
            event = {"cursor": session.sequence, "kind": "error", "message": "Event too large"}
            size = len(json.dumps(event))
        session.events.append(event)
        session.sizes.append(size)
        session.total_bytes += size
        while len(session.events) > 256 or session.total_bytes > 1048576:
            session.events.popleft()
            session.total_bytes -= session.sizes.popleft()

    async def connect(self, target, mode):
        if mode not in ("managed", "line", "raw"):
            raise ValueError("Choose managed, line, or raw mode")
        snapshot = await configuration_io(self.store.load)
        entry = ConfigurationService.target(snapshot, target)
        if self._closed: raise ServiceError("SERVER_CLOSING", "Server is shutting down")
        if self.busy(target): raise ServiceError("TARGET_BUSY", "Wait for this target's job to finish")
        if len(self._sessions) >= 16 or sum(s.target == target for s in self._sessions.values()) >= 4:
            raise ServiceError("SESSION_LIMIT", "Close an unused connection before connecting again")
        session = _Session(secrets.token_urlsafe(24), target, mode, entry.config,
                           snapshot.revision, snapshot.source, self.clock.monotonic() + 120)
        self._sessions[session.id] = session  # Reserve before any connection await.
        if self._sweeper is None: self._sweeper = asyncio.create_task(self._sweep())
        try:
            session.opener = asyncio.create_task(self._open(session))
            await session.opener
            session.state = "connected"
            self._event(session, "connected", mode=mode, host=entry.config.host, port=entry.config.port)
            return self.events(session.id, 0)
        except BaseException:
            if session.id in self._sessions: await self.disconnect(session.id)
            raise

    async def _open(self, session):
        config = session.config
        if session.mode == "managed":
            definition = get_model(config.model)
            if definition.client_factory is None: raise ValueError("Model has no managed client profile")
            session.client = definition.client_factory(config.host, config.port, config.settings)
            session.client.clock = self.clock
            def observe(e):
                self._event(session, e.kind, data=render_bytes(e.wire), message=e.message,
                            request_id=e.request_id, verb=e.verb, hardware_id=e.hardware_id,
                            observed_at=e.received_at, time_provenance=e.time_provenance)
            session.client.observe = observe
            await session.client.connect()
        else:
            session.connection = await TcpConnection.open(config.host, config.port, clock=self.clock)
            session.reader = asyncio.create_task(self._read(session))

    async def _read(self, session):
        try:
            while data := await session.connection.receive():
                session.received += 1
                self._event(session, "rx", data=render_bytes(data), length=len(data))
            self._event(session, "eof", message="Remote peer closed TCP; reconnect explicitly")
        except (OSError, TimeoutError) as exc:
            self._event(session, "error", message=str(exc)[:1024])
        finally:
            session.state = "closed"
            await session.connection.close()

    async def _no_data(self, session, before):
        await self.clock.sleep(2)
        if session.received == before and session.state == "connected":
            self._event(session, "observation", message="No data within 2 seconds; TCP remains open")

    async def submit(self, sid, payload):
        session = self._get(sid)
        if type(payload) is not dict: raise ValueError("Expected a request object")
        if session.state != "connected":
            raise ServiceError("DISCONNECTED", "Reconnect explicitly; no request was replayed")
        if session.mode == "managed":
            if set(payload) - {"verb", "fields"} or type(payload.get("verb")) is not str or type(payload.get("fields", {})) is not dict:
                raise ValueError("Supply verb and fields only")
            fields = {k: protocol_value(v) for k, v in payload.get("fields", {}).items()}
            try:
                response = await session.client.request(payload["verb"], fields)
            except LocalFailure as exc:
                self._event(session, "local_failure", code=exc.code, request_id=exc.request_id,
                            uncertain=exc.uncertain, message=str(exc))
                raise
            result = {"verb": response.verb, "id": response.request_id, "fields": json_value(response.fields)}
            self._event(session, "response", result=result)
            return result
        if set(payload) != {"text"} or type(payload["text"]) is not str:
            raise ValueError("Supply text only")
        wire = submission(payload["text"], raw=session.mode == "raw")
        if session.sending: raise ServiceError("TARGET_BUSY", "Wait for the current TCP send")
        session.sending = True
        try:
            if session.notice is not None:
                session.notice.cancel()
                await asyncio.gather(session.notice, return_exceptions=True)
            before = session.received
            await session.connection.send(wire)
            self._event(session, "tx", data=render_bytes(wire), length=len(wire))
            session.notice = asyncio.create_task(self._no_data(session, before))
            return {"sent_bytes": len(wire)}
        except BaseException:
            self._event(session, "local_failure", uncertain=True,
                        message="Send interrupted; delivery unknown. Do not automatically retry")
            raise
        finally:
            session.sending = False

    def events(self, sid, after=0):
        session = self._get(sid)
        if type(after) is not int or after < 0: raise ValueError("Cursor must be a nonnegative integer")
        oldest = session.events[0]["cursor"] if session.events else session.sequence + 1
        return {"id": session.id, "target": session.target, "mode": session.mode,
                "state": session.state, "revision": session.revision, "source": session.source,
                "host": session.config.host, "port": session.config.port,
                "expected_hardware_id": (session.client.expected_hardware_id if session.client is not None else
                                         getattr(session.config.settings, "hardware_id", None)),
                "identity_verified": bool(session.client is not None and session.client.ready),
                "oldest": oldest, "newest": session.sequence, "gap": after < oldest - 1,
                "events": [dict(e) for e in session.events if e["cursor"] > after]}

    def heartbeat(self, sid):
        self._get(sid).deadline = self.clock.monotonic() + 120
        return {"lease_seconds": 120}

    def has_target(self, target):
        return any(s.target == target for s in self._sessions.values())

    async def disconnect(self, sid):
        session = self._get(sid)
        if session.closer is None:
            session.closer = asyncio.create_task(self._disconnect(session))
        try:
            return await asyncio.shield(session.closer)
        except asyncio.CancelledError:
            await session.closer
            raise

    async def _disconnect(self, session):
        sid = session.id
        session.state = "closed"
        tasks = [t for t in (session.opener, session.reader, session.notice) if t is not None]
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if session.client is not None: await session.client.close()
        if session.connection is not None: await session.connection.close()
        self._event(session, "closed", message="TCP closed; firmware procedures were not cancelled")
        result = self.events(sid, 0)
        self._sessions.pop(sid, None)
        return result

    async def disconnect_target(self, target):
        for sid in [sid for sid, s in self._sessions.items() if s.target == target]:
            await self.disconnect(sid)

    async def expire(self):
        for sid in [sid for sid, s in self._sessions.items() if s.deadline <= self.clock.monotonic()]:
            if sid in self._sessions: await self.disconnect(sid)

    async def _sweep(self):
        while True:
            await self.clock.sleep(10)
            await self.expire()

    async def close(self):
        self._closed = True
        if self._sweeper is not None:
            self._sweeper.cancel()
            await asyncio.gather(self._sweeper, return_exceptions=True)
        for sid in list(self._sessions): await self.disconnect(sid)
