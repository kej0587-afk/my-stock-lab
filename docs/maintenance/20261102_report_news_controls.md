# Report topic controls and Korean market narrative

Baseline: `044d45ca`. Scope: report collection/presentation only; no trading grades,
thresholds, portfolio records, authentication, or database changes.

## Confirmed causes

- The manual report UI read market categories and per-category counts but never
  passed them to report_context. The collector hard-coded five articles.
- The query planner truncated explicit categories to three, then could exhaust
  its request budget on exposures before selected topics.
- Stock RSS was fetched, but market_memo discarded it whenever session context
  existed. Another generation entrypoint used an unrelated saved news list.
- Long mixed-language search expressions returned almost no usable topic news.
- Market synthesis favored semiconductor/foreign-buying headlines. Existing
  dated sector and public investor observations did not reach the top narrative.
- Public indicators already supplied individual and program totals, but the
  latter were ignored. Program trading is a method, not another investor.

## Changes

- Both generation paths use shared session preferences; tab/widget cleanup does
  not discard them. Disabled controls and a regeneration caption explain scope.
- All requested topics get reserved query slots. Use short OR terms, independent
  topic queries when possible, grouped queries only as needed to stay at 16 GETs
  and four RSS workers. Existing success/failure cache ages remain unchanged.
- RSS and publisher feeds overlap. Same calls and limits; no retries added.
- Retrieval allowance is separate from the display limit. A cross-topic article
  cannot disappear merely because the UI requests one article per topic.
- Requested topics have a collapsible table with source/time, article evidence,
  holding-review checks, empty/failed retrieval states, and cross-topic duplicate
  references. Global/China context is not mislabeled as a US close cause.
- Optional stock RSS is merged, with query-market provenance so a US issuer
  returned for a KR-listed ETF is assigned by article subject.
- KR top narrative connects dated sector ETF observations and investor divergence.
  Detailed investor and program amounts are separate tables. Industry ETF rankings
  explicitly describe the observed subset, not an exhaustive industry ranking.
- Shipbuilding `494670.KS` was already in rotation histories; fixed report-sector
  coverage now also supplies its live quote/short-history path.
- Individual/program values use the existing public GET. Validate raw integer
  amounts, KRX/KRW scope, dates, freshness, and exact arbitrage+non-arbitrage sum.
  Optional missing program data does not invalidate valid investor totals.
  The program's own timestamp is absent: disclose the shared response flow date.

## Verification

- Streamlit AppTest changed topics, stock count, display count, include switches,
  clicked generate, and checked the actual collector arguments.
- Regression cases cover all topic coverage within request budget, future/stale
  news, cross-market stock lookup, source filtering, duplicate display, no-data
  distinction, concurrent retrieval, investor/program arithmetic and no inferred
  institution attribution or cheap-buying motive.
- Live public news probe at 2026-11-02 22:07 KST: 16 queries, 5.574 seconds for
  news retrieval/curation/body attempts, all 11 default topics had accepted news.
  This is a local news-only observation, NOT full Cloud report elapsed time or a
  controlled before/after speed claim. Some public article bodies remain unavailable.
- The news probe captured current shipbuilding rebound/order headlines from
  News1 and Korea Economic Daily. No daily figures or headlines are hard-coded.
- Public program fields were verified directly on 2026-11-02; no credentials
  were used. Provider endpoint is undocumented; invalid responses fail closed.

Sources: [Npay market data](https://stock.naver.com/market/stock/kr/trend/trader),
[Kiwoom program trading explanation](https://download.kiwoom.com/hero4_help_new/0765.htm).

## Final checks and deployment

- Full suite: 6,219 passed, 1 skipped, 18 subtests passed in 367.03s. One new
  presentation assertion still expected an ISO timestamp after the UI had changed
  it to readable KST. Updated that assertion (no application-code change) and
  reran the affected investor/program/news/UI suites: 169 passed in 5.95s.
- Live public flow collection at 22:24 KST completed in 0.777s using the existing
  three GETs. The compact reading reported institutions net-buying while foreign
  and individual investors net-sold in both markets. Separate program tables
  displayed validated arbitrage/non-arbitrage totals; no inferred buying motive.
- Commit `d529cd2f` pushed to main. Cloud loaded new files but the operating UI
  reported mismatched in-memory modules and correctly disabled report generation.
  Profile access worked; managing apps required GitHub reauthentication. A Cloud
  reboot was requested. Do not describe a new Cloud report as verified until that
  reboot and a new generation complete.
