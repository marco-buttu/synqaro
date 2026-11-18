# Hardware integration workflow — issue #38, section 1

## Approved scope

Implement section 1 of [issue #38](https://github.com/marco-buttu/synqaro/issues/38):
document contract-driven development, create the integration workflow and require
agents to read it from root AGENTS.md. The conversation and issue are the approved
specification. Work on a branch in the current checkout, as requested previously.

## Implementation

1. Create `docs/hardware_integration_workflow.md`: required reading, conditional
   interview checklist, unknown/conflict tracking, impact assessment, completeness
   and explicit approval, and handling subsequent changes.
2. Create a short `AGENTS.md` that triggers that workflow. Link it from the existing
   hardware-contract introduction and README development documentation.
3. Check local Markdown links, whitespace and coverage of section 1. Review the
   documentation independently before commit, push, PR and merge.
4. After merge, check only section 1's three tasks and comment on issue #38 with
   the implementation and merge commit links. Leave the issue open.

## Constraints and review focus

- No runtime, GUI, tests or contract schema changes in this step.
- Never claim that validators, generated GUI or agent-loading enforcement exist.
- Reading and approval must be usable without this conversation; link real files
  and explicitly handle the not-yet-created `contracts/` schema.
- Distinguish team contract approval from maintainer architectural approval.
- Do not make hypotheses authoritative or infer hardware requirements from code.
- Preserve the user's unrelated `.gitignore` change.

## Verification record

Checked five Markdown files: 21 local links/anchors resolve and code fences are
balanced. Whitespace checks pass. Independent review approved section 1 with no
blocking findings. No runtime behavior is changed, so hardware or browser tests
do not establish additional evidence here.
