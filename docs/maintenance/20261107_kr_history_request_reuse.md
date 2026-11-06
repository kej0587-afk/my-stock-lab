# Exact KR history request reuse

## Change

One Today Check execution owns a context-local successful-response memo. The
existing reader first resolves its original ticker, start/end dates and count;
only identical endpoint/reader/code/date/count/timeframe/adjustment keys share a
response. A per-key lock joins duplicate concurrent requests without serializing
different instruments. No range slicing or implicit UTC/KST date correction.

Successes are copied, never shared with callers; empty/failed responses are not
memoized. Existing 900s success retention, 15s failure cache and provider circuit
breaker remain. Memo expiry is also bounded by 900s; public cache clear changes
the generation, and the memo is discarded at run exit. Reused alias results use
`UncachedValue` so they cannot start a new persistent-cache lifetime. No scoring,
labels, thresholds, request scope or worker-count changes.

Aggregate `kr_history_scope.*` counters expose unique/repeat/reused requests and
default/explicit-start call paths, without logging ticker or account identities.
They count reader cache misses, not all outer cache hits. The Today Check wrapper
falls back to the original path with a warning if Cloud retains the old module;
this prevents an ImportError but is not evidence of optimization being loaded.

## Fixed-input verification

- Immutable original reader: Git `24244c3e`. Eight calls include provider ticker
  aliases and equivalent explicit/default dates. Original transport sent eight
  requests; new transport sends five. The five requests exactly equal the
  original distinct URL/parameter sets. All frames, indices, dtypes and attrs
  match exactly. Different 3mo/10y/UTC-date ranges remain separate.
- Nine concurrent alias calls plus one nested-scope read issue one request;
  caller mutation does not affect subsequent readers. Separate runs/readers,
  midnight, expiry and explicit clear retain distinct retrievals.
- Provider failure/cooldown and alias-cache-lifetime tests pass.
- All app function ASTs except the scope wrapper match `24244c3e`; existing
  decision golden snapshots also pass. No goldens were regenerated.
- Focused verification: 77 passed (24.42s), including existing KR transport,
  connection, money-flow reuse, Today Check session and decision golden tests.
- Prices gate before: 259 passed / 1 failed, 44.551s; after: 265 passed / the
  same 1 failed, 46.904s. Pre-existing failure:
  `test_today_quote_performance::test_investment_functions_are_unchanged` still
  compares `calc_scores_and_decision` structurally with `31513a51`, before the
  approved helper extractions. It was not loosened or rebased to pass this task.
  This is a known blocked aggregate gate, not an all-green test-suite claim.
  New exact-request tests are now part of the prices gate.
- Offline timing (five repeats, fixed XML, simulated 20ms/request, no network):
  median **0.2110s -> 0.1333s**, 8 -> 5 requests. This isolates the redundant
  transport/parse work and is not a production latency forecast.

Private local evidence: `cache/kr_history_scope_benchmark.json`,
`cache/refactor_checks/prices_ql7651iy`, `prices_x334wje4` (ignored, not Git).

## Production verification

Code **`661431f9`** pushed and executed on production without a reboot. Both
completed JSON IDs matched the UI, and build IDs matched the respective code.
No tracked stale report modules or restart warning. `enabled_v1=1` and 277 reader
lookups prove the new request path actually executed (not just new disk files).

| Measurement | Before | After |
| --- | --- | --- |
| ID | `139e8dee026d4f68b479027bfa872c80` | `cdff8f9b4f4445c8b0572bda598272d1` |
| Build | `24244c3e` | `661431f9` |
| Start, 2026-11-07 KST | 08:45:09 | 08:48:31 |
| Full Today Check wall | 89.438s | 70.245s |
| Script including entry | 94.137s | 72.897s |
| Registered / calculated / auto-flow | 81 / 95 / 12 | 81 / 95 / 12 |
| Prices active union | 49.904s | 39.526s |
| Indicators active union | 17.911s | 18.259s |
| External-data active union | 24.321s | 9.461s |
| KR HTTP requests | 416 | 277 |
| KR HTTP active union | 29.750s | 14.976s |
| New scope unique / repeat / reuse | unavailable | 277 / 0 / 0 |

**The 19.193s reduction is NOT demonstrated savings from this optimization.**
Both use normal refresh (not fully cold); underlying provider caches survived
between runs. All after-run reader calls had default starts; explicit-period
providers were served upstream and never entered the new memo. Thus the 139
fewer KR requests are not 139 new-scope hits. Before also had one recovered
`flow_overseas_fallback` ConnectTimeout; after had zero instrumented errors.
Category unions overlap and must not be added. Account/filter settings stayed
unchanged, but live prices/automatic candidate identities were not frozen.

The existing menu's chart refresh only clears outer price caches, not the KR
provider cache; the authenticated viewer's Streamlit menu had no global-clear
control. No broader cache reset or account edits were performed. Do not run
repeated warm calculations to manufacture a speedup. The older 98.540s sample
`e36d58ac51f7463b9d86820aa3c4f8f9` is not the adjacent baseline.

Private completed profiles and screenshot in `C:/Users/82amf/Downloads/`:
`today_queue_139e8dee026d4f68b479027bfa872c80.json`,
`today_queue_cdff8f9b4f4445c8b0572bda598272d1.json`,
`stock_lab_kr_history_reuse_20261107.jpg`. Profile SHA-256 respectively:
`07bd6c2f065959b1d0f027ea4014bb442fbf84291c0d700e339d714365792085`,
`ffba9363ee4982ba31af5feb2fbd6b32d1f543aa15ad24eff5337e0c463a0246`.

## Actual identical-request check (local network, not Cloud throughput)

To separate working reuse from the warm production path, replayed three real
Naver requests via the immutable original reader and the new reader: `005930.KS`
with default start, then `005930` and `005930.ks` with the identical explicit
one-year start. Both readers used the same 2026-11-07 KST end date. No private
holdings were sent; this is a public-symbol transport check.

- Original: three HTTP requests/responses, **1.1247s**.
- New: one unique HTTP request/response, two proven scope reuses, **0.3524s**.
- All three returned **244 rows**; exact frame/index/dtype/attrs comparisons pass.
- Evidence: ignored `cache/kr_history_scope_live.json`. This single sequential
  network pair also has connection/provider variability; the request-count and
  data-equivalence results are stronger evidence than its elapsed-time ratio.

## Next bounded task and limits

Measure one completed production run after the KR provider TTL has expired,
before other price/flow screens warm it. Keep the same settings and record all
scope counters, including zero repeats. Do not add more optimization until the
real cold-path duplication is established. If it is zero, document that the safe
alias memo is not the current bottleneck; do not widen ranges or TTL to gain hits.
The pre-existing structural regression-gate failure remains separately recorded;
no test baseline or investment rule was changed to conceal it.
