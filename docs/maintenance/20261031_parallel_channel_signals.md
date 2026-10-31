# Parallel trend channels and pattern-event dates

## Confirmed gap

The existing app retained double top/bottom, head-and-shoulders/inverse, flag,
and triangle detectors, but displayed current geometry rather than an event
history. Independent high/low guides were not a parallel channel. A label on
the second peak was also misleading: it described a later neckline break as
if it were known at that peak.

Stored GOOGL display OHLCV ending 2026-10-30 confirms:

| Evidence | Date | Price |
| --- | --- | --- |
| First peak | 2026-09-22 | 364.17 |
| Interior neckline | 2026-10-01 | 335.51 |
| Second peak | 2026-10-14 | 359.40 |
| Second pivot observable after three right-hand bars | 2026-10-19 | - |
| First closing break below the neckline | 2026-10-21 | 334.76 |
| Current parallel channel first observable | 2026-10-19 | - |
| First closing break below its lower rail | 2026-10-22 | 324.22 |

The current channel is downward, not an upward channel forced to resemble
the reference image. Its main rail touches the September 22 and October 14
highs; the opposite parallel rail touches the September 24 low, 336.02.
It is currently broken below. Geometry labels now say "structure"; arrows
mark the actual observation/confirmation bar, not the old pivot.

## Implementation

- `chart_structure.py` creates one shared-slope channel from two confirmed
  trend pivots and one interior opposite extreme. The center and quarter
  lines are parallel. Insufficient anchors produce no invented channel.
- Historical events use each bar's own price prefix. No later pivots, current
  financial scores, market conditions, or portfolio weights are backfilled.
  A three-bar pivot delay is retained and explicitly labeled when applicable.
- The displayed event window is capped at 80 bars and 24 events. Repeated
  same-formation signals are suppressed. This is not a backtested strategy.
- Current buy review requires the existing executable gate, the existing
  final check's `execution_allowed`, confirmed data, and the existing volume
  confirmation criterion (1.2x). The loaded candle must also match both the
  decision's price date and the exchange calendar's latest completed session.
  Missing calendars or stale prices never inherit current buy permission.
  The final check is computed once and reused
  by the chart and lower panel. A bearish warning never inherits buy permission.
- Current quote-only/unclosed bars remain provisional; week/month signals
  are higher-timeframe context, not daily execution permission.
- Head-and-shoulders now draws all five turns and the real sloped neckline.
  Flags have parallel boundaries fitted before the breakout candle; changing
  that candle's wick cannot retroactively widen its formation. Flag direction
  must match a downward/flat bullish consolidation or upward/flat bearish one.
- Candidate-grade formulas, financial scores, market restrictions, and main
  verdict vocabulary are unchanged. Corrected pattern geometry can change
  pattern evidence and the existing workflow's interpretation of that evidence.
- Chart review ZIPs contain a separate `chart_structure` section without
  duplicating it or the prepared final summary inside `main_decision`.
- No new external data requests. A five-minute bounded cache stores only
  price-derived geometry; user-specific execution qualification stays outside.
- Triangle/flag event crosses use their existing 0.5% confirmation filter on
  both bars, so a gradual crossing is not lost between observation and confirmation.
- Channel events extend the previously observable channel by one trading bar.
  Large gaps cannot erase their own break signal. The legacy proximity filters
  remain enabled for standalone guides, not for parallel-channel construction.
- Daily chart axes compress only exchange-calendar closures. Missing actual
  sessions retain their gaps; weekly/monthly and weekend-traded data are not
  forced into an equity daily calendar.

## Validation

- Full suite before the final date-axis presentation change: 4,026 passed,
  1 skipped, 18 subtests passed in 269.89 seconds. The repository-pinned
  exchange-calendars dependency was installed locally to verify real calendars.
- Final focused chart, export, and provenance suite after all source edits:
  172 passed in 31.12 seconds.
- Structure regressions cover parallel pivot contacts, exact
  legacy/vectorized pivot equality (including ties), actual break dates,
  append-only/no-future-arrow tests, both H&S directions, both flags, bad OHLC,
  missing dates, old cached modules, and gate/final/volume/provisional limits.
- Reviewer reproductions for stale last candles, gradual real-detector triangle
  crossings, and both directions of a 10% channel gap are included.
- Stored GOOGL daily/weekly/monthly replay: 0.950 / 0.598 / 0.629 seconds,
  total 2.19 seconds before cache. The earlier unoptimized daily replay took
  3.695 seconds. Synthetic pivot outputs were preserved by vectorization.

## Definitions

- StockCharts Price Channel:
  https://chartschool.stockcharts.com/table-of-contents/chart-analysis/chart-patterns/price-channel
- StockCharts Double Top Reversal:
  https://chartschool.stockcharts.com/table-of-contents/chart-analysis/chart-patterns/double-top-reversal

The reference image is a visual guide, not executable indicator source or
proof of profitable entry/exit rules. Automatic channels remain reviewable
technical hypotheses; the app does not place orders.
