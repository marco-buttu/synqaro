"""Finite external fault scenarios; execution belongs to the model and transport.

Call the phase hooks once on actual entry, never on status polling. Call
``frequency_set_verified`` after committing a successful setting, followed by
``response_ready`` for its reply. Ordinary replies use ``response_ready`` only.
Delivery rules on either hook conservatively overlap for compatibility checks.
The caller applies returned delivery effects in order; persistent activations
are observed separately through ``is_active``. This controller never sleeps,
edits replies, changes model state, or resets itself on firmware reboot.
"""

from collections.abc import Mapping
from dataclasses import dataclass
import logging
from threading import Lock
from types import MappingProxyType


EVENTS = ("response_ready", "frequency_set_verified", "calibrate_reference_measurement")
DELIVERY_EVENTS = ("response_ready", "frequency_set_verified")
MAX_RULES = 64
MAX_OCCURRENCES = 4294967295
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Definition:
    name: str
    persistent: bool
    effect: str


_DEFINITIONS = tuple(_Definition(name, True, effect) for name, effect in (
    ("calibration_reference_unavailable", "The physical calibration reference is unavailable; normal diagnostics and calibration fail accordingly."),
    ("frequency_lock_failure", "The synthesizer cannot verify the requested frequency lock; tuning must report FREQUENCY_LOCK_FAILED."),
    ("synthesizer_failure", "The physical synthesizer fails; normal diagnostics report SYNTHESIZER_FAILURE."),
    ("frequency_read_failure", "Reading the physical frequency fails; firmware reports FREQUENCY_READ_FAILED without inventing a value."),
    ("clock_untrusted", "UTC is untrusted; firmware reports CLOCK_UNTRUSTED and omits new UTC timestamps."),
    ("procedure_stall", "Firmware procedure advancement stalls without blocking the event loop; normal deadlines still apply."),
    ("stop_unconfirmed", "Physical activity continues despite a stop request; firmware cannot confirm a controlled stop."),
)) + tuple(_Definition(name, False, effect) for name, effect in (
    ("drop_response", "Suppress this reply after execution; retain any already committed model changes."),
    ("delay_response", "Deliver this reply after delay_ms; retain any already committed model changes."),
    ("omit_lf", "Deliver the reply without its final LF terminator."),
    ("malformed_response", "Break a field separator but retain the original request ID unmodified."),
    ("reorder_responses", "Hold at most one reply per rule/session; release it after the next matching reply or after 2000 ms, whichever comes first."),
    ("disconnect", "Close the hardware connection after the relevant execution stage, before delivering this reply."),
))
_BY_NAME = {definition.name: definition for definition in _DEFINITIONS}
_COMPATIBLE_DELIVERY_PAIRS = {
    frozenset(("delay_response", "omit_lf")),
    frozenset(("delay_response", "malformed_response")),
    frozenset(("omit_lf", "malformed_response")),
}


def _definition(name: str) -> _Definition:
    if not isinstance(name, str) or name not in _BY_NAME:
        raise ValueError("unknown fault name; choose a name from FaultController.catalog()")
    return _BY_NAME[name]


def _parameters(name: str, parameters: Mapping[str, int] | None) -> Mapping[str, int]:
    _definition(name)
    if parameters is None:
        parameters = {}
    if not isinstance(parameters, Mapping):
        raise ValueError("invalid fault parameters; supply a mapping using the catalog's parameter names")
    values = dict(parameters)
    if name == "delay_response":
        delay = values.get("delay_ms")
        if set(values) != {"delay_ms"} or type(delay) is not int or not 1 <= delay <= 60000:
            raise ValueError("invalid delay parameters; supply only integer delay_ms from 1 through 60000")
    elif values:
        raise ValueError("unsupported fault parameters; use an empty mapping for this fault")
    return MappingProxyType(values)


def _event(event: str) -> None:
    if not isinstance(event, str) or event not in EVENTS:
        raise ValueError("unknown fault event; choose response_ready, frequency_set_verified, or calibrate_reference_measurement")


@dataclass(frozen=True)
class FaultContext:
    event: str
    session_id: str | None = None
    request_id: int | None = None
    command: str | None = None
    target: str | None = None

    def __post_init__(self) -> None:
        _event(self.event)
        for name in ("session_id", "command", "target"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not 1 <= len(value) <= 64
                                      or not value.isascii() or not value.isprintable()):
                raise ValueError(f"invalid {name}; provide 1–64 printable ASCII characters or None")
        if self.request_id is not None and (type(self.request_id) is not int
                                           or not 1 <= self.request_id <= 4294967295):
            raise ValueError("invalid request_id; provide an integer from 1 through 4294967295 or None")


