# Production Today Check bottleneck measurement

## Scope and provenance

- One explicit calculation on authenticated production, unchanged account/filter
  and watchlist settings. No code, investment rules, TTLs or data scope changed.
- Build: `bd65d26b495ffdef8a5320a3a53ff1668d4c4f95`; latest application change
  remains `051ac66c`. Local/upstream were clean and equal before measurement.
- Measurement: `e36d58ac51f7463b9d86820aa3c4f8f9`, 2026-11-07
  **04:05:46–04:07:24 KST** (JSON timestamps are UTC).
- `completed`, `calculation_completed=true`,
  `is_full_today_queue_measurement=true`, `measurement_reused=false`.
  UI measurement ID and downloaded completed JSON agree. This is not a
  render-only/partial `last_attempt` file.
- Input counts: registered 81, calculated 95, automatic flow candidates 12.
  UI base scope was 83 including two automatically included held instruments.
  These counts describe different stages, not a changed filter during the run.
- Cache policy: `standard_refresh_not_fully_cold`. The normal calculation button
  resets latest quotes, `load_price_df`, and batch-price caches; provider history,
  analyst six-hour cache and financial metadata may remain warm. No manual cache
  purge or second benchmark run. Entering the existing screen beforehand was a
  separate 14.9s render-only run and may have warmed dependencies.
- Export build reports `restart_required=false`, no stale tracked modules.
  Its app entry hash matches local source after newline normalization. The report
  build manifest does not independently attest every price/indicator module.
- Private evidence stays outside Git, in `C:/Users/82amf/Downloads/`:
  `today_queue_e36d58ac51f7463b9d86820aa3c4f8f9.json` and
  `stock_lab_today_bottleneck_20261107.jpg`.
  JSON SHA-256: `5fd77baaad744b954935b33235f51b02600aba2d501d1f3fccf45df27050aac2`.

## Timings

Today Check wall elapsed **98.540s**; entry preparation **2.992s**;
script elapsed **101.682s** (also includes small surrounding bookkeeping).

| Category | Exclusive work sum, seconds | Union of category active intervals, seconds |
| --- | ---: | ---: |
| Prices / waits | 239.687 | 66.016 |
| Indicators / patterns | 54.356 | 20.936 |
| External data / flow processing | 33.941 | 23.361 |
| Decision / result assembly | 22.349 | 14.269 |

Work sums remove nested child spans but still add concurrent workers. Category
active unions remove within-category overlap; **different categories still
overlap**, so neither column is an additive decomposition of the 98.540s wall
time. External data includes local flow processing, not just network waits;
prices includes cache/normalization/locking as well as network I/O.

All measured non-phase intervals together cover 74.270s. Work sum is 350.334s;
parallel excess is 276.064s. The remaining 24.270s is outside those category
intervals (phase-only/UI/bookkeeping and other uncovered work), not demonstrated
idle time. Root render self time is 10.940s and is not an extra additive category.

| Stage | Wall elapsed, seconds | Interpretation |
| --- | ---: | --- |
| Flow refresh | 20.567 | Includes ETF/theme price retrieval and processing |
| Summary | 50.828 | Parent of the following history and signal phases |
| 1y history | 9.426 | Exact-period preload |
| 10y history | 6.991 | Exact-period preload |
| RS 3mo history | 10.882 | Exact-period preload |
| Stock signals | 22.435 | Concurrent indicators/decisions/live quotes |
| Flow context | 5.447 | Post-calculation connection work |
| Review export | 2.439 | Export generation |
| Analyst enrichment | 1.800 | Already concurrent; not the leading bottleneck |

The three history phases are sequential in `get_all_summary`, totaling 27.299s;
do not add them again to their summary parent. One sample establishes a current
bottleneck, not a trend, p95, or before/after speedup. Historical ~70s samples
have different cache/market/provider conditions even where row counts agree.

## Requests versus function calls

