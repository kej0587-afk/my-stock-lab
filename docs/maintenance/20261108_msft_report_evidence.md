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

Implementation ready; authenticated production validation pending publication.
Existing operating Today export preserved before deployment. No production timing
or complete output acceptance is claimed until a new report is downloaded.

## Scope limits

One company and one latest quarterly packet. This explains demand/cash investment
and prospective equipment demand; it does not establish today's causality, pure-AI
revenue, realized supplier orders, consensus surprise, cash-exhaustion date or DCF.
Next-quarter official date is not guessed. Next checks are questions, not thresholds.
