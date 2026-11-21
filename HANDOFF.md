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
  Code `8c0caab5` pushed; owner reboot and new operating report verified below.
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

[Report calendar deployment](docs/maintenance/20261121_report_exchange_calendar.md):
code **`8c0caab5`**, owner Reboot completed after one Cloud internal-error retry.

- Auto report generated at 2026-11-21 09:08 KST: **55.337s**, completed/normal,
  measurement `38e7cbbeb5fb4abfa8a4a20bcf00b274`, no degraded reasons.
- Diagnostic base commit matches; restart_required=false, stale_modules=[].
  New clock, session, report evidence and market board loaded/disk hashes match.
- Downloaded Markdown SHA256 matches the diagnostic output SHA256.
- KR holiday, last confirmed close Nov20; US regular closed/afterhours, last
  confirmed close Nov20. Both calendar sources displayed (XKRX/XNYS).
- Full Today calculation was not rerun after reboot; this report explicitly states
  account/decision inputs are absent. No claim of a new account/grade comparison.
- Special/short-session boundaries are fixed-clock tests, not live time simulation.
  Caches were not cleared; 55.337s is an observation, not a speedup claim.

Ignored evidence: `cache/operating_20261121/stock_lab_market_report (41).md`,
`auto_report_38e7cbbeb5fb4abfa8a4a20bcf00b274.json`, `calendar_report_operating.jpg`,
`partial_bar_calendar_final.json`. Downloads originals remain intact.

Previous live full Today: 95 rows/106.065s, source `eb0af4a2`, measurement
`c4cd1b65cb224e08ae4aefaee052ed76`; see the Naver observation record, not this report run.
Fixed replay sources: Downloads `precision_review_379810.KS (4).zip` and
`precision_review_GOOGL (34).zip`. Their price input IDs and limits are in the
partial-bar audit. Keep these private files out of Git.

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
