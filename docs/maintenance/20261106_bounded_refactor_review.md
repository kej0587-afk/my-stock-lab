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
  allowed/blocked permissions and malformed results.
- Pushed fa44068b; Cloud logs confirmed update but reruns still showed the old
  module's "unconfirmed" label. Rebooted via the owner's Manage app panel.
  After restart, SOXL precision completed at 16:16 KST and portfolio commentary
  showed its actual final label "DCA hold" for the 2026-11-05 price reference.
  Market-defense restriction remained. Missing today/board cache after restart
  was disclosed rather than filled from another account or treated as permission.
- Next bounded consistency review: the portfolio flow/replacement candidate
  section can still show a reinforcement candidate while execution is withheld.
  Inspect its basis and clarify candidate versus permission before any rule
  change. The narrow comparison table also puts the execution gate offscreen;
  prioritize its presentation over adding new scores/providers.

## Candidate / Execution Presentation (2026-11-06)

- Confirmed display cause: market-alignment add candidates and recommendation
  strength came from portfolio/flow classifications without the account-scoped
  execution gate. The overview called them add/DCA candidates unconditionally.
- Introduced portfolio_candidate_view for pure display joins and extracted
  overview/recommendation rendering. One scoped signal selection is passed to
  alignment, recommendations, next-check candidates and monthly playbook.
  Match exact ticker aliases only; a theme's representative list does not
  inherit a member's permission. Duplicate or missing matches remain unlinked.
- Put restriction/reason/reference date before raw plan labels. Executable
  screening rows still require precision final checks, weights and cash.
  No price-reference date is not a completed check. Unknown evidence is not
  an approval. Counts distinguish candidates, restrictions and missing evidence.
- Preserve original ranking, score, portfolio classification, amounts and shares.
  Monthly values are explicitly calculation-only allocations, not order budgets.
  Hide repeated raw-detail tables behind expanders; no new provider calls.
- Baseline related tests: 116 passed (30.09s). Five app calculation functions
  have identical ASTs to 3b5df834; stock_lab_core/portfolio.py is unchanged.
  Expanded selected regression gate: 1,253 passed, zero failures/errors/skips
  or source mutations, 97.823s. Includes local Streamlit candidate-panel render.
  Evidence: cache/refactor_checks/all_rjynw3y_/summary.json. Test times are not
  an application-speed comparison. Compile/diff whitespace checks passed.
- Pushed b9df459f and verified authenticated Cloud rendering without reboot.
  Before: BITX was introduced as an add/DCA candidate without its gate.
  After, on the same completed today input: 1 flow candidate, 1 held/waiting,
  0 precision-final-check candidates, 0 missing connections. BITX remained in
  the list with market-defense/new-buy suspension beside it. The 10 held rows
  exposed their restrictions before raw portfolio classifications. Narrow-view
  screenshot confirmed restriction labels fit beside the asset names.
- No change to investment thresholds, allocation math, provider caching or
  market-data reference basis. Next: measure ONE price-provider bottleneck;
  the pre-deploy live today run (94.0s) is not a before/after speed benchmark.

## Price Batch Selection (2026-11-06)

- Audited the latest local full trace (70fe4d6, 103.731s): load_price_df
  739 calls / 69.124s summed / 23.310s active wall; get_money_flow_ohlc
  505 calls / 59.884s summed / 15.449s active wall; Yahoo chart 78 actual
  requests. The function counts do not prove 739 or 505 external requests.
  Existing history memoization, bulk KR quotes and bounded parallel flow I/O
  are already present. No new cache TTL or removed recovery attempt was used.
- Limited this change to repeated CPU work in downloaded-price selection.
  Extracted DownloadFrameSelector, a batch-local column index, reused across
  symbols by load_price_frames_batch. The legacy single-frame entrypoint remains.
  Preserve exact normalized-symbol matching, first level/raw match precedence,
  malformed/absent-symbol rejection, independent copies and provenance attrs.
  No app/UI, investment rule, fallback ordering, provider request, reference
  session, adjustment basis or cleaning formula changed.
- Baseline price gate: 60 passed. Targeted pipeline/board regression: 122 passed.
  Expanded selected all gate: 1,265 passed, zero failures/errors/skips or source
  mutations, 95.650s. Evidence: cache/refactor_checks/all_jnm8tggb/summary.json.
