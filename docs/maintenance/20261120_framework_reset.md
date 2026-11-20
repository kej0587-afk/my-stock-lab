# Framework Reset: Decisions Before More Connectors

## 작업 방향

전체 흐름은 **자료 확인 → 시장 환경 → 기업/상품 → 타점 → 계좌 제한 → 조건별 대응**입니다.
시황은 이 근거를 설명하는 결과물이며, 별도의 매매 허가 엔진이 아닙니다.

- 이번 단계: 공통 판단 요약, 조건별 대응과 계좌 충격의 분리, 매크로 차트 바로 접근.
- 다음 단계: 오늘점검과 정밀관측소의 진입·익절·손절 원계획을 동일 입력으로 대조하고 공통화.
- 이후: 확정 가격 보존 → 사건·실적 상태 통합 → 통제된 성능 측정 → 투자 기준 검증.
- 참고 문서의 모든 주장이나 모든 기능을 이미 구현했다는 뜻은 아닙니다.
  검증되지 않은 승률·유동성 사냥·갭 회복은 매수 근거로 자동 가점하지 않습니다.

Base: 2fbf3134. This supersedes the earlier DART-only next-task order.
User requested the whole framework be organized before further narrow repairs.
No new score weights, investment thresholds, trade permissions or orders.

## Why Repairs Kept Repeating

- A successful collector or parser was mistaken for end-to-end coverage. A
  verified event can still be unconfirmed in a separate calendar/news renderer.
- Calculation, observation and publication clocks differ. Newer rendering does
  not make a saved decision current; another provider response can reduce coverage.
- Screening, final review, holding management and stress simulations answer
  different questions, but the UI often puts them under similar decision labels.
- Local regression tests prove their contracts, not investment profitability,
  universal news understanding or consistency of every live provider response.
- Repeated feature additions enlarge rerun collection and make the user's path
  harder to follow. More metrics alone do not produce a better explanation.

## Target Flow And Ownership

| Layer | Question | Existing owner / invariant |
| --- | --- | --- |
| Observations | Which instrument, period, session, price kind and source? | Source adapters, signal_basis, data_freshness; unknown is not zero |
| Market environment | What currently restricts new risk? | build_today_market_guard + execution_context; preserve thresholds |
| Business / product | Quality, valuation and leverage structure? | Financial evidence + product profiles; forecasts separate from actuals |
| Setup | Structure, location, formation duration, liquidity proxies? | Captured chart/multi-timeframe evidence; no invented order-book/stop data |
| Account | Exposure, cash and existing limits? | Portfolio/DCA calculations; target shortfall is not purchase permission |
| Execution | Is this screening or a completed final check? | build_execution_readiness; final veto wins for presentation |
| Response | What existing condition warrants another review? | Read-only decision_brief; hypothetical response never releases a gate |
| Narrative | What happened, evidence, competing explanation, next check? | Report consumes verified observations/events, not another permission engine |

Current criteria are operational rules, not a calibrated expected-return model.
Document claims such as energy exhaustion, stop hunting, inevitable gap fills or
four-axis agreement implying high win probability are NOT implemented as facts
or automatic positive points. OHLCV cannot reveal all participant identities or
resting stops. Such hypotheses require explicit definitions and out-of-sample tests.

## Implemented Foundation

- `decision_brief.py`: one non-mutating presentation contract for data basis,
  market restriction, individual signal, account execution and conditional response.
  Uses existing readiness; no calls to scoring or providers. Missing prices,
  dates/weights remain unknown. Zero weight remains zero.
- `decision_workspace.py`: shared renderer in Today, board, precision (including
  demo) and portfolio. Separate scoped captures in the scenario workspace;
  timestamps and price basis remain attached to the original whole source row.
  No cross-source value splicing or inference that equal dates mean equal inputs.
  Selections survive Streamlit widget cleanup, with invalid options/account scope
  reset safely. Known timezone-aware calculation times display in KST; naive
  times are not guessed. Stored timestamps and numerical inputs stay untouched.
- Scenario page now separates conditional response from portfolio stress.
  The old stress body is extracted intact into `render_portfolio_stress_scenario`.
  Its arithmetic, multiplier assumptions and controls are unchanged.
- Existing first-entry condition, target and stop are shown as screening-plan
  references. They are not new entry prices, observed events or win rates.
  Direct chart/final-review navigation uses the existing precision selection API.
- Raw precision role table says screening gate / before final check. It must not
  be read as permission after a final veto elsewhere on the screen.
- Standalone market/macro navigation exposes the existing 33 observations in
  seven groups without generating a market report. Explicit group/period refresh
  captures data; chart mode/symbol reruns reuse it with the retrieval timestamp.
  Captured availability is labelled as of retrieval, not revalidated freshness.

## Reference Website Coverage

Inspected live: https://assetx2-dashboard.vercel.app/ on 2026-11-20.
Reuse the organized indicator groups, source/unit/date visibility, chart periods,
drawdowns and direct navigation. Existing macro_monitor already covers its core
33 observations, including liquidity/credit/options and country ETFs.

