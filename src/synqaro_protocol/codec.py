"""Bounded hardware-independent ASCII protocol syntax and message types.

The codec does not advance ID high-water marks, admit requests, or change state.
Numeric tokens retain their wire spelling until a field-specific validator runs.
"""

from collections.abc import Mapping
from dataclasses import dataclass
import re
from typing import TypeAlias

from synqaro_protocol.errors import ProtocolError


MAX_MESSAGE_BYTES = 4096
MAX_REQUEST_ID = 4294967295
_NAME = re.compile(r"[a-z][a-z0-9_]*", re.ASCII)
_NUMBER = re.compile(r"[+-]?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?", re.ASCII)
_CODE = re.compile(r"[A-Z][A-Z0-9_]*", re.ASCII)
_HEADER = re.compile(r'#([^ <>:,\[\]"\\=]+) +<', re.ASCII)


@dataclass(frozen=True)
class NumericToken:
    text: str

    def __post_init__(self) -> None:
        if (not isinstance(self.text, str) or len(self.text) > MAX_MESSAGE_BYTES
                or _NUMBER.fullmatch(self.text) is None):
            raise ValueError("invalid numeric token; supply a bounded decimal numeric spelling")

    def __str__(self) -> str:
        return self.text


Scalar: TypeAlias = str | bool | NumericToken
Value: TypeAlias = Scalar | list[Scalar]


@dataclass(frozen=True)
class Request:
    verb: str
    request_id: int
    metadata: Mapping[str, Value]
    fields: Mapping[str, Value]


@dataclass(frozen=True)
class Response:
    verb: str
    request_id: int | None
    fields: Mapping[str, Value]


class _SyntaxError(Exception):
    pass


class _Parser:
    def __init__(self, text: str, position: int = 0):
        self.text = text
        self.position = position

    def spaces(self) -> None:
        while self.position < len(self.text) and self.text[self.position] == " ":
            self.position += 1

    def take(self, character: str) -> bool:
        if self.text.startswith(character, self.position):
            self.position += 1
            return True
        return False

    def scalar(self, metadata: bool = False) -> Scalar:
        if self.take('"'):
            result = []
            while self.position < len(self.text):
                character = self.text[self.position]
                self.position += 1
                if character == '"':
                    return "".join(result)
                if character == "\\":
                    if self.position == len(self.text) or self.text[self.position] not in ('"', "\\"):
                        raise _SyntaxError
                    character = self.text[self.position]
                    self.position += 1
                if not " " <= character <= "~":
                    raise _SyntaxError
                result.append(character)
            raise _SyntaxError
        start = self.position
        while self.position < len(self.text) and self.text[self.position] not in " ,>]":
            character = self.text[self.position]
            if character in '<[="\\' or (metadata and character == ":") or not " " <= character <= "~":
                raise _SyntaxError
            self.position += 1
        token = self.text[start:self.position]
        if not token:
            raise _SyntaxError
        if token in ("true", "false"):
            return token == "true"
        if _NUMBER.fullmatch(token):
            return NumericToken(token)
        return token

    def value(self, metadata: bool = False) -> Value:
        if not self.take("["):
            return self.scalar(metadata)
        items = []
        self.spaces()
        if self.take("]"):
            return items
        while True:
            items.append(self.scalar(metadata))
            self.spaces()
            if self.take("]"):
                return items
            if not self.take(","):
                raise _SyntaxError
            self.spaces()

    def pairs(self, metadata: bool = False) -> list[tuple[str, Value]]:
        pairs = []
        self.spaces()
        while True:
            match = _NAME.match(self.text, self.position)
            if match is None:
                raise _SyntaxError
            key = match.group()
            self.position = match.end()
            self.spaces()
            if not self.take("="):
                raise _SyntaxError
            self.spaces()
            value = self.value(metadata)
            pairs.append((key, value))
            self.spaces()
            if metadata and self.take(">"):
                return pairs
            if not metadata and self.position == len(self.text):
                return pairs
            if not self.take(","):
                raise _SyntaxError
            self.spaces()


def _header(text: str) -> tuple[str, list[tuple[str, Value]], _Parser]:
    match = _HEADER.match(text)
    if match is None:
        raise _SyntaxError
    parser = _Parser(text, match.end())
    return match.group(1), parser.pairs(metadata=True), parser


def _id(value: Value) -> int | None:
    if not isinstance(value, NumericToken) or re.fullmatch(r"[0-9]+", value.text) is None:
        return None
    digits = value.text.lstrip("0")
    if not digits or len(digits) > 10 or (len(digits) == 10 and digits > "4294967295"):
        return None
    return int(digits)


def _bounded_frame(frame: bytes) -> bool:
    return (isinstance(frame, bytes) and 0 < len(frame) <= MAX_MESSAGE_BYTES
            and frame.endswith(b"\n") and frame.count(b"\n") == 1)


def recover_request_id(frame: bytes) -> int | None:
    """Recover only an unambiguous ID from a complete, bounded metadata section.

    Malformed payload bytes do not destroy an otherwise trustworthy header.
    Broken metadata, incomplete/oversized frames, or a second metadata ID do.
    """
    if not _bounded_frame(frame):
        return None
    try:
        _, pairs, _ = _header(frame[:-1].decode("latin1"))
    except _SyntaxError:
        return None
    ids = [value for key, value in pairs if key == "id"]
    return _id(ids[0]) if len(ids) == 1 else None


def _section(pairs: list[tuple[str, Value]], request_id: int | None) -> dict[str, Value]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError("DUPLICATE_PARAMETER", {"parameter": key}, request_id)
        result[key] = value
    return result


