# Amazon individual-company cash reading

Basef59f7c41. Selected AMZN only; no scores/gates/parser/DB/TTL/default-market
collection changes. Follow-up is actual bottleneck measurement, not another issuer.

## Original evidence and definitions

- [Q32026 10-Q](https://www.sec.gov/Archives/edgar/data/1018724/000101872426000040/amzn-20260930.htm),
  filed2026-10-30: cash-flow statement, Note8 segment information, liquidity section.
  SHA256 e0cefa4c19d9ce4662e0541a2ea8fc91aefcfcce53bd6d715372ebf4ca361f8f.
- [Company earnings release](https://ir.aboutamazon.com/news-release/news-release-details/2026/Amazon-com-Announces-Third-Quarter-Results/)
  cross-checks AWS revenue45,984/operating income17,773 millionUSD versus33,006/
  11,434 in prior Q3. Revenue growth39.3%; current margin38.7%, not cash ROI.
- Q3 cash amounts(millionUSD),2025/2026: OCF35,525/42,422; grossPP&E35,095/77,259;
  sales/incentives867/1,381; net cash capex34,228/75,878. OCF-netcapex1,297/-33,456.
  Existing gross cash difference430/-34,837 preserved separately. Netcapex/OCF
  current178.9%; YoY OCF+19.4%, netcapex+121.7%. These are quarters, not TTM FCF.
- Segment PP&E net additions2025/2026: AWS28,301/57,116; NorthAmerica8,638/14,530;
  International1,439/6,068; Corporate507/548; total38,885/78,262. These include
  unpaid/noncash activity. Technology infrastructure is allocated by usage; the
  regional segments are not pure logistics. Do not apply segment proportions to
  consolidated cash capex or call AWS additions AI-only spending.
- Other acquisitions/nonmarketable investments/other net cash use786/23,986 is
  separate from PP&E. Do not label all of it AWS equipment or all non-AI investment.
- Company explanation: technical infrastructure(mostly AWS growth support) and
  fulfillment capacity. Interpretation: demand/investment evidence must be paired
  with deliveries, revenue/margin and cash recovery, without a current-price cause.
- Next checks: AWS growth/margin/depreciation and capacity; regional investment
  efficiency; overall cash/netcapex/other investment/lease and financing pressure.
  No invented working-capital decomposition, forecast price or exhaustion date.

## Implementation and verification

- Reuses existing period/cash validation. Identity/URL/USD/review-only flags,
  timezone-aware collection/as-of date, review date, latest exact Q3, exact cash
  amounts/tags/accession/filed/form and reported operands bound to dated evidence.
  New/revised/bad latest quarter falls back to generic reading; no old-good-quarter
  substitution. Missing prior withholds all prior comparisons, keeps current.
- Existing owner/selection/failure/6h expiry behavior. Numeric comparison tables,
  wrapped explanation/check tables, separate downloadable amazon_cash_review.
  Raw packet unchanged; original8quarter gross-basis table remains expandable.
- Baseline decision1334pass103.788s(decision_ule8upmf). Focused121pass8.17s.
  New mutation tests found1USD tolerance in general validation; this dated review
  now additionally requires exact amounts. General parser/validator untouched.
- Fresh local SEC8quarter input succeeds. Cash and all segment values were
  independently checked against downloaded original HTML; source hash verified.
- Decision1334pass106.863s(decision_gp8vmulr), stable sources. Independent reviewer
  caught unconditional growth prose when prior is held; changed that one sentence
  to neutral current-period wording and added regression coverage after the gate.
  Final targeted121pass7.61s; reviewer confirmed the finding closed.
- Applicationedd125db pushed/accepted in authenticated Cloud. Actual11:49:11KST
  AMZN query and downloaded review:8quarter packet matches fresh local SEC except
  collection timestamp; complete narrative equals local computation. Original
  raw packet preserved; separate amazon_cash_review verified in download.
- Visual review confirms cash-vs-noncash labels, dates/links, readable wrapped
  explanation/next-check tables. No layout correction required in production.
- Before11:44/after11:49ZIP: same95tickers and14core score/grade/verdict/gate fields
  identical(1,330values). Not whole-ZIP identity or fresh full calculation.
- Diagnosticedd125db: amazon_cash_reading/company_deep_dive loaded/disk/Git hashes
  match, restart_required false/stale_modules empty; no reboot.11.012s is render_only,
  not a full Today or SEC-only measure and not evidence of speed improvement.
- Proof ignored under cache/amazon_*: source HTML/hash/numeric acceptance, fresh
  SEC packet, local and Cloud narratives, before/afterZIP, score acceptance,
  loaded-module diagnostic and screenshots. No private account data committed.
  No full-suite/full-Today/performance claim.

## Next bounded task

Measure an actual full Today calculation with expired caches. Preserve the input
universe and measurement ID; separate prices, indicators and external-data work
time from wall time, network requests/misses and lock waits. Use those measurements
to choose one optimization with unchanged results. No TTL changes or speed claims
from render-only diagnostics. User requested stopping issuer expansion for this.
