# Fixed-input residual summary profile

2026-11-07 KST, base `5953ce37`, clean/equal origin/main before work.
Production app and decision modules are unchanged. Added only an offline
reproducible profiling script plus this record/HANDOFF.

## Scope and verification

`scripts/profile_summary_local.py` reuses the 20 seeded scenarios and frozen full
decision outputs from the existing regression fixtures. It runs the actual
`_compute_summary_item`, source-flow calculation/normalization, chart patterns,
workflow assembly, sideways state, basis and row formatting. Upstream scoring,
indicators, MTF, leverage review, quotes, financial metadata, benchmark and
account/registration reads return fixed inputs. Name-provider lookup is also
stubbed: the first guarded replay found `lookup_yfinance_display_name` could
otherwise enter the Yahoo chart reader for synthetic tickers. This discovery
does not establish that lookup caused the production delay.

Public-demo app initialization is outside measurement. All network entry points
(socket, requests, urllib, curl_cffi) are blocked; 24 initialization attempts
were blocked, **zero attempts during replay**. No private portfolio fixtures,
credentials or live downloads are required or committed.

For each configuration: one uninstrumented reference, five timed repetitions,
then one separate sequential cProfile pass. Every full output row matches the
reference without float rounding; input frames/attributes remain unchanged.
Sequential and four-worker output SHA-256 are identical:
`fed6e90fd8a971532bf0bf2437739ae17062a635c3da4af636703efa0f0e5720`.
These checks validate the profiler, not a new scoring algorithm: frozen upstream
decisions are explicitly excluded from this residual-path benchmark.

Related tests: **29 passed in26.25s**, covering full decision snapshots, summary
replay and existing wait-diagnostic parity. No goldens regenerated. Production
app/core source has no diff; no runtime deployment or reboot is necessary.

## Measurement

Final benchmark processes ran sequentially after tests finished; an earlier
sample overlapping pytest was discarded. Windows `.venv311`, same local input.
Batch times include result serialization; stage sums exclude that serialization.

| 20-case batch | Five wall samples (seconds) | Median |
| --- | --- | ---: |
| Sequential | .465075, .431930, .426954, .423805, .427124 | **.427124s** |
| Four workers | .443530, .453138, .451034, .444091, .448505 | **.448505s** |

| Residual stage | Sequential mean sum, ms /20 cases | Share of worker elapsed | Four-worker mean sum, ms /20 |
| --- | ---: | ---: | ---: |
| Source-flow metrics + normalization | **256.379** | **59.46%** | 713.859 |
| Pattern detection | 141.065 | 32.72% | 480.381 |
| Decision workflow | 9.699 | 2.25% | 10.961 |
| MDD | 6.072 | 1.41% | 6.081 |
| Signal basis | 1.288 | .30% | 1.316 |
| Sideways state | 1.036 | .24% | 1.031 |
| Name normalization (provider fixed) | .432 | .10% | .447 |
| Pattern summary | .379 | .09% | .366 |
| Remaining glue, row formatting and fixture overhead | 14.809 | 3.43% | 460.237 |

Concurrent sums are **not wall time or independent CPU cost**. Four workers
did not speed up this local CPU/glue path (~5% slower median); summed remainder
grew from14.809ms to460.237ms/20 despite unchanged outputs and similar batch
wall time. Thread CPU sum for that remainder across100 calls was .0625s vs
.09375s, not the2.301s parallel elapsed sum. Windows short thread-CPU samples
are coarse; use this only as supporting evidence of scheduling/elapsed-time
inflation, not a precise attribution of every millisecond to the GIL.

Separate sequential cProfile (20 cases; profiler overhead included) found:

| Function | Calls | Inclusive seconds |
| --- | ---: | ---: |
| build_source_flow_context | 20 | .5618 |
| build_price_flow_row | 20 | .2918 |
| _normalize_today_flow_context_frame | 20 | .2310 |
| _compute_ticker_metrics (nested in price-flow row) | 20 | .1007 |
| detect_chart_pattern_candidates | 20 | .3063 |

The source-flow path creates a one-row DataFrame and invokes the generic
normalizer's repeated column assignment/row-apply operations. It is the largest
local residual component. Workflow/display assembly is not the primary target.
Nested profile times cannot be added or compared directly to unprofiled samples.

## What this does and does not establish

Production already measured pattern detection at1.994s/95 calls, separately from
the42.481s summary self sum. Fixed-input profiling identifies source-flow as the
dominant *local remaining calculation* and demonstrates parallel self-time
inflation. It cannot decompose all42.481s on Cloud or forecast a Cloud saving:
hardware, contention, prices/history lengths, network/cache state and upstream
work differ. No end-to-end speedup is claimed; last live result remains95.186s.

Next bounded task: optimize only the one-row source-flow normalization path,
reuse existing scalar rules and prove full row/column/value/null parity against
the generic DataFrame normalizer. Include absent/NaN/short-history inputs and
registration context. Do not change scoring/labels, source selection, TTL,
concurrency, chart detection or the radar's multi-row ranking logic. Benchmark
that local change before deciding whether any production benefit is material.

Reproduce (run separately, not alongside tests/other benchmarks):

```powershell
.venv311/Scripts/python.exe scripts/profile_summary_local.py --repeat 5 --workers 1 --output cache/summary_local_serial.json
.venv311/Scripts/python.exe scripts/profile_summary_local.py --repeat 5 --workers 4 --output cache/summary_local_parallel.json
.venv311/Scripts/python.exe -m pytest -q tests/test_decision_refactor_parity.py tests/test_summary_wait_diagnostics.py tests/test_fresh_quote_summary.py
```

Raw measurements/logs are in ignored `cache/summary_local_*`; only synthetic
aggregates and the reproducible script are committed.
