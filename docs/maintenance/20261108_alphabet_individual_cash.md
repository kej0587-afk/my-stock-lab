# Alphabet individual-company cash reading

Base: c7d4a5fe. Scope: selected-company narrative only; existing scores, grades,
gates, generic SEC packets/parser, database, TTLs and default market collection
remain unchanged.

## Evidence and meaning

- Reuse the exact original-statement recovery from
  [the Q3 reconciliation](20261108_alphabet_cash_q3.md), through the same cash
  checks used by the Big Tech comparison. Current quarter must still be
  July–September2026; a newer/invalid/duplicate period never inherits this prose.
- [2026 Q3 earnings release](https://www.sec.gov/Archives/edgar/data/1652044/000165204426000080/googexhibit991q32026.htm):
  OCF42,290 / cashPP&E51,355 / simple difference-9,065 millionUSD; ratio121.4%.
  Same comparative exhibit: priorOCF48,414 / cashPP&E23,953; YoY-12.6%/+114.4%,
  ratiochange+72.0pp. Independent prior recovery is required for YoY.
- [Official2026 Q3 call](https://abc.xyz/investor/events/event-details/2026/2026-Q3-Earnings-Call-2026-Ujou16CTw9/default.aspx),
  CFO cash-flow discussion and TPU-system Q&A: management attributes pressure
  to inventory buildup for TPU system sales and a$5.2b cash payment of the2018
  EC fine after appeal. Technical infrastructure is the majority of capex;
  its split is about65%servers/network and35%data centers, not65%of all capex.
- UI separates calculated facts, company explanation and inference. Inventory
  is a working-capital use, not another capex amount. No attribution of the whole
  OCF decline, invented inventory cash amount, adjusted OCF excluding fine,
  all-AI capex allocation, price cause, target price or cash-exhaustion forecast.
- Next checks connect inventory/receivables and deliveries to cash recovery;
  capex/depreciation to Cloud revenue/margins; later legal/working-capital payments
  to liquidity. These are conditions to inspect, not predicted improvements.
- Dated source commentary is reviewed2026-11-08 about2026-10-28 disclosures,
  not a newly fetched transcript or live consensus feed.

## UI and validation

- Selected GOOG/GOOGL only, explicit existing query. No extra network requests.
  Existing owner/selection/failure/6h expiry behavior remains. Same financial
  recovery for both share classes; no substitution for other companies.
- Natural summary, two-period cash table, three driver rows, three next-check
  rows. Generic cash/coverage prose is replaced only when recovery succeeds.
  Income reading stays generic; original eight-quarter table remains expandable
  with explicit pre-recovery hold label. Source/raw-quality tables remain.
- First Cloud visual check found long driver/check cells clipped in dataframe
  grids. Changed only these explanatory tables to wrapping static tables;
  numeric comparison grid stays unchanged. No calculation or data change.
- Download adds a separate alphabet_cash_review including narrative, source
  dates, values, change calculations and recovery audit. Original packet unchanged.
- Before decision gate:1334pass103.321s(decision_shuvalo0).
  Focused155pass8.43s. Independent read-only reviewer: no concrete scoped bugs,
  67targeted tests/isolation probes passed. Local previously collected live SEC
  packet yields exactly2recoveries and the values above without input mutation.
- Final decision gate:1334pass108.85s(decision_z13himhd), stable source hashes.
  After the two presentation calls changed to wrapping tables, the focused
  155tests passed again in8.15s. No calculation changes after the decision gate.
- Application7d9745fe and UI4fc40f67 pushed/accepted in authenticated Cloud.
  Fresh local SEC at11:26KST and actual Cloud query11:26:40KST: all8quarter packet
  fields match except collection timestamp; downloaded narrative equals local
  calculation, exactly2recoveries, raw cross-filing cash holds retained.
- Operating screenshot confirms readable wrapped driver/check tables, dated
  source labels/links and summary. Download contains separate narrative/audit.
- Before11:21/after11:28KST ZIP: same95tickers,14core score/grade/verdict/gate fields
  identical(1,330values). No whole-ZIP identity or new full calculation claim.
- Final diagnostic4fc40f67: alphabet_cash_reading, alphabet_cash_q3 and
  company_deep_dive loaded/disk/Git hashes match; restart_required false and no
  stale modules. No reboot required.11.732s is render_only, not full Today/SEC-only
  duration, and not evidence of speed improvement. No whole-suite pass claim.
- Private proof under ignored cache/alphabet_individual_*: before/after ZIP,
  fresh SEC packet, Cloud review JSON, local narrative, acceptance/score checks,
  final diagnostic and screenshot. No private account data committed.

## Next bounded task

Inspect Amazon's latest same-period original cash-flow and earnings explanations;
connect verified AWS-versus-other-investment context and next checks to its
selected-company view. Preserve raw packets, scores and on-demand collection.
No assumed AI-only allocation or unsupported working-capital attribution.
