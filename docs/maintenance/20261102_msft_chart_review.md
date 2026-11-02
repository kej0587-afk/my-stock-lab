# MSFT precision chart review

## Findings and scope

- Export and live board agree on NEW_ENTRY_LEADER and candidate score 10.
  The export's plan is first-tranche-only (R/R 1.2140223471); its final check
  is small/split. Candidate quality, screening and final review are different
  stages, not evidence of a scoring defect.
- Daily/weekly/monthly channel coordinates reproduced exactly from the
  supplied OHLCV CSVs with round-trip float parsing (251/260/121 rows).
  A falling weekly channel already broken above is a historical construction,
  not a statement that current price is falling.
- Pattern visibility incorrectly disabled the independently enabled channel
  and event layers. The chart explanation used undrawn independent trendlines
  while the plotted rails were parallel-channel rails.
- FVG/OB and equal-level labels overlapped. Daily adjustment prose could
  override the final-check wording. Zero/unset allocation looked like a met target.

## Changes

- Extract layer preparation into precision_chart_view; independent toggles,
  explanation rails from the displayed channel, cached pattern-result reuse.
- Place level names and prices in the right gutter with spaced callouts.
  Actual zone/candle coordinates and pattern pivot labels remain unchanged.
- Keep daily state classification but describe it as technical context.
- Distinguish an unheld, unset target from an already met allocation.
- No scoring thresholds, indicator formulas, gate policy, entry prices,
  allocations, units, quote providers or source dates changed.

## Verification

- Added 18 regressions: eight layer combinations, channel/pattern parity,
  label geometry, actual renderer, stale-module guard, non-policy prose,
  and four old/new plan cases.
- Existing full decision parity and golden tests remain in the suite.
- Full suite: 5,843 passed, 77 existing warnings, 18 subtests (326.20s).
  Final label-gutter and stale-module guard changes: 31 related tests passed.
- Cloud build/visual verification is reported in the delivery message; live
  quotes can change independently of this presentation fix.
