# Data and Explanation Audit - 2026-11-20

Base: 12269b6b, main. User approved broader repair, direct operating inspection,
reboots, commit and push. Private attachments and account exports are not in Git.

## Root Causes and Changes

1. Korean report closes used provider final trades, not exclusively regular-session
   closes. The new report-only `kr_regular_history.py` reads the explicit
   `regularMarketClosingPrice`, validates base/change and completed sessions,
   preserves gaps, and never splices aftermarket OHLC into those close histories.
   A missing previous trading day is not a multi-day daily return. Report quote
   repair cannot overwrite the verified regular series with a final trade.
   The main investment engine's histories and scoring thresholds are unchanged.
2. The exchange-calendar library omitted the 2026-11-19 special Korean session.
   The report calendar uses the official 10:00-16:30 session and a 15-minute
   collection grace. Source:
   https://kind.krx.co.kr/external/2026/11/05/000141/20261105000216/99303.htm
   Npay documents KRX aftermarket/final-price semantics here:
   https://help.pay.naver.com/faq/content.help?faqId=18245
   Do not claim that every historical final trade was necessarily an NXT trade.
3. Successful financial fetches could still replace saved evidence with older
   statements. `financial_refresh.py` checks annual and quarterly periods
   independently. Explicit US FMP refresh also compares one cached SEC statement
   set, selecting it only when verified periods are non-regressing, strictly newer
   in at least one dimension, and existing completeness checks pass. No provider
   field splicing, changed ratios, inferred quarter dates, or changed manual score.
   The scorecard labels external valuation retrieval separately from saved-score
   statement periods; retrieval time is not a publication date.
4. Precision chart events, execution checklist and top decision used different
   display contexts. They now share the existing final-check-qualified context.
   `precision_observation.py` displays structure, price location, duration and
   liquidity proxies from captured inputs only. Retired channels are excluded as
   current entry guides. These four axes do not add score weights or trade signals.
5. Cybersecurity aliases were incomplete, and common IPO/AI/rate stories repeated
   across industry rows. Add registered-company aliases/classification, require
   direct cybersecurity evidence, and show common body evidence once separately.
   Whole-market investor flow is not industry flow. Listing news differentiates
   planned, withdrawn/postponed and reported post-listing trading, without fixing
   a particular issuer or inventing an official listing date.
6. An earlier unfinished article-body trust fix is retained: source mismatch,
   unavailable body and inconsistent future/version timestamps are not verified
   body evidence. Korean reported earnings-beat word order is supported too.

## Reference Dashboard Coverage

Inspected https://assetx2-dashboard.vercel.app/ . Implemented a separate on-demand
macro observatory in Today > Market: 33 observations in seven groups, source links,
observation dates, units, level/drawdown charts, 1/3/5/10-year controls and raw rows.
Only the selected group is fetched; bounded workers and success/failure caching
avoid adding all 33 queries to each report or precision render. Financial units
are normalized explicitly, not by magnitude guessing. This is functional coverage,
not a copy of the site's branding, proprietary data or creator feeds.

Public local probe: 32/33 numeric observations connected. CNN returned HTTP 418,
which stays missing, not zero or a substituted sentiment index. Cboe total put/call
is one dated official observation; historical series is unconnected. Korean
explicit regular history is limited to 100 observations. Delayed completed daily
bars are labeled using the expected completed exchange date. FRED observation
dates are not release dates. No claimed investment edge or new gate is implied.

## Test Failure Classification

The previous 16 report failures were four actual body-evidence trust/display cases
and twelve stale contracts or mock-isolation cases. The stale cases included
per-section citations (not duplicate whole reports), approved macro-first section
order, historical instrumentation-only AST contracts, current-day headline scope,
and new regular-history dependency isolation. Keep date/sign/source assertions.

The expanded integration run initially found five additional failures: four old
entry-plan wording expectations predating approved commit 70ad0493, and one
regular-loader mock. Exact approved wording and whole-plan numeric/status equality
are now checked, including input immutability. No golden files were regenerated.

The separate all-scope preservation gate initially passed 1,814 tests and failed
six stale contracts. Four compared every current app function with an old
extraction snapshot, including unrelated subsequently approved changes. They now
prove the complete historical extraction against its parent, and compare current
owned functions exactly to that approved extraction. Two expected calls omitted
the session-comparison kwargs introduced by 2fad1460; default and explicit ticker
forwarding are now both exact assertions. Targeted/adjacent 331 passed and 8/8
in-memory owned-function mutations were rejected.

Expanded report/earnings/financial/precision/article integration: 2,728 passed in
112.95 seconds. Later request-context propagation and actual-provider link checks
passed their focused suites (76, then 131 article/source and 30 macro/regular-close
tests). Financial task suite: 228 passed. Final `check_refactor.py --scope all`:
1,820 passed / 0 failures / 0 errors / 0 skipped, 187.954 seconds, source hashes
unchanged (`cache/refactor_checks/all_n4ksofx1`). Operating verification follows
below. These are correctness tests, not speed benchmarks or a whole-repo pass.