- Three paired CPU-only runs after tests finished: fixed 95 symbols x 3 row
  lengths (64, 260, 2600), 285 exactly equal output frames per pair, including
  attrs. Before [0.146572, 0.145572, 0.151987]s; after
  [0.071191, 0.071374, 0.072413]s. Means 0.148044 -> 0.071659s.
  This saves only about 0.076s in the measured selection stage, NOT tens of
  seconds in the app. Neither side makes network requests in this benchmark.
- Cloud full-run timing and post-deploy screen verification were not performed
  for this change; do not reuse the previous 94.0s run as a new measurement.
  The main network bottleneck remains open. Next bounded performance work must
  measure exact provider request/cache-miss keys in a fresh full trace before
  attempting more reuse; preserve failure recovery and quote freshness.

## History I/O Overlap (2026-11-06)

- First deployed diagnostics only (3329229e): separate cache body executions,
  cache/concurrent-wait reuse, scoped history reuse and actual Naver HTTP
  requests. yfinance download counters are provider API calls, not verified
  wire requests inside yfinance. Instrumentation never records arguments/keys.
- Before optimization, Cloud 96-row full calculations with flow refresh and
  detail enabled: after reboot 106.851s (5d2ea741), then warm 67.476s
  (12a00d2f). KR HTTP requests 405 -> 0; KR cached reuses 13 -> 277.
  The first run's KR HTTP summed time 92.76s is 25.29s active wall, not 92.76s
  of page delay. Scoped histories were reused 548 times on each run.
- Only optimize prefetch_price_data_parallel: begin the existing bounded
  domestic workers while the overseas-only batch runs on the caller. Preserve
  each period and provider request, the Yahoo lock, max 8 domestic workers,
  cache TTL/clear/failure recovery and missing-overseas fallback after batch.
  No investment formula, quote timestamp or adjustment-basis change.
- Tests compare exact frames/attrs and request multisets for 1y/10y/3mo,
  missing/failed symbols, actual cold/warm cache counters, worker-local session
  lifetime and Streamlit cache execution. Expanded selected regression gate:
  1,340 passed, zero failures/errors/skips/source mutations, 103.907s.
  Evidence: cache/refactor_checks/all_ajclr7y6/summary.json.
- Fixed response/delay scheduling test, 3 pairs: mean 0.327167 -> 0.227198s,
  identical requests and results. This is synthetic I/O overlap evidence, NOT
  a measured Cloud full-calculation improvement. Post-deploy live comparison
  is recorded below after measurement; no historical 120s claim is reused.
- Deployed optimization 2834ff49; owner reboot and identical account selection,
  refresh-flow and flow-detail settings. The 96-row Cloud runs after reboot:
  106.327s (992cf951), then warm 61.367s (5b77f19d). Both have zero errors.
  App-entry-inclusive script times: cold 110.359 -> 109.976s; warm
  72.119 -> 65.885s. Compare cold with cold and warm with warm, not their mean.
  Full-run first-load improvement is negligible (0.524s); warm difference is
  6.108s, but neither single pair isolates network/CPU variability. No claim of
  guaranteed full-app speedup or completion under 60 seconds.
- Cold KR HTTP count remained exactly 405; warm remained 0 (277 cache reuses).
  Scoped history hits remained 548 on both sides. Provider periods/cache policy
  were not shortened to achieve the observed times. Cold 1y/10y phase sums
  10.648 -> 9.235s, while RS 3mo 7.144 -> 10.938s; batch-provider summed wait
  8.965 -> 16.872s. Network variance masks scheduling gains in the full run.
- Strengthened the whole-summary regression to run the legacy sequential
  preload before the new preload: full result DataFrames and saved financial
  scores equal for cold/warm and empty/error cases. Re-ran the selected full
  gate: 1,340 passed, 104.248s, zero failures/errors/skips/source mutations.
  Evidence: cache/refactor_checks/all_xk2iycr6/summary.json.
- Actual authenticated UI: full result 96 rows, execution 0, caution 96,
  hard blocks 5, same as the before-screen. Final timer 61.4s plus entry 4.4s;
  completed diagnostic ID matches the downloaded JSON. No UI/rule changes.
  Local screenshot: Downloads/stock_lab_performance_verified_20261106.png.
  Personal diagnostic JSONs/screenshots are kept local, not committed.
