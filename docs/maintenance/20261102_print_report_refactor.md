# Print Report Extraction

## Scope

Baseline: `455fc34c3ecf44faffdd9ef1313423ccc14f5c73`, including the home-work
entry quote optimization. No price provider, cache lifetime, market date,
investment threshold, account persistence, authentication, or order path changed.

`render_print_report_v2` was the largest function at 685 lines. Its app entry
is now a 14-line explicit delegation. The extracted modules contain:

- `print_report_data.py`: asset preparation, plan summaries, table formatting.
- `print_report_view.py`: Streamlit orchestration and the existing six charts.

The largest extracted function is at most 165 lines. Callbacks retain the app's
signal multiplier, name resolver, risk analysis, monthly performance and
benchmark behavior. No app import or Streamlit import is needed by the data
module, and no new long-lived cache or worker thread is introduced.

## Duplicate Work And Boundary Fix

Monthly allocation and total needed shares previously selected and normalized
the same active holdings twice. They now share one read-only prepared frame
inside one render. A subsequent render prepares it again, so changes to targets
and holdings are not hidden by a cache. Each table retains its distinct signal
fallback; multiplier calls, sizing, rounding and redistribution are unchanged.

The pre-change characterization reproduced a KeyError for a reserve-only
portfolio: after cash/reserve exclusion, filtering an empty non-boolean series
discarded all columns, including the target weight. An early empty return
preserves the schema and lets the existing no-active-assets message render.
This is the only intentional result change; no allocation threshold was relaxed.

## Verification

- Baseline characterization: 29 passed, one reproduced reserve-only failure.
- Post-change print-report and formatter tests: 82 passed in 11.86s.
- All eleven moved helper bodies have AST parity, allowing only explicit inputs,
  removal of duplicate preparation, and the documented empty-data guard.
- Golden comparisons preserve UI calls, table values, figure JSON, input frames,
  session state and callback order against the retained baseline revision.
- Forty seeded allocation cases use the actual retained signal multiplier and
  compare unformatted frames and metrics exactly, including zero/NaN prices,
  absent FX, target priority, small budgets, redistribution and blocked signals.
- Streamlit AppTest: six charts, four tables and sixteen metrics rendered;
  closing print mode updated state and reran without an exception.
- Compilation and whitespace checks passed.
- Full regression suite: 5,419 passed, 18 subtests passed, 19 warnings in
  267.35 seconds. No failing test or production-code edit followed this run.

## Measurement Boundary

`scripts/benchmark_print_report.py` reproduces the two plan-table calculations
with fixed synthetic data and the baseline signal multiplier. Initialization
is outside timing; each path is warmed, execution order alternates, and exact
output equality is asserted. This is not a live-account or network benchmark.

Measured after the full suite had stopped, five repetitions of 50 iterations
per path, with no other test command running:

| Synthetic holdings | Before mean (ms) | After mean (ms) | Reduction |
| --- | ---: | ---: | ---: |
| 10 | 3.677 | 2.892 | 21.3% |
| 85 | 16.296 | 14.965 | 8.2% |

85-row before samples (ms): 15.962, 16.875, 15.872, 16.793, 15.978.
85-row after samples (ms): 14.946, 15.485, 14.756, 14.967, 14.673.
10-row before samples (ms): 3.649, 3.618, 3.884, 3.619, 3.615.
10-row after samples (ms): 2.920, 2.889, 2.880, 2.886, 2.887.

The absolute saving is only about 0.8-1.3 milliseconds for these table
calculations. The main benefit is independently testable boundaries and one
consistent per-render selection, not seconds off the full dashboard load.

The Today Queue's measured quote/history/MTF bottlenecks remain separate work.
Wrapper call counts are not outbound request counts. No full-workflow speed
claim should be made from this print-only microbenchmark.

## Next Bounded Extractions

Remaining large functions include the monthly rebalancing calculator (631 lines),
market report sections (623), Today Queue view (619), and decision calculation
(594). Each requires its own characterization before extraction. Avoid combining
provider concurrency, changed freshness rules or investment-policy changes with
those structural moves.
