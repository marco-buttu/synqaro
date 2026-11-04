"""Manual diagnostic console; never validates or repairs the hardware protocol."""

import asyncio
from datetime import datetime, timezone
import json
import os
import stat
import sys

from synqaro_protocol.transport import TcpConnection


MAX_SUBMISSION_BYTES = 65536
MAX_INPUT_BYTES = 4 * MAX_SUBMISSION_BYTES
_ESCAPES = {"n": 10, "r": 13, "t": 9, "\\": 92}


def decode_raw(text: str) -> bytes:
    """Decode our small explicit notation, not Python literals or protocol fields."""
    if not isinstance(text, str) or len(text) > MAX_INPUT_BYTES or not text.isascii():
        raise ValueError("Use ASCII text and escapes, at most 64 KiB decoded per submission")
    result = bytearray()
    index = 0
    while index < len(text):
        char = text[index]
        index += 1
        if char != "\\":
            result.append(ord(char))
        elif index == len(text):
            raise ValueError("Incomplete escape; use \\\\ for a literal backslash")
        else:
            escape = text[index]
            index += 1
            if escape in _ESCAPES:
                result.append(_ESCAPES[escape])
            elif (escape == "x" and index + 2 <= len(text)
                  and all(c in "0123456789abcdefABCDEF" for c in text[index:index + 2])):
                result.append(int(text[index:index + 2], 16))
                index += 2
            else:
                raise ValueError(r"Invalid escape; use \n, \r, \t, \xNN, or \\")
        if len(result) > MAX_SUBMISSION_BYTES:
            raise ValueError("Submission exceeds 64 KiB; split the diagnostic input")
    return bytes(result)


def render_bytes(data: bytes) -> str:
    """Reversible terminal-safe representation, also used by the GUI."""
    escaped = {10: r"\n", 13: r"\r", 9: r"\t", 92: r"\\"}
    return "".join(escaped.get(value, chr(value) if 32 <= value <= 126 else
                               f"\\x{value:02X}" if value != 27 else r"\x1b") for value in data)


def submission(text: str, *, raw: bool) -> bytes:
    if raw:
        return decode_raw(text)
    try:
        data = text.encode("ascii") + b"\n"
    except UnicodeEncodeError:
        raise ValueError("Use ASCII text; select raw mode and \\xNN for arbitrary bytes") from None
    if len(data) > MAX_SUBMISSION_BYTES:
        raise ValueError("Submission exceeds 64 KiB; split the diagnostic input")
    return data


async def _lines(fd):
    """Read terminal/pipe input without leaving a blocked input thread on EOF."""
    loop = asyncio.get_running_loop()
    regular = stat.S_ISREG(os.fstat(fd).st_mode)
    was_blocking = os.get_blocking(fd)
    buffer = bytearray()
    try:
        if not regular:
            os.set_blocking(fd, False)
        while True:
            if not regular:
                ready = loop.create_future()
                def readable():
                    if not ready.done(): ready.set_result(None)
                loop.add_reader(fd, readable)
                try:
                    await ready
                finally:
                    loop.remove_reader(fd)
            try:
                data = os.read(fd, 4096)
            except BlockingIOError:
                continue
            if not data:
                if buffer:
                    yield bytes(buffer)
                return
            buffer.extend(data)
            while b"\n" in buffer:
                end = buffer.index(10)
                if end > MAX_INPUT_BYTES:
                    raise ValueError("Input line exceeds 256 KiB; split the submission")
                line = bytes(buffer[:end])
                del buffer[:end + 1]
                yield line
            if len(buffer) > MAX_INPUT_BYTES:
                raise ValueError("Input line exceeds 256 KiB; split the submission")
    finally:
        if not regular:
            loop.remove_reader(fd)
            os.set_blocking(fd, was_blocking)


async def run_console(config, *, raw=False, structured=False, emit=None):
    if emit is None:
        def emit(event, *, instance=None, result=None, error=None):
            record = {"version": 1, "event": event, "instance": instance, "ok": error is None,
                      "error" if error is not None else "result": error if error is not None else result}
            print(json.dumps(record) if structured else f"{event}: {error or result}", flush=True)
    def event(kind, **values):
        emit("console." + kind, instance=config.name,
             result={"observed_at": datetime.now(timezone.utc).isoformat(),
                     "time_provenance": "client_receipt_utc", **values})
    def error(exc):
        emit("console.error", instance=config.name, error={"code": "CONSOLE_ERROR",
             "message": str(exc), "actions": [f"simquaro console {config.name}" + (" --raw" if raw else "")]})

    connection = None
    tasks = []
    notice = None
    received = 0
    try:
        connection = await TcpConnection.open(config.host, config.port)
        event("connected", host=config.host, port=config.port, mode="raw" if raw else "line")
        interactive = sys.stdin.isatty() and not structured
        def prompt():
            if interactive:
                print(f"{config.name} [{config.host}:{config.port}]> ", end="", file=sys.stderr, flush=True)
        async def no_data(before):
            await asyncio.sleep(2)
            if received == before:
                event("observation", message="No data received within 2 seconds; connection remains open")
        async def send_input():
            nonlocal notice
            prompt()
            async for line in _lines(sys.stdin.fileno()):
                try:
                    wire = submission(line.decode("ascii"), raw=raw)
                except (UnicodeError, ValueError) as exc:
                    error(exc)
                    prompt()
                    continue
                before = received
                await connection.send(wire)
                event("tx", data=render_bytes(wire), length=len(wire))
                if notice is not None:
                    notice.cancel()
                    await asyncio.gather(notice, return_exceptions=True)
                notice = asyncio.create_task(no_data(before))
                prompt()
            await connection.shutdown_write()
        async def read_output():
            nonlocal received
            while chunk := await connection.receive():
                received += 1
                event("rx", data=render_bytes(chunk), length=len(chunk))
        sender, reader = asyncio.create_task(send_input()), asyncio.create_task(read_output())
        tasks = [sender, reader]
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        if reader in done:
            reader.result()
        else:
            sender.result()
            try:
                await asyncio.wait_for(asyncio.shield(reader), 2)
            except TimeoutError:
                event("observation", message="End of input; observation window ended")
        event("closed", reopen=f"simquaro console {config.name}" + (" --raw" if raw else ""))
        return 0
    except (OSError, ConnectionError, ValueError, TimeoutError) as exc:
        error(exc)
        return 1
    finally:
        for task in tasks + ([notice] if notice is not None else []):
            task.cancel()
        await asyncio.gather(*tasks, *([notice] if notice is not None else []), return_exceptions=True)
        if connection is not None:
            await connection.close()