Public ETF probe also confirmed explicit 2026-11-19 regular closes for 379810,
379800, 418660, 396500 and 0167A0, rather than validating only ordinary shares.
Article parser cache revision is v13; the six-hour success TTL is unchanged.

Code commit f6d75028 was pushed to origin/main. Owner-authorized Cloud reboot
started at 10:35 KST; the server was ready at 10:36. Operating proof follows.

Operating discovery: after machine reprovisioning the Today calculation was not
restored. `today_snapshot.py` persists these results only under server-local
`cache/`, unlike the separately stored account data/history. Account holdings were
still present. Do not claim the pre-reboot 95-row export was restored or compare a
fresh live calculation as if its market inputs were frozen. The unchanged-input
guarantee is covered by the offline preservation gate; report-generation mutation
checks should use exports immediately before/after that generation.

## Operating Verification

- Fresh Today full calculation completed in 82.1 seconds. New report generation
  completed normally in 78.689 seconds; including its preceding script work,
  102.538 seconds. These are different scopes and neither is a controlled
  before/after speedup. Report stages: prices 24.401, official data 18.857,
  assembly 18.795, persistence 11.184, news 2.160 and bodies 2.186 seconds.
  The subsequent `interrupted` script was a rerun; the separate generation
  measurement is completed with no termination exception. Its report SHA matches
  the downloaded document exactly.
- Report 10:45 KST: generation6447d5a500ed, measurement
  e11268c2d59f47108e6436fa942af04a, loaded source b883ec67223e02e8.
  All114 loaded/disk/Git source hashes match f6d75028; restart_required=false.
  Korean company rows show 11/19 regular Hynix +3.41%, Samsung +1.13%; common
  IPO/rate body evidence is separate from industry-specific rows. The current
  KR/US/portfolio three-line summary retains unavailable-coverage withholding.
- Before/after generation exports each contain95 rows. The18 checked core
  columns (prices, adjusted score, final decision/code/group, R/R, target, stop,
  first entry/condition, shortage, gate/state/reason, current/target weights,
  execution guidance and entry conditions) are identical. Do not claim complete
  file equality:49 analyst-status rows refreshed,15 flow-warning texts and2
  flow-context texts changed, and unheld NVDA quantity normalized NaN to0.
  No held quantity changed. These live external enrichments are not frozen tests.
- GOOGL precision screen: top execution, pattern checklist, observation summary,
  entry plan and final check all withhold execution for market defense. The
  four-axis table displays captured structure/location, an8-bar double-top
  formation window, provisional confirmation, and missing live volume separately.
  Chart is nonblank; existing channel geometry was not redesigned or certified
  across all tickers. Existing 1R target uses the first planned entry.
- GOOGL automatic financial refresh was exercised at10:50. Score remains4;
  annual2025-12-31 and quarterly2026-09-30 remain, providerFMP. Recalculation time
  advances; latest-publication verification is still explicitly unconfirmed.
  This live case proves the equal-period path, not a live newer-SEC transition
  (covered by regression tests). Saved-score periods and external scorecard
  retrieval timestamps are visibly distinct.
- Macro observatory works in production:7 groups, source/unit/date table and
  nonblank Fed/liquidity chart. Delayed Korean index bars are visibly labeled
  against expected11/19, rather than called current. Actual browser viewport
  was536x931; a requested desktop override did not take effect, so no desktop
  breakpoint verification is claimed.

Private evidence (ignored, not committed):
`cache/operating_20261120/{macro_observatory,precision_observation,precision_chart}.jpg`;
Downloads `stock_lab_market_report (48).md`,
`auto_report_e11268c2d59f47108e6436fa942af04a.json`,
`stock_lab_review_export_20261120_1041.zip`,
`stock_lab_review_export_20261120_1045.zip`,
`precision_review_GOOGL (2).zip` and `(3).zip`.

## Limits / Next Work

This is not proof that every market-moving event or chart pattern is correct.
Official quarterly release discovery still has a finite source registry; finding a
news mention does not make its figures verified official results. Japan CPI, IPO
offer/first-print/close details, EWY/night futures coverage, and the legacy engine
price-source scope need separate validated work. Missing values stay missing.
No full-run speedup is claimed from unmatched live runs or function-call totals.

Observed unresolved cases: US gate/price histories include11/18 while the report
indices have11/19; the report withheld all74 US company daily comparisons instead
of filling them. The live report confirms only6 official earnings issuers out of
75 inspected, with0 newly linked reported releases. Alias coverage alone did not
solve discovery. A copper article still received an over-broad AI funding
interpretation, and some closing-news headlines remain next-session material.
These are not corrected by the new regular-close loader. GOOGL financial refresh
also normalized free exploration to its registered option for the same ticker;
the raw signal changed with its registered context/live quote while execution
remained blocked. Do not describe those separate inputs as identical parity.
Reproduce on frozen inputs before changing investment logic. Today cache
durability and full chart-geometry validation also remain open, not completed.

Exactly one next bounded task: generic official quarterly release discovery and
period lifecycle, tested on a frozen multi-sector release set, starting from the
existing earnings pipeline without adding issuer-specific report prose.
