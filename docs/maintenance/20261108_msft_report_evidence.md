# MSFT business evidence in automatic market reports

Base: `5bdc22de`, clean main/origin at start. User authorized report integration,
score preservation, Cloud verification and commit/push. No user edits discarded.

## Change

- Report context collects the existing bounded official MSFT IR packet once, outside
  rendering. Successful public packets are reused for six hours; failures/partial
  packets are not stored as successful cache entries. No account data in this cache.
- New visible section after core market interpretation: demand evidence, cash
  investment burden, management outlook, conditional holding links and next checks.
- Explicit publication age (KST date), fiscal period, actual/company forecast and
  missing consensus. Old earnings are background, not today's price catalyst.
- Renderer rejects future/stale retrievals, mismatched periods/sources/units/scopes,
  duplicate metrics and nonfinite values. Expired forecast periods are withheld.
- Reuses existing holding/topic mapping; no new scoring, investment thresholds,
  decision text, automatic trading, LLM or valuation model. No new issuer adapter.
- New report and MSFT source modules registered for loaded/disk build checks.

## Verification

- Targeted report/MSFT/editorial tests: **75 passed**, 6.37s. Includes complete report
  rendering, immutable decision inputs, collection/cache counts, invalid/partial
  evidence and expired forecast cases. No regenerated golden files.
- Decision gate: **1334 passed**, 117.415s, no errors/skips/source changes during run.
  `cache/refactor_checks/decision_893wu6cg`. Subsequent changes only added report
  forecast expiry/KST-age presentation guards and tests, not any decision source.
- Report gate: before **207 pass/1 fail**,41.842s; after **207 pass/1 fail**,46.480s.
  Same pre-existing `test_theme_selection.py:47` whole-app function-set assertion.
  Historical section hashes unchanged; not a clean full-suite claim.
- Actual official-page collection:13 metrics, first5.694s, cached<0.001s, monitored
  stale modules empty. These are issuer-query times, not Today/report elapsed time.
  Tests verify three first-request pages and zero further requests across repeat
  collection and rendering. No failed-value or stale-success substitution.
- Private packet/preview/Cloud ZIP remain ignored under `cache/report_msft_*`.

## Deployment

Application commit `1259b5f7` pushed and accepted in authenticated Cloud. Fresh
automatic report downloaded at2026-11-08 03:31 KST, generationID `9fbf13d5812c`,
matching commit, loaded fingerprint `103ac1d93784f29c`, no stale-code footer warning.
No reboot needed. Actual UI and downloaded Markdown contain exactly one MSFT block
after core interpretation and before holdings, actual/guidance periods, dated
official links,13-source-metric packet-derived values and the three-row next-check
table. Publication age11 days, FY2027Q1 ended2026-09-30, FY2027Q2 outlook explicitly
future/management-only. Holding links use existing exposure mapping.

Preserved pre-deployment and post-generation Today ZIPs: same95 tickers, all14 core
score/grade/verdict/gate fields identical (1,330 comparisons). No full-file identity
claim:12 rows change auxiliary money-flow candidate scope from stock-history to
ETF/sector radar when report generation populates the existing shared flow snapshot.
Their timing labels stay unchanged; radar verdicts differ by scope. Flow numerical
scores differ only by serialization rounding(max4.76e-11). The money-flow/scoring
source is untouched. Saved/fresh input contexts must not be represented as identical.
This is the already documented scope distinction, not evidence of MSFT changing
investment decisions. Other auxiliary fields are not claimed byte-identical.

Screenshot inspected for visible explanation, official links and readable next-check
table. `cache/report_msft_cloud.png`, Markdown, comparison JSON and ZIPs are ignored.
No full Today recalculation or production performance benchmark in this task; do not
reuse issuer-only timing as whole-report elapsed time. Existing report source gaps
outside MSFT remain outside this acceptance. Independent review flagged expired
guidance; fixed and covered before publication.

## Scope limits

One company and one latest quarterly packet. This explains demand/cash investment
and prospective equipment demand; it does not establish today's causality, pure-AI
revenue, realized supplier orders, consensus surprise, cash-exhaustion date or DCF.
Next-quarter official date is not guessed. Next checks are questions, not thresholds.
