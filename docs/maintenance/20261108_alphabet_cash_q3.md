# Alphabet Q3 cash-flow reconciliation

Base:4f9dc9ab. Reviewed2026-11-08KST. Scope: recover the withheld2025/2026Q3
cash comparison in Big Tech analysis only; preserve original packets, general
SEC parsing, scores, gates and account data.

## Cause and original evidence

Companyfacts supplies nine-month cash observations from the2026Q3 10-Q and
six-month observations from the2026Q2 10-Q. The general parser correctly flags
their difference as cross_filing_difference_review. Missing data is not the cause.
Both years' direct quarters are independently printed in the2026Q3 8-K earnings
exhibit. Those direct values reconcile to the cumulative statements and the2025
original earnings exhibit agrees with the prior-year values.

All amounts below are USD millions, consolidated/unaudited. PP&E is a cash
outflow displayed as a positive investment amount, not all investing cash flow.

| Period | Item | Nine months | Six months | Difference | Direct quarter |
| --- | --- | ---: | ---: | ---: | ---: |
| 2025-07-01~09-30 | OCF | 112,311 | 63,897 | 48,414 | 48,414 |
| 2025-07-01~09-30 | Cash PP&E | 63,596 | 39,643 | 23,953 | 23,953 |
| 2026-07-01~09-30 | OCF | 127,149 | 84,859 | 42,290 | 42,290 |
| 2026-07-01~09-30 | Cash PP&E | 131,953 | 80,598 | 51,355 | 51,355 |

- [2026 direct quarter/comparative exhibit](https://www.sec.gov/Archives/edgar/data/1652044/000165204426000080/googexhibit991q32026.htm):
  accession0001652044-26-000080,filed2026-10-28,8-K; cash statement also shows
  the9month comparatives. Original-body SHA256 prefix58eccefcb075e8fd.
- [2026Q3 10-Q](https://www.sec.gov/Archives/edgar/data/1652044/000165204426000084/goog-20260930.htm):
  accession0001652044-26-000084,filed2026-10-29,2025/2026nine months.
  Original-body SHA256 prefixf08f6344b47ff7b7.
- [2026Q2 10-Q](https://www.sec.gov/Archives/edgar/data/1652044/000165204426000071/goog-20260630.htm):
  accession0001652044-26-000071,filed2026-07-23,2025/2026six months.
  Original-body SHA256 prefixcccaa5397187cfaa.
- [2025 original exhibit](https://www.sec.gov/Archives/edgar/data/1652044/000165204425000087/googexhibit991q32025.htm):
  accession0001652044-25-000087,filed2025-10-29,8-K.
  Original-body SHA256 prefixf3fd7a8992c6e61e.

Original HTML fetched with the configured SEC contact; all eight key rows checked
against numeric expectations. Release filing dates also verified via SEC
submissions. No credentials or private account records included in this document.

## Implementation and limits

- Small report-only alphabet_cash_q3 validator, following the existing narrowly
  audited MSFT recovery pattern. Requires GOOG/GOOGL CIK/source identity, USD,
  review-only/non-scoring packet, consistent collection/as-of dates, review date,
  exact Q3 dates, fiscal-year origin, cash-PP&E scope, expected status/method and
  every original operand's value/tag/form/accession/filed date. Any mismatch holds.
- No generic cross-filing permission. Other periods/issuers/revised operands stay
  withheld; no historical lookahead before2026-11-08. Existing6h UI freshness stays.
- Both recovered quarters cite the same2026 direct comparative exhibit, so YoY
  uses one comparative statement. Current OCF-PP&E=-9,065; investment/OCF121.4%,
  up72.0pp from49.5%; OCF YoY-12.6%,PP&E+114.4%. Cash burden is not insolvency,
  AI-only spending, supplier orders or a causal explanation of today's price.
- UI labels recovery/unaudited status, actual restored periods, source links and
  review date. JSON recoveries retains direct values and reconciliation; original
  packets and the expandable generic extraction table retain their original hold.
  Individual-company generic reading is unchanged; this task covers Big Tech mode.
- No new network requests, implicit market-report fetching, TTL, DB or score edits.

## Verification / deployment

- Decision before1334pass102.038s(decision_mooqv_zg); final1334pass104.438s
  (decision_cwk2u3o4),stable sources. Focused145pass7.96s covering source mutations,
  alias/identity, missing fields, other statuses, one-sided recovery, date/definition
  and actual UI labels/source links. Reviewer found no concrete scoped issues.
- Report207pass/one pre-existing historical whole-app function-set assertion
  (test_theme_selection:47),44.848s(report_dtifh14k). No golden rewrites.
- Fresh local live SEC8quarter packets produce exactly two recoveries and the
  amounts above. Public original evidence under ignored cache/alphabet_*.
- Cloud before ZIP preserved(cache/alphabet_before.zip,10:34KST). Application
  deployment and authenticated fresh-query/score parity acceptance pending commit.

## Next bounded task

Connect this verified Alphabet recovery and its source-backed cash-flow explanation
to the selected individual-company deep dive, keeping generic source packets and
scores intact. Distinguish operating/working-capital/one-off effects from AI demand;
do not infer current price causes or add implicit default-report requests.
