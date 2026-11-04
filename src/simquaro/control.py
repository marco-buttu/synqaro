"""Bounded local test control, independent of simulated hardware delivery.

The runtime supplies a bound socket and owns its filesystem path. This module
never creates, replaces, or unlinks that path. Each connection carries one
version-1 LF-delimited JSON request and one response. Numeric strings in model
snapshots pass through unchanged; control does not invoke the hardware grammar.
"""

import asyncio
import json
import math
from pathlib import Path
import socket
import sys


REQUEST_BYTES = 8192
RESPONSE_BYTES = 65536
DEADLINE = 2.0
_ARGUMENTS = {
    "status": (set(), set()),
    "fault.status": (set(), set()),
    "fault.activate": ({"name"}, {"parameters"}),
    "fault.clear": ({"name"}, set()),
    "fault.schedule": ({"name", "when"}, {"times", "parameters"}),
    "fault.cancel": ({"rule_id"}, set()),
}


class _ControlError(Exception):
    def __init__(self, code, message, action):
        self.response = {"version": 1, "ok": False, "error": {
            "code": code, "message": message, "actions": [action]}}
        super().__init__(message)


def _failure(code, message, action):
    return _ControlError(code, message, action).response


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate object key")
        result[key] = value
    return result


def _constant(value):
    raise ValueError("non-finite JSON number")


