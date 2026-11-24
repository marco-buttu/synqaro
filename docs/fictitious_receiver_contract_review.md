# Fictitious receiver contract — review and approval (0.2)

**Status:** revision 0.2 explicitly approved by the project owner on 2026-11-24; implementation migration pending. [Issue #38, section 4](https://github.com/marco-buttu/synqaro/issues/38).

Review [`contracts/models/fictitious_receiver.yaml`](../contracts/models/fictitious_receiver.yaml)
against the currently approved [Hardware Protocol](hardware_protocol.md). The YAML
is the approved receiver-specific behavioral reference, together with the referenced
shared protocol. Section 5 covers implementation migration within the approved scope;
no shared-protocol or framework extension is authorized. No production files have
been changed by this approval record.

## Source and evidence record

The input is the project owner's ZIP of the working tree. The original workflow and schema
Git blob IDs match those previously read on `main` at merge `937d2444f9e2cca2ddd28df8e17894e8cbcf0e31`.
The ZIP has no Git metadata; that is a match for these files, not proof of the
entire tree's commit identity. Git blob IDs in the YAML identify source content,
not Git commits. The issue records below were read directly on GitHub.

| Source | Revision or evidence | Role |
| --- | --- | --- |
| `AGENTS.md` | `847bc4d34e434d492f8cf32358b5614de34b8893` | Mandatory workflow and approval boundary |
| `README.md` | `5a7718bdf659b5b961beca5133ca367d842a049c` | Development workflow and project boundary |
| `docs/ai_project_context.md` | `5b415c753e64c33493fd87179f86b12b5505273f` | Rationale and collaboration rules, not normative implementation spec |
| `docs/hardware_integration_workflow.md` | original blob `f3c33bf6f7e6336b4865fd23965c7062e4bc308a`; revised blob `ee23623bdd66a64d34d233e5e063adbd95c5b4d9` | Requirements discovery, evidence, review and approval |
| `contracts/schema-v1.json` and `contracts/README.md` | original schema blob `f857abae101a518c81639af189604c9368a61ebd`; revised schema blob `b11eb1ff8eda606335903077a6423e064c78daa3` | Original authoring format; version-1 relaxation documented below |
| `docs/hardware_protocol.md` | `ce04fb587cacd6c3a9df7336442e9d2d9fcfa635` | Approved protocol v1 and receiver behavioral profile |
| [Issue #4](https://github.com/marco-buttu/synqaro/issues/4), [issue #6](https://github.com/marco-buttu/synqaro/issues/6), completion comments | PRs #5 and #7, merged commits in YAML | Evidence of prior approval of the protocol/profile decisions |
| `docs/hardware_contract.md`, `docs/device.md`, `docs/project_vision.md`, `docs/getting_started.md` | supplied ZIP | Scope and architectural separation; introductory walkthrough is not a complete hardware spec |
| `docs/simquaro.md` | `17d33cb0e694c97d7e402c9f395c1c479038fe30` | Implemented simulator and existing conformance-test mapping |
| `docs/superpowers/specs/2026-10-28-simquaro-design.md` | `57092c9622791cacb621568465a94443c16e28eb` | Explicit implementation choices, not authority to revise the protocol |
| [Issue #8](https://github.com/marco-buttu/synqaro/issues/8), [#22](https://github.com/marco-buttu/synqaro/issues/22), [#32](https://github.com/marco-buttu/synqaro/issues/32), [#36](https://github.com/marco-buttu/synqaro/issues/36) | issue bodies | Context for existing client, documentation and GUI; not new hardware decisions |
| [Issue #38](https://github.com/marco-buttu/synqaro/issues/38) and its four completion comments | sections 1–3a checked; PRs #39–42 | Migration scope and explicit approval gate |

Implementation evidence: `src/simquaro/models/fictitious_receiver/{config,model,procedures,validation}.py`,
`src/synqaro_protocol/profiles/fictitious_receiver.py`, `src/synqaro_protocol/client.py`,
`src/synqaro/web/static/{index.html,app.js}`, existing `tests/simquaro/` and browser tests.
This is source inspection, not a fresh end-to-end test run. See the existing
[conformance scope](simquaro.md#executable-conformance-scope) for earlier evidence.

## Readable contract summary

| Topic | Agreed requirements in revision 0.2 |
| --- | --- |
| Purpose | Tune and calibrate a fictitious receiver; no scientific measurements or acquisition. |
| Interface | TCP ASCII protocol v1, `get`, `set`, `run`, `status`, `cancel`, `reboot`; shared framing and correlation rules stay in the protocol. |
| Configuration | Flat read-only descriptor: identity, firmware/build, capabilities, profile limits and clock capability. No inferred compatibility or silent fallback for this model. |
| Firmware compatibility | Protocol v1 is mandatory; no verified physical firmware release is declared. The empty list is not a wildcard. Prefer verified firmware reuse; evaluate reasons for replacement. |
| Frequency | Read/write, 1–10 GHz inclusive, 1 kHz grid; validate original range before nearest rounding, ties toward higher frequency. Apply and verify within 1 s; overlapping writes return BUSY, never queued. |
| Reading | Fresh observation when valid; no firmware-side cache. Trustworthy acquisition timestamp when available. Unavailability is not a guessed value; UNVERIFIED applies after loss of tuning verification, distinct from a failed acquisition. |
| Calibration | No parameters; invalidate prior calibration, save frequency, calibrate, verify and restore before success. Failure/cancellation leaves it invalid. A successful same-frequency setting preserves calibration; a changed frequency or failed setting that loses verification invalidates it. Rejection before hardware effects preserves it. Normal simulated duration about 10 s; execution deadline 30 s. |
| Scan | Required start, stop, GHz, dwell 1–1000 ms. Ten distinct monotonic rounded targets including endpoints; hold after verification, count only completed holds, leave final frequency. Execution deadline 20 s. |
| Cancellation | Calibration except finalization; scan throughout. Accepted is not stopped. Repeated cancel does not reset stop deadline; actual success may win a race. |
| Controlled stop | Additional 5 s after timeout or accepted cancellation; if stop is unconfirmed, STOP_TIMEOUT, active/unknown activity, no false terminal result, no conflicting work. |
| Status | Separate health, activity, calibration validity, active fault codes and boot identity. Current/latest procedure outcome retained through reconnect, not guaranteed across reboot. |
| Reboot | Separate verb, accepted before restart; active procedures may be interrupted. New boot ID; no invented procedure outcomes or automatic repeat. |
| Connection | 4096-byte frames including LF, 2 s incomplete-frame limit, four pending requests per connection, increasing IDs, independent correlation. |
| Recovery | Client 2 s response/connect-attempt deadlines, 5 s pause after failed reconnect, default 500 ms procedure polling. One status probe after timeout, fresh affected state, no automatic modifying replay. |

The approved scan example from the protocol is an independent oracle: from 5 to
5.2 GHz, the targets are `5, 5.022222, 5.044444, 5.066667, 5.088889, 5.111111,
5.133333, 5.155556, 5.177778, 5.2`. Descending is the reverse. These are targets,
not observations. No assumption of exact equidistance or data synchronization.

## Assessment and discrepancies

### Duplication and implementation-specific choices

| Finding | Source inspection | Assessment / later work |
| --- | --- | --- |
| Fixed profile limits duplicated | `config.py` contains defaults and a fixed-value validation dictionary; `_descriptor()` in `model.py` assembles capability lists; client `_descriptor()` in `profiles/fictitious_receiver.py` separately enumerates the same values. | Keep one approved model contract; in section 5 derive applicable model and descriptor checks, retaining independent protocol/conformance oracles. Firmware remains authoritative for its physical limits. |
| Frequency and scan validation duplicated | `validation.py:parse_frequency`, `model.py:_scan_parameters`, client `_refresh_usable` contain hardcoded bounds/grid/count. `procedures.py:status` hardcodes ten points and progress scaling. | Derive applicable constants and checks from the approved definitions, without turning behavioral rules into a new language. Do not change the currently approved rounding or scan algorithm. |
| GUI operations hardcoded | `index.html` has fixed frequency/scan fields, unit labels and procedure options; `app.js` registers explicit receiver operation handlers and polling. | Section 5 should drive standard controls/validation from the approved model contract. Manual/raw diagnostics, session policy, safety confirmation and simulator administration remain separate. |
| Error meanings repeated | Protocol catalog, shared `errors.py`, receiver client profile, and simulator raise sites. | Link common errors to protocol; keep receiver-specific consequences and recovery in contract. Generated catalogs can reduce drift, but independent tests retain explicit expectations. |
| Nominal timing and internal reference | `ReceiverConfig` uses 100 ms tuning/stop and 1/8/1 s calibration phases; `_calibrate` tunes to 6 GHz. Procedure tests inspect these internals. | Simulator choices, not requirements for receiver physics. Keep approximately 10 s nominal simulation and documented behavior distinct from exact simulator scheduling. Do not require 6 GHz calibration reference or a universal 5 GHz boot frequency. |
| Documentation scope differs | Getting Started introduces frequency and calibration; scan is intentionally deferred there (#22). | Educational omission is not a removal of an approved scan capability. Keep full contract separate from tutorial. |

### Decisions confirmed by the project owner (revision 0.2)

All four blocking questions in revision 0.1 were resolved in the review dialogue
with the project owner on 2026-11-24, who explicitly authorized the schema, authoring tests,
contract and review updates. The record below summarizes those decisions and their
rationale; these earlier decisions alone did not constitute approval of the complete
contract. The later explicit approval is recorded below.

1. **Firmware version policy (`firmware_scope`).** The owner agreed that protocol
   version and firmware release are independent; firmware need not exist at
   contract authoring or approval. Reuse verified compatible firmware when
   available; assess the team's reasons if it rejects reuse. The owner authorized
   an empty `firmware_versions` list; it means no declared verified releases,
   never arbitrary compatibility. `0.1.0` and `example-build` are illustrative
   descriptor defaults. The current client checks only for nonempty labels;
   that does not establish firmware compatibility. The contract claims no physical
   firmware conformance. Authorized simulator tests and exploratory probes remain
   possible without a prior production compatibility declaration. Record the
   identified build and conformance evidence before declaring compatibility.
2. **Overlapping short sets (`short_set_overlap`).** The owner agreed to reject
   a second setting during an existing setting with BUSY, without a queue. This
   agrees with the current `_busy` implementation, but the requirement comes
   from the decision, not the code. Sequential requests remain supported.
3. **Unverified frequency (`unverified_reason`).** The owner agreed to return
   VALUE_UNAVAILABLE with reason UNVERIFIED after loss of frequency verification
   until a reliable value can be obtained. Preserve the existing distinction
   between CALIBRATING, TUNING and an actual failed acquisition
   (FREQUENCY_READ_FAILED). This clarifies a model-specific reason, not a new
   common protocol error code.
4. **Calibration validity (`uncertain_calibration`).** The owner agreed that a
   successful same-effective-frequency setting preserves calibration; a successful
   change invalidates it; failed application that loses verification invalidates it
   even when requesting the same value; rejection before hardware effects leaves
   validity unchanged. Invalid calibration cannot be restored by merely reading
   or setting the same frequency; a new successful calibration is needed. This
   follows from the decision to invalidate calibration. General status retains
   the original rule to omit the field in other genuinely indeterminate cases.
   The model's `_tune` currently clears calibration only on target change or a
   diagnosed synthesizer failure, so a same-target lock failure can leave
   `_calibrated` true despite lost verification. This is a section-5 discrepancy
   to verify with an independent regression test and correct after approval.

The schema relaxation is separately authorized by the maintainer. No wire protocol
or production framework change is authorized. The contract records the four
requirements as confirmed and removes their blocking entries; the remaining
open items are explicit scope exclusions. Existing implementations have not been
adapted to these decisions. Verification of simulator behavior belongs to section 5.

## Schema fit and remaining verification

Schema v1 can express the two properties, fixed descriptor fields, scan parameters,
procedure states, constraints, errors, requirements and scenarios. The separately
authorized schema-v1 relaxation permits an empty firmware release list, while
retaining the required field, unique nonempty string items and all other rules.
No new schema syntax is introduced. Existing valid v1 contracts remain valid;
older validators reject empty lists and must be updated.
`configuration.value` is a logical object with all fields required; on the wire the
response is still flat. Shared `status` and `reboot` are not additional properties or
`run` procedures. Their response shapes and lifecycle rules are in the referenced
protocol and behavioral requirements; optional status fields are not forced into the
schema's all-fields-required object representation. Standard GUI actions still need
shared protocol support in addition to model definitions.

Version 1 lacks cross-field references for value descriptors. The same frequency
bounds and resolution must therefore appear in the frequency property and two scan
endpoint descriptors; descriptor field descriptions point back to these definitions
rather than copying every constant. Capability lists also need exact-set semantics
in prose (array item enums and lengths do not by themselves prohibit duplicates).
The numeric `deadline_ms` is the execution deadline, not an unconditional guarantee
of a terminal result. After unconfirmed stop, the state may remain nonterminal.
These are documented semantic checks, not claims of automated schema enforcement.
No other schema constraint or validator logic is changed.

### Evidence and scenario review

Existing independent expectations can be found in:

- `tests/simquaro/test_protocol.py`: exact rounding, original bounds, types and syntax.
- `tests/simquaro/test_receiver.py`: descriptor, validation, lock failure, clock faults,
  concurrent tuning and disconnection.
- `tests/simquaro/test_procedures.py`: restoration, exact ascending/descending sequence,
  hold validity, stop deadline, non-cancellable finalization, completion race and reboot.
- `tests/simquaro/test_server.py`, `test_conformance.py`, `test_recovery.py`: framing,
  correlation, admission, lost outcomes, descriptor compatibility, reconnection and reboot.
- `tests/web/test_browser.py`: existing managed operations, manual console separation,
  scan, cancel, reboot and explicit authorization of modifying checks.

These tests have not been rewritten or run in this review, and are not automatically
normative. Section 5 must trace them to the approved requirement IDs and add missing
independent scenarios, especially for the four decisions above. The YAML scenarios
are acceptance descriptions, not executable tests or proof that hardware conforms.

### Exclusions and completeness

All workflow topics have a documented disposition: identity/compatibility (policy
confirmed; no verified physical firmware release declared); physical platform
(not applicable to fictitious receiver);
communication, values, procedures, cancellation, concurrency, startup, errors,
configuration, clocks and verification (defined within the selected scope).
No physical hardware, physical clock/measurement accuracy, scientific acquisition
or data-frequency association, bulk transfer, streaming, real-time control,
independent protection, external reset, generic recovery, Device cache or deployment
history infrastructure is included. The original protocol and Device architecture
retain these deferred topics/requirements; exclusion here is not rejection of a
future capability. Simulator startup/phase defaults and fault administration remain
separate implementation concerns. No exploratory real-hardware probes are possible.

## Validation and approval gate

Validation results for revision 0.2: the repository validator accepted both the
illustrative example and the receiver draft. All 21 contract unit tests passed
using Python 3.13.5 and the available PyYAML/jsonschema dependencies. Two tests
were added to verify empty lists in draft and approved contracts, and rejection
of missing, duplicate, blank or non-string firmware version entries. The
validator implementation itself required no change: it reads the schema. A
successful structural/consistency check does not
establish semantic completeness, hardware behavior or approval. The full runtime
and browser suites were not rerun. The author performed a static comparison; there
was no independent reviewer or hardware verification.

Revision 0.2 has 21 confirmed requirements and 19 verification scenarios, with
no remaining blocking questions within the defined scope. All requirements have
scenario references. The exact YAML revision and scope/exclusions were submitted
for explicit approval before implementation migration.

## Formal approval

- Approver: Marco Buttu, project owner acting as hardware-team approver.
- Date: 2026-11-24.
- Approved revision: `0.2` of `fictitious_receiver`.
- Scope: the 21 confirmed requirements, 19 verification scenarios, referenced
  protocol and explicit exclusions in the submitted contract and this review.
- Evidence: in the contract-review conversation, after the explicit request for
  formal approval of revision 0.2, the owner replied: "Ti do la mia approvazione"
  ("I give you my approval"). This record transcribes that approval; it is not
  a GitHub comment or a cryptographic signature.
- Submitted draft SHA-256: `ac85c4fb27939a5dfe2d6e4cd6a2369ccdca495777b8c2e825ce5a1402ddd4ee`.

The approval update changes only the YAML status, approval metadata and header
comment; the substantive contract is identical to the submitted draft. The
approved revision remains 0.2. The repository validator and all 21 contract
unit tests passed again after recording approval. No independent review, full
runtime/browser suite or physical-hardware verification was performed.

GitHub previously rejected branch creation with HTTP 403. The approved contract
and review are supplied for the owner to commit/push. Link the published revision
and approval evidence from issue #38 and update its section-4 checklist. No
GitHub issue update or section-5 implementation has been performed in this step.
