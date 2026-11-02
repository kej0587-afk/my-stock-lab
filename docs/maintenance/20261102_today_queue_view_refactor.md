# Today Queue Detail View Extraction

## Scope And Baseline

Baseline: `26da1c00a97afc6d53f52d551e9a069216d25c8d`.
Only Today Queue's concentration notice, detail tables, classification tabs and
export/validation/candidate-panel calls are extracted. This is not a redesign
of the investment policy or the full Today Queue pipeline.

`_render_today_queue_tab` shrinks from 619 to 427 lines. The new
`stock_lab_core/today_queue_view.py` has five functions of 9-59 lines:

- `prepare_detail_view`: private display copy with execution guidance.
- `_render_concentration`: existing candidate concentration notice.
- `_render_detail_table`: sorting, display columns and per-table CSV download.
- `_render_queue_tabs`: existing twelve-tab layout.
- `render_today_queue_details`: export, research, tabs, validation and candidate
  panel orchestration.

Holdings, computed masks and application callbacks are explicit inputs. The view
does not own session state, account lookup, network clients or a cache. Source
registration uses the existing build-diagnostics mechanism.

## Preserved Contracts

- Every statement before the extracted detail section, including the timing
  decorator, calculation, gate adjustments, refresh branch, owner isolation,
  snapshot restore/save and portfolio-signal synchronization, is AST-identical
  to the baseline.
- Investment thresholds, price dates, providers, timeouts, cache lifetimes and
  financial calculations are untouched.
- Tab order/counts, text, column configuration, CSV bytes/filenames/widget keys,
  sort order and callback order/payloads match the baseline.
- Export, validation and candidate callbacks still receive the original
  classified summary, not the display copy. Frame attributes are preserved.

## Duplicate Work Removed

Execution guidance used to be recomputed for each classified group and again
for the full table. It is now computed once on a private copy per rendering.
The groups and full table reuse that copy, but keep their independent existing
sort rules. There is no cross-session or cross-render cache; changed gate inputs
are reflected immediately. For 85 rows partitioned into ten groups, guidance
calls decrease from 170 to 85.

## Verification

- Before extraction: 33 characterization tests passed.
- After extraction: 110 targeted detail-view, loading, flow-scope, performance
  and market-guard tests passed in 30.32 seconds.
- Fixed-baseline comparisons include empty/minimal data, constant/mixed states,
  noncontiguous/duplicate/string indices, overlapping masks, wait-only
  concentration, missing raw plans and twenty randomized numerical/gate cases.
- Real Streamlit AppTest compares the old and new twelve-tab UI, 22 populated
  dataframes, eleven downloads and callback order. Rerunning with only two rows
  also matches the baseline, including empty groups.
- Raw inputs, attributes, masks and state are unchanged. A dedicated test checks
  170-to-85 guidance calls and another checks fresh guidance on subsequent runs.
- Compilation and whitespace checks passed.
- Full suite: 5,584 passed, 18 subtests passed, 77 warnings in 346.86 seconds.
  The new randomized display cases exercise 58 additional warnings from the
  unchanged Pandas numeric-sort helper. Only trailing-blank-line cleanup followed
  this run; no executable production code changed.

## Measurement Boundary

`scripts/benchmark_today_queue_view.py` compares the retained baseline's
guidance/sorting block with the extracted preparation using identical synthetic
inputs. Both paths are warmed, order alternates and all output frames are
asserted exactly equal. Five repetitions of ten iterations were measured with
no competing test process:

| Rows | Before mean | After mean | Reduction |
| ---: | ---: | ---: | ---: |
| 85 | 46.599 ms | 40.202 ms | 13.7% |

Before samples (ms): 46.669, 46.487, 46.811, 46.370, 46.658.
After samples (ms): 40.194, 40.319, 39.972, 40.475, 40.051.

This is a small local display-preparation improvement, not a measurement of
full Today Queue/Cloud latency. No live account data or database writes were
used. Cloud UI and live provider latency are not verified by these tests.

## Remaining Work

The 427-line app function still owns input/cache orchestration, existing display
policy corrections and enrichment wiring. Those are intentionally not moved in
this patch. Future extraction should preserve their input/output, refresh and
owner-isolation contracts separately rather than moving the whole function at
once. Other large calculation and rendering functions remain in the app.
