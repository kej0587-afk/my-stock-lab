# October 29 dashboard and news audit

## Scope

Preserve signal scores, thresholds, price dates, market gates and brokerage
settings. No orders. Retire the optional event-ledger UI and report section;
keep its storage module/schema and any existing records intact.

## Confirmed causes and changes

- Regular-close facts omitted important subsequent company releases. A separate
  post-close evidence block now feeds the headline and story, with publication
  timestamps and sources. It never explains an earlier close with later news.
- Add up to four issuer queries inside the existing sixteen-query budget.
  Report and precision news share the bounded RSS cache. Distinguish reported
  extended-hours reactions from verified prices and verified company figures.
- CIBR news can follow F5/Fortinet earnings and guidance, not only the ETF name.
  Canadian CIBR:CA evaluation articles and consumer deposit promotions are
  excluded. Short ticker matches cannot match arbitrary words or publishers.
- CIBR membership is a partial, dated official snapshot, not a complete live
  holdings feed. Current-membership claims expire on November 3 KST. Cybersector
  company searches remain available without asserting current membership.
  No constituent's ETF price contribution is inferred from a headline or weight.
- KOSDAQ sector investor-flow responses were stored but not consumed by the
  report. Both markets now have explicit missing/failure/mock/stale reasons.
  Preserve the five-minute limit and do not sum overlapping sector totals.
- The live mock sector table also displayed -301 as a percentage. The official
  ka10051 example uses implicit hundredths while its field description says
  formatted percent. Validate the rate against current price and signed prior
  change; accept /100 only when it uniquely matches within 0.005 percentage
  points. Otherwise retain an explicit decimal rate without contradictory
  price evidence, or show missing with the original value and reason. Never
  apply /100 unconditionally. Investor-flow amounts are unchanged.
- Replace the briefing's long change list with holdings-first counts and
  compact before/after/reason tables; keep full reasons in a collapsed section.
- Default screen captions previously showed US closed even during KR trading.
  Reuse the existing KR/US session helpers and call the clock a screen retrieval
  time, not the underlying price observation time.
- Correct misleading holding explanations: price RS does not prove actual
  capital flows; an ETF is not free of issuer/structure risks. Scores unchanged.
- Scenario bug: `SH` matched `iShares`/`ProShares`, incorrectly reversing some
  long ETFs. Use token boundaries for inverse ticker abbreviations, preserving
  the intended inverse and leveraged multipliers. This corrects scenario
  arithmetic, not the investment-decision engine.

## Evidence checks

- [Alphabet Q3 SEC release](https://www.sec.gov/Archives/edgar/data/1652044/000165204426000080/googexhibit991q32026.htm):
  revenue $127.577bn; operating cash flow $42.290bn; capex $51.355bn; FCF
  -$9.065bn. Q2 FCF was also negative: do not call Q3 the first negative quarter.
- [F5 October 27 release](https://investors.f5.com/news/news-details/2026/F5-Reports-Fourth-Quarter-Results-with-23-Product-Revenue-Growth/default.aspx):
  FY2027 revenue-growth outlook 8-9%. Consensus disappointment requires a dated
  consensus comparison; growth alone is not proof of either a beat or miss.
- [Fortinet October 28 release](https://www.fortinet.com/uk/corporate/about-us/newsroom/press-releases/2026/fortinet-reports-third-quarter-2026-financial-results):
  annual billings guidance raised. Do not merge this into a generic downgrade.
- [First Trust official fund holdings](https://www.ftportfolios.com/Retail/Etf/EtfHoldings.aspx?Ticker=CIBR):
  October 27 membership confirms FTNT/FFIV/MSFT/GOOGL. A same-day ETF return
  attribution, analyst downgrade original and options traders' intent were not
  independently established.

These dated results are audit evidence, not numbers hardcoded into the report.
The app's LLM hook remains a placeholder. This change improves bounded retrieval,
entity/session linking and rule-based interpretation, not a full LLM newsroom.

## Live UI verification

Authenticated assets, today, board, portfolio, precision, scenario and short-term
pages were visited. Portfolio/scenario/short-term analyses completed without a
visible exception. GOOGL/CIBR precision showed aligned entry deferral across the
top, plan and final-check areas; a holding assessment is a separate question.
Weekly/monthly period-end labels were explicitly distinguished from actual bars.
Not every ticker, chart pixel or provider price was independently audited.

Kiwoom ka10032, ka90001 and ka10051 returned tables in the configured mock
environment. This is successful read access, not verified real-market investor
flows. No credentials, account quantities or provider environment were changed.

## Performance

The uploaded full calculation took 99.32s. Price-history activity covered 33.72s
and latest quotes 26.72s; these intervals overlap and must not be summed.
728 history calls and 133 quote calls are instrumented calls, not necessarily
network requests. A separate rerun ended normally, not with an application error.

Move price preloading out of app.py. Reuse existing KR transport per worker
within one batch, join workers before closing sessions, and keep the app's
instrumented loaders. Source order, TTLs, fallbacks and concurrency unchanged.

Controlled three-run benchmark: 24 tickers, four workers, fixed simulated 30ms
connection cost and 5ms request cost. Exact frames, metadata and requests match.

| Run | Before ms | After ms |
| --- | ---: | ---: |
| 1 | 451.839 | 262.793 |
| 2 | 455.844 | 286.957 |
| 3 | 479.955 | 312.696 |
| Mean | 462.546 | 287.482 |

Requests remain 24; connections fall from 24 to 4. This is a synthetic transport
comparison, not a measured reduction of the Cloud 99.32s calculation.

## Validation boundaries

Regression coverage includes delayed/future/wrong-market news, CIBR expiry,
no inferred causal attribution, flow freshness and mock exclusions, unchanged
hold scores, inverse ETF identity, session cleanup and real Streamlit cache
execution. Full suite: 2,733 passed plus 18 subtests in 111.08s. A separate
Kiwoom/integration set passed 56 tests. These are verification durations, not
production calculation times. Deployed-source results are in the task close-out.
