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
must not imply fresh investment decisions.

Code1e9a538290b4 was pushed and operating-verified. Cloud invalidated the old
report; the new report was generated at 12:01 KST, loaded source
ec492c7643df180a, generation d7d69de2f01f. No reboot was needed. Private download:
`C:/Users/82amf/Downloads/stock_lab_market_report (44).md`.

Comparison with the preceding operating export (43): all seven holding names,
confirmed-close cells and status/weight cells match exactly. All seven current
quote rows retain dated KST timestamps; three same-clock comparison-unavailable
notices are restored. Each complete holding row occurs once in the report.
Newly fetched intraday prices differ; this is not a frozen-price performance or
data-provider accuracy comparison. The stale-input warning remains unchanged.

The operating run had connected extended quotes, so unavailable extended-quote
states were verified with missing-data fixtures and Streamlit AppTest, not by
claiming a live provider failure. Actual narrow-screen inspection confirmed
horizontal table scrolling reaches all restored columns without text overlap.
Private screenshots (ignored by Git):
`cache/holdings_display_20261116_comparison.png` and
`cache/holdings_display_20261116_sessions.png`.

## One Next Task

Audit semantic duplicate news in the current report with a frozen article set;
do not change holdings, investment rules or add new data connections.
