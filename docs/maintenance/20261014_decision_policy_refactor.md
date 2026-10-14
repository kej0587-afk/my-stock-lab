# Decision Policy Extraction: 2026-10-14

## Scope

The largest original function was calc_scores_and_decision (1346 lines).
Its first extraction pass leaves 798 lines of orchestration and remaining risk
rules. Other large UI functions were not refactored in the same change.

Five keyword-only pure selectors now live in stock_lab_core/decision_policies.py:
- select_free_mode_decision
- select_profitable_holding_decision
- select_holding_decision
- select_new_entry_decision
- select_portfolio_guard_decision

Inputs are the same already-calculated values. Outputs use the existing
DecisionOutcome. Unmatched portfolio guards return None, retaining the former
guard -> remaining policy order. Source prices, data fetching, live overlays,
safety overrides, panic scope and sizing remain in the app.
No labels, numeric thresholds, feature scope, auth or persistence changed.

## Verification

Before extraction, 20 deterministic representative scenarios were saved as
full-output snapshots, separate from the existing reduced golden snapshots.
The new baseline creation refuses to overwrite an existing baseline.
Each of the five extractions passed the full-output and existing golden tests
before the next extraction started (17 tests per step).
Normalized AST hashes preserve every moved condition, literal and rule order;
only len(df) is replaced by the equivalent explicit history_days input.
The structural check also detects missing selectors.
Eight direct guard tests check priorities, storm boundaries, unmatched handoff
and preservation of the input DCA context.
Final full suite: 858 passed in 39.57s, one existing pykrx warning.
Independent read-only review found no missing inputs or output dependencies.

## Runtime Limits

This is a behavior-preserving structural change, not a demonstrated fix for the
reported five-minute Cloud run. More symbols increase history, benchmark,
multi-timeframe and analyst-provider work. Actual Cloud phase timings are still
needed to distinguish computation from provider waits/retries.
No authenticated Cloud runtime or deployment was performed.
Deploy app.py and the new decision_policies.py together, then restart so the
complete helper module is loaded. Existing golden snapshots were not rewritten.
