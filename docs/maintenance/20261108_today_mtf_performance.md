# Full Today measurement and unused daily MTF snapshot

2026-11-08 KST; base `c2d9397e`, clean main equal to origin before work.
No scoring, verdict text, provider order, TTL, account data or news changes.

## Production baseline

Authenticated full Today calculation, 12:14:19–12:15:44 KST,
ID `c0463d50817d4d8faa53ef2c400a2f28`: **85.258s**; script94.910s,
entry9.474s. Registered81/calculated95/flow additions12; full flow refresh on.
Completed diagnostic, not render-only; zero instrumented errors, no stale
modules/restart requirement. Private diagnostic and input/result ZIP are in
ignored `cache/perf_20261108_before.*`.

| Category | Active union seconds | Concurrent work sum seconds |
| --- | ---: | ---: |
| Prices | 54.923 | 229.044 |
| Indicators | 19.029 | 43.843 |
| External data | 22.189 | 32.435 |
| Decisions | 8.664 | 11.419 |

Category active unions can overlap; sums are not additive wall time. Prices are
largest. Summary38.719s; stock signals21.53s; flow refresh20.73s; analyst1.84s.
KR HTTP389 requests,105.41s concurrent sum/30.38s union. History lookup435:
419 misses(96.3%),16 prior-cache reuses;419 reader calls =389 HTTP +30 exact
request reuses. Price frame lookups164/163misses/1reuse;548 preloaded frame hits.
The712 `load_price_df` invocations are **not712 network requests**. Yahoo chart
137 requests; seven yfinance batch calls and17 individual download calls.

This is predominantly expired KR/price caches, **not a fully cold app**.
Manual refresh clears three price caches; financial metadata can remain warm.
News/analyst clear was followed by a display render before measurement, so73
analyst lookups include70 cache reuses and3 misses. Do not claim cold analysts.
Analyst providers/locks are not the dominant bottleneck in this run.

## One bounded optimization

The95 Today workers build daily indicators and a multi-timeframe pack, then use
only its weekly/monthly snapshots for the guard. The pack rebuilt a daily
snapshot that the worker never reads. The new private optional flag disables
only that unused snapshot in `_compute_summary_item`. Defaults remain enabled
for precision/review/chart callers; source frames, long-history fallback and
weekly/monthly computation remain identical. No cross-run memoization is added.
The optimization avoids95 daily rebuilds when all95 inputs are valid.

## Verification

- Before: decision gate1,334pass in103.742s. Prices gate265pass/1pre-existing
  failure in52.010s: the old whole-app AST comparison predates DART provider
  repairs. Recorded before edits; not hidden or removed.
- Focused100pass in53.01s: immutable `c2d9397e` AST, all precision pack defaults,
  empty/short/missing-volume inputs, week/month guard parity, and20 complete
  Today worker rows with fixed upstream decisions. Real indicators, live-price
  adjustment, MTF and guard execute; providers/leverage upstream are fixed.
- AST adapters restore only the optional argument/conditional and the one
  Today call. Frozen decisions/references are not regenerated.
- `scripts/benchmark_today_mtf.py`,20 fixed260-day daily/2,600-day histories,
  three alternating A/B repeats, network blocked. Sequential median
  **.819337s -> .703249s (-14.17%)**; six-worker median
  **.870645s -> .747107s (-14.19%)**. Exact frames/weekly-monthly snapshots/
  guarded decisions; zero replay requests. This is a local MTF substage,
  **not a whole-app or Cloud speedup**. Private samples:
  `cache/perf_20261108_mtf_benchmark.json`.

- Final decision gate **1,367 passed** in133.850s, stable sources; prices
  **265passed/one same pre-existing failure** in52.003s. Private gate records:
  `cache/refactor_checks/decision_e8m_v6sv`, `prices_xkoi2svn`. Independent
  read-only review found no concrete scoped correctness/parity/deployment issue.

## Production acceptance

Application **d1d17690** committed/pushed. After deployment an old browser session
remained on Running in the asset page; Stop did not produce a visible response.
A fresh authenticated session opened normally. This navigation delay is not
included in Today timing and its server cause is unproven; no reboot was needed.

Completed full calculation12:31:27–12:32:46 KST, ID
`f3f000044b2f4119ab93d94a12a84e13`, **79.759s**/script89.212s. Same95 symbols,
81registered/12flow candidates and full-flow setting. The prior full calculation
was17minutes earlier, beyond the900s KR provider TTL. Actual events confirm
421/437KR cache misses(96.3%),16cache reuses,391HTTP and30exact request reuses.
Prices164lookups/163misses,548preloaded hits; analysts still70reuses/3misses.
This remains mixed-cache, not a fully cold app. No instrumented errors.

| Measurement | Before | After |
| --- | ---: | ---: |
| Whole Today, seconds | 85.258 | 79.759 |
| Prices active union, seconds | 54.923 | 53.189 |
| Indicators active union, seconds | 19.029 | 15.755 |
| External active union, seconds | 22.189 | 16.349 |
| MTF calls | 95 | 95 |
| Indicator builds | 380 | **285** |
| Summary phase, seconds | 38.719 | 36.549 |
| Stock-signal phase, seconds | 21.534 | 22.403 |
| Flow-refresh phase, seconds | 20.735 | 16.365 |
| Analyst phase, seconds | 1.839 | 1.647 |

Observed whole time decreased5.499s, but flow/network also differed (KR389->391
requests, Yahoo chart137->135; stock-signal wall actually increased). This is
**not a controlled5.5s patch speedup**. The causal fixed-input evidence is the
local~14% MTF reduction and the removed95 indicator builds in production.

Before/after master exports have identical95ticker sets and all1,045values in
11score/grade/verdict/gate columns. Across common columns only calculation
timestamps(95rows) and analyst-query timestamps(3rows) differ. No claim of
whole ZIP byte identity. Local/loaded/disk app SHA-256 all
`582907764c7087a2cd07d1013fbb58000228c466f8a69cd2565fc9738f3fe4c0`;
stale modules empty/restart false. Private proof:
`cache/perf_20261108_after.json`, `_after.zip`, `_acceptance.json`, `_after.png`.

Prices remain the largest measured category. Do not extend TTLs, remove
data coverage, or merge distinct date-range requests to promise a1minute run.
The agreed next step returns to a shared company/market-context analysis path;
further performance changes require a distinct measured opportunity.