This is NOT a certification of the reference site's data. Its visible liquidity
cards showed total assets 6.74T with a weekly change labelled -17.4T, illustrating
why unit conversion must be independently verified. Do not copy thresholds,
unqualified causal prose, creator-channel feeds or proprietary branding.
CNN connection, Cboe ratio history and long Korean regular history have documented
limits. A direct chart is not a promise of real-time licensed market data.

## Locked Work Order

1. **Framework / response contract (this change).** Same role vocabulary and
   readiness rule in four views; scoped source comparisons; independent macro
   navigation; no hidden provider calls in conditional views/chart mode reruns.
2. **One original numerical plan.** Audit the queue's first-entry choice against
   the detailed precision plan. Ordinary non-waiting poor-R/R paths currently use
   different branches. Capture both, compare fixed inputs, choose/document an
   authoritative plan before changing numbers. Then reuse it, rather than add
   another formula. This is the single next implementation task.
3. **Observation continuity.** Retain verified closes only for the exact
   instrument/session/price-kind key; handle official revisions explicitly;
   display missing constituents and stable breadth denominators. Separate
   continuous futures, settlement and intraday reference prices. Audit special
   session calendars and every gate component's input timestamp.
4. **Canonical events and claims.** Store issuer/speaker/source sentence/period,
   event ID and lifecycle. Reuse confirmed earnings and listing states across
   calendar, narrative and evidence views. Reject contextual keyword collisions,
   promotion and multi-issuer claim leakage. DART transport is one dependency in
   this work, not the entire product roadmap.
5. **Performance and strategy validation.** Measure collection, cache misses,
   assembly and rendering separately. Compare identical fixtures/conditions.
   Only after inputs/plans agree, evaluate existing criteria by product/timeframe
   with out-of-sample trades, costs, gap risk and uncertainty before proposing
   threshold changes. Keep leverage day-reset and Bitcoin trading clocks separate.

Do not restart this order for every new report critique. Attach new evidence to
the relevant contract. Exceptions: wrong financial numbers, sign reversals,
fabricated/misassigned facts, privacy or execution-safety bugs take priority.

## Review 58 Triage

The supplied critique is output evidence, not proof of each provider root cause.

| Reported issue | Contract / verification still required |
| --- | --- |
| US closes 74 to 51; cybersecurity breadth shrinks | Observation continuity / exact same-day replay with missing/stale responses |
| Gold/silver same-date values change | Price kind, contract and observation/revision identity; do not call continuous quotes settlement |
| Three-company article leaks facts | Sentence-level issuer and speaker attribution |
| Securities forgery becomes oil; loan promotion | Contextual eligibility before market classification |
| Completed IPO remains planned | One event lifecycle across all output consumers |
| Repeated executive/rates stories | Event-level deduplication, not only URL/title |
| Gate/quote dates and special KR close | Explicit component clocks and exchange schedule; compare like with like |
| Japan CPI, EWY/night futures absent | Coverage gap, not synthetic data; assess priority after core contracts |

These remaining issues are not declared fixed by a presentation framework.
The new response panel is not a predictive support/rebound strategy, and its
screening references are not yet the unified detailed execution plan in step 2.

## Verification

- Focused decision/workspace/preservation tests: 82 passed. After the final saved
  freshness-label correction, the 46 workspace/integration tests passed again.
- Frozen-source correctness gate: `scripts/check_refactor.py --scope all`,
  1,820 tests, zero failures/errors/skips, 201.566 seconds. Evidence:
  `cache/refactor_checks/all_6pr0tjk9/summary.json`. No code changed during this run.
  Two earlier runs had zero test failures but were rejected because source edits
  occurred during the run; those are not used as the passing gate.
- The integration test compares the extracted stress function body to base
  2fbf3134 and verifies all four view connections. AppTest proves explicit macro
  collection and reuse on symbol/mode/group/period changes, with unchanged gates.
- These are selected correctness contracts, not a complete repository test run,
  a speed benchmark, strategy profitability validation, or complete site parity.
- Operating verification of 7c3c50d5 after reboot: direct macro view queried on
  request, produced a nonblank 250-observation S&P chart, and kept the same query
  timestamp when changing to drawdown. KOSDAQ/Bitcoin late observations visibly
  stayed labelled late, not current. Narrow 536px browser layout checked.
- A new Today run calculated 95 symbols in 88.8 seconds (single live observation,
  not a controlled speed comparison). SOXL's existing market-defense restriction
  was displayed consistently in Today, portfolio, board and precision. The
  scenario shortcut opened SOXL precision and its chart/final check.
- Live navigation exposed a selection reset when returning from precision; added
  a non-widget selection store and an AppTest covering leave/return and account
  changes. Final focused run: 80 passed (workspace, integration, portfolio holding
  review, macro monitor, formatters), 12.69 seconds.
- Final frozen-source gate after the navigation/time-format fix: 1,820 passed,
  zero failures/errors/skips, 205.946 seconds; evidence
  `cache/refactor_checks/all__gjbnona/summary.json`. No changed source during run.
- Final operating selection-persistence verification follows the follow-up push.
