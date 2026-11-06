# Today Check: bounded MFI window optimization

Date: 2026-11-06 KST. Code commit: `ff2e8490`.

## Preservation and scope

- Home checkout and upstream were clean and equal at `29d90955`. A local
  preservation branch, `codex/home-baseline-20261106-29d90955`, retains that state.
- Followed HANDOFF's single task: reduce one measured Today Check bottleneck.
  No news changes, threshold changes, provider/TTL changes, or extra concurrency.
- `build_indicators` repeatedly called ta 0.11.0's MFI rolling Python callbacks.
  Two warm runs spent 17.843s / 17.267s active wall in 430 indicator invocations.
  Local profiling assigned 0.782s of 2.530s instrumented indicator work to MFI.
- Replace only these MFI window reductions with bounded NumPy window batches.
  Preserve the 14-bar finite-data requirement, window sum order, warmup NaNs,
  zero-flow behavior, float32-to-float64 rolling behavior, index and input data.
  This is not a new indicator or a rolling-sum approximation.
- Register the TA module's actual import hash in the existing precision build
  diagnostics so a disk-only deployment cannot masquerade as a loaded update.

## Correctness and local timing

- Before changes: selected `all` gate **1379 passed**,
  `cache/refactor_checks/all_um1dgosw/summary.json`.
- Added reference comparisons passed against the old implementation first.
  Final 74 cases cover ta-library exact equality, missing price/volume, infinity,
  zero volume, monotone/flat prices, short histories, float32, timezone/duplicate
  dates, and 4096-window chunk boundaries.
- Froze 30 complete synthetic indicator frames before editing; all columns are
  exactly equal after editing (`check_exact=True`). No golden files regenerated.
- After: `prices` **260 passed** (`prices_25lfbci9`), selected `all` **1453 passed**
  (`all_vm2rbj5n`), no errors/failures/skips or source edits during either gate.
  These gates include full-summary/decision contracts; they are not the full test suite.
- Home Python: `.venv311/Scripts/python.exe`.
- Fixed local benchmark, 90 indicator calls per run, five runs per version:
  median **0.884662s -> 0.646907s (-26.9%)**. This is not a Cloud full-run result.
  Frozen inputs/timings remain in ignored `cache/mfi_parity_20261106/`.

## Live baseline

Authenticated Cloud UI, four selected accounts, 95 calculated rows, 81 registered
items, 12 automatic flow candidates; flow refresh and flow detail enabled for
repeat runs. Standard refresh resets quote/frame caches; provider/financial caches
can remain warm. Entry time is outside Today Check elapsed time.

| Run | Full elapsed | Entry | Indicator calls | Indicator work / active wall | Yahoo chart requests | KR history requests |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| First current-session load | 88.786s | 4.690s | 429 | 20.523s / 14.160s | 69 | 405 |
| Warm A | 79.505s | 2.910s | 430 | 31.180s / 17.843s | 56 | 0 |
| Warm B, leverage-cache expiry | 70.672s | 3.324s | 430 | 29.306s / 18.165s | 68 | 0 |
| Warm C | 69.758s | 2.446s | 430 | 29.157s / 17.267s | 56 | 0 |

All completed with no instrumented function errors. Baseline loaded build was
`29d90955`, with no reported stale modules. A/C had zero leverage-watch rebuilds;
B rebuilt five profiles. Do not silently blend cache-expiry and first-load cases.
A/C have 153/149 history-cache
lookups, 152/148 misses, one reuse each, three batch-cache misses each, and 277
KR-history cache reuses each. Function calls are not request counts; yfinance
download invocations are not individual HTTP requests either.

Baseline IDs, in table order:
`e0a7e82a04e7495f9c7b1679833824e2`, `ce30caf5c727457f9c0a09ada01712a8`,
`56b7c0dc828b47aabb9dfd2735a49f3e`, `1479097a17f644dfa75ba488aeeb99c2`.
Files are `today_queue_<id>.json` in local Downloads, intentionally outside Git.
The UI download control needs a rerender after completion to expose the latest
complete trace; partial/rerender traces were not substituted for calculations.

