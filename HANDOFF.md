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

Current task: summary-worker/analyst wait instrumentation based on `f746134c`.
Focused tests 166 passed; decisions, calls, cache keys/policy and concurrency
unchanged. Per-symbol stage timings plus analyst-context lock/throttle/provider
timings and cache events added. Production verification pending code push.
See [wait diagnostics](docs/maintenance/20261107_summary_wait_diagnostics.md).

Latest change: **`a25bd5ff` pushed**, exact **6mo leveraged-watch batching**, based on `b82d1b61`.
One summary scope shares successful frames, avoids overlapping batch duplicates,
and retains KR/missing/forced-refresh/original precision paths. No rules changed.
Focused contracts 205 passed plus final batch contracts 44 passed. Prices gate
remains 265 passed / one pre-existing AST failure. Local measured path 7.567s ->
2.437s, actual Yahoo chart HTTP 23 -> 23; not a controlled Cloud speedup.
**After user Reboot, new path verified** in full Cloud run
`6f1101e4f03b4f929275cce41dcfeb6e` (11:26–11:27 KST), build `42e80cb1`:
95 rows, **107.934s** / script 119.269s, zero instrumented errors.
Four 6mo batches, 13 shared hits, 36 batch-frame hits, two original KR fallbacks;
new quote/history/batch timers present. New path union 12.250s. Prior 90.206s
run used the old module; the latest full run is slower, not a proven speedup.
Analyst phase 2.212s -> 9.038s, stock signals 25.054s -> 34.858s; conditions differ.
KR scope still reuses 30 requests (416 -> 386 HTTP). All cache/rule settings kept.
UI/export ID and local/loaded app hashes match; no further reboot needed. See
[watch-history record](docs/maintenance/20261107_leveraged_history_batch.md).

Earlier measurement: **KR provider-cache expiry run**, 2026-11-07 09:37–09:39 KST,
ID `2f717dae89a341ba8e3c2f08676d4bcd`, build `5b5d81f6`. About 48 minutes elapsed
since the last visible calculation; no preliminary price/flow reload. Same
95-row calculation/settings. **91.089s** Today Check / **94.807s** script.
Actual duplicate reuse confirmed: 427 provider-cache lookups = 13 existing-cache
hits + 414 reader calls; **414 = 384 HTTP requests + 30 new-scope reuses**.
30 bypass events preserve cache age. No instrumented errors. Provider misses
96.96%; financial caches can still be warm, so not a fully cold app benchmark.
Price / indicator / external-data active unions: **56.841 / 19.137 / 28.666s**
(overlapping). Prices still dominate; leveraged watch rows cover 17.129s active
union (five builds, 38 rows), a bounded next I/O target. No code/rule changes.
See [expiry measurement](docs/maintenance/20261107_kr_history_expired_measurement.md).

Latest code: **`661431f9`**, exact KR daily-history request reuse, pushed and
verified executing in production (`kr_history_scope.enabled_v1=1`, 277 lookups).
Only identical resolved provider/date/count requests share successful copied
frames in one run. Existing TTL/failure/refresh and decision rules unchanged.
Fixed-response requests 8 -> 5; actual local Naver duplicate requests 3 -> 1
(1.125 -> 0.352s), with all 244-row frames exactly equal. All non-wrapper app
functions match immutable `24244c3e`; decision golden checks pass.
Focused tests 77 passed. Prices gate retains the same pre-existing structural
AST-freeze failure before/after (259 / 265 passed); no golden rebasing.

Adjacent full production runs: **89.438 -> 70.245s**, same 95-row count/settings,
but provider caches were warmer afterward and new-scope reuse was **zero**.
Do not attribute the 19.193s reduction or 416 -> 277 KR requests to this change.
Before had one recovered overseas fallback ConnectTimeout; after none.
No reboot required, no account changes. See the exact IDs, cache limitations,
request proof and private evidence in the
[request reuse record](docs/maintenance/20261107_kr_history_request_reuse.md).

Previous task: **production Today Check bottleneck measurement**, on build
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

Latest record: [Watch history batching](docs/maintenance/20261107_leveraged_history_batch.md).

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

**Verify the new wait diagnostics in one full production Today Check.**

Keep the existing all-account/95-row scope and flow-refresh option. Confirm new
per-symbol timers and analyst-context cache/lock/provider events in the matching
completed JSON. Distinguish worker sums from wall time and callbacks from HTTP.
If old modules remain loaded, record evidence before requesting Cloud reboot.
Do not change TTL/concurrency or investment rules. Commit/push the measured
findings and select exactly one evidence-based next task.

## Evidence and Remaining Limits

- Latest: [Watch history batching](docs/maintenance/20261107_leveraged_history_batch.md).
- Latest: [KR cache expiry measurement](docs/maintenance/20261107_kr_history_expired_measurement.md).
- Previous: [Exact KR request reuse](docs/maintenance/20261107_kr_history_request_reuse.md).
- Previous: [Today Check bottleneck measurement](docs/maintenance/20261107_today_bottleneck_measurement.md).
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
