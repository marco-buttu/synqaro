"""Common instance configuration and strict registry-directed serialization."""

from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields
import re


_UNSET = object()


@dataclass(frozen=True)
class InstanceConfig:
    """One instance with independently validated model settings.

    Port zero is reserved for direct test/server construction. The internal
    settings name is generic; instance_record preserves each model's JSON key.
    """

    name: str
    model: str
    host: str
    port: int
    settings: object = _UNSET

    def __post_init__(self) -> None:
        from simquaro.registry import get_model

        if (not isinstance(self.name, str)
                or re.fullmatch(r"[a-z][a-z0-9_-]{0,47}", self.name) is None
                or self.name == "all"):
            raise ValueError("invalid instance name; use 1–48 lowercase letters, digits, '_' or '-', starting with a letter, except 'all'")
        definition = get_model(self.model)
        if (not isinstance(self.host, str) or not self.host or not self.host.isascii()
                or any(character.isspace() or not character.isprintable()
                       for character in self.host)):
            raise ValueError("invalid host; provide an ASCII address or hostname without whitespace")
        if type(self.port) is not int or not 0 <= self.port <= 65535:
            raise ValueError("invalid port; choose an integer from 1 through 65535, or 0 for a direct test server")
        if self.settings is _UNSET:
            object.__setattr__(self, "settings", definition.config_type())
        if type(self.settings) is not definition.config_type:
            raise ValueError("invalid model settings; provide the selected model's validated configuration type")


def instance_record(config: InstanceConfig) -> dict:
    """Use a model-owned key, preserving existing receiver JSON records."""
    from simquaro.registry import get_model

    definition = get_model(config.model)
    return {"name": config.name, "model": config.model, "host": config.host,
            "port": config.port, definition.config_key: asdict(config.settings)}


def instance_from_record(record: dict) -> InstanceConfig:
    """Decode data only; model names never become imported Python paths."""
    from simquaro.registry import get_model

    if type(record) is not dict:
        raise ValueError("invalid instance record; provide a configuration object")
    definition = get_model(record.get("model"))
    expected = {"name", "model", "host", "port", definition.config_key}
    if set(record) != expected:
        raise ValueError("invalid instance fields; use only the selected model's configuration fields")
    settings = record[definition.config_key]
    if type(settings) is not dict or set(settings) != {f.name for f in fields(definition.config_type)}:
        raise ValueError("invalid model settings fields; provide the complete supported profile")
    return InstanceConfig(record["name"], record["model"], record["host"], record["port"],
                          settings=definition.config_type(**settings))


def validate_inventory(configs: Mapping[str, InstanceConfig]) -> dict[str, InstanceConfig]:
    """Return an independent mapping after validating inventory-wide constraints."""
    result = dict(configs)
    endpoints = set()
    for name, config in result.items():
        if not isinstance(config, InstanceConfig) or name != config.name:
            raise ValueError("inventory key does not match its instance; use the InstanceConfig.name as the key")
        if config.port == 0:
            raise ValueError("inventory port cannot be zero; choose a fixed port from 1 through 65535")
        endpoint = (config.host, config.port)
        if endpoint in endpoints:
            raise ValueError(f"duplicate endpoint {endpoint!r}; give each instance a unique host and port")
        endpoints.add(endpoint)
    return result
