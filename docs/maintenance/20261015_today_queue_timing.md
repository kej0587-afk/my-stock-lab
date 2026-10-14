# Today Queue Timing and Bounded Speed Improvements

## Scope

No features, decision thresholds, labels, authentication, or database writes
were removed or changed. This is not a Cloud deployment or a measured cure for
the reported five-minute delay.

## Measurements

The synthetic run uses 77 deterministic stocks, unchanged 1y/10y/3mo source
frames, fixed financial scores, no live display overlay, and a 20ms simulated
history-provider delay. It includes summary and analyst enrichment, but not
full money-flow refresh, the UI, app import, or private portfolio access.

| Measurement | Before | After |
| --- | ---: | ---: |
| Summary + analyst elapsed time | 13.713s | 11.067-12.234s |
| Individual history provider calls | 79 | 0 |
| Instrumented batch history calls | 2 | 3 |
| Technical indicator calls | 462 | 308 |
| Benchmark phase elapsed time | 2.137s | 0.435-0.486s |

The first after run spent 0.871s on 1y prefetch, 1.041s on 10y prefetch, and
0.882s on RS classification/prefetch. A final repeat, after parallelizing
classification, took 11.067s (1y 0.825s, 10y 0.992s, RS 0.854s). These are
individual observations, not statistically significant speed estimates.
All 77 output rows had the same result digest:
`ae29bbd1d6062143d694f1438e8f45381b631b8db0c308c35b32960ab059ca27`.

Public SPY/MSFT/NVDA histories and real analyst providers took 9.253s total:
4.974s summary, then 4.279s analyst enrichment. This probe still used fixed
financial scores and no display-price overlay; it is not an authenticated
end-to-end Cloud test and cannot be extrapolated to the full watchlist.

The all-theme synthetic flow calculation retained 475 rows/381 unique tickers.
OHLC extraction and metric calls fell from 475 to 381, elapsed time from
0.713s to 0.570s, with identical output digest:
`3ff464fedaebbce55a5e5240413d5e3781a56cc390c14eb1e9dc8bb143539356`.

## Changes

- Prefetch RS histories in their original 3mo period, including market/sector
  benchmarks. Classifications use at most six workers and existing provider
  locks/cooldowns. Never approximate 3mo data by slicing 1y data. If an older
  loaded price module lacks scoped histories, skip this optimization and keep
  the existing individual-loader behavior instead of crashing on import.
- Reuse successful frames in a ContextVar scoped to one run and copied into
  each worker. Return independent DataFrames; retain individual fallback for
  domestic/missing histories. No global long-lived replacement cache.
- Reuse freshly built weekly/monthly indicators in their snapshots. Default
  snapshot calls still rebuild indicators; daily behavior remains unchanged.
- Reuse ticker metrics inside each flow calculation while preserving every
  theme row and copying metrics before row-specific ranking bonuses.

## Diagnostics

After a Today Queue calculation, the collapsed timing panel reports:
tab elapsed time, elapsed time before entering the tab, script elapsed time
through the tab, named phases, and the ten slowest instrumented functions.
The latest calculation report survives ordinary rerenders. Aggregated logs
contain function names/timings, never holdings, tickers, credentials, or values.

Function totals overlap for nested calls. Category totals use exclusive time
but sum concurrent worker time and are NOT elapsed time or CPU time. Phase
totals include their children and must not be added together. Display prices
include API waits/fallbacks; external-data scopes also include associated
classification/flow processing. Exception counts do not include provider
failures returned as status objects.

The pre-tab timer includes imports/common header work but does not break that
work down by function. Timings end at tab completion, before the diagnostics
panel and any subsequent app work. Retained reports refer to their prior run.

Reproduce: `.venv311/Scripts/python.exe scripts/profile_today_queue.py
--provider-delay 0.02`; optional `--public-live` contacts public providers.

## Verification and Limits

Tests cover scoped-history isolation/copies/expiry, fallback behavior, exact
timeframe snapshots, complete summary parity against the old RS/MTF paths,
including cold/warm caches, KR/US rows, empty/error rows, row order and
financial-score state; also flow row preservation, ranking bonuses, trace
nesting/thread propagation and timing-panel rendering/report retention.
Existing full-output decision snapshots are unchanged.

Final full suite: 891 passed (45.26s); one existing pykrx deprecation warning.
Public-demo AppTest first render: zero exceptions. Review prompted additional
per-ticker source/score distinctions and identical initial financial-score
state in the complete-summary parity test.

The one-minute target is plausible for cached/reasonably responsive providers,
not guaranteed for cold full-theme refresh or provider throttling. Deploy
all changed files plus `stock_lab_core/performance.py` together, restart, and
use the phase report to identify the actual Cloud bottleneck. No force-refresh
semantics or data-quality checks were weakened to meet a timing target.

Official guidance consulted:
[Streamlit threading](https://docs.streamlit.io/develop/concepts/design/multithreading)
and [caching](https://docs.streamlit.io/develop/concepts/architecture/caching).