def _float(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("non-finite JSON number")
    return result


def _decode(frame):
    try:
        return json.loads(frame.decode("utf-8"), object_pairs_hook=_pairs,
                          parse_constant=_constant, parse_float=_float)
    except (UnicodeError, ValueError, RecursionError):
        raise _ControlError("INVALID_JSON", "Expected strict UTF-8 JSON without duplicate keys or non-finite numbers.",
                            "Send one complete JSON object followed by LF.") from None


def _encode(value, limit, code):
    # iterencode prevents building an arbitrarily large result string before
    # applying the ceiling. Production status containers are separately bounded.
    frame = bytearray()
    try:
        for chunk in json.JSONEncoder(ensure_ascii=True, allow_nan=False, separators=(",", ":")).iterencode(value):
            encoded = chunk.encode("ascii")
            if len(frame) + len(encoded) + 1 > limit:
                raise _ControlError(code, "Control JSON exceeds the allowed frame size.",
                                    "Reduce request arguments or inspect bounded simulator state before retrying.")
            frame.extend(encoded)
    except (TypeError, ValueError, RecursionError):
        raise _ControlError("INVALID_JSON", "Control data cannot be represented as strict JSON.",
                            "Use JSON objects, arrays, strings, booleans, null and finite numbers.") from None
    return bytes(frame) + b"\n"


async def _read_frame(reader, limit, *, response=False):
    frame = bytearray()
    while len(frame) < limit:
        chunk = await reader.read(limit - len(frame))
        if not chunk:
            raise _ControlError("INCOMPLETE_RESPONSE" if response else "INCOMPLETE_REQUEST",
                                "Connection ended before a complete LF-delimited frame.",
                                "Check the local simulator endpoint and send a complete JSON line.")
        newline = chunk.find(b"\n")
        frame.extend(chunk if newline < 0 else chunk[:newline + 1])
        if newline >= 0:
            return bytes(frame)
    raise _ControlError("RESPONSE_TOO_LARGE" if response else "REQUEST_TOO_LARGE",
                        f"Control frame must include LF within {limit} bytes.",
                        "Reduce the JSON frame to the documented byte limit.")


def _request(value):
    if type(value) is not dict or set(value) != {"version", "action", "arguments"}:
        raise _ControlError("INVALID_REQUEST", "Expected only version, action and arguments.",
                            "Send {version: 1, action: <allowed action>, arguments: <object>} as JSON.")
    if type(value["version"]) is not int or value["version"] != 1:
        raise _ControlError("UNSUPPORTED_VERSION", "Control protocol version must be integer 1.",
                            "Use version 1 with a compatible simulator.")
    action, arguments = value["action"], value["arguments"]
    if type(action) is not str or action not in _ARGUMENTS:
        raise _ControlError("UNKNOWN_ACTION", "The requested control action is not allowed.",
                            "Use status, fault.status, fault.activate, fault.clear, fault.schedule or fault.cancel.")
    required, optional = _ARGUMENTS[action]
    if type(arguments) is not dict or not required <= set(arguments) or set(arguments) - required - optional:
        raise _ControlError("INVALID_ARGUMENTS", "Missing or unknown control arguments.",
                            f"Required arguments: {', '.join(sorted(required)) or 'none'}; "
                            f"optional arguments: {', '.join(sorted(optional)) or 'none'}.")
    for name in ("name", "when", "rule_id"):
        if name in arguments and (type(arguments[name]) is not str
                                  or not 1 <= len(arguments[name]) <= 64
                                  or not arguments[name].isascii()
                                  or not arguments[name].isprintable()):
            raise _ControlError("INVALID_ARGUMENTS", f"{name} must be 1–64 printable ASCII characters.",
                                "Choose a documented fault, event or pending rule identifier.")
    if "times" in arguments and type(arguments["times"]) is not int:
        raise _ControlError("INVALID_ARGUMENTS", "times must be a JSON integer.",
                            "Supply an integer from 1 through 4294967295.")
    if "parameters" in arguments:
        parameters = arguments["parameters"]
        if (type(parameters) is not dict or set(parameters) - {"delay_ms"}
                or any(type(value) is not int for value in parameters.values())):
            raise _ControlError("INVALID_ARGUMENTS", "Fault parameters must contain only integer delay_ms when supported.",
                                "Use the offline FaultController.catalog() parameter schema.")
    return action, arguments


async def _close(writer):
    writer.close()
    try:
        await asyncio.wait_for(writer.wait_closed(), DEADLINE)
    except (ConnectionError, OSError, TimeoutError):
        writer.transport.abort()


class ControlServer:
    def __init__(self, sock: socket.socket, model, faults, *, run_token: str, hardware_server=None):
        if (type(run_token) is not str or not 1 <= len(run_token) <= 128
                or not run_token.isascii() or not run_token.isprintable()):
            raise ValueError("invalid run token; supply 1–128 printable ASCII characters")
        if sock.family != socket.AF_UNIX or sock.type != socket.SOCK_STREAM:
            raise ValueError("invalid control socket; supply a prebound Unix stream socket")
        if model.faults is not faults:
            raise ValueError("fault controller differs from model; pass the model's controller")
        self.sock, self.model, self.faults = sock, model, faults
        self.run_token, self.hardware_server = run_token, hardware_server
        self._listener = None
        self._clients = {}
        self._closed = False

    async def start(self):
        if self._closed:
            raise ValueError("control server is closed; construct a new server with a new owned socket")
        if self._listener is None:
            # Python 3.13 added path cleanup even for supplied sockets. Runtime
            # ownership verification, never asyncio, must decide any unlink.
            options = {"cleanup_socket": False} if sys.version_info >= (3, 13) else {}
            self._listener = await asyncio.start_unix_server(self._connect, sock=self.sock,
                                                            limit=REQUEST_BYTES, **options)

    def _connect(self, reader, writer):
        if self._closed or len(self._clients) >= 4:
            writer.transport.abort()
            return
        writer.transport.set_write_buffer_limits(high=RESPONSE_BYTES, low=0)
        task = asyncio.create_task(self._serve(reader, writer))
        self._clients[task] = writer
        task.add_done_callback(self._clients.pop)

    def _dispatch(self, value):
        action, arguments = _request(value)
        # No awaits between validation and mutation: each action is atomic on
        # the owning event loop. All mutation replies have a fixed small shape.
        if action == "status":
            listener = ("unverified" if self.hardware_server is None else
                        "listening" if self.hardware_server.listening else "closed")
            result = {"run_token": self.run_token,
                      "runtime": {"control": "ready", "hardware_listener": listener,
                                  "hardware_communication": "unprobed",
                                  "hardware_communication_verified": False},
                      "model": self.model.snapshot(), "faults": self.faults.snapshot()}
        elif action == "fault.status":
            result = self.faults.snapshot()
        else:
            try:
                if action == "fault.activate":
                    self.faults.activate(arguments["name"], arguments.get("parameters"))
                elif action == "fault.clear":
                    self.faults.clear(arguments["name"])
                elif action == "fault.cancel":
                    self.faults.cancel(arguments["rule_id"])
                else:
                    rule_id = self.faults.schedule(arguments["name"], when=arguments["when"],
                                                   times=arguments.get("times", 1),
                                                   parameters=arguments.get("parameters"))
                    return {"version": 1, "ok": True, "result": {"ok": True, "rule_id": rule_id}}
            except ValueError as error:
                raise _ControlError("INVALID_FAULT", str(error),
                                    "Inspect the offline fault catalog and fault.status, then correct the request.") from None
            result = {"ok": True}
        return {"version": 1, "ok": True, "result": result}

    async def _serve(self, reader, writer):
        try:
            async with asyncio.timeout(DEADLINE):
                try:
                    frame = await _read_frame(reader, REQUEST_BYTES)
                    reply = _encode(self._dispatch(_decode(frame)), RESPONSE_BYTES, "RESULT_TOO_LARGE")
                except _ControlError as error:
                    reply = _encode(error.response, RESPONSE_BYTES, "RESULT_TOO_LARGE")
                writer.write(reply)
                await writer.drain()
        except TimeoutError:
            if not writer.is_closing():
                writer.write(_encode(_failure("TIMEOUT", "Control exchange exceeded 2000 ms.",
                                             "Send a complete JSON line promptly; inspect state before retrying a modification."),
                                     RESPONSE_BYTES, "RESULT_TOO_LARGE"))
        except (ConnectionError, OSError):
            pass
        finally:
            await _close(writer)

    async def close(self):
        self._closed = True
        listener, self._listener = self._listener, None
        if listener is not None:
            listener.close()
        clients = tuple(self._clients.items())
        for task, writer in clients:
            # A cancelled task may never have started its coroutine/finally.
            writer.close()
            task.cancel()
        if clients:
            await asyncio.gather(*(task for task, _ in clients), return_exceptions=True)
            await asyncio.gather(*(_close(writer) for _, writer in clients))
        if listener is not None:
            await listener.wait_closed()


def _response(value):
    if type(value) is dict and type(value.get("version")) is int and value["version"] == 1:
        if value.get("ok") is True and set(value) == {"version", "ok", "result"} and type(value["result"]) is dict:
            return value
        if value.get("ok") is False and set(value) == {"version", "ok", "error"}:
            error = value["error"]
            if (type(error) is dict and set(error) == {"code", "message", "actions"}
                    and all(type(error[key]) is str and error[key] for key in ("code", "message"))
                    and type(error["actions"]) is list and error["actions"]
                    and all(type(action) is str and action for action in error["actions"])):
                return value
    raise _ControlError("INVALID_RESPONSE", "Endpoint returned an invalid control envelope.",
                        "Verify simulator ownership and protocol version before modifying state.")


async def control_request(path: Path, action: str, arguments: dict, *, timeout=DEADLINE) -> dict:
    """Return a complete versioned envelope; never retry a modification.

    Connection/timeout errors cannot establish whether an earlier write executed.
    Callers must verify the run_token from status before lifecycle operations.
    """
    writer = None
    try:
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= DEADLINE:
            raise _ControlError("INVALID_TIMEOUT", "Control timeout must be finite and at most 2 seconds.",
                                "Choose a positive timeout no greater than 2.0 seconds.")
        request = {"version": 1, "action": action, "arguments": arguments}
        frame = _encode(request, REQUEST_BYTES, "REQUEST_TOO_LARGE")
        _request(request)
        async with asyncio.timeout(timeout):
            reader, writer = await asyncio.open_unix_connection(str(path), limit=RESPONSE_BYTES)
            writer.write(frame)
            await writer.drain()
            return _response(_decode(await _read_frame(reader, RESPONSE_BYTES, response=True)))
    except _ControlError as error:
        return error.response
    except TimeoutError:
        return _failure("TIMEOUT", "Local control exchange timed out; modification outcome may be uncertain.",
                        "Inspect simulator status and run identity before deciding whether to retry.")
    except (ConnectionError, OSError, ValueError):
        return _failure("CONNECTION_FAILED", "Cannot complete the local control connection; modification outcome may be uncertain.",
                        "Check the instance runtime, owned endpoint and simulator process status.")
    finally:
        if writer is not None:
            await _close(writer)
