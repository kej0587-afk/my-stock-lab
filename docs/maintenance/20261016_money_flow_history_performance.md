# Money-flow history loading: 2026-10-16

## Scope and Evidence

The supplied `today_queue_performance.json` reports 158.715 seconds of wall
time. `flow_refresh` takes 59.125 seconds, including 43.294 seconds inside
`calculate_image_theme_flow_df`. Those nested timings must not be added.
Category totals include concurrent work and are not elapsed time.

The ETF and theme calculations both loaded KRX histories serially, although
their tickers are independent. The new `_load_universe_metrics` shares this
work between both entrypoints and loads at most four KRX histories concurrently.
A process-wide semaphore limits this path across simultaneous sessions.

## Preserved Behavior

- Same KRX-first/FDR-fallback provider order for each domestic ticker.
- US/international fallbacks remain serial; no increased Alpha Vantage quota.
- Metrics still execute on the caller thread in original ticker order.
- Each unique ticker is loaded and scored once per calculation.
- ETF ranking bonuses, duplicate theme membership, final sorting and empty/
  short-history handling are unchanged.
- Existing 900-second outer caches and refresh/clear hooks are unchanged.
- No new persistent cache, credentials, trading thresholds or account writes.
- Unexpected exceptions still propagate; semaphore slots are released.
- Worker timings remain attached to the current performance report. The new
  `flow_history_and_metrics` phase is also nested, not an extra elapsed cost.

## Verification

- Nine new tests cover exact DataFrame equivalence against the original serial
  loop, all/selected themes, ETF bonuses, duplicate/missing/short histories,
  bounded simultaneous sessions, provider order, exception recovery, empty/
  single/non-KRX paths and performance-context propagation.
- Focused performance/regression tests: 71 passed.
- Full suite: 909 passed; one existing pykrx deprecation warning.
- Synthetic benchmark: 32 domestic tickers, 252 bars, 30ms simulated provider
  delay, three runs. Median serial 1.007s; parallel 0.248s. Scores exactly equal.
  This is not a live-network or end-to-end Streamlit benchmark.

## Deployment and Follow-Up

Only `stock_lab_core/money_flow.py` changes at runtime. `app.py` and the user's
new performance instrumentation are retained. No Cloud deployment was performed.
After deployment, compare the same refresh operation and universe using the JSON
report. Warm-cache results should not be compared to a cold-cache baseline.

The supplied report also shows 86.874 cumulative seconds for live-price loading
and 75.647 cumulative seconds for individual Naver quote calls. These remain a
separate follow-up: cross-stage quote reuse must preserve quote timestamps and
manual refresh behavior. No claim is made that total 158.715s has fallen by the
synthetic benchmark ratio.
