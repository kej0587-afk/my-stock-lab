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

Pending deployment and matching completed-run exports. Previous measurement
`e36d58ac51f7463b9d86820aa3c4f8f9` was 98.540s on 95 rows, but hours earlier;
do not treat it as a controlled before/after test. Record a fresh pre-deployment
run and the deployed result, actual scope reuse, cache state and limitations.