## Deployment and after measurements

Code pushed and authenticated Precision Observatory rendered normally. The
downloaded `precision_review_GOOGL (26).zip` identifies `ff2e8490`, no stale
modules, and TA loaded/disk/committed-blob SHA256 all equal to
`c39ac3affbf312783e1c4ebc06ed38c9a85e130cacf0de2f4ac6de30167344ac`.
No extra Cloud reboot was needed. This private export remains outside Git.

| After run | Full elapsed | Entry | Indicator calls | Indicator work / active wall | Yahoo chart requests | KR history requests |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| First full run after deployment | 89.651s | 3.819s | 432 | 28.662s / 16.405s | 67 | 405 |
| Warm A | 68.491s | 3.751s | 432 | 31.381s / 17.148s | 55 | 0 |
| Warm B, one leverage-cache expiry | 69.879s | 4.332s | 433 | 21.845s / 13.542s | 57 | 0 |
| Warm C, four leverage-cache expiries | 69.548s | 3.836s | 433 | 30.867s / 17.987s | 65 | 0 |
| Warm D, one leverage-cache expiry and two KR-history misses | 70.932s | 4.444s | 433 | 29.495s / 16.387s | 57 | 2 |

First-after ID: `00ab7b54362e4d20b2cb427f4c7f0d54`. No instrumented errors.
Financial/quote warmup and live prices differ between first loads; they are not
a controlled cold-cache speed comparison. Warm IDs:
`8796f32ae4364ea4994196a32f3247cf`, `bf0a4aeffc734ee9bc7e4504094eddaf`,
`860bc2b1adde4ed39cea5c73f807fe9b`, `7c59e8ad8b634c719abbf88f607e3204`.
All four are completed full calculations, with the same 95-row input/options and
code `ff2e8490`; no instrumented function errors. Warm B/C/D rebuilt one/four/one
leverage profiles. D additionally made two KR-history HTTP requests. These are
staggered existing TTL expiries, not extra concurrency or a new cache policy.

Warm A history-cache lookups/misses/reuses were 149/148/1, B 157/156/1,
C 169/167/2 and D 157/156/1. Each had three batch-cache misses and 277 KR-history
cache reuses. Actual chart requests are in the table; invocations are not HTTP counts.

## Interpretation and completion

| Descriptive repeat-run mean | Before (3 runs) | After (4 runs) |
| --- | ---: | ---: |
| Today Check elapsed | 73.312s | 69.712s |
| Entry time, separately | 2.893s | 4.091s |
| Stock signals phase | 24.692s | 22.815s |
| Indicator active wall | 17.759s | 16.266s |
| Indicator summed work | 29.881s | 28.397s |
| Flow refresh | 11.540s | 9.349s |
| History batch active wall | 11.755s | 11.672s |

The mean full elapsed is 3.599s lower (4.9%), but this is **not a controlled
causal speedup estimate**. After A has the same zero-leverage-rebuild / zero-KR-HTTP
condition as before A/C; further runs crossed different 300-second leverage TTLs,
so a second identical-cache after sample was not achieved. All attempts are shown,
including the slower extra run. Live-quote indicator rebuild counts also varied.
Network/Cloud CPU variation and the cheaper flow refresh explain some of the total
difference. Do not subtract overlapping work or claim the entire gain came from MFI.

Fixed-input local evidence supports the MFI computational improvement; production
proves successful loading, complete calculations, and no observed regression errors.
First-load elapsed did not improve (88.786s -> 89.651s); no sub-minute guarantee.
No further scope was added to chase that target or staggered cache expiries.

Authenticated UI screenshot: `stock_lab_mfi_verified_20261106.jpg` in Downloads,
showing the completed full 70.9s measurement. Private screenshots/exports are not
committed. HANDOFF now assigns exactly one next task: held-instrument cross-view
consistency using the same snapshot. Further refactoring is separate.
