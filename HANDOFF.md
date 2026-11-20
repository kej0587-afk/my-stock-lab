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

[2026-11-21 report exchange calendar](docs/maintenance/20261121_report_exchange_calendar.md),
based on `58a51bff`. One shared local calendar now drives report session state,
completed daily bars and market-board cutoffs. KR special-session exceptions reuse
existing verified calendar data; US holidays/early closes use the same schedule.

- Nov19 16:00 KST stays intraday until 16:30; KR report and board preserve their
  existing separate close delays (0 / 15 minutes). US preserves 15 minutes.
- KR holidays, US Thanksgiving/13:00 early close, normal DST sessions, actual-open
  checks, unavailable calendars and input immutability are covered offline.
- Calendar unavailable means unknown/withheld, not a guessed weekday completion.
  Year-based calendar reuse adds no quote requests or changes to cache TTLs.
- Short-day regular hours do not certify extended-venue hours; do not invent a
  20:00 afterhours end on an early-close date. Normal extended windows are retained.
- Final related contracts: **253 passed**, 23.01s (41 new calendar/boundary cases). The previous special-session strict xfail now passes.
  Test dates with invented holiday prices were corrected; values/goldens retained.
- Fixed saved 379810/GOOGL consumer-audit JSON is exactly equal before/after.
  Current price, RSI, ATR, return, R/R and scenario date/close all match. These
  captures are normal-session cases, not a new full grade/live report calculation.
- Initial selected-all gate: 2,454 pass, 12 historical digest mismatches, no errors.
  Direct output diff isolates two calendar-source text cells. The contract now
  asserts those new sources and preserves original hashes for every other byte;
  all 20 tests in that file pass. Selected-all rerun: **2,466 passed**, 229.844s,
  `cache/refactor_checks/all_swbjv6ii`. After preserving non-equity caller boundaries,
  final selected-report gate: **208 passed**, 47.276s,
  `cache/refactor_checks/report_9lrrgl58`; final saved JSON remains exactly equal.
  Deployment/owner reboot verification is pending below.
- Mixed futures/FX/macro daily and observation windows retain the old filters and
  existing macro expected-date guard. They are not certified by the equity calendar.
- Decision functions, partial-bar scoring policy, thresholds and decision labels
  are untouched. Source-calendar metadata changes are intentional.

Previous [partial-bar audit](docs/maintenance/20261121_partial_daily_bar_audit.md)
explains the intentional decision/observation differences and preserved input IDs.
Private artifacts stay under ignored `cache/operating_20261121/`; do not add to Git.

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

**Clarify the displayed daily-return basis without changing the decision result.**

Use the saved GOOGL intraday and 379810 completed-session inputs from the prior
consumer audit. Inspect how precision/Today/report show the source trading date,
comparison close date and provisional/completed status next to the return. Saved
`전일등락` wording is ambiguous for an active-day bar. Preserve the numeric policy,
existing score/decision wording and return values; add or reuse separate evidence
labels only where the actual input certifies them. Missing timestamps stay unknown.
Do not change quote providers, TTLs, scoring, or globally exclude partial bars.
Prove fixed-input parity, then verify the relevant operating display as available.

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
