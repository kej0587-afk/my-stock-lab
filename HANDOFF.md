# Stock Lab Work Handoff

Updated: 2026-11-07 KST. Read before inspecting large source files or editing.
Check Git first; this document is not evidence that another computer has no newer edits.

## Resume Safely

1. Run `git status --short`, `git branch --show-current`, `git log -6 --oneline`
   and inspect upstream after `git fetch origin`. Preserve uncommitted/divergent work;
   never reset or force-pull it. Use `pull --ff-only` only on clean, compatible history.
2. Read AGENTS.md, this file and the latest linked measurement record below.
3. Use the installed environment. Home verification used
   `.venv311/Scripts/python.exe`; the other computer used `venv/Scripts/python.exe`.
4. Private exports/screenshots are outside Git and may not exist on another computer.
   Do not commit account data or secrets. Request login only if the UI needs it.

Repository: `https://github.com/kej0587-afk/my-stock-lab.git`, branch `main`.
Production: `https://3insky.streamlit.app/`.

## Current State

In progress: exact KR daily-history request reuse, verified locally against
immutable `24244c3e`. Fixed responses: 8 -> 5 actual identical requests; frames
and all non-wrapper app functions match. Focused tests 77 passed. Prices gate
has the same pre-existing AST-freeze failure before/after (259 / 265 passed);
see [request reuse record](docs/maintenance/20261107_kr_history_request_reuse.md).
Production before/after verification is pending the code deployment; do not
claim a Cloud speedup or old-module application until scope counters appear.

Latest task: **production Today Check bottleneck measurement**, on build
`bd65d26b`, measurement `e36d58ac51f7463b9d86820aa3c4f8f9` (2026-11-07
04:05:46–04:07:24 KST). Complete 95-row calculation: 98.540s wall, 101.682s
including entry/bookkeeping. Standard refresh, not fully cold; unchanged scope.
Price / indicator / external-data active unions: 66.016 / 20.936 / 23.361s;
these overlap and must not be summed. KR history made 414 HTTP requests, with
30.074s active union; the number of avoidable duplicates is not yet established.
Analyst enrichment (1.800s) and KR cluster snapshots (0.524s) are not the current
dominant bottleneck. Completed export/UI ID and local build matched; tracked
report modules were not stale. Documentation-only task, no reboot needed.
See [full measurement and limits](docs/maintenance/20261107_today_bottleneck_measurement.md).

Latest bounded refactor: **`051ac66c`**, pushed from clean/equal `11565166`.
Extracted only SMC context assembly into
`stock_lab_core/decision_smc.py::build_decision_smc_context`.
All ten original locals and seven dependency calls retain their order; result
assembly, detector algorithms, charts, thresholds, labels and amounts unchanged.
`calc_scores_and_decision`: 467 -> 463 lines; no measured speedup claimed.
The purpose is responsibility isolation, not merely reducing line count.

Verification: decision gate **1,132 passed before** (93.962s), **1,171 passed after**
(95.224s, 39 new tests). Focused SMC/follow-up/priority/import tests: 174 passed.
Twenty pre-edit full results match; exact unrounded outputs, dependency order,
nonmutation, failure propagation and loaded/stale provenance verified.
No golden files regenerated; immutable reference Git `11565166`.

Post-push GOOGL precision calculation, SMC detail display and review ZIP passed.
New helper loaded/disk/local hashes match; no stale modules/restart required.
No account/watchlist edits. Private UI/ZIP evidence is linked in the record below.

Latest record: [Today Check bottleneck measurement](docs/maintenance/20261107_today_bottleneck_measurement.md).

## Preserved History

- `042c0bef`: idempotent ETF exemption writes prevent clearing saved signals on
  precision visits. Decision gate 1045 passed; Cloud retained all 10 connected
  results after the visit. See the connection review below for exact evidence.
- `ff2e8490`: exact-parity MFI window optimization. Selected all gate 1453 passed;
  fixed-input indicator benchmark improved 26.9%. Cloud repeat times were noisy
  (roughly 70s), first-load time did not improve; no sub-minute guarantee.
  Full timing/cache/deployment limits are in the MFI record below.
- Home baseline branch `codex/home-baseline-20261106-29d90955` remains local.
  No user edits were discarded. Private exports/screenshots stay outside Git.

## Next Task Only

**Investigate and deduplicate only identical KR daily-history requests within one run.**

Start with `kr_flow_history.py::load_kr_flow_history`, the explicit period-start
caller in `prices.py`, and the default-start caller in `money_flow.py`. Record
sanitized exact-request identity/call-site counts before assuming the measured
414 requests are redundant. Normalize identity only when provider code, effective
start/end, request count and adjustment semantics are identical. Existing exact
period scopes already reuse 553 calls; do not replace them with broad range slicing.
Preserve timezone boundaries, frame/index/dtype/attrs, defensive copies, failure
cooldown and manual refresh. Do not alter TTLs, concurrency, data scope, rules or
portfolio values. If exact duplicates are not demonstrated, stop speculative reuse.
Run the prices regression gate before/after code changes, fixed-response parity
and request-count checks, then one comparable completed production calculation.
Report wall/self/parallel time and actual requests separately. Keep private
exports outside Git; commit/push verification and update this handoff.

## Evidence and Remaining Limits

- Latest: [Today Check bottleneck measurement](docs/maintenance/20261107_today_bottleneck_measurement.md).
- Previous: [SMC context extraction](docs/maintenance/20261107_decision_smc_extraction.md).
- Previous: [Decision finalization extraction](docs/maintenance/20261107_decision_finalization_extraction.md).
- Previous: [Theme stock display extraction](docs/maintenance/20261107_theme_stock_display_extraction.md).
- Previous: [Theme group display extraction](docs/maintenance/20261107_theme_group_display_extraction.md).
- Connection: [Held-view connection review](docs/maintenance/20261107_held_view_connection_review.md).
- Performance: [MFI window optimization and measurements](docs/maintenance/20261106_mfi_window_review.md).
- Previous: [Yahoo chart connection measurements](docs/maintenance/20261106_yahoo_chart_connection_review.md).
- Workflow: [Bounded refactor review](docs/maintenance/20261106_bounded_refactor_review.md).
- Previous timing IDs are in the MFI record. Connection evidence is in the held-view
  review; latest refactor verification is in the theme extraction record.
  Full JSON/ZIP/screenshots remain outside Git.
- The preceding connection optimization improved its quote segment but not full
  runtime (64.779s -> 66.336s on a different 96-row input). Do not blend those old
  measurements with today's 95-row runs or claim a sub-minute guarantee.
- Broader refactoring and investment-rule redesign remain separate future tasks.
