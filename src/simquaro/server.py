"""Bounded persistent TCP service and Linux firmware-reboot transmission policy."""

import array
import asyncio
import fcntl
import logging
import termios

from synqaro_protocol.clock import SystemClock
from simquaro.model import SimulatorModel
from simquaro.session import HardwareSession, bounded


_LOGGER = logging.getLogger(__name__)


def _outgoing_bytes(writer):
    """Linux tcp(7) TIOCOUTQ: queued, not yet acknowledged TCP data bytes.

    Zero does not establish that the peer application read the response.
    """
    sock = writer.get_extra_info("socket")
    if sock is None:
        raise ConnectionError("TCP socket unavailable during transmission observation")
    result = array.array("i", [0])
    try:
        fcntl.ioctl(sock.fileno(), termios.TIOCOUTQ, result, True)
    except ValueError as error:
        # A transport closed after drain may retain a socket wrapper with fd -1.
        raise ConnectionError("TCP socket closed during transmission observation") from error
    return result[0]


class HardwareServer:
    def __init__(self, model: SimulatorModel, host, port, *, clock=None, max_clients=16):
        if type(max_clients) is not int or not 1 <= max_clients <= 16:
            raise ValueError("invalid hardware client limit; choose an integer from 1 through 16")
        self.model, self.host, self.port = model, host, port
        self.clock = clock if clock is not None else SystemClock()
        self.max_clients = max_clients
        self._listener = None
        self._closing_listeners = []
        self._sessions = set()
        self._sequence = 0
        self._restart_task = None
        self._closed = False

    @property
    def sessions(self):
        return tuple(self._sessions)

    @property
    def listening(self):
        """Actual listener state; this does not verify hardware communication."""
        return self._listener is not None and self._listener.is_serving()

    async def start(self):
        if self._listener is None:
            self._closed = False
            self._listener = await asyncio.start_server(self._connect, self.host, self.port, limit=4096)
            self.port = self._listener.sockets[0].getsockname()[1]
        return self.host, self.port

    def _connect(self, reader, writer):
        if self._closed or self._restart_task is not None or len(self._sessions) >= self.max_clients:
            writer.transport.abort()
            return
        self._sequence += 1
        session = HardwareSession(self, reader, writer, f"session-{self._sequence}")
        self._sessions.add(session)
        asyncio.create_task(session.run())

    async def _stop_listener(self):
        if self._listener is not None:
            listener, self._listener = self._listener, None
            listener.close()
            # Python 3.12 wait_closed includes existing client transports.
            # Close those after acceptance delivery, before awaiting the listener.
            self._closing_listeners.append(listener)

    async def _close_sessions(self):
        sessions = tuple(self._sessions)
        await asyncio.gather(*(session.close() for session in sessions))
        self._sessions.difference_update(sessions)
        listeners, self._closing_listeners = self._closing_listeners, []
        for listener in listeners:
            await asyncio.wait_for(listener.wait_closed(), 2)

    async def close(self):
        self._closed = True
        if self._restart_task is not None:
            await asyncio.shield(self._restart_task)
        await self._stop_listener()
        await self._close_sessions()

    def _accept_reboot(self, session, response, effects, events):
        if self._restart_task is None:
            self._restart_task = asyncio.create_task(self._restart((session, response, effects, events)))
        return self._restart_task

    async def reboot(self):
        if self._restart_task is None:
            self._restart_task = asyncio.create_task(self._restart())
        await asyncio.shield(self._restart_task)

    async def _restart(self, acceptance=None):
        try:
            await self._stop_listener()
            if acceptance is not None:
                session, response, effects, events = acceptance
                deadline = self.clock.monotonic() + 1
                try:
                    complete = await session.deliver(response, effects, events, deadline=deadline)
                    if not complete:
                        raise ConnectionError("acceptance intentionally lost or malformed")
                    await bounded(session.writer.drain(), self.clock, deadline)
                    while _outgoing_bytes(session.writer):
                        if self.clock.monotonic() >= deadline:
                            raise TimeoutError
                        await self.clock.sleep(min(.01, deadline - self.clock.monotonic()))
                except (ConnectionError, OSError, TimeoutError):
                    _LOGGER.warning("reboot acceptance delivery uncertain boot=%s session=%s id=%s; accepted restart proceeds",
                                    self.model.boot_id, session.session_id, response.request_id)
            await self._close_sessions()
            await self.model.reboot()
            if not self._closed:
                await self.start()
        except Exception:
            _LOGGER.exception("firmware restart failed; correct listener/model failure and restart service")
            raise
        finally:
            self._restart_task = None
