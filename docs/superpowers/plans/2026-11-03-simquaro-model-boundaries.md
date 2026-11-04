# Simquaro Model Boundaries Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans for inline execution.

**Goal:** make a new hardware model independent of protocol and runtime code.

**Architecture:** generic protocol/transport and finite fault machinery consume
an explicit model definition; receiver-specific behavior lives together. Preserve
existing wire and CLI records while migrating the internal Python configuration.

**Tech Stack:** Python >=3.12, Linux, asyncio, unittest, no new dependencies.

**Spec:** [Model boundaries design](../specs/2026-11-03-simquaro-model-boundaries-design.md).

## Global Constraints

- First follow-up step only; no production client, GUI, external loader, or firmware.
- Preserve wire messages, CLI grammar, receiver JSON, timeout/recovery semantics.
- Explicit registry only; no imported model paths, discovery, or plugin framework.
- Existing documentation edits belong to the user and must be preserved.

## Review Focus

1. Non-receiver successful setters must not trigger receiver-specific wire events.
2. Clock quality is supplied by the model, not inferred by transport fault names.
3. Invalid model/settings/scenario input must fail before worker startup or mutation.
4. Different model catalogs must remain isolated, including offline CLI validation.
5. Receiver JSON and runtime bootstrap must retain the existing record shape.

## Task 1: Separate model responsibilities and connect the registry

**Files:** add `src/simquaro/model.py`, `registry.py`,
`models/fictitious_receiver/{config,validation,errors,faults,model,procedures}.py`;
adapt `protocol.py`, `errors.py`, `faults.py`, `config.py`, `worker.py`, `cli.py`,
`runtime.py`, `instances.py`, `session.py`, and existing test imports/helpers.
Add `tests/simquaro/test_model_boundaries.py`.

**Interfaces:** `ModelReply(response, delivery_effects=(), reboot_requested=False,
delivery_events=())`; `SimulatorModel` as described in the spec;
`ModelDefinition(config_type, factory, fault_factory, error_catalog, config_key)`;
`get_model(name)`; `instance_record(config)` / `instance_from_record(record)`.
`FaultController(scenario=Scenario(), *, definitions=(), events=("response_ready",),
delivery_events=("response_ready",))`; receiver supplies its catalog by factory.

- [x] Add a test-only non-receiver model/definition and failing tests proving
  registry selection, preserved receiver JSON, strict wrong-model/settings
  rejection, model-scoped faults, TCP handling without receiver clock faults,
  and successful-set event isolation. Run them and observe expected failures.
- [x] Move existing receiver implementation/configuration/validation/catalogs;
  extract neutral reply/interface; inject catalogs and use registry composition.
  Move model-dependent fault validation to controller/decoded bootstrap admission.
- [x] Update existing test imports and Python inventory to the new internal API,
  preserving original wire assertions and scenario expectations.
- [x] Run focused boundary, protocol, model, fault, server, bootstrap and CLI tests,
  then the complete `env PYTHONPATH=src python3 -m unittest discover -s tests -t . -q`.
  Expect all existing behavior tests plus boundary tests to pass.

## Task 2: Explain, verify, and review the completed refactor

**Files:** update `docs/simquaro.md`, approved follow-up checklist, and this plan.

- [x] Document the actual module responsibilities and how to add a model by one
  directory and registry entry. Keep GUI and other future work visibly separate.
- [x] Run full tests, `python3 -m compileall -q src tests`, CLI help/list/offline
  fault catalog, and `git diff --check`. Verify documentation paths and fences.
- [x] Perform one fresh-context whole-change review; reproduce important findings
  with failing tests before fixing, then rerun the full suite.
- [x] Record results, mark only first-step work complete, and commit pertinent
  local changes. Do not push, create GitHub artifacts, or merge without a request.

## Execution log

- Baseline: 232 tests passed in 45.177 seconds on 2026-11-03.
- User authorized continuous completion of this bounded step; no further design
  questions are required. The implementation details above are engineering calls
  within the approved separation, not approval of later features.
- Boundary tests: six expected failures before implementation, then all six pass.
- Full suite: 238 tests passed in 45.482s and again in 45.635s. The original 232
  scenarios remain, with import/helper migrations and no duplicated suite.
- `compileall`, documentation links/fences, and whitespace checks passed. CLI
  help, instance JSON, and offline fault-catalog JSON match baseline outputs.
- A verification wrapper initially lacked the sandbox permission for local
  sockets. A minimal socket creation reproduced EPERM; the preapproved direct
  unittest runs above passed, and the wrapper was rerun with explicit permission.
- Authorized wrapper rerun: 238 tests passed in 45.602s; no code changed between
  these full runs. Python compilation, documentation checks, and CLI comparison
  also passed.
- Fresh read-only review: no Critical, Important, or actionable Minor findings.
  The reviewer independently exercised 50 non-socket cases; two TCP cases were
  sandbox-blocked, so complete TCP/subprocess evidence is the executor's full
  suite, not an independently repeated full suite. The executor checked the
  documentation changes and completion checkboxes.
- Review exclusions match the approved scope: production client/manual CLI/GUI/
  editor, real apparatus, additional product models/plugins, and legacy internal
  Python import compatibility are not delivered here. The sandbox wrapper issue
  was diagnosed and its authorized rerun passed; it is not an open product issue.
- First follow-up step complete on `codex/simquaro-model-boundaries`. The shared
  library/manual CLI, external configuration, and mandatory GUI still require
  their detailed design discussions. No push, PR, or merge is part of this step.
