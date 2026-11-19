# Exploratory hardware verification — issue #38, section 3a

## Approved scope

Document the user's approved iterative discovery cycle for existing hardware:
the agent guides access, obtains a bounded test authorization, probes real hardware,
records evidence, discusses mismatches and refines the draft before contract approval.
Distinguish declared, observed and agreed behavior; approval remains required for
production implementation changes. No actual hardware access or probing is requested
in this documentation task.

## Work

1. Add a section after the interview in the existing integration workflow; update
   completeness/approval wording to permit separately authorized exploratory probes.
2. Explain the cycle simply in the hardware-contract introduction.
3. Add section 3a before receiver-contract definition in issue #38, preserving the
   existing section numbers and completed work. Mark its documentation tasks after
   merge, not actual physical testing.
4. Check links, whitespace and consistency; independently review, commit, push,
   PR and merge. Comment with commit and verification evidence.

## Review focus

Do not confuse reachability with authorization, read-only names with harmless
effects, observed quirks with requirements, or TCP replies with physical proof.
Account for automatic library/bootstrap traffic and uncertain command outcomes.
Reuse agreed authorization rather than requiring approval for every individual probe.
Keep schema and runtime unchanged; source references can carry evidence records.

## Verification

Checked three documents and 14 local links/anchors, balanced code fences and clean
whitespace. Independent documentation review approved the exploratory scope and
approval boundaries with no blocking findings. No runtime or physical-hardware
tests were run; this delivery defines the process only.
