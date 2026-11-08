# Selected-company prior-year cash comparison

2026-11-08 KST; base08b2ac4e. Review-only, no score/verdict/threshold/TTL,
database, raw8-quarter packet or app.py changes.

## What belongs in market commentary

Cash burden is one sustainability check, not the main ranking rule for every
sector. Market commentary should explain the changing market environment, sector
leadership, earnings/outlook evidence, portfolio implications and next observable
checks. Precision review keeps company financial quality assessment. Quarterly
cash-flow changes support a hypothesis; they do not prove today's price cause,
excess investment, cash exhaustion or the next leading sector.

References checked: [Fidelity sector rotation](https://www.fidelity.com/learning-center/trading-investing/markets-sectors/intro-sector-rotation-strats)
(macro conditions/rates/input prices), [SEC financial statements guide](https://www.sec.gov/investor/pubs/begfinstmtguide.htm)
(separate income, balance sheet and operating/investing/financing cash flows).
These are framework references, not present-day market forecasts. Cloud buyers,
equipment suppliers and software firms should not all be described as lacking cash.

## Bounded implementation

- Shared fiscal-quarter selector allows52/53-week year shifts, requires one prior
  match and comparable quarter length. It never substitutes a different quarter.
- Existing explicit SEC query parses prior-year columns from the SAME downloaded
  earnings exhibit. Still one submissions JSON + two HTML requests; no extra HTTP.
  Both prior quarter/YTD must match validated raw operands. Latest recovery remains
  available if prior evidence fails. Original raw fields/statuses remain unchanged.
- Pure `company_cash_comparison` verifies both cash flows, matched scope/tags and
  same primary10-Q/10-K filing for current/prior. Recovered pairs also require the
  same8-K document/hash. Missing/ambiguous/revised/incompatible operands stay held.
- UI shows exact periods, amounts, absolute/percentage changes, investment/OCF
  ratios and simple residual. Nonpositive bases do not get growth or burden ratios.
  Both-period software costs/company FCF are separate when reconciled. No assumed
  zero for missing development costs, no inference that PPE is all AI investment.
- Existing Alphabet/Amazon validated reviews already compare cash periods and are
  not duplicated. Download adds `cash_comparison`; default collection unchanged.
  Intro distinguishes market leadership, financial quality and cash sustainability.

## Official sample verification

[DDOG8-K99.1](https://www.sec.gov/Archives/edgar/data/1561550/000162828026069792/ex-991x20260930x8k.htm),
2025Q3 vs2026Q3, million USD:

| Metric | Prior | Current |
| --- | ---: | ---: |
| Operating cash | 251.470 | 289.951 |
| PPE cash investment | 16.786 | 10.872 |
| Separate software development | 20.732 | 28.445 |
| Company FCF (both costs deducted) | 213.952 | 250.634 |

PPE/OCF6.68%→3.75%; including separate development14.92%→13.56%.
Cash generation and company FCF increased while development spending increased.
This is NOT evidence that all technology companies have reduced investment.

[NVDA8-K99.1](https://www.sec.gov/Archives/edgar/data/1045810/000104581026000073/q2fy27pr.htm):
prior quarter productive-asset purchases are1,894m, versus1,895m calculated from
the raw10-Q YTD operands3,122m−1,227m. Prior OCF15,365m matches. The1m difference
is not silently tolerated or called rounding without reconciliation. Prior-year
comparison stays held; latest verified OCF24,077m / investment2,677m remains.
No issuer/date-specific exception or source-value overwrite.

## Verification / deployment

Baseline decision1367pass134.934s (`decision_sw762u8u`). Focused234pass15.83s.
Independent bounded review found no actionable issue; confirmed1m mismatch hold,
calendar/source guards, no additional requests and raw preservation. A new UI test
initially leaked its fake loader into later tests; isolated/restored the fixture,
then reran the full focused scope successfully. No production fix for that fixture.
Offline replay of real SEC documents: DDOG verified comparison, NVDA held, unchanged
latest recovered values and exactly3request callback invocations per company.

Final decision1367pass137.468s (`decision_vo13ocia`), stable source hashes.
Commit and authenticated Cloud verification pending at this checkpoint.
Private evidence in cache/cash_yoy_* only; never commit account exports/screenshots.

## Next task

Refine `report_leadership.leadership_lines` market-wide storyline using existing
dated sector relative/absolute strength, macro and earnings/news evidence: explain
which leadership is weakening, which alternatives are improving and what would
confirm the shift. Keep missing evidence explicit and scores/gates unchanged.
No new broad data-collection pipeline or further issuer cash exception in that task.
