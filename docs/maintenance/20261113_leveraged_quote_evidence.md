# Leveraged quote observation audit

Base: a477dcac, 2026-11-13 KST. Scope: SOXL, RAM, BITX, 418660.KS.

## Findings and changes

- Report quote validation checked time-window membership but not whether the
  provider field (pre/post/overnight/day) matched that window. Reject mismatches
  even for delayed references; disclose rejection instead of inventing a quote.
- Precision scalar current-price inputs have no reliable observation timestamp.
  Preserve these existing decision inputs; do not infer their session from the
  clock. A small extracted view displays separately validated quote evidence:
  actual timestamp in KST, session, regular-close comparison date and source.
- Only the selected US product uses the existing quote loader (60-second success,
  15-second failure cache, 4-second HTTP timeout). No new source or batch scan.
- 418660.KS is Korean-listed and never receives US extended/daymarket prices.
  Existing Korean current-price input remains explicitly session-unverified.
- Refresh-button time is labelled request time, not a trade timestamp. Manual
  overrides are explicitly separate from the provider observation.
- No scoring, allocation, entry/exit thresholds, channels or execution price
  inputs changed. New observations are read-only evidence, not trading signals.

## Verification

- Immutable decision gate before/after: 1367 passed (126.512s / 134.941s).
  These are test durations, not performance claims for the production app.
- Focused quote/view regressions: 132 passed, 2 excluded. The two calendar Mock
  tests fail with AttributeError `__name__` under both HEAD and edited quotes;
  reproduced by executing HEAD's report_quotes source in memory before pytest.
- Existing leveraged comparison/watch/product/build tests: 208 passed.
- Live public responses around 13:36 KST had valid exact-symbol overnight
  observations for all three US products; negative signs preserved. Private
  account data and raw provider payloads are not committed.
- Code `487605f9` pushed. Cloud final completed-result screens verified around
  13:40-13:41 KST without reboot: SOXL, RAM, BITX all showed daymarket observations,
  negative changes and Nov 12 US regular-close bases. Displayed observation times
  were 13:39:16, 13:39:22 and 13:40:25 KST respectively. 418660.KS showed the
  Korean-listed exclusion, not an imported US quote. No exception seen in those
  completed results. Do not compare changing live prices as numerical parity.
- Private visual evidence: Downloads/leveraged_SOXL_quote_session_verified.jpg.
  Narrow-screen wrapping was checked; evidence is outside Git.

## Limits

This does not establish profitability or validate a trading strategy. Live
after-hours cannot be observed during daytime; after/pre/day and DST transitions
are covered with timestamped fixtures. Existing special/short-session limitations
remain conservative (unavailable, never guessed). No broker-to-broker price parity
or future quote availability is promised.

Next bounded task: review SOXL entry interpretation against verified observations,
without adding or changing investment thresholds.
