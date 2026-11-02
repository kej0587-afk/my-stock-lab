# Monthly Rebalancing Extraction

## Scope And Baseline

Baseline: `8d6ee440f4fe2386fc8c218ccbabf165b944b795`.
Only the monthly contribution calculator is refactored. Quote providers, market
dates, cache lifetimes, investment decisions and thresholds are unchanged.

The original 631-line `render_monthly_rebalancing_calculator` now has a nine-line
app adapter. Responsibilities are separated into:

- `monthly_rebalance.py`: active holdings, base allocations, redistribution,
  share counts and status calculations.
- `monthly_rebalance_view.py`: inputs, tables, accumulation controls and
  completion state; main view is 57 lines.
- `monthly_rebalance_log.py`: existing confirmation and save/carryover/reset UI,
  with the owner, demo flag and save callback passed explicitly.

The largest extracted function is 110 lines. The app's existing signal
multiplier is injected, not copied or replaced. The print-report formula is
not reused: it has different normalization and signal-fallback rules.

## Preserved Contracts

- Target selection, cached-signal precedence, leverage dip boundaries and
  always-invest exclusion for leverage.
- Exact floating-point arithmetic order, 0.5% normalization tolerance, integer
  share conversion, FX handling and remainder calculation.
- Existing accumulated-money consumption timing, accumulation buttons,
  completion checks, month-scoped keys and rerun boundaries.
- Full-account and explicit confirmation guards, real contribution/NAV/dividend
  inputs, demo write prohibition, saved rows and owner-scoped widget keys.
- Display strings, table order, input defaults and data-frame immutability.

The existing accumulation behavior and month-clock policy are deliberately not
redesigned during this structural change. No account or database data was
written during verification; all save callbacks were isolated test doubles.

## Duplicate Work Removed

The same target weight used to be converted separately during filtering,
denominator summation and per-row allocation. A private holdings copy now
converts it once, and the latter two stages reuse that exact float. There is no
cross-render cache: subsequent edits to targets are immediately recalculated.
For N eligible rows, target conversions drop from 3N to N.

## Verification

- Before extraction: 74 calculator/confirmation tests passed.
- After extraction: 235 calculator, confirmation and print-report tests passed
  in 16.62 seconds.
- Thirteen extracted blocks have AST parity with the baseline, allowing only
  explicit dependencies and reuse of the normalized target weight.
- Eighty seeded scenarios compare every unformatted allocation, share count,
  multiplier and status exactly; six cases cover the 1.005 normalization edge.
- Whole-render comparisons cover signal overrides, blocked/leverage/swing
  assets, empty data, FX boundaries, accumulation, saved records, save failures,
  partial accounts, demo mode, completion state and month rollover.
- Real Streamlit AppTest exercised contribution changes, accumulation add/reset,
  and a disabled unconfirmed save. Existing log-confirmation widget tests remain.
- Compilation and whitespace checks passed.
- Full regression suite: 5,547 passed, 18 subtests passed, 19 warnings in
  262.93 seconds. No production-code edits followed this run.

## Measurement Boundary

`scripts/benchmark_monthly_rebalance.py` compares the original and extracted
calculation with identical synthetic holdings and the original multiplier.
Both paths are warmed, execution order alternates, and outputs are asserted
exact. UI rendering, database writes and external price requests are excluded.
These measurements cannot demonstrate a faster full Today Queue or Cloud run.

Measured after the test suite stopped, five repetitions of 50 iterations per
path, on the same machine with fixed inputs and no competing test process:

| Synthetic holdings | Before mean (ms) | After mean (ms) | Change |
| --- | ---: | ---: | ---: |
| 10 | 1.530 | 1.597 | 0.067 ms slower |
| 85 | 9.374 | 8.849 | 0.525 ms faster |

85-row before samples (ms): 8.869, 9.120, 10.589, 9.183, 9.109.
85-row after samples (ms): 8.699, 8.630, 8.852, 8.958, 9.107.
10-row before samples (ms): 1.471, 1.483, 1.457, 1.484, 1.754.
10-row after samples (ms): 1.551, 1.544, 1.634, 1.709, 1.549.

Target conversions fell from 255 to 85 for the 85-row fixture and 30 to 10 for
the 10-row fixture. The additional function/frame handling offsets this tiny
saving at small sizes; this is not a universal speedup. The main gain is safe,
testable separation without changing allocation policy or saved records.
