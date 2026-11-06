# Report 33 Review (2026-11-06)

## Confirmed Input Fault

SOXX's 3:1 split took effect on November 5, not its November 3 record date.
Official source: https://www.sec.gov/Archives/edgar/data/1100663/000119312526430480/d156277d497.htm

A read-only provider check on November 6 found mixed historical units:
October 30 Close 157.17, November 2 Close 453.65, November 4 Close 450.41.
The regular quote separately supplied November 5 Close 131.90 and previous
Close 150.137 (approximately -12.15%). Thus blindly dividing ALL historical
prices by three would corrupt already-adjusted October data.

`report_price_quality` isolates report inputs from decision histories:
- Adjust a uniform prior basis only with a verified split event and corroborating
  dated regular quote or adjusted-close ratio; never infer a split from a loss.
- Withhold mixed/missing histories. On the verified split day, a validated
  regular quote may supply daily return, but not 5D/3M momentum.
- Unverified ETF daily moves over 40% are excluded, not clipped or guessed.
- Leveraged reference returns below -100% are invalid, not predicted losses.
- XLC's -0.59% agrees with its regular quote; it is not corrected.

## Display Changes

- Current valuation weights are explicitly distinguished from starting weights.
  Dividing a current weight by (1+r) does not recover starting NAV, cash, FX,
  or transactions; no fabricated starting-weight contribution is added.
- Reserve the visible core-news top three for body attempts within the existing
  four-article budget and publisher allowlist. Display failure/not-attempted reasons.
- Prior US crash news can appear separately as overseas context, not a KR cause.
- Exclude election broadcast ratings from vote/seat progress.
- Coalesce unknown halt direction into a unique known direction, retaining sources.
- Reuse dated KR semiconductor/flow/halt evidence in the current-state summary.

## Performance Findings and Remaining Work

Uploaded full calculation: 103.731 seconds, no recorded errors.
`load_price_df`: 739 calls, 69.124 cumulative work seconds, 23.310 active wall seconds.
`get_money_flow_ohlc`: 505 calls, 59.884 cumulative, 15.449 active wall seconds.
These nested/concurrent durations must not be summed as elapsed time or network calls.

Uploaded render attempt: 69.644 seconds, interrupted by Streamlit RerunException
(control flow, zero errors). `report_context`: 35.558 seconds, of which 17.175
self time; `report_news`: 4.592 seconds. RSS already has a 300-second cache,
article success results 21600 seconds, public market evidence 180 seconds, and
price histories have exact-request scoped reuse. No blanket cache was added
to live/account context. End-to-end speed improvement is NOT claimed.

Separate follow-up: source-level cache-hit/transport timing and identical-input
repeated benchmarks; verified daily investor-flow backfill for complete 5/20
trading sessions; an authoritative AP chamber-call feed. Missing election or
flow results remain missing rather than inferred from headlines/sparse snapshots.

No trade thresholds, holdings, quantities, or saved decisions are changed.
