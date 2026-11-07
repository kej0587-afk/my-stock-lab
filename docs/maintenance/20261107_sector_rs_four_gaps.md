# Four KR sector-RS mapping gaps

2026-11-07 KST; base `d9900090`, clean and equal to origin before work.
User permitted moving past blocked SEC acquisition. This bounded task addresses
the four unresolved sector benchmarks recorded in the refactor closure inventory.

## Change

| Stock | Comparison ETF | Boundary |
| --- | --- | --- |
| 나노신소재121600.KQ | TIGER2차전지테마305540.KS | CNT battery-materials proxy; semiconductor/display/solar businesses also exist. |
| 녹십자006280.KS | TIGER헬스케어143860.KS | Broad healthcare, not plasma-product specialists only. |
| 네오팜092730.KQ | TIGER화장품228790.KS | Cosmetics business, not a pharmaceutical inference from its name. |
| 대한항공003490.KS | KODEX운송140710.KS | Airlines, shipping and logistics; not airlines only. |

Only four entries in `sector_map.json` and their provenance records were added.
Sources and limitations are exposed through the existing provenance loader.
Explicit mappings precede name/network inference. No numeric RS values hard-coded;
missing/unaligned price histories still follow existing missing-data handling.

Company/issuer evidence is recorded in each source entry: company-authored
[ANP IR presentation](https://file.alphasquare.co.kr/media/pdfs/company-ir/20250704%EB%82%98%EB%85%B8%EC%8B%A0%EC%86%8C%EC%9E%AC_%E2%80%B2KOSDAQ_Connect_2025%E2%80%B2_%EC%B0%B8%EA%B0%80.pdf),
[GC product introduction](https://www.gcbiopharma.com/kor/index.do),
[Neopharm company overview](https://www.neopharm.co.kr/ko/company.do), and
[KODEX transport factsheet](https://m.samsungfund.com/sheet/20170908/2ETF30_20170831.pdf).
Historical issuer factsheets establish product scope, not current constituent
weights. TIGER healthcare/cosmetics factsheet descriptions were readable in search
results; direct PDF fetch returned403. No claim of independently downloaded current
fund holdings. Proxy choices are research judgements, not exclusive classifications.

## Verification

- Before focused tests57 passed (2.46s); after62 passed (2.84s).
- New contracts cover four suffix-normalized resolvers, precedence over inference,
  correct dated provenance, mismatched-proxy rejection and ETF catalog presence.
  Immutable `d9900090` comparison proves all prior mapping/provenance entries intact.
- Actual existing `load_price_df(...,'3mo')` plus `compute_relative_strength(...,20)`
  succeeded for all four pairs, with61 common sessions each. Both sides end
  2026-11-06; comparison starts2026-10-08; Close/Close basis. These are local live
  provider responses, not a Cloud UI test or independent exchange-price certification.
- Ratio-return changes:33.5670%,11.6701%,22.8224%,-1.1761% respectively. This is
  relative price-ratio change, not percentage-point return subtraction or cash flow.
  Do not interpret relative strength as an absolute-return or buy recommendation.
- Private output/log: `cache/sector_gaps_live_20261107.json` and adjacent `.log`.

No executable app/core source changed. `get_rs_score`/`get_rs_slope` continue using
the separate market benchmark; sector RS remains review evidence. No financial
score recalculation, account write, policy/label change or golden regeneration.
Selected decision regression: **1,327 passed**, zero failures/errors/skips/source
mutations,103.707s. Evidence: `cache/refactor_checks/decision_x0_pflhf`.
This is selected regression coverage, not the entire suite or a backtest.

## Deployment boundary

Commit/push contains data and tests/docs. Existing1hour benchmark caching may retain
the old missing mapping until explicit refresh/expiry. No TTL change is made.
Production display and loaded cache state were not checked in this task. Next
bounded task is four-case Cloud verification, not another unbounded refactor.

SEC acquisition/parser work remains deferred with its existing source dependency.
