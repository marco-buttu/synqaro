# Simquaro model boundaries

**Scope:** first follow-up step only, authorized for implementation by the user.
Preserve the existing hardware protocol and CLI. The mandatory GUI, production
communication library, external configuration editor, and system orchestration
belong to later steps. Python >=3.12, Linux, standard library only.

## Approach and responsibilities

The selected approach is an explicit model registry and small structural model
interface. Automatic discovery and a plugin framework were rejected because
they add lifecycle/distribution machinery without a demonstrated requirement.
Keeping the current receiver dependencies in generic modules was rejected
because another hardware model would have to change those modules.

- `protocol.py`: bounded ASCII syntax and message types only.
- `errors.py`: common symbolic errors and bounded rendering; rendering accepts
  a model's combined error catalog explicitly.
- `faults.py`: immutable scenario records, finite rule execution, and common
  delivery effects. A controller receives model-specific cause definitions and
  event names as data. Records validate their structure; model-dependent name
  and trigger checks happen at controller admission and private bootstrap decode.
- `model.py`: `ModelReply` and `SimulatorModel` structural interface. A reply
  carries its domain delivery events, so transport never infers frequency events
  from successful `set` requests. A model supplies `utc_timestamp()` so sessions
  do not know the name of its clock fault. The remaining interface is `clock`,
  `boot_id`, `faults`, `handle(request, *, session_id)`, `snapshot()`, `reboot()`,
  and `close()`; there is no inheritance hierarchy or generic procedure engine.
- `models/fictitious_receiver/`: receiver configuration/validation, error and
  fault catalogs, model implementation, and procedures.
- `registry.py`: the one explicit composition point. Each definition contains
  the settings dataclass, model factory, fault-controller factory, error catalog,
  and serialized settings key. This is a table, not a registration service.
- `config.py`: common instance name/model/endpoint validation with opaque typed
  `settings`, plus strict registry-directed record encoding/decoding.
- `worker.py`, `cli.py`, and `runtime.py`: select definitions or instance record
  helpers, never concrete receiver types. TCP/session/control remain generic.

An instance uses `settings` in Python. Existing receiver JSON keeps its `receiver`
key through the registry definition: CLI records, runtime ownership metadata,
and private bootstrap remain compatible. Existing Python imports and inventory
construction are migrated together; do not retain duplicate implementations or
unnecessary compatibility facades for this unreleased prototype.

## Required evidence

Retain the current behavior tests, moving imports rather than duplicating their
scenarios. Add focused tests using a tiny **test-only** non-receiver model to
exercise the registry, strict configuration/bootstrap, offline fault catalog,
generic TCP sessions, UTC diagnostics, and model-owned delivery-event release.
Reject unknown registered-model names and mismatched settings before startup;
never import a path supplied through bootstrap data. Keep catalogs isolated
between controllers and leave scenarios immutable/replayable.

The initial 232-test suite is the baseline. Run all tests, compile sources, check
CLI output and document links, and perform a fresh review before completion.
Update the operator guide to explain the real boundaries and extension point.

## Execution choices

Continue in the same checkout on a dedicated `codex/` branch, preserving the
already edited documentation. The user requested continuous completion of this
step, so proceed with inline execution rather than another approval round. Keep
the approved behavior as authority; do not publish, push, or merge implicitly.
