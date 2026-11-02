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

## Follow-up: 2026-11-03 public body and finance coverage

- After the user rebooted, Cloud generated a report at 2026-11-02 22:38 KST
  with build `72c3f290cf5d`. Shipbuilding and separate investor/program tables
  were present. Finance remained empty in that run; most rows were title-only.
- Finance matching now covers financial holdings and named banks, excludes
  central-bank-only headlines and routine promotion, and prefers material
  earnings/regulatory/capital stories. Retrieval still has at most 16 search
  requests; source validation now accepts the official Financial News RSS.
- Publisher feeds previously dropped sector stories before curation. They now
  preserve matching topics. Added the publisher's documented finance/stock feeds
  (4 feeds total, 2 workers) and narrowly scoped public body extraction. Body
  requests remain capped at 4, with per-topic variety for the GLOBAL bucket.
- Headline metadata contained `&apos;` while RSS used literal quotes; normalize
  HTML entities before identity comparison. Keep different-headline, restricted,
  future-version and timestamp checks. Empty bodies do not claim verification.
- Prefer actual broad-market reports over IPO `상승 마감` stories; do not read
  two broad recaps from the same market. Selected shipbuilding/finance material
  receives a body-reading slot before routine features where available.
- Institution buying and opening-session context have separate evidence labels.
  Opening weakness is not presented as the whole-day cause. A finance governance
  article does not become a prediction of banking-stock gains.
- Same public HTML inputs (4 articles, collected 2026-11-03 00:07 KST): old
  parser verified 1/4; new parser verified 4/4. This is a targeted reproduction,
  not a universal coverage rate. Source bodies are not stored in the repository.
- Local bounded news collection at 23:59 KST took 6.182s; body work 0.687s.
  Re-selecting the same accepted pool after fixes took 0.688s for four bodies.
  These are local observations, not Cloud/full-today timings or a controlled
  speedup claim. Cold/warm synthetic tests confirm no extra warm network calls.
- Related regression suite: 494 passed in 15.60s. Covers identity, future data,
  public access, source whitelist, finance classification, UI preferences,
  article limits, cold/warm equality (excluding measured duration), and stories.

Publisher feed documentation: https://www.fnnews.com/rss

## Follow-up: production body connection diagnosis

- Build f3666d86 was verified after reboot. Production finance headlines appeared,
  but the body remained unverified on repeat generation, while the same public
  URL verified locally. Do not infer successful production extraction from local
  success or infer HTTP blocking without a recorded status.
- Preserve safe HTTP/timeout/parse failure codes and include a four-row bounded
  body-connection check in the collapsed selected-topics section. Distinguish
  an unselected article, an unsupported publisher, failed fetch, identity/date
  rejection, and a read body without a supported interpretation. No extra network
  requests, exception strings, full bodies, credentials, or user data are added.
- Independent review reproduced an inline-markup defect: `itertext()` fragments
  shorter than 25 characters lost bank-governance evidence when `strong`/links
  split a sentence. Preserve inline text within block boundaries, keep unrelated
  paragraphs separate, and invalidate the provider cache revision. This is a real
  parser defect but not yet proof of the Cloud discrepancy's cause.
