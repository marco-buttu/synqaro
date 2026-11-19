# Contract schema and validation — issue #38, section 3

Implement the approved section 3 without migrating the receiver or changing runtime
behavior. Read AGENTS.md, the integration workflow, hardware-contract introduction,
README overview and protocol definitions/open issues at base `5d24665`.

## Design

- YAML documents validated against a local JSON Schema 2020-12, version 1, under
  `contracts/`. Use standard PyYAML/jsonschema as optional development dependencies;
  do not write a schema language/parser or add runtime dependencies.
- Definitions cover hardware/firmware identity, protocol references, properties,
  procedures and their state model, errors, requirements and prose scenarios.
- Stable map keys support references. A small semantic pass checks those references,
  numeric/collection constraints, procedure states and approval metadata consistency.
- Drafts may contain proposed requirements and open questions. Approval checks only
  validate declarations, never authenticate an approver or prove semantic completeness.
- A clearly illustrative, unapproved example is a validator fixture, not a supported
  hardware model. The receiver contract remains section 4.
- Repository CLI: `python tools/validate_contracts.py [paths...]`; default validates
  examples and actual model contracts. No network fetching or hardware access.

## Tasks and verification

1. Add tests for valid contracts and independent invalid cases; observe failure
   before implementing schema and validator.
2. Add schema, example, validator and optional development extra. Test malformed
   YAML, duplicate keys, unknown fields, types, references, constraints, states,
   unsupported schema versions and approval/dependency consistency.
3. Document authoring, command, limits and semantic review; update workflow status.
4. Run repository tests plus contract CLI; independently review, then commit, push,
   PR and merge. Check only section 3 and leave issue #38 open.

## Review focus

Reject silently overwritten keys, unsupported YAML objects, nonfinite numbers,
contradictory constraints and dangling references. Do not confuse valid draft,
approved scope and actually available hardware capabilities. No generated runtime
or test behavior is claimed in this step.

## Review and verification

Initial tests failed because the validator was absent. Independent review then
reproduced three defects: JSON scientific numbers parsed as YAML strings, malformed
explicit YAML tags escaping as tracebacks, and finite-deadline state graphs with
nonterminating branches. Three regression tests reproduced the failures before
fixes; all 19 contract tests now pass. JSON has its own strict parser, explicit
YAML tags are rejected, and finite-deadline graphs require a terminal path.

Optional `contracts` dependencies are development-only; the documented contributor
command installs them and runs contract checks within the base unittest suite.
Final verification: 337 tests ran without failures (one optional installer test
skipped), including 19 contract tests; default validator passed. Six documents and
42 local links/anchors checked, with balanced code fences and clean whitespace.
