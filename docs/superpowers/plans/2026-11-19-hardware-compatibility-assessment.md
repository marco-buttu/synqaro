# Compatibility assessment — issue #38, section 2

## Scope and approach

Implement all six checkboxes in section 2 of
[issue #38](https://github.com/marco-buttu/synqaro/issues/38).
Expand the existing assessment section of the hardware integration workflow;
reuse its AGENTS.md entry point and approval process rather than adding parallel
instructions. The issue and preceding discussion supply the approved requirements.

## Work

1. Make the assessment actionable: separate needs from solutions, check existing
   capabilities with evidence, locate limitations, compare alternatives and record
   a recommendation and decision.
2. Specify separate maintainer proposals and explicit dependency states so approval
   is not mistaken for implementation or availability. Add a grounded example from
   the protocol's existing scan/data-association limitation.
3. Verify the six requirements, Markdown links and whitespace; obtain independent
   documentation review. No runtime or contract-schema changes are in scope.
4. Commit, push, PR and merge; check only section 2's six boxes and comment with
   commit references. Keep issue #38 open.

## Review focus

- Supported integrations do not need unnecessary architectural approval.
- Implementation defects do not automatically require rewriting a contract.
- Unknown limitations remain unknown until evidence supports their classification.
- Maintainer approval and proven capability availability remain distinct.
- A deferred extension does not silently erase the team's operational need.

## Sources consulted

Issue #38 and repository files at base commit `2fabb41`: AGENTS.md, README overview,
hardware-contract introduction, integration workflow, protocol open issues and
Project Vision status. `contracts/` does not exist yet; this is a documentation
assessment procedure, not schema validation or a new hardware-contract approval.

## Verification

Five Markdown files checked; all 22 local links/anchors resolve, code fences are
balanced and whitespace checks pass. Independent documentation review approved
coverage of all six section-2 requirements without blocking findings. No runtime
behavior changed; no runtime tests were run.
