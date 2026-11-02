# Score And Decision Follow-Up Extraction

## Scope

Baseline: `bf1302fff6b2b657095d20bea9bc70967029ebdd`.
This step extracts only personal-mode follow-up selection from
`calc_scores_and_decision`, after its existing portfolio-priority guards.
The large app function shrinks from 594 to 501 lines.

`stock_lab_core/decision_followup.py` separates two responsibilities:

- `_select_core_or_technical_signal` (76 lines): core accumulation, limited
  history, MFI/extension/band checks, ETF accumulation and strength-add signals.
- `select_portfolio_followup_decision` (106 lines): select the first common
  signal, otherwise delegate to the existing profitable-holding, holding or
  new-entry policy. Dependencies are explicit keyword arguments, not `locals()`
  or Streamlit state.

The original per-invocation `_set_decision` closure and intermediate
label/color/outcome tuples are removed from this path. The selected outcome is
unpacked once at the app boundary. This is duplicate implementation/result
packaging removal, not a new cache or a reduction in financial calculations.

## Unchanged Behavior

- Input normalization, source close selection, live-bar handling, return windows,
  scores, financial inputs, RS, ATR/RR, SMC and position calculations are intact.
- Free-mode decisions do not invoke the extracted personal-mode selector.
- Priority decisions still short-circuit all follow-up selection. A common
  signal still short-circuits holding/new-entry policies.
- All conditions, comparison operators, threshold values, Korean labels, colors,
  codes and reason order remain unchanged. Profitable holding still means
  `cur_p > my_price * 1.02`; it is not replaced with a rounded return comparison.
- Safety override, holding translation, non-core panic restriction, data-error
  override, buy-amount reset, sizing and result assembly retain their exact order.
- No price provider, external-call count, timestamp basis, cache TTL, account
  input, UI or automatic-order behavior is changed.
- Selected-policy errors propagate; they do not silently fall through to a
  different investment decision.

## Verification

- Before implementation, 27 branch/boundary tests passed, including eight
  deterministic batches totaling 400 colliding-condition cases.
- The expanded dedicated suite has 58 tests. It compares outcomes and reasons
  directly, including NaN, threshold neighbors, new ETFs, core signals,
  overweight/market priority, holding profit boundaries and exception behavior.
- Twenty full-calculation scenarios compare every returned value against the
  retained original function without rounding: component scores, grade, price,
  returns, RR, cash amounts, sizing, decision code/text, reasons and metadata.
  Caller price frames and attributes are unchanged. Data/score/sizing callback
  order and counts also match exactly.
- AST checks rebuild the original follow-up chain from both helpers. Only
  result unpacking and `len(df)` to explicit `history_days` are normalized; all
  conditions, literals and delegated-policy arguments are compared exactly.
- Restoring the extracted block and removed closure gives the exact original
  main-function AST, including calculation prefix, free mode, priority gates,
  final overrides, sizing and timing decorator.
- Existing priority-extraction tests normalize this separately tested extraction
  before checking their own older baseline. Original golden snapshots are not
  regenerated or edited.
- Spies verify only one selected outcome/policy runs, free mode and priority
  decisions skip follow-up entirely, and failures remain visible.
- The new module is included in both source-provenance lists. Fresh/stale
  imports are tested even when the cached metadata list predates the new module.
- Targeted decision, golden, engine and shared-live-input suites: 266 passed in
  26.51 seconds. Compilation and whitespace checks passed; no removed local
  variables remain referenced in the app function.
- Full regression suite: 5,740 passed, 18 subtests passed and 77 warnings in
  272.84 seconds. No executable code changes followed this run.

## Limits And Next Boundary

This step makes the decision-selection boundary independently testable. It does
not claim a measurable end-to-end speed gain. Provider calls and score
calculations intentionally retain their previous count and order. Validation
uses deterministic prices/provider doubles, not live-account or Cloud UI checks.

The app still assembles price, technical, position and entry contexts. Further
extraction should preserve those data contracts and use full, unrounded output
comparison before considering any shared-computation optimization.
