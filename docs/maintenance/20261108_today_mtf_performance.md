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
largest. Summary38.721s; stock signals21.53s; flow refresh20.73s; analyst1.84s.
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

Deployment and post-change full run pending; do not infer production improvement
from the local benchmark.
