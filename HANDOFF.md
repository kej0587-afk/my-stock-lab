# Stock Lab Work Handoff

Updated: 2026-11-07 KST. Read before inspecting large source files or editing.
Check Git first; this document is not evidence that another computer has no newer edits.

## Resume Safely

1. Run `git status --short`, `git branch --show-current`, `git log -6 --oneline`
   and inspect upstream after `git fetch origin`. Preserve uncommitted/divergent work;
   never reset or force-pull it. Use `pull --ff-only` only on clean, compatible history.
2. Read AGENTS.md, this file and the latest linked measurement record below.
3. Use the installed environment. Home verification used
   `.venv311/Scripts/python.exe`; the other computer used `venv/Scripts/python.exe`.
4. Private exports/screenshots are outside Git and may not exist on another computer.
   Do not commit account data or secrets. Request login only if the UI needs it.

Repository: `https://github.com/kej0587-afk/my-stock-lab.git`, branch `main`.
Production: `https://3insky.streamlit.app/`.

## Current State

Latest bounded audit/fix: **`042c0bef`** pushed, following clean/equal `870c675a`.
Compared the preserved Today snapshot through board/portfolio display paths and
inspected authenticated Today, board, Precision and Portfolio screens. Found one
reproduced lifecycle defect: first precision visit to an already-exempt ETF rewrote
unchanged financial metadata and cleared all Today/board portfolio signal caches.
`mark_fin_score_not_applicable_db` now skips that identical write. Actual input
changes still save/invalidate. No scoring, thresholds, labels, amounts or gates changed.

Baseline decision gate: **1039 passed** (`decision_sbu30koo`, 92.117s).
Final decision gate: **1045 passed** (`decision_xuhsaf5x`, 88.248s), including six new
exemption regression cases. Private 10-holding export replay: no display/handoff
mismatch; it is not full OHLCV/precision recomputation. Cloud post-push verification
passed in a new browser session: board calculated at 00:03 KST, precision completed
at 00:04, then Portfolio retained all 10 connected results and showed the reviewed
ETF's final execution restriction. New precision export reports `042c0bef`,
`restart_required=false`, no stale modules. No Cloud reboot was needed.

Latest audit: [Held-view connection review](docs/maintenance/20261107_held_view_connection_review.md).
Private exports and the ignored replay script/result remain outside tracked files.
Do not change unrelated zero-quantity/context semantics or loosen gates based on
differences between earlier completed sessions and later live calculations.

## Previous Performance Work

Home checkout and upstream were clean/equal at `29d90955`. That state is preserved
on local branch `codex/home-baseline-20261106-29d90955`; no home edits were discarded.
Code commit **`ff2e8490`** is pushed. Use Git log for this later documentation commit.

Completed the previous Next Task Only: one measured Today Check bottleneck.
`stock_lab_core/ta_engine.py` now computes the existing MFI(14) with NumPy window
batches instead of a Python callback for each rolling window. Preserve finite-data
requirements, warmup/missing values, window sum order and exact reference output.
No indicator thresholds, decision labels, provider/TTL/observation policy, refresh
behavior, concurrency limits or other functions were refactored.

The TA module's import hash is included in existing precision build diagnostics.
Authenticated Cloud Precision Observatory export confirms `ff2e8490`, no stale
modules, and loaded/disk/committed TA hashes equal. No extra reboot was required.
Source SHA256: `c39ac3affbf312783e1c4ebc06ed38c9a85e130cacf0de2f4ac6de30167344ac`.

## Previous Performance Verification

- Before: selected `all` gate **1379 passed** (`all_um1dgosw`).
- After: `prices` **260 passed** (`prices_25lfbci9`); selected `all` **1453 passed**
  (`all_vm2rbj5n`). No failures/errors/skips or source edits during the gates.
  Evidence is under ignored `cache/refactor_checks/<run>/summary.json`.
- 74 exact MFI/reference cases, including missing live volume, infinity, zero-flow,
  short/long history, float32, timezone/duplicate dates and chunk boundaries.
- 30 complete synthetic indicator frames frozen before editing exactly match after.
  Existing summary/decision contracts pass. No golden files regenerated.
- Local fixed-input indicator benchmark median **0.884662s -> 0.646907s (-26.9%)**
  for 90 calls. This is not a Cloud full-calculation result or a full-suite pass.

## Measured Performance

Current comparison uses 95 calculated rows, 81 registered items, 12 automatic flow
candidates, four account selections, flow refresh/detail enabled. Standard refresh
resets quotes/frame caches; provider/financial caches can remain warm.

| Metric | Before | After |
| --- | --- | --- |
| Repeat full elapsed | 79.505 / 70.672 / 69.758s | 68.491 / 69.879 / 69.548 / 70.932s |
| Repeat elapsed mean | 73.312s | 69.712s |
| Entry mean, separately | 2.893s | 4.091s |
| Indicator active-wall mean | 17.759s | 16.266s |
| Stock-signals phase mean | 24.692s | 22.815s |
| First current-session/full-after-deploy load | 88.786s | 89.651s |

The repeat means are descriptive, **not a controlled causal speedup**. Leverage
cache rebuild counts were 0/5/0 before and 0/1/4/1 after; the last after run also
had two KR-history misses (otherwise zero). One after run matches the zero-rebuild
baseline condition; further runs crossed staggered TTLs. Do not attribute all
3.599s of the mean difference to MFI or claim a sub-minute result. First-load time
did not improve. Local fixed-input computational savings are stronger evidence
than these noisy Cloud elapsed comparisons. All attempts are in the linked record.

All saved full measurements completed with no instrumented function errors.
Do not treat summed concurrent work as wall time or function calls as HTTP counts.
Live prices can change between runs; exact output equality was tested on fixed inputs.

## Next Task Only

**Extract one display-data preparation helper from `render_image_theme_flow_section`.**

It is currently the largest top-level function in app.py (521 lines before this
audit). Recheck latest code first. Select one contiguous deterministic table/data
preparation block, freeze representative current outputs, and move only that block
to a pure helper with exact before/after equality. Run the relevant existing
report/decision contracts before and after; inspect the money-flow UI. Preserve
ordering, labels, ranking, scoring, dates, cache/provider behavior and account scope.
No additional performance changes, whole-function rewrites, threshold changes or
new features in this task. Do not claim speed gains from extraction alone.
Commit/push, then leave exactly one next task with verification/deployment limits.

## Evidence and Remaining Limits

- Latest: [Held-view connection review](docs/maintenance/20261107_held_view_connection_review.md).
- Performance: [MFI window optimization and measurements](docs/maintenance/20261106_mfi_window_review.md).
- Previous: [Yahoo chart connection measurements](docs/maintenance/20261106_yahoo_chart_connection_review.md).
- Workflow: [Bounded refactor review](docs/maintenance/20261106_bounded_refactor_review.md).
- Previous timing IDs are in the MFI record. Latest deployment/connection evidence
  is in the held-view review. Full JSON/ZIP/screenshots remain outside Git.
- The preceding connection optimization improved its quote segment but not full
  runtime (64.779s -> 66.336s on a different 96-row input). Do not blend those old
  measurements with today's 95-row runs or claim a sub-minute guarantee.
- Broader refactoring and investment-rule redesign remain separate future tasks.
