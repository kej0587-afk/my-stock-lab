# Public investor-flow backfill (2026-11-06)

## Scope

- Report-only KOSPI/KOSDAQ foreign and institutional 5/20-session net totals
  and exact consecutive buying/selling days. No investment gates, portfolio
  quantities, prices, scores, or thresholds changed.
- Existing snapshot-history arithmetic was extracted into
  `summarize_daily_values`, reused without changing its arithmetic or rules.
- `app._collect_today_report_context` collects the daily feed before current
  public snapshots. Rendering performs no network requests. Demo skips it.

## Verified provider contract

- Source: https://stock.naver.com/market/stock/kr/trend/trader
- Daily feed: https://stock.naver.com/api/domestic/market/trend/daily
- The page's actual daily-table JS uses KRX, KOSPI/KOSDAQ, `startIdx`, `pageSize`
  and `bizdate`. Page SSR chart examples are NOT used.
- `diffValue`, `buyPrice`, `sellPrice` are KRW; each component must satisfy
  buy minus sell equals net. Missing, duplicated or malformed components are
  not replaced with zero. The provider's foreign group sums 9000+9001;
  institutions sum 1000/2000/3000/3100/4000/5000/6000/7000 once each.
- The response does not echo exchange/market metadata; provenance is bound to
  the explicit market-specific KRX request, as on the provider page. This is
  an undocumented public endpoint, not a guaranteed/stable API or official
  KRX final ledger.
- Live responses ignored the requested `bizdate` cutoff and included Nov 6
  intraday. Filter by XKRX completed-session calendar independently. Allow
  20 minutes after close before including today's daily row, and retain the
  provisional/correction warning. No weekday-only holiday approximation.
- The table is labelled completed-session history, separate from today's
  intraday snapshot. Backfilled values are retrospective, not historical
  point-in-time evidence and are never supplied to backtests or decisions.

## Missing data and caching

- Exactly two bounded GETs, one per market; at most 60 rows per response.
  Existing response-size cap, connect/read timeouts, credential-free session
  and no redirects are reused. No pagination loop or retry storm.
- Success cache 600 seconds, unsuccessful result cooldown 60 seconds. Cache
  key includes completed session so a close boundary cannot reuse yesterday's
  target. The table rejects stale/future collection timestamps.
- A 5/20-session total requires all corresponding XKRX dates; missing dates
  are counted in the table. Exact streaks require a zero/opposite-sign boundary;
  a missing preceding day or a run longer than available history is unknown.
- No imputed values, residual-derived totals, zero fill, or new persistent
  account records. A failed market does not hide the other valid market.

## Live verification

Collected 2026-11-06 11:25 KST, both HTTP 200. Requested 60 rows per market,
59 accepted historical dates after excluding today's intraday row. Two GETs
took 0.593 seconds locally; this is not an end-to-end app speed benchmark.

Completed-session end: 2026-11-05; amounts in 100 million KRW, provisional:

| Market | Investor | 5 sessions | 20 sessions | Exact run |
| --- | --- | ---: | ---: | --- |
| KOSPI | Foreign | -93340.36 | -224434.93 | Sell 5 |
| KOSPI | Institution | +35008.62 | +64450.75 | Buy 2 |
| KOSDAQ | Foreign | -1761.89 | -9779.80 | Sell 1 |
| KOSDAQ | Institution | -3442.47 | -6821.38 | Sell 1 |

Offline tests cover source-shaped payloads, KRW units/signs, exact sums/runs,
holidays, weekends, close buffer, partial data, duplicate dates/groups,
current/future rows, HTTP/timeout failure, stale cache, rendering without
current-feed availability, input immutability and report-only integration.

Validation: focused flow/narrative suite 128 passed; full suite 6734 passed,
18 subtests passed (336.12 seconds). Full-suite warnings were existing
dependency/pandas warnings. Cloud report regeneration is a separate deployment
check, not represented by this local live-provider verification.
