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
