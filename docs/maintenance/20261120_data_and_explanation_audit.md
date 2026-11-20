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

## Limits / Next Work

This is not proof that every market-moving event or chart pattern is correct.
Official quarterly release discovery still has a finite source registry; finding a
news mention does not make its figures verified official results. Japan CPI, IPO
offer/first-print/close details, EWY/night futures coverage, and the legacy engine
price-source scope need separate validated work. Missing values stay missing.
No full-run speedup is claimed from unmatched live runs or function-call totals.

Exactly one next bounded task: generic official quarterly release discovery and
period lifecycle, tested on a frozen multi-sector release set, starting from the
existing earnings pipeline without adding issuer-specific report prose.
