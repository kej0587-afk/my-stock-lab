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

Final focused integration: 238 passed in 14.04 seconds (filing discovery,
pipeline/reconciliation, official result/cash sources, ETF issuer evidence,
report review and catalyst presentation). Final preservation gate: 1820 passed,
0 failed, 0 skipped in 200.467 seconds, unchanged source hashes
(`cache/refactor_checks/all_y48q057n`). No golden rebaseline. These are selected
regression suites, not a claim that every repository test or live issuer passes.
Code `fc9a0197` pushed to origin/main; authorized Cloud reboot at 11:26 KST.

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

## Operating Verification and Follow-up

After the authorized 11:26 KST reboot, code `fc9a0197` produced the 11:32 report
(`stock_lab_market_report (49).md`, private Downloads). Its 116 loaded/source
hashes matched, restart was not required and no stale module was reported.
Generation `96e716e0ea16499197b0a616c1d6b5f2` completed normally in 101.297 s;
the later Streamlit rerun interruption is not a generation failure. Official
earnings collection took 25.658 s, including 23.677 s bounded filing discovery.
The cold Today calculation took 89.4 s. These are observations, not controlled
before/after speedup measurements. The report checksum matched the download.

Pre/post generation review exports (11:29/11:33) retained 95 rows and all 18
compared decision/price/allocation-input fields. External descriptive enrichment
can change independently; this is not byte equality of every export field.
Official release coverage rose from 6 to 18 companies in this live run; time and
cache conditions differ. PANW's 11/18 FY2027Q1 actual revenue/profit/FCF and Q2
outlook, and NVDA's 11/17 FY2027Q3 actuals/Q4 outlook were visible in the report
and operating US earnings table. Missing CAPEX and other unparsed values stayed
missing. The narrow browser view still makes the long earnings table hard to
scan; no broad table-layout redesign is claimed.

Operating evidence identified four bounded follow-ups:
- Exclude ETF/FUND metadata even when exported rows lack the original is_etf flag
  (the TDF fund had entered the company request catalog).
- Expose DART company-identifier failures at the failing stage. Reuse the existing
  dated public identity snapshot only for transient transport failures, and reject
  expired cached snapshots. Never substitute it for financial values or mask an
  authentication/API error. The existing local public snapshot is expired; this
  fallback does not establish successful generic KR coverage in the live run.
- Reject accounting definitions/disclaimers misclassified as outlook (DDOG's
  definition of non-GAAP results was the observed case), without inventing a
  replacement forecast.
- Count DART report receipt separately from earnings announcement confirmation;
  do not promote a periodic filing receipt as a new earnings catalyst.

Follow-up focused integration: 270 passed in 16.49 s. An intermediate selected
gate had 12 report-section digest failures because a zero-count filing annotation
changed unrelated historical prose. Production rendering was corrected to add
that annotation only when filings exist; no golden was changed. Targeted
report-section/discovery/catalyst checks then passed 76/76. The final focused
integration passed 270/270 in 16.14 s. The final selected preservation gate passed
1820/1820, no errors/skips, in 197.65 s (`all_m_oiy2ps`); source hashes were
unchanged throughout that gate. Follow-up operating verification follows below.

Code `29d918b0` was pushed and rebooted with the user's prior authorization.
The 11:54 KST report (private report50, generation25fe25d49720412596d6b439f422854a)
completed in115.888s with no termination exception. All116loaded/disk/Git hashes
matched; report download SHA matched. Pre/post exports11:51/11:55 again matched
95rows/18corefields. The cold Today calculation was117.0s. Official collection
26.148s/discovery23.582s,76instrumented requests; these changing live conditions
do not support a performance improvement claim.

Operating coverage was74registered issuers,13official announcement confirmations,
12periodic-report confirmations (categories can overlap). The TDF no longer
entered the company catalog. DDOG retained its actuals/FCF but the accounting
definition was no longer reported as outlook. PANW still showed explicit FY2027Q1
actuals/FCF and FY2027Q2 outlook. Unlike the preceding run, live DART identity and
report-list requests succeeded for12companies: report receipt/period were shown
separately, not treated as announcement date or complete numerical actuals.
Other companies remained explicitly deferred by the bounded collection budget.

That newly connected DART branch exposed a display defect: some unknown-universe
issuers used the filing title as the company name. The parser now carries the
verified DART corp_name separately from report_nm; absent names fall back to the
ticker, not the filing title. Three source/pipeline regression cases cover this.
Final focused integration including report-section contracts:293pass/15.79s.
The final label-fix preservation gate passed1820/1820 with no errors/skips and
unchanged source hashes,201.32s (`all_z97aj3ek`).
