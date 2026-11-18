# Synqaro GUI Package Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans.

**Goal:** Expose `synqaro gui` with ownership of the common GUI in the Synqaro package.

**Architecture:** Move the web package and assets to `synqaro.web`; give `synqaro` a small CLI. Reuse existing Simquaro inventory/runtime/check services directly; do not extract another framework. Keep `synqaro_protocol` independent. The old GUI command is a deprecated lazy forwarding shim only.

**Tech Stack:** Python/setuptools, existing FastAPI/HTML/JS GUI, Bash installer, unittest/Playwright.

**Spec:** User-approved separation: common GUI belongs to Synqaro, simulator lifecycle/fault commands remain Simquaro. Clean design, no new service or duplicated GUI. Implementation choices: distribution name Synqaro, two console entry points, preserve current config/runtime paths, compatibility alias warning on stderr.

## Constraints and review focus

- No migration/deletion of user inventory or runtime paths.
- Both CLIs expose help without optional web imports; GUI errors preserve --config and structured stdout.
- Installed wheel includes relocated static assets; old alias uses the same implementation.
- Installer never overwrites foreign executables; removal only unlinks launchers pointing to its own prefix. Existing v1 installation markers remain valid; companion launcher is derived from the recorded launcher's directory.
- Existing configuration/GUI behavior and local-only boundary remain unchanged.

## Task 1: GUI package and CLI

- [x] Write failing new CLI/help/error/alias and launch tests.
- [x] Move web files without duplication, add synqaro entry point, update imports/package metadata.
- [x] Verify base and API/browser suites with canonical command.

## Task 2: Installation and documentation

- [x] Add failing tests for foreign synqaro launcher and safe two-launcher removal.
- [x] Add companion launcher install/remove, preserve existing marker and config paths.
- [x] Update active documentation and real-install test; run real isolated install/reinstall/removal including installed HTTP/static assets.
- [ ] Independent review, commit, push, PR, merge and issue closure.

## Progress

- Clean main at start. Task 2 consumes the two entry points and renamed package from Task 1; installer publishes only after validating both entry points.
- RED observed for missing canonical module, legacy warning, foreign companion conflict, and stale companion link on removal. GREEN after implementation. The missing-web fixture initially had insecure file permissions; corrected to 0600 before verifying the expected dependency error.
- Verification: 318 base tests passed (one optional skip), 26 API/browser tests passed using the canonical entry point; the separately enabled real install/reinstall/removal test passed. Installed HTTP and static assets verified after source snapshot deletion; failed reinstall preserves both launchers; an existing v1 marker without a companion launcher upgrades successfully. Bash syntax and diff whitespace checks passed.
- Development environment migration documented: uninstall the old distribution before installing the renamed one; installer users need no manual migration because each release uses a fresh private environment.
- Independent review attempt ended at the reviewer's usage limit without a verdict. Final self-review checked CLI delegation, error/config propagation, package assets, companion-launcher ownership and marker compatibility; no blocking defect found. This is not an independent-review completion claim.
