# Precision chart geometry review (2026-10-31)

## Evidence

Replayed `precision_review_GOOGL (6).zip`, display OHLCV ending on
2026-10-30. No external quotes or personal portfolio values were needed.
The submitted screenshot was consistent with the old pattern and trendline.

| Item | Before | After |
| --- | --- | --- |
| Double-top pair | 08/24 351.60 -> 09/22 364.17 | 09/22 364.17 -> 10/14 359.40 |
| Neckline | 09/10 327.74 | 10/01 335.51 |
| Pattern geometry | High-to-high diagonal, no trough | High -> interior trough -> high, separate horizontal neckline |
| Pattern annotation | Fixed chart corner, unrelated to formation date | Arrow anchored at the second pivot |
| Resistance | Regression through smaller rebound highs, labeled rising | Actual 09/22 and 10/14 confirmed highs, labeled falling |
| Bearish invalidation explanation | Incorrectly treated a price below the high as failed bullish recovery | A recovery above 369.63 invalidates the bearish warning; not a buy permission |

## Scope

- Double-pattern pairing favors the newest second pivot, then the existing
  confidence measure. An intervening more-extreme high/low disqualifies a pair.
- Existing 4.5% similarity, 3.5% depth, confirmation tolerances, pivot lookback,
  and lifecycle thresholds are unchanged. Necklines use strictly interior bars.
- Trend guides pass through two confirmed structural pivots, using the upper
  envelope for resistance and the lower envelope for support, not a regression
  through prices. Existing fresh-wick exclusion and distance filters remain.
- Grade formulas, financial scores, main verdict vocabulary, market restrictions,
  and final-check thresholds are unchanged. Pattern evidence and its reference
  price can legitimately change; this is not a claim of identical indicators.
- Volume starts at zero and its vertical axis cannot be panned independently.
  Price zoom/pan and the original loaded history remain available. The screenshot
  alone does not prove whether its clipped axis came from manual panning.
- Source fingerprints also cover chart helpers so stale Cloud modules are not
  mistaken for a verified new chart after deployment.

## External definitions

- StockCharts ChartSchool, Double Top Reversal:
  https://chartschool.stockcharts.com/table-of-contents/chart-analysis/chart-patterns/double-top-reversal
- StockCharts ChartSchool, Trend Lines:
  https://chartschool.stockcharts.com/table-of-contents/chart-analysis/trend-lines

These definitions support checking two comparable peaks, the intervening trough,
and actual pivot contacts. Automated geometric matches are not a guarantee of a
future price move.

## Verification

Synthetic regressions cover top/bottom geometry, recent-pair selection,
intervening-extreme rejection, both trendline directions, real pivot contacts,
irregular trading dates, label coordinates, zero-based volume, and mirrored
bullish/bearish invalidation. The stored GOOGL replay confirms the prices above.

- Full offline regression suite: 3,978 passed, 12 skipped, 18 subtests passed
  (167.18 seconds).
- Subsequent targeted run including the three new invalidation tests:
  30 passed (12.47 seconds).
