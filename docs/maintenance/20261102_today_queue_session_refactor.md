# Today Queue Session And Refresh Extraction

## Scope And Baseline

Baseline: `7dc7a6cfc30c6bc156db7617b295a294e6fce98f`.
This step extracts result restoration, invalidation, refresh orchestration and
snapshot finalization. It does not change investment decisions, thresholds,
price providers, timestamps, cache lifetimes or candidate-discovery defaults.

`_render_today_queue_tab` shrinks from 427 to 362 lines. Its original fresh-price
calculation block becomes the 17-line app helper
`_calculate_fresh_today_summary`, retaining application-specific dependencies.

The new `stock_lab_core/today_queue_session.py` separates:

- `clear_cached_summary`: invalidate the same six computed-result keys.
- `restore_cached_summary`: owner check, session fallback and scoped snapshot
  restoration, with the existing signature passed to the reader.
- `remember_calculated_summary`: original pre-deduplication state update.
- `finalize_summary`: deduplication, memory update and fresh/nonempty-only save.
- `refresh_today_summary`: optional discovery, signature/count refresh,
  calculation callback and completion timestamp.

These functions are 4-34 lines. The owner-change and clear-button paths now use
one invalidation list. The app consumes the shared signature/time keys instead
of maintaining another copy. Account lookup and snapshot storage remain injected
application callbacks; the module does not introduce a new store or cache.

## Preserved Contracts

- Owner change clears computed summaries, last-nonempty fallbacks and the
  portfolio signal frame, but keeps user inputs. The existing anonymous/demo
  owner scope and normalization remain unchanged.
- Restore priority stays session result, last nonempty result, then owner-scoped
  stored snapshot. Expected signature, frame copies and attributes are retained.
- Refresh starts from registered/held inputs, never stale automatic candidates.
  Skipped or failed discovery still calculates only that base scope.
- Quote reset, force-refresh flag, individual/batch history-cache clear,
  financial-score inputs, calculation, measurement binding, input-origin tags
  and portfolio-context stamping keep their original order.
- Calculation errors and interruption signals propagate without recording a new
  completed result. Discovery errors keep the original warning/fallback, and
  progress cleanup remains in `finally`.
- Snapshot saving remains after deduplication and only for fresh nonempty data.
  Cached rerenders do not trigger price recalculation or a snapshot write.
- Buttons, checkbox default, timestamp format, stale-signature/age warnings,
  pending messages and the enclosing performance boundary are unchanged.
- All post-calculation investment gates and detail-view behavior are unchanged.

## Verification

- Before extraction: 25 retained-baseline cache/refresh scenarios passed.
- After extraction: 145 targeted session, view, scope, loading, market-guard,
  input-safety and performance tests passed in 27.07 seconds.
- Baseline comparisons assert exact UI messages, callback order/arguments,
  computed results, state, frame attributes and propagated error types/messages.
  Cases cover empty inputs, cache/disk fallbacks, malformed metadata, owner/demo
  changes, stale results, deletion and failures at discovery, merge, calculation,
  deduplication and save boundaries.
- AST comparisons verify the extracted calculation, restoration, pre-save,
  finalization and refresh statements against the baseline. The only inlined
  substitutions are explicit dependencies and the shared six-key clear loop.
- Dedicated checks cover owner isolation, copy independence, source tags and
  fresh/nonempty-only saving.
- Real Streamlit AppTest runs both versions through calculation, discovery
  toggle, another calculation, owner A to B to A, restoration and deletion.
  Tables, captions, warnings, state and mock storage match. Price-call count
  stays at two through option-only reruns, owner switches and deletion.
- Existing flow-scope tests now compile the extracted app calculation helper;
  their failure/scope assertions remain. The view suite retains policy/timing
  AST parity, with cache/refresh parity covered by the new dedicated suite.
- Compilation and whitespace checks passed.
- Full regression suite: 5,617 passed, 18 subtests passed, 77 warnings in
  275.08 seconds. No executable code edits followed this run.

## Limits And Next Boundary

The focused parity and UI tests use test doubles for account snapshots and
provider calls, without accessing a live account. Cloud UI and end-to-end latency
are not measured here. This is a structural change with unchanged external-call
counts, not a claimed speed improvement.

The remaining app function still includes input/refresh widgets and existing
post-calculation label/mask adjustments. Those can be extracted separately using
the new state contract tests and the existing policy/UI parity checks. The full
application refactor is not complete.
