"""Byte-oriented TCP operations; protocol validation belongs to the caller."""

import asyncio
from contextlib import suppress

from synqaro_protocol.clock import SystemClock, bounded


class TcpConnection:
    def __init__(self, reader, writer, *, clock, timeout=2.0):
        self.reader, self.writer = reader, writer
        self.clock, self.timeout = clock, timeout
        self._send_lock = asyncio.Lock()

    @classmethod
    async def open(cls, host, port, *, clock=None, timeout=2.0):
        clock = clock if clock is not None else SystemClock()
        operation = asyncio.create_task(asyncio.open_connection(host, port, limit=4096))
        try:
            reader, writer = await bounded(operation, clock, clock.monotonic() + timeout)
            return cls(reader, writer, clock=clock, timeout=timeout)
        except BaseException:
            if operation.done() and not operation.cancelled() and operation.exception() is None:
                _, writer = operation.result()
                writer.close()
                with suppress(ConnectionError, OSError, TimeoutError):
                    await bounded(writer.wait_closed(), clock, clock.monotonic() + timeout)
            raise

    async def send(self, data: bytes):
        if not isinstance(data, bytes):
            raise TypeError("send requires bytes")
        deadline = self.clock.monotonic() + self.timeout
        async def write():
            async with self._send_lock:
                for offset in range(0, len(data), 4096):
                    self.writer.write(data[offset:offset + 4096])
                    await self.writer.drain()
        await bounded(write(), self.clock, deadline)

    async def receive(self, max_bytes=4096) -> bytes:
        if type(max_bytes) is not int or not 1 <= max_bytes <= 4096:
            raise ValueError("read size must be from 1 through 4096 bytes")
        return await self.reader.read(max_bytes)

    async def shutdown_write(self):
        if self.writer.can_write_eof():
            self.writer.write_eof()
            await bounded(self.writer.drain(), self.clock, self.clock.monotonic() + self.timeout)

    async def close(self):
        self.writer.close()
        try:
            await bounded(self.writer.wait_closed(), self.clock, self.clock.monotonic() + self.timeout)
        except (ConnectionError, OSError, TimeoutError):
            self.writer.transport.abort()
