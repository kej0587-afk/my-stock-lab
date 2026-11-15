# Report coverage follow-up — 2026-11-15

Base: f78c6fd2, origin/main matched at start; company edits and the preserved
Nov08 Customs stash remain intact. User clarified that the Nov13/14 examples
define required breadth, not just layout. No supplied article numbers were
hardcoded as current market facts.

## Causes and changes

- Main reading path previously cut KR/US news at four, each theme at two, and
  earnings at four issuers. Comprehensive mode now retains distinct validated
  articles and verified body facts. Legacy default selection remains unchanged.
- Independent events at the same issuer or central bank must not disappear
  into a broad theme cluster. Exact URL/title duplicates are removed; global
  context and post-close evidence retain their own publication window.
- New pure report_coverage module displays every collected base-sector ETF,
  rather than only top/bottom and a fixed technology subset. SOXX/SMH duplicate
  exposure is suppressed. Same-day market-relative comparisons reuse the
  existing evidence rules. Representative/registered company returns show a
  count of available observations, never a fabricated market-wide top100 count.
- Earnings can display all collected issuers, with revenue/EPS, guidance and
  cash/investment metrics together. Missing consensus stays missing. Recent
  economic releases retain their reaction column and no longer drop at three.
- Central-bank official results and Korean market safeguards remain visible
  in the main reading path. General post-close news no longer requires one of
  the fixed company tickers, so Fed reports and other issuers can be included.
- Broad market/earnings queries replace six-AI-company and election-heavy
  wording in existing query slots. Request limit/order/reservations/TTLs stay
  unchanged. Query coverage is not a guarantee that every event is retrieved.
- Russell2000, US natural-gas futures and dollar index join the existing batch
  price path. Gas/dollar are report-only, excluded from rotation/decision inputs.
  Existing 10Y day_change_bp and other macro day_ret are displayed alongside
  their separately labeled one-month comparison. Sources and units are retained.

No scores, gates, allocation, source-ranking rules or existing TTLs changed.
Three additional price symbols may add cache misses; this is coverage work,
not a claimed speed improvement. Rendering itself adds no network requests.

## Verification

Focused coverage/evidence suite: 258 passed / 9.02s before final legacy-board
contract adjustment. Offline fixture report generated under ignored
cache/report_coverage_20261115/sample; not a current market report.
Earlier decision execution had 1369 passing assertions but was marked BLOCKED
because tests changed while running; it is not the final stable gate.
Stable decision gate: 1369 passed / 223.697s, decision_svqclgk3; concurrent test
jobs make this unsuitable for speed comparison. Final focused suite281 passed /
9.52s, including twelve historical report digest cases with the original board
isolated from the three intentionally added symbols; no golden values changed.
Report gate207 passed /1 pre-existing theme-selection whole-app AST failure,
45.596s (report_96mub2iu). Subsequent report-only morning-story/citation fixes
passed the focused suite; score modules remain unchanged.
The source probe returned 250/250/251 rows for DXY/NG/RUT through the real batch
loader, latest Nov13 for each, in2.961s. No local-to-Cloud speed equivalence claim.

Production baseline revealed another coverage/accuracy defect: a morning-rally
article was selected as background for a negative KR close, and summary citations
hid detailed facts below. Morning-only snapshots are now excluded from closed
market synthesis, while independently timed news remains available. A wrap that
explicitly describes the later closing reversal is still valid.

## Coverage limits

The existing collector still has category/60-row budgets and a bounded article
body budget. Company-material query creation still depends on technology
exposure. Some official result collectors depend on dated IR schedules.
2Y Treasury, European gas, option gamma/0DTE positioning and KOSPI night futures
do not have complete automatic numeric source connections here. Those values
must not be inferred from the user's examples, a 13-week bill or an ETF proxy.
Verified news can describe these issues, qualified as source claims; it does
not substitute for a same-session numeric observation or prove price causation.

Data-source symbol references checked 2026-11-15:
- https://finance.yahoo.com/quote/%5ERUT/
- https://finance.yahoo.com/quote/NG%3DF/
- https://finance.yahoo.com/quote/DX-Y.NYB/

## Deployment

Pending final commit and production regeneration. Pre-deployment live full
Today Check78.2s; report58.3s, ID62070e9d8d4f45089f56ff86e6621ed4. Downloaded report
and matching timing retained in ignored cache/report_coverage_20261115. The IAB
Cloud Linked accounts page explicitly reports no source-control sign-in despite
email authentication. Reboot is authorized but access is not established.

Code50551641 was committed and pushed to origin/main, confirmed0/0 divergence.
Post-push app reload reached the authenticated asset page but did not regenerate
a report. The attempt to select the user's existing Edge management window was
stopped because the browser tool could not establish its current URL. Stopped
browser work immediately; no reboot, no after-generation timing, and no claimed
post-deployment UI/data verification. Next task remains production coverage
validation after a supported authenticated management connection/reboot.
