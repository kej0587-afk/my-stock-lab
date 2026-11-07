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

## Production verification completed

2026-11-07 **14:34:35–14:35:59 KST**, build **`d5dc6c02`**, completed ID
**`d7330531d2d046b98cf29e2878ee7c3b`**. Same four accounts,81 registered,
95 calculated,12 automatic candidates and full-flow refresh checked; flow detail
initially collapsed as in the reference run. UI/export IDs match. Loaded/disk/
local normalized app SHA-256 all match:
`8d98a9a109134866ac028ed5fda632d7e72a2fb0c3513331d0c0aca10f43fbcc`.
New helper is in this app source, so no separate helper-module reboot is needed.
No stale tracked modules or instrumented exceptions. Full run, not reused/partial.

| Wall/active seconds | Prior pre-change run | New full run |
| --- | ---: | ---: |
| Today Check wall | 95.186 | **83.929** |
| Script including entry | 101.073 | 92.993 |
| Summary phase | 44.221 | 39.727 |
| Stock signals phase | 28.828 | 26.391 |
| Analyst phase | 8.900 | 1.862 |
| Flow refresh | 19.334 | 20.155 |
| Prices active union | 55.496 | 54.497 |
| Indicators active union | 22.161 | 17.993 |
| External-data active union | 32.884 | 21.495 |

Category active unions overlap. Analyst cache73 lookups now **70 reuse/3 misses**
(three unavailable), versus73 misses before. Cache state and network conditions
are not controlled; **11.257s elapsed improvement is not attributable entirely
to the patch**. Summary self sum42.481 ->4.363s also includes scheduling/cache
differences. No per-source-flow live span exists to isolate its saving.
KR history still384 actual HTTP requests plus30 exact-request reuses; its active
union28.051s vs27.244s. Thus price I/O remains substantial, and no sub-minute
guarantee or reason to change rate-limit protection is established.

This verification turn changed documentation only; prior1327 gate/32 adjacent
passes remain applicable. Task complete through push and live verification.
Next bounded work returns to behavior-preserving refactoring: split only the
theme-selection/description UI block of the452-line theme-flow renderer while
preserving widget keys, order, lazy-run behavior and outputs. Later checkpoints
are cross-view integration and a final regression/deployment check; not additional
unbounded micro-optimizations or investment-rule changes.

Private evidence: `C:/Users/82amf/Downloads/today_queue_d7330531d2d046b98cf29e2878ee7c3b.json`
and `stock_lab_source_flow_verified_20261107.png`.
JSON SHA-256: `9623416c6539472349fa662e2b1b81afc6c2b24d885fefbbe6d351a5358870b2`.
