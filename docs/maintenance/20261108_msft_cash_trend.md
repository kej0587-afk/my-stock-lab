# MSFT eight-quarter cash burden in automatic reports

Base `cab147bf`; clean main/origin verified with fetch. User requested same-basis
eight-quarter interpretation, score preservation, Cloud verification and publication.

## Implemented

- Reuse the existing SEC quarter parser and identity-checked loader. One MSFT
  query during explicit report collection, before rendering. Public successful
  packet reused for6 hours; no failure-cache/old-success substitution or account writes.
  Existing score/provider TTLs and financial/decision calculations are untouched.
- Compare cash PP&E / positive operating cash flow, with OCF-minus-PP&E as a
  separately labelled simple residual (not cash balance/company adjusted FCF).
- Require USD, exact MSFT quarters, verified field provenance, arithmetic matching
  source facts and matching filings. Year-on-year pairs must share one filing's
  comparative statements. Noncash leases/commitments/acquisitions excluded.
- Show all eight observed quarters; missing/revised/cross-filing quarters held,
  never zero-filled. No TTM sum, interpolated trend, DCF, scoring or trade signal.
- New visible report section explains latest burden, rate of cash investment vs
  cash generation, valid comparison coverage, dates/filing links and next checks.
- Independent review found briefing captured `now` before source collection;
  reordered it after collection. A replay test verifies fresh evidence remains visible.
- Added loaded/disk registrations for SEC parser/review and new report modules.

## Verification

- Targeted cash/MSFT/SEC/source-flow tests:204 passed in22.46s.
- Decision gate final:1334 passed,101.937s, no errors/skips/source edits during run;
  `cache/refactor_checks/decision_ae08z2lt`.
- Initial decision gate correctly caught intentional changes in report collection/
  clock ordering against the historical whole-app AST contract. A narrow shared
  adapter normalizes only those approved statements; every other app statement
  remains compared to original Git baselines. No golden files regenerated.
- Report gate before207 pass/1 fail(42.888s), after207 pass/1 fail(44.974s). Same
  pre-existing `test_theme_selection.py:47` function-set assertion. No new failure.
- Live SEC ticker identity and companyfacts both HTTP200:2 requests,4.560s total;
  repeat cache0.000626s with no additional requests. These are issuer-only timings.
- Actual latest period2026-09-30 vs2025-09-30: cash investment/OCF43.0433% ->67.8741%
  (+24.8309pp); cash investment+102.9855%,OCF+28.7258%,simple residual change-7.030bn USD.
  Three valid YoY pairs all have higher burden. Two Q4 observations remain held due
  to cross-filing cumulative differences; no assumption that their amounts are wrong.
- New local build monitor stale list empty. Private packet, sample, measurement
  and baseline ZIP ignored under `cache/msft_cash_*`; no secrets/account data in Git.

## Deployment / limits

Application commit `21758193` pushed and accepted in authenticated Cloud.
Fresh report generated2026-11-08 05:56KST, generationID `e83457ce3b52`, loaded
fingerprint `8192e9e8ad135e9d`, matching application commit and no stale-code warning.
No reboot required. Downloaded Markdown contains exactly one cash-burden section;
its entire text/table/filing links match local calculation from live SEC evidence
exactly. Latest43.0% ->67.9%(+24.8pp),3 valid YoY pairs,2 held quarters all verified.
Report download and pre/post Today ZIP downloads succeeded. Same95 tickers; all14
core financial/candidate score, grade, verdict and execution-gate fields match
(1,330 comparisons). No whole-ZIP/auxiliary flow-scope identity claim.
Actual UI explanation and8-quarter table inspected; private screenshot, Markdown,
live packet, source-only timing and acceptance JSON are ignored under cache/msft_cash_*.
The separate briefing clock route is covered by a replay test, not a second live
report generation. Report/decision/provider logic outside this bounded task unchanged.

Do not describe issuer query time as Today/report speedup. No full Today benchmark.
Comparative company cash flows do not isolate AI, verify business-scope stability,
prove today's price cause or establish cash-exhaustion timing. Two held Q4 quarters
need official same-basis source review before restoring comparisons.
