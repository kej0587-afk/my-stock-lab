# Theme group display extraction

## Scope

Started from clean `main == origin/main == 612ab8c4` after fetching upstream.
Completed the single handoff task: extract one contiguous deterministic table
preparation block from `render_image_theme_flow_section`, then 521 lines.

Code commit: `20ff2662` (pushed).

`stock_lab_core/theme_flow_view.py::prepare_theme_group_display` now prepares
the subtheme summary table/CSV. It copies the input, applies the existing badge
mapping and percentage formatter, formats numeric display columns, removes
empty optional columns and returns the existing ordered selection. The renderer
passes its unchanged badge mapping and `fmt_flow_pct` function explicitly.

The original renderer is now **489 lines**. Its charts, descriptions, filters,
ranking, classification, metric calculations, provider calls, cache policy,
lazy execution and account state are unchanged. This is a maintainability change;
no measured speedup or shorter end-to-end loading time is claimed.

## Before/after verification

- Existing report gate before: **180 passed**, 7.962s,
  `cache/refactor_checks/report_dlh7p5lh/summary.json`.
- Existing money-flow renderer/UI contracts before: **12 passed**, 26.28s.
- Before editing production code, froze six original table outputs in ignored
  `cache/theme_group_before.json`; all six match the extracted helper exactly.
- New parity tests use immutable Git revision `612ab8c4`, rather than a regenerated
  expected-output fixture. Inputs cover finite/nonfinite/zero values, nullable
  values, unknown/missing states, minimal columns, all-empty optional columns,
  empty frames, reversed columns/rows and duplicate named indexes.
- Exact DataFrame values/dtypes/order/attrs and CSV strings match. Input frames
  remain unchanged, including when the returned display is subsequently edited.
- A source-structure contract checks the renderer wiring and that everything
  outside the extracted block and table argument stays syntax-identical.
- Existing report gate after: **180 passed**, 7.515s,
  `cache/refactor_checks/report_ous2lzkx/summary.json`.
- New parity plus existing money-flow renderer/UI contracts: **19 passed**, 27.19s.
  After strengthening the wiring assertion, the seven new tests passed again.
- `git diff --check` passed. These are selected contracts, not a full-suite pass.

## UI and deployment

Authenticated production money-flow screen opened successfully after rebinding
the browser connection. The pre-change theme calculation rendered summary charts
and the subtheme table. A built-in CSV download attempt timed out; CSV parity is
verified offline, not claimed as a successful browser download.

After push and a fresh page reload, navigated Money-flow Radar -> Theme source
and ran the power/energy infrastructure theme at 00:19 KST. The screen showed
46/46 calculated instruments, 11 subthemes, charts and the complete 11-row summary
table, with percent/numeric formatting and column order intact; no UI traceback.
Saved the private screenshot `Downloads/stock_lab_theme_table_20261107.jpg`.
The post-push CSV download event also timed out, so browser delivery remains
unverified (this does not establish an application CSV-generation defect).
No module-hash export was collected for this display helper; this was an
authenticated UI smoke check, with exact-output parity established offline.
Private screenshots/exports remain outside Git. No holdings or watchlist edits.

## Remaining scope

The stock-detail display formatting is still inline in the same renderer. Its
classification, ordering and captions were deliberately left unchanged. Broader
label/rule reviews and performance measurement remain separate tasks.
