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

Latest bounded refactor: **`fd0fe52e`**, pushed from clean/equal `c623569b`.
Extracted only the final safety/sizing orchestration into
`stock_lab_core/decision_finalization.py::finalize_decision_sizing`.
`calc_scores_and_decision`: 480 -> 467 lines. Same explicit policy dependencies,
same call order and five outputs restored to original locals before unchanged
`build_decision_result(locals())`. No threshold/label/amount/provider/cache changes.
New module records its loaded source in existing precision provenance.

Verification: selected decision gate **1,045 passed before** (88.583s),
**1,132 passed after** (93.431s, includes 87 new tests). Forty full-result cases
were frozen before editing the caller and all match; unrounded original/current
outputs, policy calls, failure propagation and input nonmutation also match.
Focused follow-up/priority/import checks passed (215 tests before the final
seven edge/provenance additions). No golden files regenerated.
This is a structural extraction, not a measured application speed improvement.

Post-push authenticated GOOGL precision calculation and review ZIP succeeded.
New helper loaded/disk/local hashes match; `restart_required=false` and
`stale_modules=[]`. UI judgement/hold table rendered without traceback.
No account/watchlist edits; exports and screenshot remain outside Git.

Latest record: [Decision finalization extraction](docs/maintenance/20261107_decision_finalization_extraction.md).

## Preserved History

- `042c0bef`: idempotent ETF exemption writes prevent clearing saved signals on
  precision visits. Decision gate 1045 passed; Cloud retained all 10 connected
  results after the visit. See the connection review below for exact evidence.
- `ff2e8490`: exact-parity MFI window optimization. Selected all gate 1453 passed;
  fixed-input indicator benchmark improved 26.9%. Cloud repeat times were noisy
  (roughly 70s), first-load time did not improve; no sub-minute guarantee.
  Full timing/cache/deployment limits are in the MFI record below.
- Home baseline branch `codex/home-baseline-20261106-29d90955` remains local.
  No user edits were discarded. Private exports/screenshots stay outside Git.

## Next Task Only

**Extract only SMC context assembly from `calc_scores_and_decision`.**

It remains the largest top-level app function at 467 lines. Recheck current
code; isolate from `smc_structure_labels = build_smc_structure_labels(...)`
through the `smc_insight = build_smc_insight(...)` assignment, into one pure helper
with explicit inputs/dependencies. Return the existing structure/event/liquidity/
FVG/PD/action/insight values to the same locals; preserve result assembly.
Do not change detection algorithms, drawing, thresholds, labels, providers or
cache policy. Freeze existing outputs, compare unrounded results, input
nonmutation and exact dependency call order. Run the decision gate before/after.
Do not regenerate goldens. Commit/push, verify deployment and leave one next task.

## Evidence and Remaining Limits

- Latest: [Decision finalization extraction](docs/maintenance/20261107_decision_finalization_extraction.md).
- Previous: [Theme stock display extraction](docs/maintenance/20261107_theme_stock_display_extraction.md).
- Previous: [Theme group display extraction](docs/maintenance/20261107_theme_group_display_extraction.md).
- Connection: [Held-view connection review](docs/maintenance/20261107_held_view_connection_review.md).
- Performance: [MFI window optimization and measurements](docs/maintenance/20261106_mfi_window_review.md).
- Previous: [Yahoo chart connection measurements](docs/maintenance/20261106_yahoo_chart_connection_review.md).
- Workflow: [Bounded refactor review](docs/maintenance/20261106_bounded_refactor_review.md).
- Previous timing IDs are in the MFI record. Connection evidence is in the held-view
  review; latest refactor verification is in the theme extraction record.
  Full JSON/ZIP/screenshots remain outside Git.
- The preceding connection optimization improved its quote segment but not full
  runtime (64.779s -> 66.336s on a different 96-row input). Do not blend those old
  measurements with today's 95-row runs or claim a sub-minute guarantee.
- Broader refactoring and investment-rule redesign remain separate future tasks.
