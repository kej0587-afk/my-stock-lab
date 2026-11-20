# Official Earnings Discovery, 2026-11-20

## Scope

Base `0a8bbb73`. Report-only collection and evidence reconciliation. No investment
threshold, score, price, allocation, trade order or golden baseline changes.
This is not completion of the wider dashboard/chart/news backlog.

Previously the report submitted a fixed seven-company front list, followed by a
finite issuer/quarter URL registry (32-request cap). Updating names/news aliases
could not discover a new official earnings release or advance its fiscal period.

## Changes

- Holdings/watchlist issuer catalog drives discovery, held issuers first. ETFs,
  cash and duplicate share-class aliases are excluded from company filing requests.
- SEC company directory -> matching CIK/ticker submissions -> latest eligible
  Item 2.02 8-K -> same-accession Exhibit 99.1 -> issuer/result heading, explicit
  fiscal quarter and release dateline checks. Filing acceptance cutoff is checked;
  acceptance time is never presented as the announcement time.
- US releases expose reported revenue/profit/CAPEX/FCF separately from management
  outlook. Outlook bullets inherit their explicit forward-looking section; they
  cannot supply missing realized figures. Missing values remain missing.
- Existing verified IR parsers/fallbacks remain. Matching-quarter, matching-day
  cached evidence is retained without a second download; it cannot migrate into a
  newer quarter. A separate later confirmed call time is retained.
- DART company-code mapping -> periodic disclosure list -> latest explicit report
  period. Receipt date is labeled as receipt, not earnings announcement. Fiscal
  quarter and numerical results/outlook remain unconnected in this new generic KR
  path; the old verified IR results are not replaced by invented numbers.
- 3 workers, 24-second cold discovery budget, 10-minute issuer cache, 90-second
  failure cache, 24-hour directory cache. SEC requests are spaced 0.2 seconds.
  Every requested issuer has a result or reason; the 96-issuer hard limit and time
  deferrals are explicit. Render-only paths never invoke discovery.
- A new result is bound to its verified issuer/accession/event source; arbitrary
  same-host URLs are not accepted as matching result evidence.

## Verification

Synthetic multi-sector tests cover fiscal/non-calendar quarters, publication
versus filing dates, wrong issuer, preview/future rejection, source path boundary,
missing annual/segment/forecast actuals, outlook bullets, amendment/current-period
selection, source cache reuse, historical cutoff, DART receipt labels, report
connection and input nonmutation. Two old orchestration tests were updated because
the approved discovery contract intentionally removes the fixed seven-company
front list and uses a bounded generic issuer list. Golden fixtures unchanged.

Initial focused integration: 232 passed. Later focused integration: 237 passed.
Selected preservation gate: 1820 passed / 0 failed / 0 skipped, unchanged source
hashes during the run (`cache/refactor_checks/all__lrpeps8`, private local output).
Final checks and operating deployment evidence are appended below.

Live public-source probe at about 11:16 KST (not portfolio performance):
six issuers MSFT/GOOGL/AMZN/PANW/WMT/CAT, cold 4.448 s; warm 0.021 / 0.024 s.
Three discovered result documents, three explicit-period parser deferrals.
PANW: 11/18 release, FY2027Q1, revenue/profit/FCF/outlook connected; CAPEX missing.
CAT: 10/29 release, 2026Q3, revenue/profit/outlook connected; CAPEX/FCF missing.
GOOGL: 10/28 release, 2026Q3, revenue/profit connected; cash/outlook missing in
the current HTML parser. MSFT/AMZN retain existing verified IR fallback coverage.
WMT title lacks a four-digit fiscal year; do not infer it from filing date or FY27
outlook. JPM's large exhibit exceeded the bounded document size in a separate
probe. These are known extraction gaps, not claims of missing earnings releases.
The probe used only public issuer identifiers and a StockLab identification UA;
no account amounts or credentials were sent. It is not a before/after full-app
benchmark, and success on these issuers does not establish all-market coverage.

Official API references:
- https://www.sec.gov/search-filings/edgar-application-programming-interfaces
- https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019001

## Remaining Boundaries

- SEC 6-K/foreign issuers, some styled/periodless headlines, large exhibits and
  unsupported tables remain explicit gaps. No guessed quarterly URL/calendar.
- Generic KR periodic filings currently confirm the document/period only, not
  per-quarter numerical actuals, earnings call timing or forward guidance.
- Source errors/time budget must remain visible. Do not turn missing evidence
  into zero, a bad result, or a trading prohibition/permission.
- Data discovery does not provide earnings-surprise consensus or event-only
  causal attribution. Existing price-reaction/session guards remain in place.
- Wider delayed-US-history, chart geometry, news causality, and Today cache
  durability issues from the preceding audit are not resolved by this work.
