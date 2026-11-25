# Fictitious receiver contract application — issue #38, section 5

**Status:** implementation complete; final local test run reported passing by the project owner on 2026-11-25.

Baseline: branch `fix-issue-38`, commit `4d07931e649a0f9c23cdcb098870f31b3fbe859d`.
The supplied baseline archive's tracked tree matched GitHub tree
`0fbbeedad4c990b1588dbbffa8f129f5408cdeb8`. The [approved receiver contract](../contracts/models/fictitious_receiver.yaml)
revision 0.2, schema, approval record and [shared protocol](hardware_protocol.md)
are unchanged. The approved contract is the reference for future firmware
implementation and conformance review, not proof of compliance by any build.

## Implementation decisions

- `tools/generate_receiver_contract.py` validates and projects the approved YAML
  into the Python receiver profile, browser data and [structured reference](fictitious_receiver_reference.md).
  Generation is deterministic; `--check` detects stale or manually edited outputs.
  It introduces no production dependency on YAML or jsonschema, no new wire syntax
  and no general-purpose contract execution language.
- The simulator and managed library consume the shared Python definitions for
  property and procedure capabilities, descriptor fields, numeric constraints,
  procedure states and relevant timing. Behavioral algorithms remain explicit.
  Scan rounding and progression, verified frequency acquisition, cancellation,
  reboot and recovery are not generated from prose. Common protocol limits and
  implementations remain separate; the derived checks compare shared limits.
- A failed tuning operation that loses frequency verification now invalidates
  calibration even at the previously calibrated frequency. Rejection before hardware
  effects preserves calibration; a successful same-frequency setting preserves
  an existing valid calibration, but does not restore an invalid calibration.
  A fresh successful calibration is required. Unverified reads and concurrent
  writes have explicit independent regression assertions.
- The managed browser builds model-specific property and procedure controls from
  generated definitions, including numeric bounds, units and fixed parameters.
  Decimal comparisons and rounded scan span checks do not replace firmware-side
  validation; original input spelling is sent to the firmware. Common status,
  reboot, cancellation, session behavior, operation confirmations, the manual
  console and simulator administration remain explicit. UI example input values
  are not hardware defaults.
- Managed sessions for physical targets are read-only. The current contract's
  verified firmware list is empty. The wire descriptor cannot certify firmware
  provenance or conformance, and this change does not implement an admission
  mechanism for future verified builds. Direct library callers must apply the
  appropriate authorization policy; manual diagnostics and separately authorized
  modifying check suites remain available for exploratory verification. These are
  not a security boundary or a general authorization system.

The generator is intentionally receiver-specific. Changes to operation shapes,
rounding rules or behavioral semantics require a reviewed implementation change;
substantive changes to the approved requirements require a new approved contract.
No shared protocol or schema change is part of this migration. Validation on a
second model remains necessary before claiming a generic approach.

## Verification and traceability

The [scenario map](../tests/receiver_contract_traceability.json) links all 19
approved scenarios and 21 requirement IDs to relevant existing or new executable
tests. A consistency test checks exact scope, reference integrity and existence of
those tests. A link is not a claim of exhaustive scenario coverage, successful
execution or physical-hardware compliance.

New checks independently read the YAML and compare it to actual simulator
configuration responses, client descriptor validation, capability sets, shared
limits and error coverage. They reject stale generated outputs, drafts and
inconsistent scan definitions. Independent literal test oracles remain in the
protocol, server, receiver, procedure and recovery tests, including exact scan
points, rounding, wire frames and failure outcomes. New literal regressions
exercise failed same-frequency tuning, subsequent recalibration, overlapping
requests across actual TCP connections and cancellation after the initiating
client disconnects. HTTP tests cover the physical-target read-only policy.
Browser tests include generated input constraints and exact input preservation.

### Results (2026-11-25)

| Verification | Result |
| --- | --- |
| Approved YAML validator and generator `--check` | Passed |
| Final targeted suite: contract, config, protocol, receiver, procedure, conformance, TCP server, recovery and model boundary tests | 144 passed |
| HTTP/API suite after physical read-only policy change | 14 passed |
| GUI foreground launch test | 1 passed |
| JavaScript syntax checks (both files) | Passed |
| Agent's final non-browser pytest run | 361 passed, one failed, one skipped; 18 browser tests not run |
| Isolated rerun of `test_ctrl_c_closes_promptly` | Passed; earlier intermittent failure not diagnosed |
| Final local test run | Project owner confirmed tests pass after the pytest update; detailed output and skip counts not supplied |
| Real hardware / firmware | Not available or verified |

The agent's earlier Chromium navigation attempt was blocked by environment policy
(`net::ERR_BLOCKED_BY_ADMINISTRATOR`). The final local result is the owner's
reported verification, not an independently reproduced browser or full-suite run.
No independent implementation review or physical-hardware verification was performed.

Reproduce the checks using [developer verification](getting_started.md#scope-and-developer-verification).
The GUI's manual interaction paths and physical device verification remain distinct
from generated checks. This application is not evidence of automatic agent loading
or approval enforcement; those requirements belong to section 6 and follow-up work.
