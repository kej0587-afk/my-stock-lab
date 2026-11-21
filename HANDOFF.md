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

In progress after `bf7b385b`: [cross-view price/mode audit](docs/maintenance/20261121_cross_view_price_mode.md).
Six representative US closes/afterhours observations and one KR ETF checked against
actual providers; pre-change production Today 95 rows completed in 98.2s.
Mode evidence and portfolio comparison table implemented; 98 focused tests and
final selected decision 1,638 tests pass (`decision_iksxjci1`). Prices unchanged,
646 price tests pass. Push/owner reboot and production comparison remain before
closing this task. Preserve snapshots and finish that verification first.

### Previous completed task

Current bounded work: [cross-view evidence and SOXL close repair](docs/maintenance/20261121_cross_view_soxl_close.md).
Started clean at `c895a19b`. The user reported SOXL 42.34 versus regular close 30.88
during the cross-view audit; the explicit price bug took priority over the former
no-provider-change restriction. Implementation/tests and production verification complete.

- `1a9989fb` passes existing calculated weights into precision's shared evidence.
  Three fixed cases preserve every existing workflow field and portfolio readiness;
  only two display fields are added. Original captures are not identical full inputs.
- Yahoo's Nov20 SOXL daily row has OHL/volume but null Close, while same-symbol
  regularMarketPrice=30.88 at 16:00:04 ET. Existing cleanup dropped the row; old
  regular-close fallback selected Nov19 45.30. The 42.34 quote had no provider/time
  evidence, so its actual supplier cannot be determined from the old ZIP.
- Repair only an existing missing US tail Close with matching symbol/calendar/date,
  close-time and OHL validation. Keep Adj Close unknown. Shared scalar/batch path;
  complete frames make no extra request. Prefer chart over untimed day fallback
  outside extended sessions. No TTL/score/formula/threshold/decision-label changes.
- Corrected data can change calculated results; this is an explicit input bug fix,
  not a claim that old wrong prices must yield identical output.
- Final selected prices: **646 passed / 60.359s**, `prices_eeb6nivt`.
  Final selected decision: **1,638 passed / 153.218s**, `decision_bqkmn9n1`.
  New/focused contracts: **75 passed / 26.26s**, including NaT/duplicate-column
  guards found in focused review. No golden regeneration.
- Local and production restore Nov20 Close30.88; separate post-session quote33.3694
  carries actual supplier timestamp/session. `49ab429d` pushed, owner reboot done,
  completed SOXL ZIP confirms loaded modules match disk and account weight fields connect.

### Previous completed display task

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

[SOXL close repair](docs/maintenance/20261121_cross_view_soxl_close.md): code
**`49ab429d`**, direct owner Reboot completed, SOXL result at 2026-11-21 10:49 KST.

- base_commit matches, restart_required=false, stale_modules=[]; `prices` and
  `yahoo_daily_close` loaded/disk hashes match. Authenticated session recovered.
- Source CSV now includes Nov20 Close **30.88** (OHL 42.40/42.57/29.82 and volume
  533,762,471). Regular return -31.83% correctly compares Nov19→Nov20.
- Separate selected quote **33.3694**, Yahoo chart Nov21 **09:59:59 KST**, post.
  Screen and ZIP distinguish this observation from regular close; no claim of
  current active session or certified final afterhours close.
- Scenario/underlying axis displays $30.88. Shared workflow contains both existing
  calculated weight fields. Full Today/report was not rerun; no speedup claim.
- Prices changed, so grade changed with corrected input. Existing decision formula,
  thresholds and labels remain unchanged; fixed-input regression evidence above.
- ZIP attrs allowlist excludes daily_close_repair; proof uses actual source CSV,
  matching loaded modules and separate public raw probe, not invented export metadata.
- Private evidence: Downloads `precision_review_SOXL.zip` and `(1).zip`;
  ignored `cache/operating_20261121/soxl_close_operating.json` (7 checks passed),
  `soxl_missing_close_probe.json`, `soxl_close_operating.jpg`.

### Previous display verification

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

**Record and replay free-entry versus held-selection account limits.**

For one fixed held KR ETF, capture selection mode (`is_free`) plus matching price,
market and account inputs in Today/precision evidence. The old 379810 captures have
the same price ID but different decision codes; their missing mode/context prevents
a causal conclusion. Reproduce both modes with fixed inputs, distinguish legitimate
account-limit differences from a display/connection error, and fix only a proven
defect. Preserve existing scores, thresholds, labels, TTLs and user-owned inputs.
Do not start another broad refactor. Finish one record and exactly one next task.

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
