# Bounded Refactor Review

Baseline: `9cc99dd2`. This pass adds a local verification entrypoint only.
No production calculation, investment threshold, allocation, cache TTL or UI changed.

## Findings Against the Submitted Review

- Confirmed by AST: app.py has 35,702 lines and 898 function definitions,
  including nested functions. Largest functions: render_image_theme_flow_section
  521 lines, calc_scores_and_decision 480, render_entry_execution_plan 429,
  build_portfolio_analysis_report 411 and build_pre_buy_final_checks 381.
- Existing safety coverage is substantial: 270 test files before this pass,
  fixed decision snapshots, full-report contracts, cross-view execution tests,
  split-basis checks and cache/request replay tests. Do not recreate these.
  The core package has 199 top-level Python modules; extraction alone is no longer
  a useful progress metric. See ../20261104_architecture_refactor_map.md.
- Invocation counts are not request counts. Existing price scopes, cache tests
  and replay benchmarks already address reuse. Batch by ticker AND provider,
  adjustment basis, interval, session and observation time, not ticker alone.
- Repeated nested names are not necessarily duplicate definitions. Static
  unreferenced-name searches cannot prove functions are unused.
- RerunException is Streamlit control flow, not automatically a provider failure.
  Broad logging changes must not swallow rerun/stop or leak secrets/account data.
- Correct coverage identity is connected + unconnected + cash = 100%, only
  when categories are exclusive and use the same asset denominator/snapshot.
  Current weights cannot reconstruct start weights without cash flows/trades.
- ETF daily moves above 40% are investigation triggers, not proof of a split.
  Existing tests preserve genuine large moves and reject unverifiable adjustments.
- Freeze completed reference observations, not changing intraday observations.
  Session-pair tests need exchange calendars, DST and explicit observation times.
- Do not auto-revert on test failure: stop, inspect the diff, preserve user edits.

## One Verification Command

From the repository root, using its installed test environment:

```powershell
.\venv\Scripts\python.exe scripts/check_refactor.py --scope all
.\venv\Scripts\python.exe scripts/check_refactor.py --scope decision
.\venv\Scripts\python.exe scripts/check_refactor.py --scope report
.\venv\Scripts\python.exe scripts/check_refactor.py --scope prices
```

`--list` shows the selected files without running. The command reuses committed
fixtures; it never regenerates them. It blocks baseline-rewrite environment flags,
ignores inherited pytest filters, forces public-demo auth and records JUnit,
source/fixture hashes, selected scope, duration and failure details in ignored
`cache/refactor_checks/`. Empty, skipped, failed, timed-out or source-mutating
runs are not a pass. Failed output is retained; there is no automatic repair,
rollback, deployment or investment action.

This selected suite does not replace the full suite or live UI smoke checks.
Its elapsed time is TEST time, not Cloud calculation speed. Before/after:
run the SAME scope on the old and new code; inspect the source diff and evidence.
Snapshot baselines may only change in a separately reviewed behavior change.
No finite test set proves every live input or every investment decision correct.

## Work Plan

## Agreed Work Order (2026-11-06)

1. DONE: establish the bounded verification command; commit/push this safety baseline.
2. DONE (local verification): extract pure risk and portfolio check rows from
   build_pre_buy_final_checks. Freeze full outputs before touching production.
   Preserve thresholds, row/reason ordering, counts and execution permission.
3. IN PROGRESS: compare held-KR/held-US inputs across today queue, board, precision and
   portfolio views. Separate snapshot-age differences from genuine contradictions.
   Verify authenticated UI where available; report inaccessible views explicitly.
4. QUEUED: select ONE provider bottleneck from fresh measurements. Count requests
   and cache misses; compare identical inputs/cache state across 2-3 runs.
5. QUEUED: review investment criteria separately using the governance audit.
   Present deficiencies and proposed changes before changing investment rules.

Complete and verify one item before broadening scope. Keep each production
extraction in its own commit. Never claim test runtime as application speed.

### Extraction Checklist

1. Select one responsibility in build_pre_buy_final_checks (381 lines).
2. Inspect its existing tests and consumers; capture missing-data, held/unheld,
   target-below-price and zero-cash outputs before extraction.
3. Extract pure input/row preparation, preserving field values, reason order,
   labels, counts and permission. Do not move the entire function mechanically.
4. Run decision contracts before/after, related report contracts, then broader
   regressions and a live held-KR/held-US smoke check. Deploy only after review.
5. Optimize a measured provider bottleneck separately, comparing identical
   payloads and cache conditions over repeated runs; retain result equality.

## Investment Criteria: Proposal Only

Keep these separate: data quality, business/ETF quality, valuation, timing,
portfolio risk and execution permission. Good quality is not permission to buy;
an entry block is not an instruction to sell existing holdings.

The conversation exposed another input gap: account cash versus outside cash.
External money should affect household risk capacity only if explicitly declared
available, with emergency/near-term spending excluded. It must not silently raise
account order budgets or change the target-weight denominator.

Prioritize actual versus forecast earnings, consensus source/date, estimate
revisions, FCF/CAPEX definitions, ETF look-through overlap, daily leverage and
liquidity. Do not add another opaque score. Validate any proposed predictive
score using out-of-sample, point-in-time data, costs and overlapping-window
controls before considering new thresholds. Existing financial-governance
review: 20261031_decision_criteria_audit.md. No threshold change is approved here.

## Verification of This Pass

