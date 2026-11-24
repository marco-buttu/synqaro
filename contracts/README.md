# Hardware contracts

This directory defines the version-1 authoring format for hardware contracts.
[schema-v1.json](schema-v1.json) is the structural specification. The
[integration workflow](../docs/hardware_integration_workflow.md) defines how an
agent gathers requirements and obtains approval; it remains required reading.

The [fictitious receiver contract](models/fictitious_receiver.yaml), revision 0.2,
is approved; see the [approval record](../docs/fictitious_receiver_contract_review.md#formal-approval).
It references [Hardware Protocol](../docs/hardware_protocol.md) for shared rules.
Implementation migration remains tracked in [issue #38](https://github.com/marco-buttu/synqaro/issues/38).
The example below is not a supported hardware model or a replacement for that contract.

## Write a contract

Use one UTF-8 YAML file per hardware model/compatible firmware family under
`contracts/models/`. Instance names, network addresses and operating configuration
belong in the instance configuration, not in this shared model contract. Split
contracts when behavior differs incompatibly. Files ending in `.json` use the JSON
parser; other explicit input paths use YAML. Both must follow the same schema.

Start from [the illustrative indicator](examples/indicator.yaml). It demonstrates
properties, a procedure, failures, scenarios and an open question. It is deliberately
a draft with invented requirements, not evidence of complete real-hardware coverage.
Replace every example decision with sourced requirements; do not treat the example
as an approved hardware design or a questionnaire covering all cases.

| Section | Meaning |
| --- | --- |
| `schema_version` | Authoring format version; currently integer `1`. Not the wire protocol version. |
| `id`, `revision`, `status` | Stable model-contract identifier, revision string and `draft`/`approved` declaration. |
| `hardware` | Model, description and explicitly verified compatible firmware version strings (possibly empty). No inferred version-range matching. |
| `protocol` | Protocol name/version and a versioned specification reference. Wire framing and message syntax are not redefined here. |
| `sources` | Named source documents and their revisions. Requirement entries reference these keys. |
| `properties` | Named values, access (`readonly`/`readwrite`), type/unit/constraints, availability, write effects, requirement and error references. |
| `procedures` | Named actions with typed parameters, preconditions, effects, state transitions, terminal outcomes, cancellation and timing. |
| `errors` | Named errors with meaning, consequence and recovery guidance. An optional specification reference links to an existing error definition. |
| `requirements` | Stable requirement identifiers with statements, sources, proposed/confirmed status, dependencies and optional rationale. Include cross-cutting behavior here. |
| `scenarios` | Requirement references, initial conditions (`given`), action/fault (`when`), observable expectations (`then`) and verification level. These are prose, not executable test scripts. |
| `dependencies` | Proposed extensions and their approval/availability state, with versioned proposal and evidence references. |
| `open_items` | Questions, impact, responsible person/team, affected requirements and blocking/excluded disposition. Exclusions need a reason. |
| `approval` | `null` for drafts; reviewer, ISO date string, contract revision and versioned review evidence for an approved declaration. |

All top-level sections are required. Empty maps are permitted where nothing applies
(for example, a read-only sensor may have no procedures). Requirements and scenarios
must be nonempty. Map keys are stable, case-sensitive identifiers used by references;
renaming one requires updating its references. Labels and explanations live in
`description`, not in identifiers. Use the chosen protocol's naming rules as well:
this generic schema does not enforce one particular protocol's identifiers.

### Firmware compatibility

`hardware.firmware_versions` is a required list of distinct nonempty strings, but
may be empty in both draft and approved contracts. The protocol version is required
independently. An empty list means no compatible firmware releases have been
verified and declared; it is not a wildcard or permission to use any firmware.
A contract may be approved before firmware exists. That approval alone does not
establish production firmware compatibility. Record verified releases with build
identity and conformance evidence in a reviewed contract revision; matching the
protocol or a version label alone is insufficient. Authorized exploratory and
simulator tests do not require a prior production compatibility declaration.

The maintainer authorized relaxing this version-1 authoring constraint during
issue #38. All previously valid contracts remain valid; older validators will
reject the newly allowed empty list and must be updated to read such contracts.
The field, its item type, and the wire protocol version are unchanged.

### Values and procedures

A value has `type`, `unit` and `description`. Use `unit: null` for dimensionless or
non-numeric values. Supported types are `number`, `integer`, `string`, `boolean`,
`array` and `object`. Arrays require `items`; objects require a nonempty `fields` map.
Nested descriptors follow the same rules. All declared object fields are present;
optional or variable-shaped records need a future explicit schema decision.

Numeric bounds use `minimum`/`maximum`; `resolution`, when provided, needs a
`representation` explanation of rounding/rejection. Integer bounds and resolution
must be integral. Strings use `minLength`/`maxLength`; arrays use
`minItems`/`maxItems`. Scalar `enum` members must satisfy the type and bounds.
Inapplicable constraints are errors. Omitted bounds do not assert unlimited physical
range: describe unresolved or hardware-reported limits in requirements/open items.
No protocol-specific floating-point or frequency-grid conformance is inferred.

Procedure parameters declare whether they are required. Optional parameters must
explain `when_omitted`. `initial_state` is the state when this invocation begins,
not the receiver's global idle state; terminal states have outcomes and no outgoing
transitions in that invocation. Repeating a procedure starts another invocation.
Cancellation declares the states where it is allowed and its semantics. Timing must
explain completion; a specified `deadline_ms` is a positive integer. When no finite
deadline is justified, explain that explicitly rather than inventing a number.
Conditions, effects, recovery and timing prose require human review.

### Drafts, dependencies and approval

Keep incomplete work as `draft`; proposed requirements and blocking questions are
allowed. A structurally valid draft is not ready for implementation merely because
the command succeeds. Check completeness using the workflow.

For `approved`, the declared approval revision must match `revision`; all included
requirements must be confirmed and referenced by at least one scenario. Blocking
questions and references to awaiting/rejected/deferred dependencies are invalid.
An excluded open item cannot still refer to included requirements.

Dependencies use `awaiting_approval`, `approved_pending_verification`, `available`,
`rejected` or `deferred`. An approved contract may depend on an approved extension
still to be developed, but cannot claim it is available. `available` requires an
evidence reference. A proposal reference alone is not proof of maintainer approval;
the reviewer must check the referenced record and its exact scope.

The validator checks these declarations, **not** reviewer identity, permissions,
document contents or actual hardware capability. A copied approval record does not
authorize a changed contract. Increment the revision and obtain the applicable
approval when changing its substance.

## Validate

From the repository root, install the optional authoring dependencies in the
development virtual environment:

```sh
.venv/bin/python -m pip install -e '.[contracts]'
.venv/bin/python tools/validate_contracts.py
.venv/bin/python -m unittest tests.test_contracts -v
```

If setting up a development checkout for the first time, follow
[developer verification](../docs/getting_started.md#scope-and-developer-verification),
which creates that environment. These tools are not required by the installed GUI
or simulator and do not add runtime dependencies.

The command validates all `.yaml`, `.yml` and `.json` files under `contracts/examples/`
and `contracts/models/` by default. Supply paths to check a particular draft:

```sh
.venv/bin/python tools/validate_contracts.py contracts/examples/indicator.yaml
```

Exit code `0` means structure and the listed consistency checks passed; `1` reports
invalid/unreadable input, and `2` is a CLI usage error. Diagnostics identify the file
and field. Validation is offline: references are recorded, not fetched or executed.
The schema itself uses local definitions; files cannot select an external schema.

The YAML parser uses PyYAML's safe loader and accepts only JSON-compatible values. Quote
dates, version numbers and strings such as `on`, `off`, `yes` and `no` (YAML otherwise
interprets those as booleans). For YAML scientific numbers use a decimal point and
an exponent sign, such as `1.0e-7`; JSON also accepts `1e-7`. Use `true`/`false` for boolean fields. Unknown fields,
duplicate mapping keys, non-string keys, explicit YAML tags, aliases/merge keys, multiple YAML documents,
nonfinite numbers and non-JSON YAML types are rejected. Files are limited to 1 MiB
and 64 levels of nesting. These are authoring-tool limits, not hardware protocol limits.

## What the checks establish

JSON Schema checks required fields, types, unknown fields and basic constraints.
The additional pass checks references, range/length consistency, recursive value
constraints, reachable procedure states, terminal outcomes, a path to a terminal
state from every state when a finite deadline is declared, cancellation declarations
and the approval/dependency rules above. Tests exercise valid and invalid cases and
validate every repository contract discovered by the default command.

These checks cannot establish that prose is accurate, scenarios cover every fault,
firmware implements the contract, an external reference exists, or a deadline is
physically achievable. Scenario coverage means only that a reference exists.
Resolution/rounding semantics and protocol-specific guarantees need conformance
tests. Do not generate expected test results from firmware behavior or bypass the
workflow's semantic review and approval. GUI generation and behavioral-test
adaptation remain later work; this step does not implement either.

Schema version 1 is the first format for this prototype, not a claim of universal
hardware coverage. Preserve versioned schemas; incompatible format changes need a
new version and migration decision, not a silent edit of existing contracts.

Implementation references: [JSON Schema validation library](https://python-jsonschema.readthedocs.io/en/stable/validate/)
and [PyYAML safe-loading documentation](https://pyyaml.org/wiki/PyYAMLDocumentation).
