# Hardware console implementation

Approved scope: the conversation's GUI layout and lifetime decisions, tracked in the GUI redesign issue. Work on a branch in the existing checkout.

## Task 1: Server state

Write failing tests for persistent/discoverable sessions, observation without hardware probes, verified GUI/external ownership and mixed batch results. Extend existing session/job/runtime services rather than add a separate daemon. Existing transient session API retains lease semantics; GUI requests persistent sessions. Persistent connections are shared per target and mode within this trusted single-user server. A mode replacement must be explicit. Batch work records each target outcome and never retries uncertain operations automatically.

## Task 2: Browser interface

Write failing browser tests for mode filtering, All, management status, panel visibility, reopening and unsaved configuration preservation. Keep existing command/fault/test/configuration behavior. Add Communication target selection from active simulator processes or server-connected hardware. Observation never silently connects hardware. Unknown or failed process inspection is not counted as running.

## Task 3: Verification and delivery

Run base and web/browser suites. Review the whole change with a fresh reviewer, fix important findings with regression evidence, and inspect desktop/mobile screenshots. Update obsolete operational lifecycle notes without drafting the next documentation tutorial. Commit, push, PR, merge, and verify issue and repository state.

## Progress

- Planning: no code changes yet. Existing server ownership uses run tokens; reuse it for classification. Existing browser sessions expire after 120 seconds and pagehide disconnects; change only GUI persistent sessions.
- Pre-flight: task 2 consumes task 1 overview/session data. Keep configuration drafts independent of observation refreshes.
- Task 1: API tests observed RED for missing overview/persistence, then GREEN. Added regressions for repeat Start preserving connections and dead TCP not reported as a successful Connect; observed RED and fixed.
- Task 2: browser management workflow observed RED, then GREEN for batch startup, reopening with the same session, workspace switching, draft preservation and hardware failure details.
- Ruling: retain transient API leases for compatibility; GUI uses one persistent connection per target shared by tabs. This avoids orphan per-tab connections exhausting limits. Explicit Disconnect/mode change affects tabs sharing that target; documented in operator guide.
- Ruling: counts cover the selected category; Details and operations cover the selected target(s). No process is classified as external solely from a name; responsive verified run identity is required.
- Verification isolation: browser tests now set a private XDG_RUNTIME_DIR; previous tests could observe external instances in the default runtime directory. No external instances are stopped by the revised tests.
- Independent review found two regressions: inventory reload advanced the revision without refreshing editor values, and a hardware mode change removed its disconnected console. Both were reproduced with failing browser tests and corrected. Explicit inventory reload now refreshes editor and revision together; a selected disconnected hardware console remains available for explicit reconnection.
- Verification: 312 base tests (one optional test skipped) and 22 API/browser tests passed. Desktop and narrow screenshots inspected; no physical-hardware verification claimed. Review ended after reporting the two reproduced findings because the reviewer reached its usage limit.
