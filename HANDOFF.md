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

Latest bounded refactor: **`7f7e2e4a`** pushed from clean/equal `340fe067`.
Extracted only stock-detail table/CSV formatting into
`stock_lab_core/theme_flow_view.py::prepare_theme_stock_display`.
`render_image_theme_flow_section` decreased from 489 to 452 lines. Classification,
ranking, labels, charts, provider/TTL/lazy behavior and account scope are unchanged.
A missing-symbol reload guard applies only to the stateless formatting module,
preventing retained old Cloud modules from failing the new import.
This is structural work, not a measured speed improvement.

Verification: report gate **180 passed before and after** (`report_u5_t2zfv`,
`report__8qpu20t`); existing flow tests **19 passed before**, **40 passed after**.
All 18 pre-edit frozen stock tables match; exact DataFrame/CSV parity, input
nonmutation, renderer wiring and old-module import recovery passed. No golden
files regenerated. Stock renderer reference: Git `340fe067`; earlier group
reference `612ab8c4` remains intact.

Post-push authenticated production reload/analysis displayed 46/46 instruments,
charts and the stock table with KRW/USD prices, percentages and state badges,
without traceback. Offline CSV parity passed; browser CSV completion and helper
runtime module hash were not collected. Screenshot is private/outside Git.

Latest record: [Theme stock display extraction](docs/maintenance/20261107_theme_stock_display_extraction.md).

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

**Extract only the final safety/sizing orchestration from `calc_scores_and_decision`.**

After this extraction it is the largest top-level app function (480 lines).
Recheck current code; isolate its final block from `_apply_safety_state_override`
through `_compute_sizing_hint`, leaving `build_decision_result(locals())` in place.
Use explicit inputs/dependencies and return the same decision_outcome, dec, col,
buy_amount and sizing_hint, preserving the locals consumed by result assembly.
Do not alter ordering, thresholds, labels, ETF/holding exceptions, data-error
zero sizing, providers or cache policy. Freeze representative old outputs and
use the existing decision contracts before/after; do not regenerate goldens.
Include data-error, holding, ETF/core-DCA and panic scenarios in exact parity.
Commit/push, verify deployment and leave exactly one bounded next task.

## Evidence and Remaining Limits

- Latest: [Theme stock display extraction](docs/maintenance/20261107_theme_stock_display_extraction.md).
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