@dataclass(frozen=True)
class FaultEffect:
    name: str
    parameters: Mapping[str, int] | None = None
    # Provenance is separate from user parameters; the transport uses it to
    # key reorder holds by (rule_id, session_id), including a rule's last use.
    rule_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", _parameters(self.name, self.parameters))
        if self.rule_id is not None and (not isinstance(self.rule_id, str)
                                        or not self.rule_id.startswith("rule-")
                                        or not self.rule_id[5:].isascii()
                                        or not self.rule_id[5:].isdigit()
                                        or len(self.rule_id) > 24):
            raise ValueError("invalid rule provenance; use the rule ID returned by schedule, or None")


@dataclass(frozen=True)
class FaultRule:
    """A prospective, instance-wide initial rule, without mutable counters."""

    name: str
    when: str
    times: int = 1
    parameters: Mapping[str, int] | None = None

    def __post_init__(self) -> None:
        definition = _definition(self.name)
        _event(self.when)
        if not definition.persistent and self.when not in DELIVERY_EVENTS:
            raise ValueError("delivery effect requires a delivery event; choose response_ready or frequency_set_verified")
        if type(self.times) is not int or not 1 <= self.times <= MAX_OCCURRENCES:
            raise ValueError("invalid occurrence count; supply integer times from 1 through 4294967295")
        object.__setattr__(self, "parameters", _parameters(self.name, self.parameters))


def _compatible(first: FaultRule, second: FaultRule) -> bool:
    # Persistent causes do not compete for reply bytes. Every pair of wire
    # hooks can reach the same response, so checking equal events is unsafe.
    if _definition(first.name).persistent or _definition(second.name).persistent:
        return True
    return frozenset((first.name, second.name)) in _COMPATIBLE_DELIVERY_PAIRS


@dataclass(frozen=True)
class Scenario:
    initial_faults: tuple[FaultEffect, ...] = ()
    rules: tuple[FaultRule, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.initial_faults, (tuple, list)) or not isinstance(self.rules, (tuple, list)):
            raise ValueError("invalid scenario collections; supply tuples of FaultEffect and FaultRule")
        initial = tuple(self.initial_faults)
        rules = tuple(self.rules)
        if len(rules) > MAX_RULES:
            raise ValueError("too many scenario rules; supply at most 64 rules")
        names = set()
        for effect in initial:
            if (not isinstance(effect, FaultEffect) or not _definition(effect.name).persistent
                    or effect.rule_id is not None):
                raise ValueError("invalid initial fault; supply a persistent FaultEffect without rule provenance")
            if effect.name in names:
                raise ValueError("duplicate initial fault; specify each persistent condition once")
            names.add(effect.name)
        for index, rule in enumerate(rules):
            if not isinstance(rule, FaultRule):
                raise ValueError("invalid initial rule; supply a validated FaultRule")
            if any(not _compatible(previous, rule) for previous in rules[:index]):
                raise ValueError("incompatible scenario delivery effects; remove conflicting rules")
        object.__setattr__(self, "initial_faults", initial)
        object.__setattr__(self, "rules", rules)


@dataclass
class _ScheduledRule:
    rule_id: str
    rule: FaultRule
    remaining: int


