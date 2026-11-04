"""Versioned operator inventory and compare-and-swap atomic persistence."""

from collections.abc import Mapping
import asyncio
from dataclasses import asdict, dataclass, fields
from decimal import Decimal, InvalidOperation
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import time
from types import MappingProxyType

from simquaro.config import InstanceConfig, instance_record, validate_inventory
from simquaro.registry import get_model


MAX_CONFIG_BYTES = 1048576


class ConfigurationError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class InventoryEntry:
    config: InstanceConfig
    kind: str = "simulator"

    def __post_init__(self):
        if self.kind not in ("simulator", "hardware"):
            raise ValueError("kind must be simulator or hardware")


@dataclass(frozen=True)
class InventorySnapshot:
    entries: Mapping[str, InventoryEntry]
    revision: str
    path: Path
    source: str


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _nonfinite(value):
    raise ValueError("NaN and infinity are not configuration values")


def _number(value, *, field_type):
    if type(value) is dict and set(value) == {"number"}:
        if not isinstance(value["number"], str) or len(value["number"]) > 64:
            raise ValueError("Numeric setting must have a bounded decimal spelling")
        from synqaro_protocol.codec import NumericToken
        try:
            value = Decimal(NumericToken(value["number"]).text)
        except InvalidOperation:
            raise ValueError("Numeric setting exceeds decimal capacity") from None
    if isinstance(value, Decimal):
        if not value.is_finite(): raise ValueError("Numeric setting must be finite")
        if field_type is int:
            if value.copy_abs() > 4294967295 or value != value.to_integral_value():
                raise ValueError("Integer setting is outside its supported capacity")
            return int(value)
        if field_type is not float:
            raise ValueError("Wrong type for numeric setting")
        # Exact spelling must survive before the model-owned range/grid validator.
        # No receiver-specific limits belong to this generic persistence module.
        normalized = float(value)
        if Decimal(str(normalized)) != value:
            raise ValueError("Setting cannot be represented without changing its value")
        return normalized
    return value


def entry_from_record(record, *, tagged=False):
    if type(record) is not dict:
        raise ValueError("Instance must be a JSON object")
    definition = get_model(record.get("model"))
    key = definition.config_key
    required = {"name", "model", "host", "port"}
    if not required <= set(record) or set(record) - required - {"kind", key}:
        raise ValueError("Unknown or missing instance fields")
    kind = record.get("kind", "simulator")
    settings = record.get(key, {})
    if type(settings) is not dict:
        raise ValueError("Model settings must be a JSON object")
    declared = {item.name: item for item in fields(definition.config_type)}
    if set(settings) - set(declared): raise ValueError("Unknown model setting")
    if kind == "hardware" and not settings.get("hardware_id"):
        raise ValueError("Physical hardware requires an independently supplied hardware_id")
    normalized = {}
    for name, value in settings.items():
        if isinstance(value, dict) and not tagged:
            raise ValueError("Configuration file settings use ordinary JSON scalars")
        normalized[name] = _number(value, field_type=declared[name].type)
    config = InstanceConfig(record["name"], record["model"], record["host"], record["port"],
                            settings=definition.config_type(**normalized))
    return InventoryEntry(config, kind)


def entry_record(entry):
    return {**instance_record(entry.config), "kind": entry.kind}


def _entries(records):
    if not isinstance(records, list): raise ValueError("instances must be a JSON array")
    entries = {}
    for record in records:
        entry = entry_from_record(record)
        if entry.config.name in entries: raise ValueError("Duplicate instance name")
        entries[entry.config.name] = entry
    validate_inventory({name: entry.config for name, entry in entries.items()})
    return entries


def _encode(entries):
    document = {"version": 1, "instances": [entry_record(entry) for entry in entries.values()]}
    _entries(document["instances"])
    for name, entry in entries.items():
        if name != entry.config.name: raise ValueError("Inventory key/name mismatch")
    data = (json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    if len(data) > MAX_CONFIG_BYTES: raise ValueError("Configuration exceeds 1 MiB")
    return data


def _safe_file(info):
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_nlink != 1 or info.st_mode & 0o022):
        raise ValueError("Use a regular, nonshared configuration file owned by your user")


