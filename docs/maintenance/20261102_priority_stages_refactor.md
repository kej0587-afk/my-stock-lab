# Portfolio Priority Stages

Baseline: `16624fdef58509d461785c26ad7592d1e69f6047`.

## Scope

Only `stock_lab_core/decision_priority.py` changes application behavior structure.
The 308-line `select_portfolio_priority_decision` is now a 130-line coordinator
(including its unchanged keyword-only signature). It calls the existing portfolio
guard first, then three private stages only while no decision has matched:

1. Leverage and core drawdown rules (90 lines).
2. Quality recovery and remaining drawdown rules (85 lines).
3. Structure damage and live/exception entry rules (131 lines).

Every original condition, branch body, label, color, reason, and threshold remains
unchanged. Recovery remains after core/leverage rules and before non-core drawdown
rules. A `None` result still delegates to the existing follow-up selector.

Inputs are explicitly forwarded without recomputation. Each stage runs at most
once, and later stages never run after a match. No new market-data requests,
caches, persistence, chart behavior, UI, or sizing rules were introduced. The app's
calculation function and import path are unchanged; the existing loaded-source
check already tracks this module. This is not a network-speed optimization.

## Verification

- Reassembled branch AST equals both the immediate baseline and the original
  pre-extraction priority chain; public signature is identical.
- Every branch's existing examples, threshold neighbors, NaN/infinities, mixed
  flags (2,000 seeded cases), input non-mutation, and representative invalid-input
  exception type/message are checked.
- Short-circuit tests assert guard/stage order and at-most-once calls.
- Twenty complete calculation scenarios compare all unrounded results and
  external-call order, with unchanged input frames and metadata.
- Independent read-only review found no parity defects; focused suites passed.
- Focused verification: 111 passed (16.66 seconds).
- Full suite: 5,948 passed, 18 subtests passed, 77 existing warnings
  (318.60 seconds).

Commands:

```text
py -3.11 -X utf8 -m pytest tests/test_decision_priority_stages.py tests/test_decision_priority_refactor.py tests/test_decision_golden_snapshot.py -q
py -3.11 -X utf8 -m pytest -q
```

Private Cloud review exports stay outside the repository. Live quotes can change
between browser checks; identical-input comparisons are the result-parity proof.
