# KR history reuse after provider-cache expiry

## Run and cache evidence

- One authenticated production Today Check, unchanged filters, all existing
  accounts, full flow refresh enabled. No preliminary screen reload/navigation,
  manual cache purge, source change or rule change.
- Build `5b5d81f6ef9f5e2ca20d5e5743973fef30354459`; application change remains
  `661431f9`. Local/upstream clean and equal before work.
- ID **`2f717dae89a341ba8e3c2f08676d4bcd`**; 2026-11-07
  **09:37:49–09:39:20 KST**. Completed full calculation, not reused or partial.
- Last visible full result finished 08:49:41 KST, about 48 minutes earlier,
  exceeding the KR provider's 900s TTL. The existing tab was rebound/read without
  reloading; the first application action was the calculation button.
- Provider-cache lookups 427, misses 414, reuse 13: 96.96% entered the reader.
  This supports the expired-provider measurement. Aggregate counters cannot
  prove every shared-cache entry was cold at entry or distinguish all within-run
  outer-cache hits from other sessions' cache activity.
- This is **not a fully cold application benchmark**: policy remains
  `standard_refresh_not_fully_cold`, with financial/analyst caches potentially
  warm. Only normal quote/outer-history refresh was used.
- Registered 81, calculated 95, automatic flow candidates 12. The same settings
  and counts as earlier runs; live data/candidate identities were not frozen.

## Actual reuse: confirmed

| Layer / counter | Count |
| --- | ---: |
| KR provider-cache lookups | 427 |
| Existing cache reuse | 13 |
| Reader / new-scope lookups | 414 |
| Default-start / explicit-start calls | 278 / 136 |
| Unique resolved requests | 384 |
| Repeat requests / scope reuse | **30 / 30** |
| HTTP requests / responses | **384 / 384** |
| Reused results bypassing new persistent TTL | 30 |

Accounting checks: `427 = 13 + 414`, `414 = 384 + 30`, and scope repeat/reuse
equals cache bypass. Thus **30 actual duplicate requests were avoided**, 7.246%
of reader calls that would otherwise reach transport in this successful run.
No changed ranges or TTLs were used to produce hits. No request/parse failure or
instrumented error was recorded. These counters do not establish data accuracy
or freshness beyond the existing data checks.

## Timing and bottleneck

Full Today Check **91.089s**, before-entry **3.618s**, script **94.807s**.

| Category | Exclusive worker sum (s) | Active union (s) |
| --- | ---: | ---: |
| Prices / waits | 270.679 | **56.841** |
| Indicators / patterns | 41.713 | 19.137 |
| External data / flow | 44.517 | 28.666 |
| Decision / assembly | 18.331 | 12.853 |

Both concurrency and nesting matter: category unions still overlap across
categories and must not be summed. The union of instrumented non-phase work is
65.817s, concurrent excess 309.422s, uncovered category wall 25.271s. Uncovered
time includes phase-only/UI/bookkeeping work; it is not demonstrated idle time.

| Path | Calls | Inclusive sum (s) | Active union (s) |
| --- | ---: | ---: | ---: |
| KR history HTTP | 384 | 107.666 | 30.205 |
| Whole summary | 1 | 41.406 | 41.406 |
| Stock signals | 1 | 25.239 | 25.239 |
| Flow refresh | 1 | 21.332 | 21.332 |
| Leveraged watch rows | 5 | 25.195 | **17.129** |
| Each watch row | 38 | 33.306 | 17.085 |
| Money-flow download wrapper | 26 | 22.066 | 20.706 |
| Price batch wrapper | 3 | 14.749 | 14.749 |
| Analyst enrichment phase | 1 | 1.710 | 1.710 |

Prices remain the dominant measured category. Function call counts are not HTTP
counts: 736 `load_price_df` invocations include 540 prefetched and 12 memo hits;
yfinance reports 40 individual and three batch library calls, not its internal
HTTP total. Yahoo chart request/response counters are 73/73; Naver bulk 3/3.

The previous warm run took 70.245s and made zero new-scope reuses. Today's longer
91.089s does not demonstrate a regression: cache conditions and provider latency
differ. Nor does avoiding 30 requests establish a particular whole-run speedup;
parallel critical-path savings cannot be recovered from these aggregate sums.
The earlier pre-change 89.438s run is also not a fixed-input cold A/B baseline.

## Focused source review and next task

`leveraged_watch.py::_build_watch_row` loads a live quote and an exact **6mo**
history for each watch entry. `app.py::build_leveraged_precision_watch_rows`
passes `load_price_df` and preserves forced-refresh thread behavior. Five profile
builds cover 38 rows; their 17.129s union is material, but this export does not
attribute individual history requests to those rows or prove all are duplicated.

Next bounded task: profile exact 6mo history I/O in this leveraged-watch path,
then use existing batch/prefetch infrastructure for the required exact-period
requests if demonstrated useful. Keep live quotes/forced-refresh behavior,
profile order, source/adjustment semantics, missing-data fallback, and judgments
identical. Do not substitute slices of 1y/10y, widen TTL, change concurrency, or
add other optimizations. Verify fixed-response rows and full decision outputs,
actual requests and comparable production timing. Retain the documented
pre-existing AST-freeze test failure until independently repaired; do not rebase
goldens merely to turn a gate green.

## Verification, artifacts and deployment

Verified completed flags, UI/export ID, Git build, local app hash, no tracked
stale modules, counter equations and zero instrumented errors. No application
code changed, so prior parity tests remain applicable; no repeated regression
suite or new investment-result claim. Documentation diff checks pass.

Private evidence outside Git in `C:/Users/82amf/Downloads/`:
`today_queue_2f717dae89a341ba8e3c2f08676d4bcd.json` and
`stock_lab_kr_history_expired_20261107.jpg`.
JSON SHA-256: `808db0bf03656d93c12b5cd4c4ce56918bf1bb78848b3b6157beaee08e582c7a`.
Commit/push this record and handoff only; no application reboot required.
