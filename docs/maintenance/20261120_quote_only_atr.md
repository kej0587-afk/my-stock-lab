# Quote-Only Bars and Precision Input Labels

Base: 47935154. Follow-up to the user's SOXL review export. Private exports remain
outside Git. No new feed, guessed quote session, investment threshold or order.

## Reproduced Findings

- A quote-only placeholder was appended before the US regular session: equal
  OHLC and missing volume. `LiveQuoteOnly` already identified it, but decision ATR
  ignored the flag. True range was not zero: the previous-close gap still entered
  it and displaced an older range from the 14-bar average.
- On the supplied capture, ATR was 10.633572; source-only ATR is 11.373572. At the
  same quote 42.09 and structural target 69.730003, the unchanged current-minus-
  2ATR rule gives 19.3429 instead of 20.8229, and R/R 1.21510 instead of 1.29966.
  This is a deliberate input bug correction. Derived prices and R/R are expected
  to change for affected overlays; claiming all calculated outputs unchanged
  would be incorrect. No target is declared reachable or a price recommendation.
- The three drawdowns have different denominators or price timestamps: -85.0%
  source close / 52-week high; -86.0629% quote / that same high; -75.2164% quote /
  recent 52 daily-bar high. Weekly/monthly summary uses 52 respective bars, NOT
  52 days in all cases. Added an explicit comparison-window column.
- Volume +208.0874% is recent 20-session mean / preceding 60-session mean minus
  one. Latest daily volume / recent 20-session mean is 1.54620. Both can be true.
  Added the exact first definition (up to 60 prior observations on short history).

## Changes and Limits

- ATR filters explicit quote-only rows BEFORE previous-close shifting and the
  minimum-history check. Other real-bar inputs preserve the original arithmetic.
  Applies to all symbols using the shared decision helper, not a SOXL exception.
- Price-only RSI/MA and current-price drawdown retain the existing provisional
  behavior. A compact basis table separates them from source-close scorecards,
  ATR and prior MFI. The prior MFI is not invented live volume.
- ATR provenance says quote-only rows excluded, not that every upstream vendor
  row has independently verified session completion. Actual provider intraday
  partial bars remain a separate input audit; missing session data stays unknown.
- R/R explanation now distinguishes a geometric price ratio from success rate;
  fixed stops can mechanically improve it at lower planned entries. The plan
  invalidation line is not an automatic sale instruction for existing holdings.
  Weight capacity is not buy evidence. A/B/C B condition also states this scope.
- Loaded-source provenance now includes the decision engine and the two touched
  presentation helpers, so a retained Cloud module is detectable before review.
- No policy or market-defense gate relaxed. No performance/strategy-edge claim.

## Verification and Deployment

- Before: 259 focused tests passed (14.58s).
- First after pass: 271 focused tests (15.68s), including appended/same-date/middle
  placeholders, original arithmetic, minimum history and input immutability.
- Expanded integration: 352 passed (24.77s), including drawdown-window labels,
  unchanged plan payload, A/B/C, review export and the old full decision snapshot.
- First selected gate caught the historical quote-only ATR expectation in one
  snapshot test (1848 pass / 1 fail). The saved golden file remains unchanged.
  Its 17 non-live cases still match exactly. For the three same-date quote cases,
  only ATR and five derived prices differ; independent original-bar arithmetic
  now checks those six values. All remaining fields still compare to the old
  snapshot, including scores, decision codes, gate and sizing outputs.
- Supplied ZIP: full R/R context equality between original source bars and the
  flagged-overlay path after the fix, same quote and structural target.
- Broad selected gate: 1849 passed, zero failures/errors/skips, 202.552s;
  unchanged source hashes (`cache/refactor_checks/all_hf7r04xn`). Final focused
  integration repeat: 352 passed (31.83s). These are selected contracts, not all
  repository tests or a strategy backtest. A subsequent wording-only refinement
  limits the scorecard basis label to its RSI/52-week position, not all returns.
  Final decision gate after that label: 1401 passed, no failures/errors/skips,
  127.350s, unchanged hashes (`decision_2jepvacd`).
- Code commit `2453be28` pushed. Cloud hot-reload briefly logged a
  `stock_lab_core.browser_safety` import KeyError; an authorized reboot completed.
  This records recovery, not a claimed fix for that separate hot-reload cause.
- Production SOXL completed at 16:09 KST. The downloaded review manifest reports
  commit `2453be286552a43d3d2693888c3ed4f22773c895`, `restart_required=false`,
  no stale modules, and matching loaded/disk hashes for the decision engine,
  signal-basis helper and plan panel. Download itself did not refetch/recalculate.
- Live quote 42.00 produced stop reference 19.25 and R/R 1.22 in the execution
  check and A/B/C/management plan. Target 69.73 remained a recent internal high,
  not a forecast. Market-defense and leverage DCA deferral remained in place.
- Visually checked the four-row basis table: provisional RSI/MA dated 11/20,
  source-close scorecard and quote-only-excluded ATR dated 11/19, prior MFI
  explicitly separated. The separate session panel showed a 16:09 KST daymarket
  observation; the legacy upper-price input still correctly says session unknown.
  Equal displayed prices do not prove those two feeds have identical timestamps.
- Verified the horizontally scrollable timeframe table labels recent 52 daily,
  weekly and monthly bars, and provisional daily versus source timeframe prices.
  The live export also contains the exact volume-growth comparison denominator.
- Private UI proof: `cache/operating_20261120/quote_only_basis.jpg`; completed
  export: local `precision_review_SOXL (6).zip`. Neither is committed. During
  Streamlit rerun the previous symbol's lower sections remained temporarily;
  the completed SOXL result was verified without those old-symbol sections.

## Exactly One Next Task

Trace quote timestamp and completed-session identity end-to-end in precision
versus Today, including provider-supplied partial daily bars and channel freshness.
Do not interpret a local calendar date as an actual quote timestamp or retune
investment thresholds to hide a mixed-session input.
