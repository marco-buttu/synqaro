# Independent Receiver Console Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans.

**Goal:** Make manual console modes independent of receiver operations and combine the manual connection/console UI below operations.

**Architecture:** Reuse SessionManager with one persistent managed and one persistent manual session per target. Mode defines purpose; no second service. Operations connect on the first explicit command, never on workspace selection. The manual panel owns Literal line/Raw mode, connection controls and collapsed evidence/input.

**Tech Stack:** Python asyncio/FastAPI; existing HTML/JS; unittest/Playwright.

**Spec:** Approved conversational layout and separation. Implementation choice announced: explicit exclusive manual connection for single-client hardware, confirmed before releasing this server's connections. While exclusive manual session exists, operations cannot reconnect; manual disconnect releases it. No automatic capability detection or automatic retries.

## Constraints / review focus

- Manual mode changes/disconnect must not affect managed operations unless exclusive takeover was explicitly selected.
- Browser reload restores both session identities without probes/replay; status and evidence cannot cross targets or purposes.
- Takeover is serialized against concurrent opens and enforced server-side across tabs/API, including transient connections.
- Operations retain the existing managed client's recovery/reconnection and state reads; no automatic repetition of uncertain modifying requests. Manual connections never recover automatically.
- Closing manual details affects visibility only. Tests need both connections closed; shutdown/lifecycle still release both.

## Task 1: Server separation

- [x] Failing API tests: independent persistent sessions, raw/line conflict only within manual role, explicit exclusive takeover/block/release, concurrent opens.
- [x] Implement minimal session purpose grouping, serialized connection establishment, strict exclusive flag, metadata.

## Task 2: UI and delivery

- [x] Failing browser independence/layout/exclusive/reload tests.
- [x] Merge manual panels below operations; remove Guided selector; lazy operation client and separate status/disconnect/reconnect.
- [x] Update tests/docs, verify full suites and screenshots; independent review findings addressed.
- Delivery (commit, push, PR, merge, closure) is tracked by issue #36 and its linked PR.

## Progress

- Existing .gitignore change is user-owned and excluded. Task 2 consumes purpose/exclusive metadata from Task 1. Shared target ownership, lifecycle and inventory remain unchanged.
- Issue #36 tracks delivery. Independent review identified a target-switch race and an exclusive-takeover/shutdown race; both have reproducing regression tests and fixes. Recovery documentation now accurately describes the existing managed-client behavior. Final reviewer recheck was interrupted by its usage limit; final verification is performed by the implementer.
- Final verification: 318 core tests passed (one optional installer test skipped); 32 API/browser tests passed. Desktop and narrow screenshots inspected; no physical hardware tested.