- Before edits: 70 existing decision/report/split/cache contracts passed in 12.88s.
- New combined gate: 597 tests passed, zero failures/errors/skips; 43.035s runner
  wall time (41.18s pytest time). No source/fixture mutation during the run.
- Evidence: `cache/refactor_checks/all_08ean00u/summary.json`, `junit.xml`,
  and `pytest.log`. These contain local test evidence, not exported holdings.
- Production files and stored golden snapshots were not modified. No deployment
  or Cloud UI change was made; live provider speed was not measured in this pass.

## First Production Extraction (2026-11-06)

- Safety baseline pushed as a246f722. The preceding verification notes describe
  that baseline only; this follow-up changes app.py and adds final_check_rows.py.
- build_pre_buy_final_checks: 381 -> 334 lines. Extracted structure/timeframe/
  overheat rows and weight/macro/holding rows into two pure helpers. Call order,
  explanation text and the existing governance/final execution veto are retained.
- Reused the already-normalized daily return and computed the identical extreme
  overheat predicate once. No provider, cache TTL, date basis or threshold change.
- Captured 62 complete ordered-output digests from a246f722 BEFORE extraction;
  tests/golden/final_check_rows_v1.json is not regenerated during verification.
- Same 691 tests before/after: PASS, 44.625s / 44.776s runner wall time. These are
  verification runtimes, NOT an application speed benchmark.
- Added two local Streamlit AppTest renders of held-KR/held-US ETF final panels.
  These use deterministic inputs, not the user's current Cloud account/data.
- Additional related tests initially found a syntax-only equality assertion that
  disallowed helper extraction. Retained its old source and wording corrections;
  replaced the extracted-function AST comparison with 62 old/new full-output
  comparisons. The unchanged function still uses exact AST equality.
- No remote UI verification or live performance improvement is claimed here.
- Final expanded gate: 1,060 passed, zero failures/errors/skips, no source/fixture
  mutation; 64.899s. Evidence: cache/refactor_checks/all_tvvrnop0/summary.json.
  Compile checks and git diff --check also passed. Next: step 3, authenticated
  cross-view consistency; do not broaden to new providers or investment criteria.

## Cross-View Handoff Fix (2026-11-06)

- Live pre-change check: 379810.KS and SOXL precision upper result, management
  plan and final check all withheld execution. The board's 379810.KS gate was
  also defensive. The saved today result and freshly calculated precision result
  had different observation times; that alone is not a calculation contradiction.
- Reproduced a missing connection: after the board completed, portfolio showed
  zero connected held signals. The real board never published its prepared
  frame to the portfolio selector. Its existing `_ticker_signal_detail_df` source
  was actually produced by asset overview, but labelled as the board.
- Added capture_dashboard_signals to the existing portfolio_signal_cache module.
  It copies the displayed rows without provider calls or score recalculation,
  retains original calculation timestamp/account scope, and rejects missing or
  mismatched provenance. A rerender cannot promote an older calculation.
- The board stamps only fresh calculations, checks account scope on reuse, and
  publishes after its existing gate preparation. Account/watchlist invalidation,
  explicit clear and recalculation remove the derived portfolio copy. Legacy
  source is now labelled asset overview. No investment rule, price/date basis,
  allocation or cache TTL was changed.
- Regression: 8 held tickers x 4 gates; exact displayed values/date preservation,
  account isolation, old/new source priority, copy isolation, final-check veto,
  invalidation and actual app-branch wiring. Existing Streamlit portfolio-panel
  render/switch test is included. Initial dashboard fixture lacked the newly
  used context functions; updated its test environment, not expected decisions.
- Pre-change related baseline: 128 passed in 16.67s. Expanded selected gate:
  1,166 passed, zero failures/errors/skips or source changes during verification,
  69.086s. Evidence: cache/refactor_checks/all_ubu0295i/summary.json.
  Different test counts mean these are not before/after speed measurements.
- Pushed 74cf9b6e and verified live: board completed at 16:05 KST; portfolio
  connected all 10 held tickers with price reference dates (previously zero).
  SOXL displayed board saved 16:05 and precision calculated 16:03 separately.
  Both retained market-defense/new-buy restrictions. This is not an exhaustive
  audit of every holding or tab.

### Follow-Up Found During Live Verification

- Portfolio commentary still called SOXL's completed final check "unconfirmed".
  render_pre_buy_final_check_panel returns {ticker, rows, summary}, whereas
  portfolio readers expected final_label/execution_allowed directly on final.
- Normalize this envelope at capture AND read time in portfolio_holding_review,
  preserving older summary-only snapshots and already-stored envelopes. Keep
  the original calculated summary, missing-data veto and account isolation;
  no inference from positive labels and no rescore. Malformed summaries remain
  unconfirmed, never execution approval. Do not mutate existing session evidence.
- Follow-up selected gate: 1,174 passed, zero failures/errors/skips or source
  mutation, 71.414s. Evidence: cache/refactor_checks/all_x7o0zklq/summary.json.
  Covers renderer envelope/summary parity, old-cache reads, commentary labels,
  allowed/blocked permissions and malformed results. Cloud follow-up pending.
- Next bounded consistency review: the portfolio flow/replacement candidate
  section can still show a reinforcement candidate while execution is withheld.
  Inspect its basis and clarify candidate versus permission before any rule
  change. The narrow comparison table also puts the execution gate offscreen;
  prioritize its presentation over adding new scores/providers.
