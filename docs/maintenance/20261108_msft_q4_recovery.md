# MSFT two-quarter cash-flow recovery

Base `64383d2b`; clean main/origin verified. Bounded user request: compare the
two held quarters to original filings, restore only if proven, preserve scores,
verify Cloud, publish and update handoff.

## Finding and source reconciliation

The original hold was conservative provenance handling, not an arithmetic error.
Companyfacts provides annual and nine-month cash flows in different filings.
However, the FY2026 earnings exhibit **directly reports both Q4 quarters** in
one comparative cash-flow statement. It independently corroborates the subtraction.

USD millions; fiscal Q4 is April 1–June 30 (not calendar Q4):

| Quarter end | OCF annual | OCF 9M | Direct Q4 OCF | PP&E annual | PP&E 9M | Direct Q4 PP&E | OCF−PP&E | PP&E/OCF |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2025-06-30 | 136162 | 93515 | 42647 | 64551 | 47472 | 17079 | 25568 | 40.0% |
| 2026-06-30 | 182935 | 127494 | 55441 | 115948 | 80146 | 35802 | 19639 | 64.6% |

Original sources downloaded HTTP200 and checked on 2026-11-08:

- [2026 8-K exhibit99.1](https://www.sec.gov/Archives/edgar/data/789019/000119312526323632/msft-ex99_1.htm): cash statements, four columns = Q42026/Q42025/FY2026/FY2025. Direct quarter figures are unaudited; the report labels this.
- [2026 10-K](https://www.sec.gov/Archives/edgar/data/789019/000119312526323660/msft-20260630.htm): annual2026 and comparative2025 amounts match the exhibit.
- [2026 Q3 10-Q](https://www.sec.gov/Archives/edgar/data/789019/000119312526191507/msft-20260331.htm): nine-month2026 and comparative2025 amounts match each annual-minus-direct-quarter difference.
- [2025 original 8-K exhibit99.1](https://www.sec.gov/Archives/edgar/data/789019/000095017025100226/msft-ex99_1.htm) and [2025 10-K](https://www.sec.gov/Archives/edgar/data/789019/000095017025100235/msft-20250630.htm): original2025 direct quarter and annual values match the later comparative presentation.
- [Original FY2025 Q3 cash-flow statement](https://www.microsoft.com/en-us/investor/earnings/fy-2025-q3/cash-flows): nine-month OCF93515 and PP&E47472 agree with later2026 comparative values.

Both rows represent consolidated company cash operations and cash PP&E additions.
There is no difference in these selected original/comparative amounts. This is
not proof of an unchanged organic business mix, AI-only cash flow or equal
segment definitions. Noncash leases, acquisitions, dividends and buybacks are
outside PP&E. OpenAI/non-GAAP income adjustments are not substituted for GAAP cash.

Source byte SHA256 (private full pages remain ignored under cache/msft_q4_*):

| Source | SHA256 |
| --- | --- |
| 2026 10-K | 1f4b6bfe40084c5e7a6be4fc9d9a659742a7e8f8051e43d0760c7e692be6c96c |
| 2026 Q3 10-Q | 2a206eea8e03849c7185efb234c8ec8f0213b4c093baed8abae09ed4623adb52 |
| 2026 exhibit | 95fd98b090746fa2468c587042ff567f30796e232fbdfe8436f9ed7c366d20a3 |
| 2025 exhibit | 01a2a23932cdc889b4f646cbb56f3ef1617a2605dda89c1652979b8a4eb107c5 |
| 2025 10-K | 02589c176a6786f2fe758d82c8766b320d3652042c1f1deffe0b409f7063ec7c |
| Original2025 Q3 | 69fee9322329dd6c0e3306fdff72ee39e5c4485b312c6c45234bed8d66ab9b5f |

## Bounded implementation

`msft_cash_q4.py` contains reviewed public facts for these two periods only.
It is used solely by the report's cash-trend view after normal validation fails.
Raw SEC parser and precision evidence, financial scores, decision code, thresholds,
provider TTLs and database data are untouched. Original packet is not mutated.

Recovery requires a fresh identity-checked MSFT packet and the exact reviewed
field status/method, currency, definition, dates, values, both filing accessions,
filing dates, forms and tags. Any changed operand or new/amended filing remains
held pending re-review. No recovery before review date, missing-field fallback,
zero imputation, extrapolation or generic cross-filing exception. Runtime uses
the existing live companyfacts query; no additional network calls.

Recovered output links the direct2026 exhibit (same filing for both quarters),
with unaudited/original-review footnote. The other six rows and three valid YoY
comparisons remain unchanged. New fourth YoY pair is allowed because both direct
quarter values appear in the same exhibit. Latest headline remains43.0%→67.9%.

## Verification and deployment

- Before: decision gate1334 passed102.713s (`decision_u5ts0689`).
- Targeted Q4/cash/SEC/report contracts109 passed7.13s.
- Independent bounded code review: no concrete issues found.
- Fresh live SEC identity/companyfacts:2 requests HTTP200,1.709s; cached repeat
  0.000778s/no added requests. Eight rows,zero held; existing latest comparison
  unchanged. Issuer query only, not a report/Today speed benchmark.
- Final decision gate1334 passed105.460s, no source changes/errors/skips
  (`decision_fwbvwnym`). Report gate207 passed/one known failure45.924s
  (`report_whezebf0`): same pre-existing `test_theme_selection.py:47` whole-app
  function-set assertion. No golden regeneration or new failure.
- Authenticated Cloud acceptance: pending before publication.

## Next bounded task

Connect the same reviewed Q4 provenance annotations to the read-only MSFT
precision evidence display, preserving raw SEC results and all scoring paths.
Use a shared reviewed helper; do not weaken the generic parser or introduce
another financial override.
