# Report reading quality and holiday status — 2026-11-08 KST

Base ce13c311, clean and synchronized with origin. The user redirected the next
task to the supplied 00:48 report and two timing exports. No scoring, trading
thresholds, account records, provider TTLs or authentication were changed.

## Findings and bounded changes

- The report contains about83k characters/789 lines. Existing market synthesis
  appeared after large evidence blocks. There is no live LLM writer: the current
  hook returns its prompt, so article reading and interpretation are bounded rules.
- The US was on a weekend in exchange-local time. current_state_lines excluded
  US_CLOSE observations, then described the empty live list as disconnected.
  Weekend/no-extended-window now displays validated S&P500/Nasdaq/SOX closing
  observations and their dates. Missing/stale/wrong-date closes still stay missing;
  normal daymarket/pre/postmarket and active regular sessions retain their rules.
  No cached futures are advertised as current weekend prices.
- Two sponsored volleyball-team stories were included as finance news. The finance
  matcher now rejects sports-only coverage but retains financial results/regulation.
  Review caught an overbroad coach keyword matching the financial regulator; removed
  it and added regulator regressions before publication.
- New report-only editorial layer uses existing session-qualified market synthesis,
  at most3 verified article-body topics, existing holding exposure mapping, and
  explicit next-observation questions. Opposite KR/US directions are distinguished
  without projecting one market's explanation onto the other. Reverse directions
  and missing live data are tested. It makes no new network requests or model calls.
- Reading order places current status, interpretation, holdings and upcoming checks
  ahead of numerical audit tables. Full evidence remains in exported Markdown;
  several audit sections collapse in the UI. The new module participates in loaded
  source checking. Historical output digests are not regenerated.

This does not deliver a discretionary analyst's multi-year valuation or cash-runway
model. Such a model requires dated financial statements, reconciled periods, explicit
CAPEX/FCF assumptions, consensus and sensitivity analysis. A premise from a user
reference image is not independently verified fact. Official earnings in the app
still have missing fields and differing TTM/quarter scopes. Do not invent numbers.

External checks: [NYSE sessions](https://www.nyse.com/markets/hours-calendars),
[Amazon official Q3 release](https://ir.aboutamazon.com/news-release/news-release-details/2026/Amazon-com-Announces-Third-Quarter-Results/default.aspx),
[KR close report](https://www.yna.co.kr/view/AKR20261106130151008).
The KR article's investor amounts differ from the app's provisional source; they
are different observations and were not overwritten/mixed to make them agree.

## Uploaded timing audit (not before/after improvement)

| Measurement | Status | Today wall | Script incl. initialization |
|---|---|---:|---:|
| ef9a145f... | complete95 instruments |87.220s|94.800s|
| f974e9fb... / last_attempt7 | report render, RerunException |71.960s|80.296s|

Complete run category active-wall unions: prices43.258s, external29.773s,
indicators18.353s, decision9.496s. These overlap and cannot be added. Summary
wall46.436s includes stock_signals21.177s. Self-work335.634s includes waits and
unmeasured callees; measured wall union65.743s, concurrent overlap269.891s.
KR history calls431 = cache292 + HTTP139. Function counts are not HTTP counts.

Report render71.960s contains briefing60.085s and report_context34.772s (nested),
including news4.525s and report prices1.588s. Briefing self24.236s is unclassified;
no LLM timer exists. RerunException matches the existing save-then-rerun flow, not
proof of a failed calculation. No same-input/cache before-after comparison or
speedup claim is justified. Next performance candidate is narrowing that full
rerun; actual savings require measurement and are not part of this patch.

## Verification and deployment boundary

- Final targeted190 tests passed in10.40s: holiday/source dates, source attribution,
  reverse directions, finance classification, input immutability, integration,
  layout and historical section contracts.
- Report gate before change:207 passed/1 failed,43.642s
  (`cache/refactor_checks/report_iu_ep7jr`). Failure is the pre-existing whole-app
  AST function-set assertion in test_theme_selection.py:47.
- After intentional editorial changes,12 historical digest cases initially failed.
  The contract now disables only the new editorial/order hooks and restores the
  fixture's old weekend sentence; unchanged baseline hashes still prove parity of
  all other sections. Independent tests exercise actual new integration/output.
  Gate after adapter:207 passed/same1 failed,43.183s
  (`cache/refactor_checks/report_oyls_dss`). No all-green/full-suite claim. Final
  neutral-direction/filter refinements are covered by the190-test run.
- The user report's price/macro subset and one attributed article summary were
  reconstructed through the new helpers for a local preview. Remaining detailed
  sections are the supplied original, not regenerated live/account calculations.
  Private sample/screenshot live under ignored cache/market_report_editorial_preview_20261108.md
  and cache/report_editorial_preview_20261108.png. UI inspected at127.0.0.1:8534.
- Production generated-report acceptance remains pending after publication. No
  reboot is requested without observed stale-runtime evidence. Missing consensus,
  limited article-body coverage and the source of account coverage87.8% are not
  repaired by this presentation patch.
