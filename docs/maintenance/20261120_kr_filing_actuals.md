# Korean Filing Actuals, 2026-11-20

Base: `7bd6e6d5`, main. Bounded report-only extraction for the existing held/watch
issuer universe. No investment thresholds, score inputs, prices, allocation,
orders or golden baselines changed. No issuer-specific financial prose added.

## Official Contracts

- [DART full financial statements](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS003&apiId=2019020):
  interim IS/CIS `thstrm_amount` is the three-month amount;
  `thstrm_add_amount` is year-to-date. CF `thstrm_amount` is year-to-date.
- [DART company profile](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019002):
  official `acc_mt` identifies fiscal close month. Match report title/end month,
  fiscal year and report code before extracting numbers.
- Require the same issuer, receipt, year/code, currency and consolidated/separate
  basis throughout the response. A restatement mismatch is missing, not an old
  value reused under a new receipt. No nearby-date announcement matching.

## Implementation

`earnings_dart_financials.py` contains pure account extraction and receipt-bound
reconciliation; `report_dart_earnings.py` contains read-only summary/detail views.
The existing bounded discovery collector fetches company profile and full
accounts. Consolidated first; separate fallback only on explicit no-data013,
not auth/quota/transport errors. Existing24second budget/3workers remain.
Company profile cache1day, receipt-scoped financial cache10minutes, failure90s.
Warm report rendering makes no new financial request.

Quarter income and cumulative cash flows occupy separate fields/columns. Annual
amounts are not Q4 amounts. Direct FCF/CAPEX accounts only; tangible asset
purchases are explicitly not total CAPEX. No cumulative subtraction, CFO-CAPEX
model, zero-filling, guidance guessing or price-causality claim.

The filing remains a regulatory receipt, not an earnings announcement. Existing
IR collection continues separately, including same-quarter announcements.
Receipt events stay excluded from catalyst calendars, cross-announcement
interpretation and event-study sampling. Report and portfolio evidence labels
retain the receipt/announcement distinction. Summary shows at most3held/watch
issuers; details show all connected reports. No score consumer changed.

## Verification

- Pre-change focused baseline:144passed/11.88s.
- Expanded extraction/collection/report/portfolio/reading integration:498passed/25.19s.
- Covers Q1/Q2/Q3/annual, non-December fiscal year, negative/zero/missing values,
  conflicting accounts, parent-specific versus total profit, currency/basis and
  receipt mismatches, future results, missing-quarter preservation, CFS/OFS,
  timeout retry/failure cache, time budget and unchanged input objects.
- Earlier preservation runs passed1820tests but were correctly blocked because
  final extraction/reading edits occurred during those runs. The frozen-source
  gate and actual operating verification are pending; do not count a changed
  source manifest as a passed gate. Final frozen-source gate:1820passed,
  0failures/0errors/0skips,198.635s, hashes unchanged (`all_hbys7a7g`).
  Actual operating verification remains pending deployment.

## Limits

Only the latest discovered periodic report per issuer is fetched, not an entire
historical quarterly series. Cash-flow quarter values are intentionally absent
when only cumulative values are reported. Custom unrecognized accounts, delayed
XBRL, receipt mismatch, API failures and exhausted collection budget stay missing.
Actual announcement date, consensus, outlook and price reaction require separate
official evidence; filing receipt cannot fill those gaps. This does not complete
all earlier audit backlog.

## Operating Follow-up

Code e7e29020 was pushed and rebooted with existing authorization. The13:11report55
completed94.634s with118loaded/disk/Git source hashes and report checksum equal,
no stale modules/restart requirement/termination exception. Its DART directory
request failed with connect_timeout. A second13:14report56 also retained that
explicit gap, rather than presenting fictional actuals. These are not successful
live numerical-connection checks.

The discovery-only directory loader now retries a transient transport failure
once, only with at least6seconds left in its original24second budget. It does not
retry auth/API/HTTP failures or consume an expired snapshot. Mapping attempt
count is recorded. Expanded integration503passed/22.62s; a new frozen-source gate
and operating retry are pending. This does not modify global DART consumers.

## Final Verification Status

Code a85be653 was pushed and hot-loaded without another reboot. The13:19report57
(generation1ec907b1c1524099956ad879ab3f4ac1) completed84.249s, with118loaded/disk/Git
hashes and report checksum equal. No stale module, restart requirement or
termination exception. Discovery still reports DART directory connect_timeout;
numerical production connection is NOT verified. No missing financial amounts
were fabricated or replaced by zero. Three generated reports encountered the
same prerequisite failure; these timings are observations, not speedup evidence.

Final frozen-source preservation gate:1820passed/0fail/0skip,204.497s,
unchanged hashes (`all_49f6rj5l`). Relevant integration503passed/22.62s. No golden
baseline regenerated. The13:09and13:20private review ZIP exports match95rows/18
core fields: price, adjusted score, reading/code/classification, R/R, target,
stop, first-entry basis/condition, allocation gap, gate/state/reason, weights,
execution guidance/condition and market execution state. This compares a single
Today calculation across report generation, not prices before/after reboot.

Operating evidence view was inspected: KR issuers retain the specific DART
company-identity transport failure; neither fictional quarter amounts nor new
announcement dates appear. Private screenshot (ignored by Git):
`cache/operating_20261120/kr_filing_connection_blocked.jpg`.

Exactly one next task: diagnose the Cloud-to-DART corporate-directory transport
failure, then verify the already-implemented quarter/YTD/receipt fields with a
successful operating response. Do not keep extending financial features while
that prerequisite is failing. Do not read/export Cloud secrets, date-shift the
expired identity snapshot, weaken identity validation, or claim API-wide outage
from these Cloud-only timeouts. Same-quarter IR/filing consolidation remains
deferred until numerical live connection is verified.
