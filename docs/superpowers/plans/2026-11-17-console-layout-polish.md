# Console Layout Polish Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans for this single frontend task.

**Goal:** Apply the user's approved visual refinements without changing backend behavior.

**Architecture:** Keep existing panels and event handlers; replace the workspace select with three native buttons and one selected-workspace state. Use existing panel styling and CSS grid/flex layout.

**Tech Stack:** HTML, CSS, JavaScript, Playwright/unittest.

**Spec:** User-approved design in this conversation: matching control heights/alignment; concise status such as `✓ receiver-a: running · GUI: 1 · External: 0`; smaller footer `Closing this page keeps simulators and connections active.`; Workspace panel with aligned heading and Communication/Test/Configuration buttons, none selected initially. Header unchanged.

## Constraints and review focus

- No backend or connection-lifetime changes.
- Selected workspace remains unambiguous and keyboard-accessible.
- Switching workspace preserves existing sessions and configuration drafts.
- Mobile controls wrap without overflow; desktop controls align.
- Ownership/error details remain available under Details.

## Task 1: Frontend polish

Files: static index.html, style.css and app.js; tests/web/test_browser.py; brief operator-guide clarification.

- [x] Add failing browser tests for control bounds, heading alignment, concise status/footer and exclusive button selection.
- [x] Replace the select and migrate existing browser interactions to native buttons; retain initial empty workspace and existing target filtering.
- [x] Align management controls and add matching Workspace panel; preserve detail messages while simplifying the summary.
- [x] Run base and web suites, inspect desktop/mobile screenshots and obtain independent review.
- [ ] Commit, push, PR, merge and close issue with verification evidence.

## Progress

- Approved design captured above; existing branch was clean before work. One task, no cross-task interfaces.
- Two new browser tests failed before implementation (control bounds and absent workspace buttons), then passed. Full suites: 24 API/browser tests passed; 312 base tests passed with one optional test skipped. Desktop/mobile screenshots inspected. Preview test rerun passed after adding initial-state screenshot capture.
- Independent review: no critical/important regressions. Minor deferred: unused legacy `.workspace-selector` CSS is harmless and can be removed in later CSS cleanup.
- Ruling: stale Configuration runtime status after Start predates this change; track separately rather than expand the approved presentation scope. Cost: that existing panel can still show an old observation until explicitly refreshed.
