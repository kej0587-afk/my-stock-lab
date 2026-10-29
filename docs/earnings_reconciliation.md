# Earnings schedule / result reconciliation

## Scope

This is a report-only change. Candidate grades, execution gates, scoring,
portfolio quantities and trading rules are unchanged. No orders are sent.

The prior calendar checked announcement pages but never replaced a scheduled
release with the corresponding published result. A passed call time therefore
remained unconfirmed even when the report had already collected result news.

## Data contract

- Match issuer (including share-class aliases), fiscal period and release date.
- A fetched, validated official result promotes the event to `released`.
- An attributed result headline matching the issuer, quarter and date window
  becomes `reported_results`; official figures remain unconfirmed.
- A preview, elapsed date, another issuer or another quarter cannot confirm a
  release. Publication timestamps and collection cutoffs must not be future.
- Revenue, profit/EPS, CAPEX, FCF, management guidance and price response are
  separate fields. Missing is not zero; outlook is not an actual result.
- Source wording retains currency, period and GAAP/non-GAAP qualifications.
  Alphabet cash flow uses the explicitly labelled quarter, not YTD or TTM.
- A date-only result does not inherit its conference call's timestamp.
- Existing timestamped quote observations may describe a regular or extended
  session move. This is not an event-study return or causal attribution. A
  headline's cash-flow decline cannot be interpreted as a stock-price decline.

## Collection and limits

The collector is bounded to existing connected issuers and verified official
result URLs/periods, not an all-company or next-quarter discovery service.
NVIDIA's future call is not a published result. Calls are made only during
explicit report context collection, with three workers, bounded timeouts,
six-hour success caching and a short failure cooldown. Rendering does no I/O.

A transport failure may show a labelled, time-bounded last successful result.
Changed or contradictory evidence invalidates that fallback. These caches are
process-local; a restart without another successful fetch cannot recover them.

Source diagnostics distinguish failed access from missing result coverage.
New modules participate in the existing loaded-source fingerprint check so an
old running renderer cannot silently claim the new build.

## Verification

Offline regression fixtures cover schedule/result distinction, issuer and
fiscal-year matching, duplicate aliases, wrong periods, future publications,
source allowlists, quarter-vs-TTM cash flow, missing/deferred fields, stale
fallback, cache isolation, bounded fetching, actual quote schemas and unchanged
input objects. Report integration checks collection once and rendering without
refetching. Live source retrieval is checked separately from synthetic tests.

2026-10-29 verification: 2,818 tests and 18 subtests passed. Live source checks
connected SK hynix, Meta and Microsoft. Alphabet/SEC and Tesla returned HTTP
403; Samsung timed out. Those failures are not a claim of successful automatic
coverage. Microsoft's revenue/profit were read from its result page; guidance
was explicitly deferred to the conference call. Alphabet's current-quarter
CAPEX/FCF table extraction is fixture-tested, not live-connected in this run.

## Official alternatives (2026-10-29 follow-up)

Alphabet's SEC exhibit can return HTTP 403 and Samsung Newsroom can time out.
For those transport failures, the collector now tries one issuer-linked PDF:
Alphabet's Q3 release on its Q4 CDN, or Samsung's Q3 earnings-call presentation
on its official IR asset server. The exact issuer, path and covered period are
allowlisted. A wrong-period document is rejected, not hidden by a fallback.
No redirects, arbitrary URLs or retries on a blocked SEC endpoint are used.

Each request keeps the existing connect/read timeout. PDF downloads are capped
at 8 MB and 24 pages. Successful alternatives use the same six-hour result
cache and record both source attempts. A failed alternate remains unconfirmed
unless a valid, labelled last success exists within the existing age limit.

PDF parsing is isolated in `earnings_result_pdf.py`; it does not read holdings,
alter grades or calculate a trading signal. Alphabet uses the explicitly
labelled current-quarter reconciliation, never its adjacent TTM column.
Samsung's cash-flow PP&E purchase is labelled separately from total CAPEX.
Samsung's PDF does not directly report FCF, so that field is not calculated
from operating cash flow minus PP&E or supplied by a forecast. PDF creation
time is not treated as the release time; date-only evidence stays date-only.

This remains finite, verified-period coverage, not automatic discovery of all
future quarters. Investor Day guidance is not a quarterly actual and is not
silently inserted into these result fields.

Follow-up verification: 2,845 tests and 18 subtests passed (107.34 seconds),
including 117 focused earnings tests. Independent review added conflicting
period-header regressions; a later YTD table cannot inherit a quarter header.
At 2026-10-29 13:23-13:27 KST, the production collector reproduced SEC 403 and
Samsung Newsroom ReadTimeout, then retrieved both official PDF alternatives.
Alphabet returned Q3 revenue/operating income/CAPEX/FCF from pages 1/8;
Samsung returned Q3 revenue/operating income/PP&E cash purchase from pages
5/15, leaving FCF missing. Actual report rendering confirmed those source
pages and the distinction between PP&E cash outflow and company total CAPEX.
These local live checks do not assert Cloud deployment completion.

## Strategic outlooks: Oracle pilot

Investor Day is now a separate `official_outlooks` report context, never an
earnings-result event or an input to scores, gates, orders or the watchlist.
The common event contract preserves issuer, event kind, publication date,
observation time, field-level evidence and source URLs. Issuer-specific
discovery/parsing stays outside the report renderer and `app.py`.

The Oracle adapter reads the public news feed used by its official IR widget
and follows at most one Investor Day article. It scans the latest 60 notices
for the last 90 days; future dates, event invitations, quarterly releases,
foreign URLs, mismatched titles/dates and unrecognized layouts are rejected.
This is not a universal corporate outlook crawler, nor a claim that later
quarterly guidance has not superseded the Investor Day outlook. A new issuer
requires its own verified adapter and fixtures, not a copy of the renderer.

CAPEX, FCF and additional funding are labelled company plans. Financing
exclusions and already-completed ATM funding remain distinct: a funding
ceiling is not shown when its scope cannot be verified. Missing or changed
wording is not inferred from a prior release. The semiconductor implication
is conditional on physical orders/deployments, with customer-owned hardware,
financing and other customers' investments identified as alternative factors.

Collection runs only during explicit report-context generation. It adds at
most two bounded requests (2-second connect / 3-second read timeout, 2 MB per
response, 10-second checked collection budget). Success/partial results use
a six-hour process cache; failures use a 60-second cooldown. Concurrent
sessions do not wait for the network or launch duplicate fetches. The report
renderer performs no I/O and rejects future or over-one-day-old observations.
No manual financial numbers or fabricated publication minute are inserted.

2026-10-29 live check: official feed and article returned all five fields in
1.00 second. The article identified FY27-FY28 peak CAPEX / FY29 reduction,
H2 FY28 positive FCF / USD 30 billion+ FY29 target, and the USD 20 billion
incremental funding limit with exclusions. Values were read from the live
article, not from production constants. Final regression: 2,878 tests and
18 subtests passed (107.34 seconds); 33 new synthetic tests cover isolation,
missing data, scope, dates, URL restrictions, failure/cache paths and display.
Independent review found conditional sentence tails and prior-cycle financing
exclusions could be lost. Whole-sentence matching and adjacent current-plan
scope validation now reject both cases; live extraction remained confirmed.
