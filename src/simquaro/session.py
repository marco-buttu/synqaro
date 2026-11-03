"""One bounded hardware stream, ordered admission, and serialized reply writes."""

import asyncio
from dataclasses import dataclass
import logging

from synqaro_protocol.errors import ProtocolError
from simquaro.faults import FaultContext
from synqaro_protocol.codec import MAX_MESSAGE_BYTES, NumericToken, Response, encode_response, parse_request, recover_request_id


_LOGGER = logging.getLogger(__name__)


from synqaro_protocol.clock import bounded


def _text(value, limit=64):
    if not isinstance(value, str):
        return None
    return "".join(c if " " <= c <= "~" else "?" for c in value[:limit]) or None


@dataclass
class _Hold:
    when: str
    release: asyncio.Future


class HardwareSession:
    """Private to a connection. Model work remains owned by the shared model."""

    def __init__(self, server, reader, writer, session_id):
        self.server, self.reader, self.writer = server, reader, writer
        self.model, self.clock = server.model, server.clock
        self.session_id = session_id
        self.high_water = 0
        self._pending = set()
        self._holds = {}
        self._writer_lock = asyncio.Lock()
        self._closed = False
        self._runner = None
        writer.transport.set_write_buffer_limits(high=16384, low=4096)

    @property
    def pending_count(self):
        return len(self._pending)

    async def run(self):
        self._runner = asyncio.current_task()
        buffer = b""
        first_byte = None
        received_at = None
        try:
            while not self._closed:
                if b"\n" in buffer:
                    frame, buffer = buffer.split(b"\n", 1)
                    # Before each read the retained buffer contains no LF.
                    # All bytes after this LF therefore came in the latest read.
                    first_byte = received_at if buffer else None
                    admission = self._admit(frame + b"\n")
                    if buffer and not buffer.endswith(b"\n"):
                        await bounded(admission, self.clock, first_byte + 2)
                    else:
                        await admission
                    continue
                if len(buffer) >= MAX_MESSAGE_BYTES:
                    break
                read = self.reader.read(MAX_MESSAGE_BYTES - len(buffer))
                chunk = (await read if first_byte is None else
                         await bounded(read, self.clock, first_byte + 2))
                if not chunk:
                    break
                received_at = self.clock.monotonic()
                if first_byte is None:
                    first_byte = received_at
                buffer += chunk
        except (ConnectionError, OSError, TimeoutError):
            pass
        finally:
            await self.close()
            self.server._sessions.discard(self)

    async def _admit(self, frame):
        request_id = recover_request_id(frame)
        if request_id is None:
            await self._diagnostic(Response("error", None, {"code": "INVALID_ID"}))
            return
        if request_id <= self.high_water:
            fields = {"code": "ID_NOT_INCREASING", "last_id": NumericToken(str(self.high_water))}
            try:
                request = parse_request(frame)
                fields["rejected_verb"] = _text(request.verb, 128)
                target = _text(request.fields.get("name"), 128)
                if target is not None:
                    fields["rejected_name"] = target
            except ProtocolError:
                pass
            timestamp = self.model.utc_timestamp()
            if timestamp is not None:
                fields["received_at"] = timestamp
            await self._diagnostic(Response("error", request_id, fields))
            return
        self.high_water = request_id
        try:
            request = parse_request(frame)
        except ProtocolError as error:
            fields = {key: _text(value, 128) if isinstance(value, str) else value
                      for key, value in error.fields.items()}
            await self._diagnostic(Response("error", request_id, {"code": error.code, **fields}))
            return
        if len(self._pending) >= 4:
            await self._diagnostic(Response("error", request_id, {
                "code": "TOO_MANY_PENDING_REQUESTS", "limit": NumericToken("4")}))
            return
        task = asyncio.create_task(self._execute(request))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)
        # Start admitted handlers in receive order before an inline rejection's
        # response_ready hook can overtake them. Execution remains independent.
        await asyncio.sleep(0)

    def _effects(self, response, request=None):
        return self.model.faults.emit(FaultContext(
            "response_ready", self.session_id, response.request_id,
            _text(request.verb) if request else None,
            _text(request.fields.get("name")) if request else None))

    async def _diagnostic(self, response):
        # Receive-loop backpressure bounds diagnostics without another task/queue.
        effects = self._effects(response)
        self.model.faults.validate_delivery_effects(effects)
        await self.deliver(response, effects, {"response_ready"})

    async def _execute(self, request):
        try:
            reply = await self.model.handle(request, session_id=self.session_id)
            # No delivery await may intervene between handle and this hook.
            effects = reply.delivery_effects + self._effects(reply.response, request)
            self.model.faults.validate_delivery_effects(effects)
            events = {"response_ready", *reply.delivery_events}
            if reply.reboot_requested:
                await asyncio.shield(self.server._accept_reboot(self, reply.response, effects, events))
            else:
                await self.deliver(reply.response, effects, events)
        except (ConnectionError, OSError, TimeoutError, ValueError, ProtocolError):
            self.writer.transport.abort()
            await self.close()

    async def deliver(self, response, effects, events, *, deadline=None):
        """Return true only when a complete ordinary frame was enqueued/drained."""
        frame = encode_response(response)
        names = {effect.name for effect in effects}
        releases = [(key, hold) for key, hold in self._holds.items() if hold.when in events]
        for key, _ in releases:
            self._holds.pop(key)
        reorder = next((effect for effect in effects if effect.name == "reorder_responses"), None)
        hold = None
        if reorder is not None and not any(key == reorder.rule_id for key, _ in releases):
            hold = _Hold(reorder.when or "response_ready", asyncio.get_running_loop().create_future())
            self._holds[reorder.rule_id] = hold
        try:
            if "disconnect" in names:
                self._log_wire("dropped", response, frame, effects)
                self.writer.close()
                return False
            if "drop_response" in names:
                self._log_wire("dropped", response, frame, effects)
                return False
            for effect in effects:
                if effect.name == "delay_response":
                    wait = self.clock.sleep(effect.parameters["delay_ms"] / 1000)
                    if deadline is None:
                        await wait
                    else:
                        await bounded(wait, self.clock, deadline)
            if hold is not None:
                try:
                    await bounded(asyncio.shield(hold.release), self.clock,
                                  min(self.clock.monotonic() + 2, deadline) if deadline is not None
                                  else self.clock.monotonic() + 2)
                except TimeoutError:
                    if deadline is not None and self.clock.monotonic() >= deadline:
                        raise
                finally:
                    if self._holds.get(reorder.rule_id) is hold:
                        self._holds.pop(reorder.rule_id)
            if "malformed_response" in names:
                # Preserve the trustworthy metadata ID, damage only field grammar.
                frame = frame.replace(b": ", b"; ", 1) if b": " in frame else frame[:-1] + b"; broken\n"
            if "omit_lf" in names:
                frame = frame[:-1]
            await self._write(frame, deadline)
            self._log_wire("emitted", response, frame, effects)
            return "omit_lf" not in names and "malformed_response" not in names
        finally:
            for _, previous in releases:
                if not previous.release.done():
                    previous.release.set_result(None)

    def _log_wire(self, action, response, frame, effects):
        _LOGGER.info("wire %s boot=%s session=%s id=%s rules=%s monotonic=%s bytes=%r",
                     action, self.model.boot_id, self.session_id, response.request_id,
                     [effect.rule_id for effect in effects], self.clock.monotonic(), frame)

    async def _write(self, frame, deadline=None):
        if deadline is None:
            deadline = self.clock.monotonic() + 2
        async def send():
            async with self._writer_lock:
                if self._closed:
                    raise ConnectionError("hardware session closed")
                self.writer.write(frame)
                await self.writer.drain()
        await bounded(send(), self.clock, deadline)

    async def close(self):
        if self._closed:
            return
        self._closed = True
        self.writer.close()
        current = asyncio.current_task()
        tasks = [task for task in self._pending if task is not current]
        if self._runner is not None and self._runner is not current:
            tasks.append(self._runner)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._holds.clear()
        try:
            await asyncio.wait_for(self.writer.wait_closed(), 2)
        except (ConnectionError, OSError, TimeoutError):
            self.writer.transport.abort()
