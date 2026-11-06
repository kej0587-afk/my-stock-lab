# Held-view connection audit and ETF reopen fix

## Scope and preservation

Started from clean `main == origin/main == 870c675a`; fetched upstream before
editing and before pushing. No home edits were discarded. The earlier baseline
branch remains local. Audited Today Check, board, Precision Observatory and
Portfolio Analysis. No scoring/threshold/label/amount changes or performance
refactoring were mixed in.

## Evidence and diagnosis

- Browser control recovered; authenticated production navigation worked.
- Replayed the preserved 2026-11-06 21:53 Today export through board display and
  portfolio handoff helpers. All 10 positive-quantity holdings retained their
  code, gate, reason, technical signal and reference date. Source data remained
  unchanged; absent precision reviews did not grant execution permission.
- That CSV replay supplies an isolated audit context because CSV does not retain
  DataFrame attributes. It verifies display/handoff, not reconstruction of the
  original OHLCV calculation or a live account context hash.
- Production Portfolio Analysis initially linked all 10 saved Today results and
  showed the original 21:53 storage time. The board subsequently recalculated at
  23:51 during the US session. Its newer prices are not same-input parity evidence.
- A held Korean ETF's completed precision export agreed with its saved Today
  gate/code/date and showed the same restriction in the narrative and final check.
  The export reported `870c675a`, `restart_required=false`, no stale modules.
- Returning from that precision visit to Portfolio Analysis showed **0 connected
  saved signals**, without an account/holding edit.

The precision screen calls `mark_fin_score_not_applicable_db` on the first ETF
visit in each session. It unconditionally upserted even an already-exempt record.
The successful upsert calls `invalidate_watchlist_dependent_state`, which removes
both Today and board signal snapshots. This is a connection/cache lifecycle bug,
not evidence that the investment gate itself should be loosened.

## Bounded change

`042c0bef` makes the exemption write idempotent for an existing normalized record
whose source is `not_applicable`, auto/final scores are zero and manual score is
absent. It returns success without rewriting or invalidating saved signals.
New records, changed scores, manual overrides and other sources still follow the
existing save/invalidation path. Reads use the existing owner-scoped loader;
no new provider calls, cache TTL changes, schema or authentication changes.

The first encounter with genuinely different legacy metadata can still invalidate
old results intentionally. This change does not resurrect stale snapshots or
bypass account/input context checks.

## Verification

- Baseline decision gate: **1039 passed**, 92.117s,
  `cache/refactor_checks/decision_sbu30koo/summary.json`.
  All 509 recorded source hashes were checked unchanged before the patch.
- Added six regression cases: unchanged ETF reopening preserves saved views;
  changed final/manual/auto scores, a different source and a missing row still save.
- The preservation test failed before the fix. An intermediate verification also
  exposed a test fixture using uppercase DB keys; corrected it to the normalized
  lowercase key returned by the real loader, without changing production policy.
- Final selected decision gate: **1045 passed**, 88.248s, no errors/failures/skips,
  `cache/refactor_checks/decision_xuhsaf5x/summary.json`. `git diff --check` passed.
- Existing frozen-input execution-context tests cover Today/board/precision
  across the representative universe and market/target-data cases; existing
  portfolio bridge tests cover gate/date ownership and final-check permissions.
- Private replay script/result: ignored `cache/held_view_snapshot_audit.py` and
  `.json`. Original and precision ZIPs remain in local Downloads, outside Git.
  No account amounts, credentials or private exports are committed.

## Deployment and limits

Code `042c0bef` pushed to `origin/main`. Post-deployment authenticated UI verification
passed in a fresh browser session:

1. Board finished a new calculation at 2026-11-07 00:03 KST.
2. Opened the same already-exempt held ETF in Precision; result completed at 00:04.
3. Downloaded its completed review ZIP: `base_commit=042c0bef`,
   `restart_required=false`, `stale_modules=[]`.
4. Opened and ran Portfolio Analysis: **10/10 saved results remained connected**
   with price reference dates, rather than the pre-fix 0/10. The comparison table
   also received the reviewed ETF's final `실행 보류` state; other unreviewed
   instruments remained `미점검`.

The source storage time remained 00:03; the screen did not falsely restamp it as
the later portfolio render. No Cloud reboot was needed. A private screenshot is
saved as `Downloads/stock_lab_connection_verified_20261107.jpg`, not tracked.
Selected contracts are not a full-suite pass, investment performance validation,
or proof that every live instrument uses identical timestamps across screens.
No new full-calculation speed claim is made.
