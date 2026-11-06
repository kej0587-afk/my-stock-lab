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

Latest bounded refactor: **`20ff2662`** pushed from clean/equal `612ab8c4`.
Extracted only the subtheme summary table/CSV preparation into
`stock_lab_core/theme_flow_view.py::prepare_theme_group_display`.
`render_image_theme_flow_section` decreased from 521 to 489 lines. Ranking,
classification, labels, charts, provider/TTL/lazy behavior and account scope did
not change. This is structural work, not a measured speed improvement.

Verification: report gate **180 passed before and after** (`report_dlh7p5lh`,
`report_ous2lzkx`); existing money-flow UI/renderer tests **12 passed before**;
with seven new exact-output/CSV/wiring tests **19 passed after**. Six original
outputs frozen before extraction also match. No golden files regenerated.
The reference renderer is retained at Git commit `612ab8c4`.

Post-push authenticated UI check passed after reload: theme source screen at
00:19 KST displayed 46/46 instruments and the 11-row subtheme table/charts without
traceback. Browser CSV-download completion was not confirmed; offline CSV parity
passed. No runtime module-hash export was collected for the new display helper.
Latest record: [Theme group display extraction](docs/maintenance/20261107_theme_group_display_extraction.md).

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

**Extract only the stock-detail table formatting from `render_image_theme_flow_section`.**

The renderer is still 489 lines and currently the largest top-level app function.
Recheck current code and isolate the block from `show_stock = stock_view.copy()`
through the `_it_show_cols` projection, using the new theme-flow view module.
Preserve currency/percent formatting, badges, column order and missing-column
handling. Do not move or alter classification, deduplication, ranking, captions,
charts, selection/watchlist actions, provider calls or cache policy in this task.
Freeze old outputs, test exact DataFrame/CSV parity and input nonmutation, run
relevant existing contracts before/after and inspect the authenticated theme UI.
Commit/push and leave one bounded next task. Do not claim speed gains without
measurements or mix investment-rule changes into the extraction.

## Evidence and Remaining Limits

- Latest: [Theme group display extraction](docs/maintenance/20261107_theme_group_display_extraction.md).
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