| Counter | Result | Meaning |
| --- | ---: | --- |
| `load_price_df` | 750 | Wrapper invocations, not HTTP requests |
| Prefetched / memo history hits | 540 / 13 | In-run reuse already active |
| Price-history cache lookups / misses / reuse | 197 / 196 / 1 | Different layer from KR provider cache |
| KR history cache lookups / misses / reuse | 427 / 414 / 13 | 3.04% reuse at this layer |
| KR history HTTP requests / responses | 414 / 414 | Actual instrumented feed requests; no unavailable event |
| Yahoo chart requests / responses | 73 / 73 | Actual instrumented chart requests |
| Yahoo chart sessions created / reused | 8 / 65 | Connection reuse is working |
| Naver bulk requests / responses | 3 / 3 | Actual instrumented bulk requests |
| yfinance single / batch downloads | 54 / 3 | Library calls, not underlying HTTP request counts |

These counters are not a complete network audit: yfinance internals and some
external providers do not expose request-level counters here. Missing events
must not be interpreted as zero network traffic.

`kr_history_http`: 111.228s cumulative, **30.074s union active**, 2.214s longest
call, 414 calls. `load_price_df`: 117.078s inclusive / 61.506s self; do not add
its inclusive total to child KR transport time. `load_price_frames_batch` is
25.617s across three calls, overlapping domestic workers in each preload.
`build_precision_multi_timeframe_pack`: 55.010s inclusive / 25.864s self,
19.577s union active; its 380 indicator child calls total 24.903s.
`get_analyst_snapshot`: 73 calls, 5.969s cumulative but 1.768s union active.
`build_kr_cluster_snapshot`: 36 calls, only 0.524s. KR quote fallback wait rounds
to 0.000s. Instrumented error counters are zero; that alone does not prove every
provider returned fresh/complete data.

## Dominant path and one next task

**Prices are the dominant measured category; investigate exact-request reuse in
the KR daily-history path next.** The evidence does not establish that all 414
requests are duplicates or that removing them would save 30s of total wall time.

Focused source inspection:

- `app.py::get_all_summary` independently preloads 1y, 10y and RS 3mo histories.
  Its explicit contract keeps RS on its original source rather than slicing 1y.
- `prices.py::price_frame_scope` already reuses exact ticker/period snapshots.
- `prices.py::_fetch_pykrx_ohlcv` passes an explicit period start; money-flow
  `get_money_flow_ohlc` calls `load_kr_flow_history` with its default start.
- `kr_flow_history.py::load_kr_flow_history` caches original call arguments,
  while `KrFlowHistoryReader.read` subsequently normalizes the ticker to a
  six-character provider code and dates to day boundaries. Thus superficially
  different call keys can represent identical provider requests, but distinct
  ranges must remain distinct. Current exports do not identify per-request keys,
  so the avoidable portion is not measured yet.

Next bounded task: establish sanitized exact-request identity/call-site counts
for this KR path, then coalesce **only demonstrated identical** provider requests
within the run. Identity must include provider code, effective start/end,
request count and adjustment semantics. Compare old/new frames including index,
dtypes and attrs on fixed responses, and preserve failure cooldown, copy
isolation, manual refresh and timezone/date boundaries. Do not unify UTC-local
and KST dates implicitly, slice different ranges, widen history requests, change
TTL/concurrency, or alter rules. If no identical requests are demonstrated, do
not implement speculative reuse; document that result. Use prices regression
gate before/after any code change and one comparable complete production run.

## Verification and deployment

Programmatic checks passed for completion flags, identity, local commit/app hash,
tracked stale-module state, error counters and timing arithmetic. Production UI
showed successful 98.5s completion and exported the same measurement. This task
changes documentation only: no regression suite rerun, application deployment,
cache purge or reboot is required. Commit/push this record and `HANDOFF.md`;
private profile and screenshot remain untracked outside the repository.