def _parse(frame: bytes, request_id: int | None) -> tuple[str, dict[str, Value], dict[str, Value]]:
    if not _bounded_frame(frame) or any(byte < 32 or byte > 126 for byte in frame[:-1]):
        raise ProtocolError("MALFORMED_REQUEST", {}, request_id)
    try:
        verb, pairs, parser = _header(frame[:-1].decode("ascii"))
        if _NAME.fullmatch(verb) is None:
            raise _SyntaxError
        metadata = _section(pairs, request_id)
        parser.spaces()
        fields = {}
        if parser.position != len(parser.text):
            if not parser.take(":"):
                raise _SyntaxError
            fields = _section(parser.pairs(), request_id)
        return verb, metadata, fields
    except _SyntaxError:
        raise ProtocolError("MALFORMED_REQUEST", {}, request_id) from None


def parse_request(frame: bytes) -> Request:
    request_id = recover_request_id(frame)
    if request_id is None:
        raise ProtocolError("INVALID_ID", {})
    verb, metadata, fields = _parse(frame, request_id)
    return Request(verb, request_id, metadata, fields)


def _validate_response(response: Response) -> None:
    request_id = response.request_id
    if response.verb not in ("ok", "accepted", "error"):
        raise ProtocolError("MALFORMED_REQUEST", {}, request_id)
    if request_id is None:
        if response != Response("error", None, {"code": "INVALID_ID"}):
            raise ProtocolError("INVALID_ID", {})
    elif type(request_id) is not int or not 1 <= request_id <= MAX_REQUEST_ID:
        raise ProtocolError("INVALID_ID", {})
    if response.verb == "error":
        code = response.fields.get("code")
        if not isinstance(code, str) or _CODE.fullmatch(code) is None:
            raise ProtocolError("MALFORMED_REQUEST", {}, request_id)
        if code == "INVALID_ID" and request_id is not None:
            raise ProtocolError("MALFORMED_REQUEST", {}, request_id)


def parse_response(frame: bytes) -> Response:
    if (_bounded_frame(frame) and re.fullmatch(
            rb'#error *: *code *= *(?:INVALID_ID|"INVALID_ID") *\n', frame)):
        return Response("error", None, {"code": "INVALID_ID"})
    request_id = recover_request_id(frame)
    if request_id is None:
        raise ProtocolError("INVALID_ID", {})
    verb, _, fields = _parse(frame, request_id)
    response = Response(verb, request_id, fields)
    _validate_response(response)
    return response


def _encode_scalar(value: Scalar, *, quoted: bool = False) -> str:
    if isinstance(value, NumericToken):
        return value.text
    if isinstance(value, bool):
        return "true" if value else "false"
    if (not isinstance(value, str) or len(value) > MAX_MESSAGE_BYTES
            or any(not " " <= character <= "~" for character in value)):
        raise ProtocolError("MALFORMED_REQUEST", {})
    if (not quoted and value and _NUMBER.fullmatch(value) is None and value not in ("true", "false")
            and not any(character in ' ,<>=[]"\\' for character in value)):
        return value
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _encode_value(value: Value, *, quoted: bool = False) -> str:
    if not isinstance(value, list):
        return _encode_scalar(value, quoted=quoted)
    parts = []
    size = 2
    for item in value:
        encoded = _encode_scalar(item, quoted=quoted)
        size += len(encoded) + (2 if parts else 0)
        if size > MAX_MESSAGE_BYTES:
            raise ProtocolError("MALFORMED_REQUEST", {})
        parts.append(encoded)
    return "[" + ", ".join(parts) + "]"


def encode_request(request: Request) -> bytes:
    """Encode bounded requests, retaining numeric spellings and quoted strings."""
    if (not isinstance(request.verb, str) or _NAME.fullmatch(request.verb) is None
            or type(request.request_id) is not int
            or not 1 <= request.request_id <= MAX_REQUEST_ID
            or "id" in request.metadata):
        raise ProtocolError("MALFORMED_REQUEST", {})
    def pairs(values):
        result = []
        size = 0
        for key, value in values.items():
            if not isinstance(key, str) or _NAME.fullmatch(key) is None:
                raise ProtocolError("MALFORMED_REQUEST", {})
            part = key + "=" + _encode_value(value, quoted=True)
            size += len(part) + 2
            if size > MAX_MESSAGE_BYTES:
                raise ProtocolError("MALFORMED_REQUEST", {})
            result.append(part)
        return ", ".join(result)
    metadata = pairs(request.metadata)
    body = pairs(request.fields)
    frame = (f"#{request.verb} <id={request.request_id}"
             + (", " + metadata if metadata else "") + ">"
             + (": " + body if body else "") + "\n").encode("ascii")
    parse_request(frame)
    return frame


def encode_response(response: Response) -> bytes:
    _validate_response(response)
    prefix = f"#{response.verb}"
    if response.request_id is not None:
        prefix += f" <id={response.request_id}>"
    parts = []
    size = len(prefix) + 1
    for key, value in response.fields.items():
        if not isinstance(key, str) or len(key) > MAX_MESSAGE_BYTES or _NAME.fullmatch(key) is None:
            raise ProtocolError("MALFORMED_REQUEST", {}, response.request_id)
        encoded = _encode_value(value)
        part = f"{key}={encoded}"
        size += len(part) + 2
        if size > MAX_MESSAGE_BYTES:
            raise ProtocolError("MALFORMED_REQUEST", {}, response.request_id)
        parts.append(part)
    return (prefix + (": " + ", ".join(parts) if parts else "") + "\n").encode("ascii")