class ConfigStore:
    def __init__(self, path=None):
        self.explicit = path is not None
        if path is None:
            xdg = os.environ.get("XDG_CONFIG_HOME", "")
            base = Path(xdg) if Path(xdg).is_absolute() else Path.home() / ".config"
            path = base / "simquaro" / "instances.json"
        self.path = Path(path).expanduser().absolute()

    def _defaults(self):
        from simquaro.instances import builtin_inventory
        entries = {name: InventoryEntry(config) for name, config in builtin_inventory().items()}
        revision = "builtin:" + hashlib.sha256(_encode(entries)).hexdigest()
        return InventorySnapshot(MappingProxyType(entries), revision, self.path, "builtin")

    def load(self, *, _allow_missing=False):
        try:
            fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
            with os.fdopen(fd, "rb") as stream:
                _safe_file(os.fstat(stream.fileno()))
                data = stream.read(MAX_CONFIG_BYTES + 1)
            if len(data) > MAX_CONFIG_BYTES: raise ValueError("Configuration exceeds 1 MiB")
            document = json.loads(data, object_pairs_hook=_unique, parse_constant=_nonfinite, parse_float=Decimal)
            if (type(document) is not dict or set(document) != {"version", "instances"}
                    or type(document["version"]) is not int or document["version"] != 1):
                raise ValueError("Expected version-1 configuration with instances")
            entries = _entries(document["instances"])
            return InventorySnapshot(MappingProxyType(entries), hashlib.sha256(data).hexdigest(), self.path, "file")
        except FileNotFoundError:
            if not self.explicit or _allow_missing: return self._defaults()
            raise ConfigurationError("CONFIG_NOT_FOUND", f"{self.path}; run simquaro --config {self.path} config init") from None
        except (ValueError, TypeError, OSError, InvalidOperation) as exc:
            raise ConfigurationError("INVALID_CONFIGURATION", f"{self.path}: {exc}; correct the file and run config validate") from exc

    def initialize(self):
        snapshot = self.load(_allow_missing=True)
        if snapshot.source == "file": return snapshot
        return self.save(snapshot.entries, expected_revision=snapshot.revision)

    def save(self, entries, *, expected_revision):
        lock_fd = None
        temporary = None
        replaced = False
        try:
            data = _encode(entries)
            missing = []
            directory = self.path.parent
            while not directory.exists():
                missing.append(directory)
                directory = directory.parent
            for path in reversed(missing):
                try: path.mkdir(mode=0o700)
                except FileExistsError: pass
            parent_info = self.path.parent.lstat()
            if (not stat.S_ISDIR(parent_info.st_mode) or parent_info.st_uid != os.getuid()
                    or parent_info.st_mode & 0o022):
                raise ValueError("Choose a nonshared configuration directory owned by your user")
            lock_fd = os.open(self.path.with_name(self.path.name + ".lock"),
                os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, 0o600)
            _safe_file(os.fstat(lock_fd))
            deadline = time.monotonic() + 2
            while True:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise ConfigurationError("CONFIG_BUSY", "Another save is active; retry after it finishes")
                    time.sleep(.01)
            current = self.load(_allow_missing=True)
            if current.revision != expected_revision:
                raise ConfigurationError("CONFIG_CONFLICT", "Settings changed since editing began; reload before saving")
            fd, temporary = tempfile.mkstemp(prefix="." + self.path.name + "-", dir=self.path.parent)
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            temporary = None
            replaced = True
            parent_fd = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try: os.fsync(parent_fd)
            finally: os.close(parent_fd)
            return self.load()
        except ConfigurationError:
            raise
        except (OSError, ValueError, TypeError, InvalidOperation) as exc:
            code = "CONFIG_DURABILITY_UNCERTAIN" if replaced else "CONFIG_SAVE_FAILED"
            raise ConfigurationError(code, f"{self.path}: {exc}; reload to inspect saved settings before retrying") from exc
        finally:
            if temporary is not None:
                os.unlink(temporary)
            if lock_fd is not None:
                os.close(lock_fd)


async def configuration_io(operation, *args, **kwargs):
    """Keep filesystem work off-loop, but never abandon an in-flight write."""
    task = asyncio.create_task(asyncio.to_thread(operation, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise


@dataclass(frozen=True)
class ApplyResult:
    outcome: dict
    started: object | None


class ConfigurationService:
    def __init__(self, store, runtime):
        self.store, self.runtime = store, runtime

    @staticmethod
    def target(snapshot, name):
        if name not in snapshot.entries:
            raise ConfigurationError("UNKNOWN_TARGET", "Select a configured instance")
        return snapshot.entries[name]

    async def inspect(self, name):
        snapshot = await configuration_io(self.store.load)
        entry = self.target(snapshot, name)
        result = {"saved": entry_record(entry), "revision": snapshot.revision,
                  "source": snapshot.source, "active": None, "pending": None}
        if entry.kind == "hardware":
            return {**result, "state": "not_applicable"}
        state = await self.runtime.inspect(entry.config)
        if state["ok"] and state["outcome"] == "running":
            active = state["startup_config"]
            return {**result, "state": "running", "active": active,
                    "pending": active != instance_record(entry.config), "runtime": state}
        return {**result, "state": "stopped" if state["ok"] else "unknown", "runtime": state}

    async def apply(self, name, *, expected_revision):
        snapshot = await configuration_io(self.store.load)
        if snapshot.revision != expected_revision:
            raise ConfigurationError("CONFIG_CONFLICT", "Saved settings changed; reload before applying")
        entry = self.target(snapshot, name)
        if entry.kind != "simulator":
            raise ConfigurationError("FORBIDDEN_TARGET_KIND", "Physical hardware has no simulator startup settings to apply")
        started = await self.runtime.restart(entry.config)
        # Transfer ownership immediately: no fallible/cancellable follow-up I/O
        # between child creation and returning its handle. A later inspect()
        # compares the latest saved snapshot with this trusted startup evidence.
        outcome = {**started.outcome, "requested_revision": snapshot.revision,
                   "active_evidence": started.outcome}
        return ApplyResult(outcome, started if started.child is not None else None)
