# DDOG / NVDA cash-flow source reconciliation

2026-11-08 KST; base `7dd38ffe`. Review evidence only; no score, verdict,
threshold, price cache TTL, raw financial packet or database changes.

## Cause and official evidence

The common extractor did not miss a same-filing quarterly operand. These 10-Q
cash statements contain YTD flows; quarter differences use different filings,
so `cross_filing_difference_review` correctly prevents unchecked interpretation.
The corresponding 8-K earnings exhibits independently state the exact current
quarter AND YTD. Both must match the held 10-Q arithmetic before recovery.

| Company / period | OCF quarter / YTD (USD) | Cash investment quarter / YTD (USD) | Scope |
| --- | --- | --- | --- |
| DDOG 2026-07-01–09-30 | 289,951,000 / 940,446,000 | 10,872,000 / 32,119,000 | Property/equipment |
| NVDA 2026-04-27–07-26 | 24,077,000,000 / 74,421,000,000 | 2,677,000,000 / 4,434,000,000 | Property/equipment, software/intangible assets |

DDOG previous YTD OCF650,495,000 / PPE21,247,000; NVDA50,344m /1,757m.
DDOG capitalized software development28,445,000 is a separate outflow:
OCF−PPE279,079,000 is NOT company FCF250,634,000. The additional development
cost reconciles the difference. NVDA simple difference21,400m is not unrestricted
cash or AI return. Periods/scope differ: do not compare as same-quarter AI spend.

Official documents inspected:

- [DDOG 10-Q](https://www.sec.gov/Archives/edgar/data/1561550/000162828026070292/ddog-20260930.htm)
- [DDOG 8-K99.1](https://www.sec.gov/Archives/edgar/data/1561550/000162828026069792/ex-991x20260930x8k.htm)
- [NVDA 10-Q](https://www.sec.gov/Archives/edgar/data/1045810/000104581026000075/nvda-20260726.htm)
- [NVDA 8-K99.1](https://www.sec.gov/Archives/edgar/data/1045810/000104581026000073/q2fy27pr.htm)

## Implementation and boundaries

`sec_cash_recovery` is shared, with no issuer/date exceptions. Explicit selected
company query only: one SEC submissions request, one uniquely selected8-K2.02
primary document, one99.1 exhibit (15s HTML request timeout each). No background
market/Today collection or query on selection/rerender. Existing contact setting
reused; URLs remain bound to CIK/accession and redirects rejected.

Exact quarter/YTD column dates, USD scale and consolidated actual cash-flow scope
are required. Each table must independently contain both flows and periods.
Complete heading blocks preserve projected/affiliate qualifiers. Accounting
punctuation and split currency cells preserve OCF signs. Conflicting tables,
wrong periods/units/operands, ambiguous filings/exhibits and source failure remain
held. Unsupported layouts remain held, not estimated or replaced by older data.

Export adds separate `cash_recovery` with source/hash and exact bound operands.
Raw8-quarter packet/status stays unchanged. Selected-company explanation replaces
only the verified cash axis; coverage explicitly distinguishes original extraction
from separately recovered evidence. Raw table moves into a labeled expander.
This does not recover historical eight-quarter trends or provide forecasts/DCF.

## Verification and deployment

- Baseline decision gate1367passed133.454s (`decision_3b82rzyf`).
- Final focused208passed14.11s, including malformed dates/scope/sign/exhibit,
  packet immutability, offline UI trigger and whole-app AST boundary checks.
- Local live dynamic discovery + original HTML reconciliation succeeded for both
  companies; quarter/YTD/source identity checked. Private evidence `cache/cash_*`.
- Independent review found sign/scope/exhibit parsing weaknesses; corrected with
  counterexamples. Independent reviewer confirmed closure;47focused tests passed.
  Final decision1367passed132.291s (`decision_1bdyko67`), stable source hashes.
- Application not yet pushed/Cloud verified at this checkpoint. Update this section
  after real selected-company queries, downloads, module hashes and score comparison.

## Next bounded task

Make same-period prior-year cash-burden comparison generic for the selected company,
using only validated same-scope operands; hold incompatible/missing periods. Preserve
scores and explicit collection. This is separate from recovering this latest quarter.