class FaultController:
    """Synchronous atomic consumption; keep the same object across firmware reboot.

    Snapshots retain live rules and only the most recent matching emission,
    never an unbounded history. Python logging carries schedule/consume/remove
    evidence; callers add their process/boot/clock and actual-execution evidence.
    """

    def __init__(self, scenario: Scenario = Scenario()):
        if not isinstance(scenario, Scenario):
            raise ValueError("invalid scenario; provide a validated Scenario")
        self._lock = Lock()
        self._active = {effect.name: effect for effect in scenario.initial_faults}
        self._rules: list[_ScheduledRule] = []
        self._next_id = 1
        self._last_event: dict | None = None
        for rule in scenario.rules:
            self.schedule(rule.name, when=rule.when, times=rule.times, parameters=rule.parameters)

    def activate(self, name: str, parameters: Mapping[str, int] | None = None) -> None:
        effect = FaultEffect(name, parameters)
        if not _definition(name).persistent:
            raise ValueError("delivery effects cannot be activated; schedule one at an allowed delivery event")
        with self._lock:
            self._active[name] = effect
            _LOGGER.info("fault activated name=%s", name)

    def clear(self, name: str) -> None:
        if not _definition(name).persistent:
            raise ValueError("delivery effects are not persistent; cancel their scheduled rule instead")
        with self._lock:
            self._active.pop(name, None)
            _LOGGER.info("fault cleared name=%s", name)

    def schedule(self, name: str, *, when: str, times: int = 1,
                 parameters: Mapping[str, int] | None = None) -> str:
        rule = FaultRule(name, when, times, parameters)
        with self._lock:
            if len(self._rules) >= MAX_RULES:
                raise ValueError("scheduled rule capacity reached; cancel or consume a rule before adding another (limit 64)")
            if any(not _compatible(existing.rule, rule) for existing in self._rules):
                raise ValueError("incompatible delivery effects may reach the same reply; cancel the conflicting rule first")
            if self._next_id > 9223372036854775807:
                raise ValueError("rule identifier space exhausted; restart the simulator process to create new rules")
            rule_id = f"rule-{self._next_id}"
            self._rules.append(_ScheduledRule(rule_id, rule, times))
            self._next_id += 1
            _LOGGER.info("fault scheduled rule=%s name=%s event=%s times=%s", rule_id, name, when, times)
            return rule_id

    def cancel(self, rule_id: str) -> None:
        with self._lock:
            for index, scheduled in enumerate(self._rules):
                if scheduled.rule_id == rule_id:
                    del self._rules[index]
                    _LOGGER.info("fault cancelled rule=%s", scheduled.rule_id)
                    return
            raise ValueError("rule is not pending; choose a live rule ID from snapshot()")

    def is_active(self, name: str) -> bool:
        _definition(name)
        with self._lock:
            return name in self._active

    @staticmethod
    def validate_delivery_effects(effects: tuple[FaultEffect, ...]) -> None:
        """Check accumulated hook results before touching reply bytes.

        Usually the model's phase event and response_ready are emitted without
        an intervening await. This guard also handles caller composition after
        intervening control mutations; it checks data and executes nothing.
        """
        for index, effect in enumerate(effects):
            if not isinstance(effect, FaultEffect) or _definition(effect.name).persistent:
                raise ValueError("invalid delivery effect; supply only returned wire effects")
            for previous in effects[:index]:
                if frozenset((previous.name, effect.name)) not in _COMPATIBLE_DELIVERY_PAIRS:
                    raise ValueError("incompatible accumulated delivery effects; arrange compatible rules before handling another request")

    def emit(self, context: FaultContext) -> tuple[FaultEffect, ...]:
        if not isinstance(context, FaultContext):
            raise ValueError("invalid event context; supply a validated FaultContext")
        with self._lock:
            effects = []
            consumed = []
            for scheduled in self._rules:
                rule = scheduled.rule
                if rule.when != context.event:
                    continue
                effect = FaultEffect(rule.name, rule.parameters, scheduled.rule_id)
                if _definition(rule.name).persistent:
                    self._active[rule.name] = effect
                else:
                    effects.append(effect)
                scheduled.remaining -= 1
                consumed.append(scheduled.rule_id)
                _LOGGER.info("fault consumed rule=%s name=%s remaining=%s context=%s",
                             scheduled.rule_id, rule.name, scheduled.remaining, context)
            self._rules = [scheduled for scheduled in self._rules if scheduled.remaining]
            if consumed:
                self._last_event = {"event": context.event, "session_id": context.session_id,
                                    "request_id": context.request_id, "command": context.command,
                                    "target": context.target, "rule_ids": consumed}
            return tuple(effects)

    @staticmethod
    def catalog() -> list[dict]:
        result = []
        for definition in _DEFINITIONS:
            name = definition.name
            parameters = ({"delay_ms": {"type": "integer", "min": 1, "max": 60000}}
                          if name == "delay_response" else {})
            limits = ({"held_replies_per_rule_session": 1, "release_timeout_ms": 2000}
                      if name == "reorder_responses" else {})
            example = {"name": name}
            if not definition.persistent:
                example["when"] = "response_ready"
            if parameters:
                example["parameters"] = {"delay_ms": 2500}
            compatible = [other.name for other in _DEFINITIONS
                          if other.persistent or definition.persistent
                          or frozenset((name, other.name)) in _COMPATIBLE_DELIVERY_PAIRS]
            result.append({"name": name, "persistent": definition.persistent,
                           "activation_allowed": definition.persistent,
                           "events": list(EVENTS if definition.persistent else DELIVERY_EVENTS),
                           "parameters": parameters, "effect": definition.effect,
                           "limits": limits, "compatible_with": compatible,
                           "example": example})
        return result

    def snapshot(self) -> dict:
        with self._lock:
            active = [{"name": effect.name, "parameters": dict(effect.parameters),
                       "rule_id": effect.rule_id} for effect in self._active.values()]
            rules = [{"rule_id": scheduled.rule_id, "name": scheduled.rule.name,
                      "when": scheduled.rule.when, "remaining": scheduled.remaining,
                      "parameters": dict(scheduled.rule.parameters)} for scheduled in self._rules]
            last_event = None if self._last_event is None else {
                **self._last_event, "rule_ids": list(self._last_event["rule_ids"])}
            return {"active": active, "rules": rules, "last_event": last_event,
                    "rule_limit": MAX_RULES}
