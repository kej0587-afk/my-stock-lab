# Today Queue Performance: 2026-10-14

## Preserved Behavior

No features, trading labels, thresholds, indicator formulas or lookback periods
were removed or shortened. Money flow, themes, weekly/monthly analysis and
individual-provider fallbacks remain. Auth, secrets and DB writes are unchanged.

## Changes

- Overseas 1y and 10y histories use bounded yfinance batch downloads (max four
  internal workers). Domestic histories retain pykrx-first individual loading.
- Missing/ambiguous batch symbols fall back to individual loading. Each symbol
  uses the same selector, OHLCV cleanup, adjusted-close retention and alignment
  as the former individual path.
- Pass prefetched frames directly to calculation workers and MTF analysis.
  Short 10y histories still attempt max, 5y and 2y in the same order.
- Reuse one live-price indicator overlay for both decisions and chart patterns.
  Read source_close before overlay and copy the prepared frame for decisions.
- Split wide batch columns before copying, rather than copying the entire
  multi-symbol frame for every ticker.
- History downloads, money flow and macro reads share one lock so yfinance
  download globals cannot collide across those paths. Internal batch concurrency
  stays bounded; no timeout was shortened.
- Price refresh clears the new batch cache. Older loaded helpers fall back to
  the former individual path instead of failing app imports.

## Measurements

Controlled actual summary-engine benchmark: 20 synthetic symbols, 260 daily and
600 long-history bars, 10ms fake provider delay, execution order before/after/
after/before. All rows and columns were exactly equal with pandas assertions.

| Metric | Before | After |
| --- | ---: | ---: |
| Run 1 wall time | 3.100s | 2.655s |
| Run 2 wall time | 3.093s | 2.827s |
| Mean wall time | 3.097s | 2.741s |
| Indicator builder calls | 160 | 140 |
| Individual history-loader calls | 60 | 0 |
| Batch-download calls | 0 | 2 |
| Underlying symbol-history requests | 40 | 40 |

Batching does not mean one Yahoo HTTP request for all symbols. It schedules the
same history requests within bounded concurrency. These controlled wall times
are not production/Cloud latency or a promised speedup for a private portfolio.

Wide batch selection microbenchmark: 77 symbols, 2520 rows, six fields each.
Selecting all symbols fell from 0.5382s to 0.0355s (selection only).

Live public-provider check: MSFT and SPY, 1y daily bars. The batch completed in
1.779s; both returned 251 rows and were identical to the individual loader,
including Adj Close. No private holdings or credentials were sent.

Initial worker profiling with synthetic loaders identified MTF processing,
decision calculation and duplicate live overlays as major measured paths.
Its nested inclusive timings overlap and synthetic-loader generation adds
cost; that profiled run is not a production performance measurement.

## Verification

Regression tests cover full decision parity with/without prepared live input,
symbol isolation, adjusted close, domestic/missing-symbol fallback, short-history
MTF parity, refresh invalidation and older-module compatibility.
Existing golden decision snapshots were not regenerated.
Final full suite: 848 passed in 36.27s, with one existing pykrx warning.
`git diff --check` reports no whitespace errors.
Cloud deployment and authenticated private-portfolio latency remain untested.

Official API reference consulted:
https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html
