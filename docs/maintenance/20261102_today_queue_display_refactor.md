# Today Queue Display Policy Extraction

## Scope And Baseline

Baseline: `57ba39a96d45197bd3a04a6a6dd14fb001feab9b`.
This step moves the existing post-calculation label and mask adjustments into
`stock_lab_core/today_queue_display.py`. It does not change investment rules,
thresholds, financial scores, dates, providers, cache lifetimes or UI wording.

`_render_today_queue_tab` shrinks from 362 to 222 lines. The new module separates
leverage labels (62 lines), defense labels (67), display masks (12) and their
preparation entry point (18). The app retains input/refresh orchestration,
market-guard construction, enrichment, final execution gates and rendering.

## Preserved Contracts

- Adjustment order remains recovery tracking, leverage market defense, regional
  scout restrictions, conditional observation, defense labels, planned panic
  entry, core accumulation, market-action labels and display masks.
- Private `_DisplayText` holds the original Series snapshots. They refresh only
  at the original assignments. Rereading every label after each mutation would
  change downstream precedence and is deliberately not done in this refactor.
- The public helper copies its input. Frame indices, attributes, missing-column
  defaults and the caller's signal-group Series are preserved.
- Risk-table generation, analyst/flow enrichment, final execution gate columns,
  portfolio attributes and final queue partitioning stay in the same app order.
  Display masks do not replace final execution gates.
- No new cache, I/O, global session state or cross-run memoization is introduced.

The only calculation reuse is the pure leveraged-scout scan. Previously it ran
twice against identical rows before any mutation, once for allowed observations
and once for market-blocked observations. Its result is now reused locally.
Recovery/defense calls with intervening label changes are not combined.

## Verification

- 60 retained-baseline scenarios passed before extraction. The expanded display
  suite has 65 tests, including exact frame/Series, labels, reason buckets,
  downstream execution gates and partition comparisons.
- Cases cover domestic/US/regional market restrictions, macro-risk boundaries,
  leveraged observation, overweight/overheat, core/panic labels, missing data,
  fallback classification, duplicate/noncontiguous indices and 36 seeded
  numeric-edge scenarios.
- AST comparison reconstructs the moved statements from the new helpers. After
  restoring local Series names and expanding the one reused scout expression,
  all conditions, text constants and refresh points match the baseline.
- Tests count the scout scan reducing from two to one, verify identical original
  inputs and ensure changed weights/market state are recalculated on every call.
- The existing view suite still checks unchanged pre-adjustment preparation and
  post-adjustment gates/enrichment/rendering syntax. Moved policy is covered by
  the new dedicated suite rather than dropping its verification.
- Display, view and session suites: 135 passed (including existing Streamlit
  AppTest coverage). Compilation and whitespace checks passed.
- Full regression suite: 5,682 passed, 18 subtests passed and 77 warnings in
  270.47 seconds. No executable code changes followed this run.

## Same-Input Timing

Command: `python scripts/benchmark_today_queue_display.py --rows 85 --repeat 5 --iterations 20`.
Five alternating A/B rounds, twenty calls per round, the same fixed 85 rows,
including frame copies. Outputs were exactly equal and inputs were unchanged.

| Round | Before (ms/call) | After (ms/call) |
| --- | ---: | ---: |
| 1 | 25.812 | 22.094 |
| 2 | 25.767 | 22.173 |
| 3 | 26.344 | 22.434 |
| 4 | 25.852 | 22.007 |
| 5 | 25.885 | 22.229 |
| Mean | 25.932 | 22.187 |

This small display-only stage decreased by 14.4% in this local run. The benchmark
excludes providers, investment calculations, enrichment and UI rendering. It is
not a measurement of the full Today Queue or Cloud latency; external-call counts
are unchanged.

## Limits

Verification uses synthetic inputs and offline UI/provider doubles. Cloud UI and
live account results are not independently exercised in this step. No forecast,
investment-performance improvement or full-application refactor completion is
claimed. Remaining orchestration and larger calculation functions can be split
separately using the retained behavioral boundaries.
