# Entry Signal Preparation Refactor

## Scope

Baseline: `3e872d1f39d288047246aacba240e089e1814d54`.

The 267-line `build_entry_signal_context` previously mixed momentum entries,
MA5/FVG pullbacks, quality recovery, structure risk, and ETF accumulation.
It now delegates to four pure stages in `stock_lab_core/decision_signals.py`.
The public assembly function is 70 lines; stage lengths are 54, 45, 74, and 83.

- Existing conditions, thresholds, short-circuit order, return keys/order, and
  exceptional-input behavior are unchanged.
- `decision_engine` re-exports the function for existing callers. The app imports
  the new module directly so a cached old engine cannot hide the new binding.
- The new module participates in loaded-source checks for Cloud deployments.
- No price providers, caches, trading policies, grades, sizing, or UI were changed.
- This is a maintainability change, not a network latency or performance claim.

## Verification

- Exact AST comparison of every original calculation statement and return mapping.
- Threshold neighbors, zero/NaN, ETF/stock/leveraged profiles, and 2,000 seeded
  combinations. Invalid FVG input keeps the original exception type/message.
- Twenty complete calculation scenarios compare unrounded results, unchanged
  price frames, and identical external-provider call order.
- Local saved-price replay for MSFT and 418660.KS: all 96 output fields match
  before/after, with external inputs and account inputs held fixed. Raw exported
  OHLCV is rebuilt through the indicator engine; this is a parity check, not a
  claim that a later live quote equals an earlier export.
- Full suite before the final direct-import adjustment: 5,909 passed,
  18 subtests passed, 77 existing warnings (315.49 seconds).
- Final import, stale-module, policy, golden-snapshot, input, and source-provenance
  checks: 286 passed (26.42 seconds).

Commands:

```text
py -3.11 -X utf8 -m pytest -q
py -3.11 -X utf8 -m pytest tests/test_decision_signals_refactor.py tests/test_decision_inputs_refactor.py tests/test_decision_followup_refactor.py tests/test_decision_priority_refactor.py tests/test_decision_refactor_parity.py tests/test_decision_golden_snapshot.py tests/test_precision_build.py -q
```

Private account snapshots remain outside the repository. The regression fixtures
contain only synthetic inputs and existing public-code baselines.
