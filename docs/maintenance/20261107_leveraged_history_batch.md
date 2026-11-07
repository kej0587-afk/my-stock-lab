# Exact 6mo watch-history batching

## Scope and evidence

Started clean/equal on `b82d1b61`; no user edits discarded. Only the leveraged
watch history I/O path changes. Candidate/decision thresholds, labels, amounts,
OHLCV providers, adjustment options, period and TTL remain unchanged.

Previous complete Cloud run `2f717dae89a341ba8e3c2f08676d4bcd`: 95 rows,
91.089s overall, five watch profiles/38 rows, 17.129s watch-build active union.
That number includes quotes, history and waiting; it is not 17s of duplicate I/O.

Focused local public-profile probe (SOXL/RAM/BITX/QLD/NASDAQ100_2X_KR):
38 history invocations, 25 cache misses, 13 existing hits; 23 overseas individual
downloads plus two KR requests. Plain per-profile batching would raise actual
Yahoo chart HTTP requests from 23 to 29, so that prototype was not deployed.

## Implementation

The summary worker scope now shares successful exact 6mo frames across profiles.
A lock prevents simultaneous overlapping batches from fetching the same symbols.
Existing overseas batch loader/options are reused; missing/KR symbols use the
original loader. Errors are not memoized; copied frames expire with the summary
scope and never seed the general history cache. Quotes and all row calculations
are unchanged. Two row slots, summary workers and existing batch concurrency
settings are unchanged. Outside the summary (including precision visits), and
for forced refresh, the original route is retained. Old loaded modules safely
fall back without an ImportError.

Timers now distinguish quote, 6mo history, batch and batch-wait time. Exported
events distinguish shared-frame hits, batch-frame hits and original fallbacks.

## Verification

- Before: 130 focused row/decision contracts passed. After: 205 selected
  row/batch/decision/provenance/request-scope contracts passed; final batch-only
  suite 44 passed (two extra cache/outside-scope contracts added afterward).
- Prices gate: before **265 passed / 1 known failure**, after same 265 / 1.
  The remaining `test_investment_functions_are_unchanged` compares previously
  approved decision extractions to old `31513a51`. No golden rebasing.
- Existing watch-wrapper tests retain old-module fallback coverage. A new
  immutable `b82d1b61` comparison permits only explicit I/O wrapping in the two
  changed app functions; all their original calculation statements stay equal.
- Concurrent overlapping profiles request A/B/C once each; failed symbols
  retry, new scopes refetch, original forced-refresh thread/cache copying and
  clearing, empty/single/missing histories, exceptions and control flow covered.
- 38 captured live-frame rows exactly equal with fixed positive quote inputs.
  All 22 closed-session overseas Close series were exact. BTC's last in-progress
  Close moved between sequential downloads; with a fixed quote its return bases
  and output rows still match. This is not proof that later live snapshots match.
- Some Yahoo Adj Close values differ between batch/single responses. They are
  not consumed by watch rows and are never injected into other analysis caches.

Local final row-path timing: **7.567s -> 2.437s**. Actual curl chart HTTP count:
**23 -> 23** (one initial cookie request before). 23 individual Yahoo calls ->
four batch-library calls; 13 shared hits, 36 batch-frame hits, two KR fallbacks.
KR provider cache was warm in the after arm, and network/Yahoo internals are not
controlled; this is not a Cloud speedup percentage or a fully cold A/B result.

Private local evidence (ignored `cache/`): `watch_history_live_probe.json`,
`watch_history_frames.pkl`, `watch_history_live_row_parity.log`,
`watch_history_row_timings.json`, `watch_history_scoped_timings.log`,
`watch_history_final_tests.log`, `watch_batch_final_contracts.log`,
`watch_history_prices_final.log`. No account exports or secrets are committed.

## Deployment

Code **`a25bd5ff`** committed/pushed. One full Cloud calculation completed on
the new app build: **`bf29aab0bc784045aac20065be73d19e`**, ending
2026-11-07 10:48:13 KST, 81 registered / 95 calculated / 12 automatic candidates,
full flow refresh enabled. Elapsed **90.206s**, including entry **96.396s**;
zero instrumented errors. Prices/indicators/external active unions
55.131 / 21.839 / 22.155s (overlap; do not sum). KR reuse still works:
414 reader calls = 384 HTTP requests + 30 scope reuses.

**Deployment verification remains pending a Cloud Reboot.** The new app build
is confirmed, but all new watch events/timers are absent despite five watch
builds/38 rows. Even the new quote/history timers in the original row function
are absent: the old imported module is still executing. Three Yahoo batch calls
are the existing 1y/10y/3mo preloads, not the new 6mo path. Watch-build active
union 11.373s is therefore **not evidence of this optimization's speedup**.
The report build's `stale_modules=[]` only covers its tracked report sources and
does not prove the watch module was refreshed. Safe old-module fallback worked.

The accessible app menu offers Print/Record screen, not Reboot. Asked the user
to Reboot 3insky in Streamlit Cloud, then repeat one complete calculation and
verify the new events. No extra source edits or cache-policy changes to force it.

Private Downloads evidence:
`today_queue_bf29aab0bc784045aac20065be73d19e.json`,
`stock_lab_review_export_20261107_1048.zip`,
`stock_lab_watch_batch_pending_20261107.png`.
The upper completed-export button initially returned the previous measurement;
the **"이번에 완료한 계산 시간 진단 JSON"** button returned the matching ID.
Always check file/UI ID rather than filename freshness alone. The review ZIP
contains CSV tables, not watch-module hashes; do not claim hash validation from it.
