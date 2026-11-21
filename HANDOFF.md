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

[2026-11-21 daily-return display basis](docs/maintenance/20261121_daily_return_basis.md),
based on `c759c585`. This is display evidence only, not a new return calculation.

- Source return now carries the actual previous/current row dates. No assumed
  previous trading day replaces a missing source row.
- Calendar/calculation time separates active partial bars from elapsed closes;
  elapsed close time still does not certify supplier finalization.
- Latest-price comparison identifies the actual last source Close. Supplier time
  and session remain unknown when the selected price carries no observation.
- Same evidence appears in precision input table, tactical/narrative displays and
  Today/dashboard detail columns. Existing return numbers, day_ret_label, scores,
  decision reasons, execution gates, price identity and cache TTLs remain unchanged.
- Report already separates completed/intraday values. Its computations/output were
  not rewritten or replaced with the decision engine's return.
- Two saved normal/intraday captures reproduce price, RSI, ATR, return, R/R and
  scenario date/price. Existing build_signal_basis fields are equal for the same
  frames/quote/clock; only three display fields are added.
- Baseline selected decision gate: **1,638 passed**, 153.437s,
  `cache/refactor_checks/decision_0r18f482`. Initial relevant tests: **140 passed**.
  New evidence tests: **19 passed**, 5.81s; final evidence/calendar/audit contracts
  **72 passed**, 11.82s. Final selected decision gate: **1,638 passed**, 151.881s,
  `cache/refactor_checks/decision_pmcv6zmr` (no failures/errors/skips/source drift).
  Code `35dd624d` pushed; owner reboot and precision operating verification completed.
- Ignored fixed-input record: `cache/operating_20261121/daily_return_basis_fixed.json`.
  No private ZIP/report goes into Git.

Previous [calendar fix](docs/maintenance/20261121_report_exchange_calendar.md)
aligned report equity sessions with exchange calendars while preserving separate
close buffers and legacy non-equity feed handling. It was deployed and verified
in `8c0caab5`; the record retains detailed tests and the operating report evidence.

The former 1,787-line handoff is preserved, unabridged, at
[HANDOFF_HISTORY_20261121.md](HANDOFF_HISTORY_20261121.md). It was copied before this
rewrite; its links retain their repository-root meaning. Read specific historical
records only as needed. Do not resume an older next task from that archive.

## Last Direct Production Verification

[Daily-return basis deployment](docs/maintenance/20261121_daily_return_basis.md):
code **`35dd624d`**, owner Cloud Reboot completed directly; authenticated session recovered.

- GOOGL completed capture at 2026-11-21 09:42 KST: base_commit matches,
  restart_required=false, stale_modules=[]. `signal_basis` loaded/disk hashes match.
- Precision table and expanded tactical panel display actual source Close
  Nov19 → Nov20, elapsed-close/supplier-finalization-unknown status, and separate
  selected quote timestamp Nov21 09:42:12 KST / afterhours session.
- Downloaded context and execution_workflow agree on all three new fields.
  Replaying the source dates and captured clock reproduces both date/status fields.
- Current quote/input ID differs from the pre-deploy capture. No like-for-like
  operating score equality is claimed. Numeric preservation uses the saved fixed
  inputs and selected regression gate above. The existing source-bar audit rejects
  this new quote-overlay capture by design; it was not weakened to force a pass.
- Today/dashboard detail columns are contract-checked; no new full Today run or
  report generation this turn. Cross-view evidence audit is the next task below.
- Private evidence: Downloads `precision_review_GOOGL (35).zip` before and `(36).zip`
  after; ignored `cache/operating_20261121/daily_return_basis_live.json` and
  `daily_return_basis_operating.jpg`. The captured tactical panel visibly confirms
  the tactical UI path, not merely a module fingerprint.

### Previous Report Verification

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

**Audit cross-view decisions using three representative fixed-input cases.**

Compare Today, precision and portfolio evidence for one ordinary US stock, one
KR-listed ETF and one leveraged product. Preserve snapshots/input IDs; compare the
same price/financial/market/account inputs wherever possible. Distinguish candidate
quality, technical timing and execution/account limits; legitimate role differences
are not duplicated votes. First identify whether divergent displays use different
inputs/times or truly disagree. Fix only a demonstrated connection/display defect,
with fixed-input parity. Do not change scores, thresholds, labels, quote providers,
TTLs or create another scoring engine. Record one bounded result and one next task.

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
