# Receiver Operations First Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans for this single frontend task.

**Goal:** Clarify running simulator ownership and prioritize guided receiver operations.

**Architecture:** Retain existing backend and sessions; place connection controls in their own always-visible Communication panel, then receiver operations, then a native Console disclosure initially closed.

**Tech Stack:** HTML, CSS, JavaScript, Playwright/unittest.

**Spec:** User-approved conversation design: `1 simulator running, started by this GUI` with plural support; append external running count only when nonzero. Receiver operations above collapsed Console. Connect/Disconnect/status outside disclosure; closing it never disconnects. The proposed command/package rename is explicitly separate.

## Constraints and review focus

- No changes to connection lifetime, protocol or backend ownership classification.
- Connection mode stays visible too, so Raw mode cannot silently disable guided operations behind a closed disclosure.
- Native disclosure must preserve session and wire evidence across open/close.
- Communication panels remain hidden in Test/Configuration; keyboard/mobile behavior retained.
- Counts cover currently running instances, with zero, singular and plural forms.

## Task 1

Files: static index.html, style.css, app.js; tests/web/test_browser.py; docs/simquaro.md and getting_started.md.

- [x] Add failing browser checks for collapsed-console guided operations and new ownership text.
- [x] Reorganize panels with semantic DOM order and native details/summary; update count wording.
- [x] Update existing browser tests to open Console only when using literal input/evidence.
- [x] Run base and web suites, inspect screenshots, independent review.
- [ ] Commit, push, PR, merge, close issue.

## Progress

- Approved scope captured; main was clean at start. One task with no cross-task dependencies.
- RED: new wording and collapsed-console tests both failed against the previous implementation. GREEN: final suite passed all 26 API/browser tests; 312 base tests passed with one optional skip. Real CLI process verified external counting and disappearance at stop. Screenshots inspected at desktop and 390px; reviewer independently checked keyboard disclosure and overflow at 320px.
- Independent review: ready to merge, no blocking regressions. Minor deferred: hardware management and per-target connection panels both use the heading `Connection`; distinguish their headings in later UI refinement.
- No physical-hardware compatibility claim. CLI/package rename remains a separate task.
