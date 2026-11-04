# Simquaro combined-delivery verification

Scope: the approved 2026-11-03 client/console and configuration/GUI plans, starting
at `6ce93b7`. The earlier explicit model-registry delivery is the baseline, not
new work in this delivery. GitHub completion is not authorized by implementation
alone; commits stay on the existing local branch until requested.

## Acceptance before independent review

- Base suite: 293 passed on Python 3.12.3 (56.206 seconds).
- Required web suite: 11 passed on Python 3.12.12 (23.143 seconds), including
  five real-browser workflows, five API tests and one foreground launch test.
- Chrome 156.0.8078.79: isolated browser contexts, Chromium sandbox enabled;
  desktop and 390 px screenshots inspected. No Node/CDN/frontend build.
- Linux Mint 22.1, Ubuntu noble base. FastAPI 0.162.0, Uvicorn 0.54.0,
  HTTPX 0.28.1 and Playwright 1.64.1 installed only in the repository .venv.
- A normal wheel includes HTML/JS/CSS. A clean temporary venv imported production
  modules with `-I` and no web extra; the GUI reported its missing-extra remedy.
  After installing the web extra, the installed wheel served the actual page,
  assets and inventory over HTTP from `/tmp`, outside the checkout.
- Physical hardware was not tested. Precise scientific-data alignment, bulk
  transfer, historical configuration/audit snapshots and remote multi-user serving
  are not delivered by this workbench.

## Engineering rulings and their costs

These consolidate the execution ledgers, including choices made before this
continuation; they are not additional user requirements.

1. Execute inline with one independent whole-delivery review, rather than a
   fresh implementer/reviewer per task. This bounds context/cost; errors may be
   discovered later, so per-task regression gates remain required.
2. Preserve the parser's existing inclusion of header `id` in parsed metadata.
   Roundtrip assertions compare fields/request ID separately; this does not prove
   whole-object metadata equality. Malformed metadata has independent tests.
3. Permit shared TCP `receive()` chunk sizes 1–4096 to bound partial managed
   frames without another reader. Strict chunk-size validation remains necessary.
4. Existing anomaly tests filter newly added TX/RX evidence when asserting anomaly
   categories. Exact anomaly checks and independent literal frames remain; an
   incorrect filter would otherwise hide evidence omissions.
5. Use directly approved socket-enabled unittest commands with recorded results,
   rather than the skill's wrapper. No tests are omitted; manual ledger accuracy
   replaces automatic task-completion bookkeeping.
6. Reuse the existing Python 3.12.12 binary for the local .venv because system
   Python 3.12.3 lacks pip. No system Python/pyenv settings change; both versions
   must be stated instead of implying one universal interpreter environment.
7. Consolidate component review into the final combined review to avoid reviewing
   the client twice before the mandatory GUI; integration defects may surface later.
8. Generic configuration normalization verifies exact decimal/float roundtrip,
   then delegates range/grid validation to model settings. Unsupported decimal
   spellings are rejected rather than silently rounded; no receiver limits leak
   into generic storage code.
9. Apply transfers the new child immediately with trusted Runtime startup evidence.
   Latest saved/active comparison happens on the following refresh, avoiding
   fallible/cancellable I/O before ownership transfer. The apply reply pins the
   requested revision, not an instantaneous comparison with a concurrent later save.
10. Reuse the managed client's Task-2 wire observer in GUI services; no second
    observer/state machine. Registered profile factories must return the ordinary
    production client expected by this interface.
11. Consolidate normal-wheel/core-only/web installation verification with final
    packaged assets, not an intentionally assetless intermediate distribution.
    Packaging defects can therefore surface at the final gate.
12. Outside-checkout base tests need repository ROOT, not `src`, on PYTHONPATH
    for deliberate `tests.simquaro.support` subprocess helpers. With PYTHONPATH
    unset, 16 failures/one error were traced to invisible test helpers; production
    imports independently resolve to installed site-packages. This is not evidence
    that production requires the checkout.

## Independent review

Pending the single fresh-context whole-delivery review and any substantive
RED→GREEN fixes. No merge or physical-hardware validation claim follows from
the pre-review results above.
