# Stock Lab Work Handoff

Updated: 2026-11-21 KST. Read before large source files or edits.
This is the current work order. Historical next-task instructions are superseded.

## Resume Safely

1. Inspect `git status --short`, branch, recent commits and upstream after fetch.
   Preserve home/company edits; never reset or force-pull. Fast-forward only when compatible.
2. Read AGENTS.md, this file and the latest bounded record. Installed home Python:
   `.venv311/Scripts/python.exe`; another computer may use `venv/Scripts/python.exe`.
3. Private exports/captures are ignored under cache or Downloads and may be absent
   elsewhere. Never commit credentials, account quantities or private reports.
4. Commit/push and necessary owner reboot are already authorized. Do not request
   permission again. Ask for direct authentication only when an actual UI requires it.
5. Finish one bounded task, verify, then update this file with exactly one next task.
   Keep output compact; do not start another broad task when unable to finish it safely.

Repository: https://github.com/kej0587-afk/my-stock-lab.git, branch `main`.
Production: https://3insky.streamlit.app/.

## Big Picture

[ROADMAP](docs/maintenance/ROADMAP.md) defines the sequence and exit criteria:
**data identity/period/session → cross-view consistency → market/company/account
explanation → measured performance → bounded large-function extraction**.

Quality, timing and account/execution limits answer different questions. The report
explains their evidence; it must not implement another scoring/permission engine.
Many shared helpers already exist. This is continuation, not a rewrite. Missing
supplier fields are explicit limitations, not a reason to block all later stages.
No score thresholds, decision labels, TTLs or trading permissions may be changed
under a behavior-preserving task. Investment performance validation is separate.

## Latest Completed Task

[2026-11-21 fixed partial-daily-bar audit](docs/maintenance/20261121_partial_daily_bar_audit.md),
based on `32541f3a`. New offline diagnostic/tests only; application code unchanged.

- Restored two private precision exports with exact price input IDs. Saved current
  price, RSI, ATR, source day return and R/R all match; saved scenario date/close match.
- 379810: 245 rows through Nov20 in both decision and completed observations.
- GOOGL: decision uses Nov20 partial bar (252 rows); A/B/C and report close use
  Nov19 (251 rows). Report intraday separately retains Nov20 with provisional label.
- GOOGL source RSI 36.838639 / ATR 10.818564 vs completed-only 30.579554 / 10.657137.
  Fixed quote/target R/R sensitivity 1.156570 -> 1.174086 is NOT a new decision.
- Differences are purpose-specific. Source rows do not certify completion; do not
  globally exclude partial bars under an unchanged-score task.
- Found report-only calendar inconsistency: on the code's Nov19 special session,
  16:00 KST is still before 16:30 close but generic report/board filters include it
  and phase says closed. Separate KR regular history already protects that path.
- Saved GOOGL intraday return label `전일등락` is ambiguous; leave numerical policy
  and decision labels untouched. Presentation clarification is a later bounded item.
- Verification: existing relevant contracts **344 passed** (32.66s; 2 existing
  pandas warnings); new audit **11 passed, 1 strict xfailed** (6.94s). The xfail
  reproduces the known special-session defect; it is not a completed fix.
- Actual saved operating inputs replayed with network blocked; no new live report,
  grade calculation or Cloud reboot. KR report's separate provider capture is not
  in these ZIPs; same-source helper comparison is not full-report certification.
- Artifact: ignored `cache/operating_20261121/partial_bar_consumer_audit.json`.
  Only synthetic fixtures, diagnostic source and docs go into Git.

Prior [Naver comparison](docs/maintenance/20261121_naver_source_comparison.md) was
completed in `32541f3a`: keep existing route, unknown polling time stays unknown;
basic per-symbol requests did not establish a no-extra-cost equivalent replacement.

The former 1,787-line handoff is preserved, unabridged, at
[HANDOFF_HISTORY_20261121.md](HANDOFF_HISTORY_20261121.md). It was copied before this
rewrite; its links retain their repository-root meaning. Read specific historical
records only as needed. Do not resume an older next task from that archive.

## Last Direct Production Verification

[Selected-quote observation record](docs/maintenance/20261121_naver_quote_observation.md):
production source `eb0af4a2`, documentation `f915d5ee`, owner Cloud reboot completed.

- Existing Naver basic evidence retains its own aware time/session; polling records
  source identity with unknown per-item time. Existing batch reuse preserves the carrier.
- Previous final selected-all gate: **2,466 passed**, zero failures/errors/skips,
  234.228s, `cache/refactor_checks/all_t0oang_2`. Not rerun for documentation/probe work.
- Operating Today: 95 rows, **106.065s**, completed measurement
  `c4cd1b65cb224e08ae4aefaee052ed76`; no stale tracked report modules.
- 45 domestic rows used untimed polling; 50 Yahoo rows retained chart timestamps.
  These 45 missing provider timestamps are not pending transport fixes.
- 379810 precision before/after: price 23,180, input ID `bf23c77900eefde6`, financial
  and technical scores, grade, decision code and gate matched. No global live guarantee.
- This was a normal refresh with potentially warm caches, not a fully cold run or
  proof of speed improvement. No new production calculation in the comparison task.

Private evidence: `cache/operating_20261121/`; Downloads
`stock_lab_review_export_20261121_0107.zip`, `precision_review_379810.KS (3).zip` /
`(4).zip`, `today_queue_c4cd1b65cb224e08ae4aefaee052ed76.json`.
The GOOGL precision `(34).zip` captured a regular-session partial daily bar,
input `e4f3a675caffbd4d`. Inspect availability before assuming a fixed replay exists.

## Next Task Only

**Align report session status and completed-bar cutoffs to the existing exchange calendar.**

Fix the reproduced special-session mismatch in `report_session.market_session_states`,
`report_evidence.closed_daily_frame` and the report-facing market-board filter through
one explicit session reference. Preserve intended per-consumer close buffers and
KR regular-history guards. Cover normal days, KR holidays/special hours, US early
closes and missing calendars without fabricating completion.

Start from `test_known_special_session_report_consumers_should_wait_for_actual_close`
in `tests/test_daily_bar_consumer_audit.py`; remove its xfail once the defect is fixed.
Run relevant report/price/session contracts before and after. Prove same fixed normal
session outputs; explain only intended special-session corrections. Do not alter
decision functions, partial-bar scoring policy, thresholds, labels, TTLs or sources.
Then verify the deployed report path as available; preserve exports and record exact
scope. Do not mix in new report features, the ambiguous return-label cleanup or more
provider replacement work. This is one report-calendar consistency task.

## Verification Discipline

- Use relevant existing contracts before/after edits:
  `.venv311/Scripts/python.exe -X utf8 scripts/check_refactor.py --scope decision`
  (or `report`, `prices`, `all`). Freeze sources while the gate runs.
- No golden regeneration to pass; old Nov-7 private baselines stay archived in
  `cache/historical_baselines_20261107/`, not restored over current caches.
- Compare remote requests/cache misses separately from calls; distinguish elapsed
  critical path from overlapping worker totals. Do not change TTLs to claim speedups.
- New offline audit command and exact limits: latest audit record above.
- Source architecture: [map](docs/20261104_architecture_refactor_map.md).
  Refactor procedure: [review](docs/maintenance/20261106_bounded_refactor_review.md).
