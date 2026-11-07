# Single-row source-flow normalization

2026-11-07 KST. Base `125748fc`; clean/equal origin/main before editing.

## Change

`build_source_flow_context` uses `_normalize_source_flow_row` for the single
price-derived row instead of constructing a DataFrame and repeatedly applying
row functions/assigning columns. It still calls the existing scalar helpers in
the same dependency order; field insertion order and present-but-null fields
are retained. Final Series scalar boxing matches the original `.iloc[0].to_dict`.
Insufficient histories retain the original bypass; invalid filtered ticker rows
retain IndexError behavior. Broad-context exceptions retain the sector fallback.

The multi-row `_normalize_today_flow_context_frame` is byte-for-AST unchanged.
No ranking, chart detection, decision thresholds/text, provider routing, cache,
concurrency, auth or account state changed. The helper lives in app.py alongside
the existing normalizer, so this change adds no cross-module import dependency.

## Parity and scope checks

- Focused source-flow tests: **156 passed in19.73s**. Includes 120 randomized
  missing/existing/null-field cases across held/watch/unregistered states,
  empty/short/20/30/260/365-bar histories with/without volume, actual source
  context, exception fallback and registration call parity.
- New immutable `125748fc` AST contract verifies every existing app function
  unchanged except the single source-context call replacement. Generic radar
  normalization is protected by the same contract.
- Two older full-app AST guards delegate only this wrapper/helper to the new
  parity tests; no golden baseline was regenerated or scoring guard removed.
- The decision gate now includes source-flow tests. Before: **1,171 passed,
  zero failures/errors/skips,95.294s**. After: **1,327 passed, zero failures/
  errors/skips,100.760s**. Adjacent summary/observatory/history/timing AST checks:
  **32 passed in28.32s**. Gate time is test runtime, not app performance.

## Sequential fixed-input benchmark

Same existing seeded20 scenarios, five repeats, external providers fixed;
benchmark processes run separately from tests. The complete output hash remains
identical before/after:
`fed6e90fd8a971532bf0bf2437739ae17062a635c3da4af636703efa0f0e5720`.
Input frames/attributes unchanged; zero replay network attempts. Public-demo
initialization network attempts are blocked and outside timing.
Final four-worker replay: five repeats, median**.332098s**, same full output
hash as original sequential and optimized sequential runs; input preservation
and zero replay-network assertions passed. Benchmark ran after tests completed.

| Local residual calculation | Before | After |
| --- | ---: | ---: |
| Median20-case batch wall time | .426508s | **.321040s** |
| Source-flow mean/20 cases | .251149s | **.144432s** |
| Pattern detection mean/20 cases | .138222s | .139650s |
| Decision workflow mean/20 cases | .009519s | .009644s |

Whole residual batch reduction **24.73%**, source-flow reduction **42.49%**.
Batch samples before: .424052,.422280,.426508,.429609,.429495s;
after: .320860,.324535,.319602,.321072,.321040s.

Separate cProfile (includes profiler overhead): normalization20 calls fell
from.2226s to.0119s; unchanged `build_price_flow_row` remained.2889/.2888s.
This attributes the local improvement to normalization, not a scoring change.
These are NOT full Today Check, Cloud speed, cold-cache or investment tests.
Last measured production full run remains95.186s; do not scale it by24.73%.

Evidence in ignored cache: `source_flow_before.json`, `source_flow_after.json`,
`source_flow_focus.log`, `source_flow_gate_before.log`, `source_flow_gate_after.log`,
`source_flow_adjacent.log`. No private account data committed.

## Deployment / next step

Verified code and this record are committed/pushed together; no live calculation
was performed in this bounded local optimization task. Next: one complete production Today
Check, verifying the current app fingerprint and the resulting performance file.
Compare like-for-like scope and report cache/network limits. Do not infer a live
speedup from this local benchmark or change more rules to meet a timing target.
