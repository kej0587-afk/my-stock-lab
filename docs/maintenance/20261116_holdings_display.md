# Holdings Session Qualifiers

## Scope and Cause

Base: 15e86ac5. Restore holding-table timestamps, comparison qualifiers and
missing extended-session notices only. No providers, thresholds, price or
account calculations, decision functions, cache TTLs or input dates changed.

The reader projected away the comparison column and only kept the current-quote
column when some cell contained a signed numeric percentage. Thus missing
quotes silently disappeared. Closed-mode tables also appended extended-session
status only when a quote/reference object existed.

## Changes

- `report_reading.py` retains the generated holding header and every cell,
  including unknown future schemas. It does not infer a quote from a timestamp
  or replace missing values. Existing scrollable table layout is retained.
- `report_account_section.py` keeps the already computed extended-session
  missing reason in the status cell when closed mode has no current-quote column.
- Full holding rows promoted to the reader are no longer duplicated in the
  appendix by the existing exact-row deduplication. Separate caveats remain there.
- Historical golden digests remain unchanged. The old full-output test removes
  only the exact newly approved closed-session notice and checks its count;
  all other bytes, prices and decisions still match the old digest.

## Verification

- Before change: both requested regressions fail (unavailable extended quotes,
  omitted same-clock comparison caveats).
- Focused reader, document, quote, close, intraday, mixed-session and UI tests:
  133 passed, 5.91s. Historical section contracts: 20 passed, 2.67s.
- Coverage includes daymarket/pre/after-market timestamps, zero return, all
  missing quotes, unknown headers, closed mode and Streamlit reruns. Input
  snapshots are immutable. Missing observations are not forced to zero.
- Decision golden/parity plus historical report section contracts: 45 passed,
  9.80s. Private record: `cache/holdings_display_parity_20261116.xml`.
- Broad report suite: 1434 passed / 16 failed, 58.17s. XML comparison against
  the prior 1422 passed / 18 failed run shows exactly the two targeted regressions
  removed and no new failing test IDs. Ten new tests were added. Private record:
  `cache/holdings_display_broad_20261116.xml`. Remaining failures are outside this
  task (older layout contracts, incomplete mocks and news-quality gaps); this is
  not a full-suite pass or a speed benchmark.
- The selected report gate initially exposed two historical digest mismatches
  from the intentional closed-mode notice. After the exact-text compatibility
  check above, all 20 section contracts pass without changing golden hashes.
  The unrelated historical theme AST check remains a known baseline failure.

## Deployment

Operating pre-change table inspected: numeric quotes retained their dates,
but comparison qualifiers were absent from the first visible holding table.
The current queue has an input-change/recalculation warning; generating a report
must not imply fresh investment decisions. Post-push verification pending.

## One Next Task

Audit semantic duplicate news in the current report with a frozen article set;
do not change holdings, investment rules or add new data connections.
