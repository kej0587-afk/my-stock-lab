# Market guard input audit

Scope: input dates, duplicate risk evidence, applied score display. Base a7e34691.
No investment bands, price source, TTL, portfolio allocation or stock penalty changed.

## Observed Cloud state before edits

Market-only report generated 2026-11-13 11:51 KST:
KR caution / US caution / integrated risk, 9 = regional max 4 + flow 3 +
macro 1 + event 1. KR bars Nov 13, US Nov 12. Neither region was emergency.
KR MA20/50 below counts 4/4; US 4/5. Flow positive breadth 15.3%, acceleration
30.9%, observed denominators 98/99 and 97/99. This is medium-term breadth and
trend, not a claim that today's intraday index return is negative.
Below 8 requires at least two net score points to disappear; a one-point
improvement alone leaves risk at 8. Tactical rebound still requires the existing
breadth >=55% or acceleration >=50%, plus price-rebound and no-panic conditions.
No threshold was lowered to admit trades.

## Confirmed corrections

1. ^GSPC and SPY previously counted as two S&P500 shocks. A synthetic -6%
   observation in both incorrectly satisfied two panic indices / emergency.
   Valid index now takes precedence; SPY remains a fallback. Nasdaq Composite
   versus Nasdaq 100 and the Korean index/large-cap baskets remain distinct.
   Displayed source rows remain intact, with the excluded proxy disclosed.
2. get_macro_analysis includes event risk in final_macro_risk. The market guard
   then scored that aggregate and scored events again. Capture the macro-only
   base alongside the same snapshot and use that base only in the market guard.
   The original return tuple, final_macro_risk and stock macro penalty stay intact.
   Do not subtract a newly fetched event score from an older cached total.
   Legacy snapshots without decomposition retain their value and explicitly
   require refresh; missing values are not inferred.
3. Detailed explanation previously called raw macro/event points applied points,
   even when compose_market_guard_score suppressed them for regional score >=5.
   Show raw and applied separately and explain the existing combined condition.
4. Display flow row dates and per-indicator macro dates, not report creation time.
   Existing market-specific common-date alignment and stale-date warnings remain.
5. The deployed 12:14 report exposed a further input-date bug: all macro rows
   appeared as Nov 13. The multi-symbol Yahoo union index includes FX dates when
   US index closes are missing; ffill promoted yesterday's US value to that date
   and could also shift the 22-observation comparison. Use finite positive actual
   closes only. A union-index regression verifies US Nov 12 / FX Nov 13 and the
   observed 22-bar comparison. Formula and risk thresholds remain unchanged.

Correlated MA20/MA50/5-day weakness rules are intentional separate criteria; they
were not removed. Portfolio caution counts are not added to market-mode score.
Report stress 0-100 is a different explanatory measure, not this guard score.

## Verification

- Before correction: new regressions reproduced 5 failures / 1 pass.
- Baseline decision tests: 1367 passed, 122.68s. Wrapper marked BLOCKED because
  the new test file was added during the run (production sources unchanged).
  This is not claimed as an immutable-source gate pass.
- Focused guard/date/event/display tests: 104 passed, 11.50s.
- Frozen current-like input retains 9/risk; old Oct 30 fixture retains 12/risk.
- Exact AST inverse allows only the three reviewed function edits in older
  extraction contracts; no golden files or original Git references regenerated.
- Focused repair plus affected extraction contracts: 180 passed (49.89s).
- Report provenance/build: 10 passed (8.59s).
- Final immutable-source decision gate: 1367 passed, 127.905s; no changed sources.
  Evidence: cache/refactor_checks/decision_754545vm.

Initial deployment 1b9b6960 verified on Cloud in a new 12:14 KST market-only
report: integrated risk remains 9; SPY excluded, macro-only 0 versus legacy 1
and captured event 1; flow dates Nov 12/13. Union-date follow-up: focused 106
passed (15.95s); final immutable-source decision gate 1367 passed (125.569s),
cache/refactor_checks/decision_9iirttc3.

Final deployment d98ec8fe verified in a new Cloud market-only report generated
2026-11-13 12:25 KST. US rates/oil/VIX/MOVE observations are Nov 12; FX Nov 13.
KR/US benchmark dates Nov 13/12; flow dates Nov 12/13. SPY exclusion is visible.
Actual-observation correction changes macro base to -0.5 (aggregate 0.5 with
event 1); pressure count 2 still yields macro guard point 1. Integrated risk
remains 9 = regional 4 + flow 3 + macro 1 + event 1. Both regions are caution,
neither emergency; US below-MA20/MA50 counts are now 3/4 after proxy deduplication.
Release explanation correctly requires at least two net points to fall below 8.
Screenshots saved privately in Downloads/market_guard_audit_verified.png and
Downloads/market_guard_dates_verified.png. No account-wide recalculation was run.

No account trades, no automatic orders, no performance improvement claimed.
