# Same-period Big Tech cash comparison

Base:8736d90e. User requested cash generation versus investment with a readable
semiconductor/data-center implication; preserve all scores and decisions.

## Implementation

- Company view adds a separate explicit comparison mode for current held/watch
  MSFT/AMZN/Alphabet/META. ETFs excluded; Alphabet share classes deduplicated.
  At least2/at most4, no implicit default-report requests or DB writes.
- Existing SEC8-quarter identity-checked loader and field-provenance validator.
  Exact calendar start/end, single-quarter USD only; latest common period with
  latest individual coverage visible. Never select older complete figures merely
  because latest common metrics are withheld. Failed selected company blocks the
  comparison rather than silently disappearing from the sample.
- Ratios/differences need internally matching period/filing; YoY additionally
  requires exact prior-year dates, identical investment definitions and a common
  comparative filing. Missing/cross-filing/future/duplicate periods held.
- Cash PP&E and broader productive-asset purchases remain separately labeled;
  no cross-definition aggregate or ranking. Noncash leases/commitments/acquisitions
  excluded; simple OCF less cash investment is not company-adjusted FCF.
- Two compact tables and issuer-specific fact/interpretation/next-check prose.
  OCF<=0 gets no burden ratio. Declining cash can raise burden even when investment
  declines; wording distinguishes this. No AI-specific spending/order/price claims.
- Owner/selection-isolated session, explicit refresh clears failures,6h display
  expiry; no TTL/provider/scoring changes. JSON retains packets/provenance.

## Verification

- Decision baseline1334pass100.924s(decision_04fgbcch), final1334pass106.109s
  (decision_lusgjyqf), stable source. Not a performance measurement.
- Focused comparison/UI/company/SEC90pass7.03s. Covers owner/selection/rerender,
  failed refresh, expiry, mismatched scope/currency/period/provenance, zero/negative
  OCF, mutated derived data, latest-common/withheld cases and fiscal label mismatch.
- Bounded reviewer found YoY cross-filing and ratio-rise wording risks; fixed and
  regression-tested both. Final report207pass/one existing historical whole-app
  function-set assertion(test_theme_selection:47),45.423s(report_z_n6lvxe).
  No golden rewrites or full-suite-clean claim.
- Live SEC local8quarter queries MSFT/AMZN/GOOGL succeeded on2026-11-08.
  Common2026-07-01~09-30, previous2025-07-01~09-30. MSFT OCF58000/cashPP&E39367
  millionUSD; AMZN OCF42422/productiveassets77259 millionUSD. Ratios67.9/182.1%;
  YoY ratio change+24.8/+83.3pp. Both prior-year comparatives in the same current
  filing. Alphabet cash rows still withheld as cross-filing cumulative differences.
- Original basis references: [MSFT FY27Q1 release](https://www.microsoft.com/en-us/investor/earnings/fy-2027-q1/press-release-webcast),
  [MSFT call](https://www.microsoft.com/en-us/investor/events/fy-2027/earnings-fy-2027-q1),
  [Amazon Q3 filing](https://www.sec.gov/Archives/edgar/data/1018724/000101872426000040/amzn-20260930.htm).
  IR headline capex/lease or net-of-incentive figures must not replace the generic
  cash-statement tag values; different definitions are intentionally explicit.
- Cloud before ZIP preserved privately as cache/bigtech_before.zip. Deployment
  and authenticated Cloud actual query/download verification pending this commit.

## Next bounded task

Reconcile Alphabet's withheld latest/prior-year Q3 cash rows against original
filings. Add report-only recovery only if original comparative statements prove
the period and definition; otherwise keep withheld. No generic parser/score edits.
