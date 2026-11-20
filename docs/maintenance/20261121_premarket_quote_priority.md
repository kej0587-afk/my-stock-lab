# US pre-market quote priority — 2026-11-21

## Cause and bounded change

The Nov 20 Cloud captures exposed an existing routing error: the session selector
recognized regular trading and after-hours trading, but not pre-market trading.
During pre-market it tried the previous overnight quote before live candles.
The 16-hour quote acceptance window admitted the overnight quote, so a successful
overnight response stopped the chain before a newer candle could be requested.

Added a New York time pre-market predicate (04:00 inclusive, 09:30 exclusive),
using the existing US holiday calendar. Pre-market now shares the existing
after-hours candle-first order in the primary US selector, uncached fallback and
batch fallback. The meaning of the original after-hours predicate is unchanged.
Reference: [Nasdaq Equity 1, session definitions](https://listingcenter.nasdaq.com/rulebook/nasdaq/rules/nasdaq-equity-1).

No scoring/gate formulas, trading thresholds, provider set, cache TTL, holiday
calendar or generic freshness window were changed. A better selected price can
intentionally change downstream numeric results; this is not a promise that
different market inputs produce identical decisions. If live candle providers
fail, the existing overnight fallback remains available with its actual source,
timestamp and session. It is not relabeled as a current pre-market trade.
Previously cached values can persist until the unchanged TTL expires.

## Verification

- Before editing: focused quote/source/cache tests, 152 passed in 9.46s.
- Fixed-clock tests cover winter/summer ET/UTC/KST boundaries, both DST changes,
  existing holidays/weekends and clock failure. Provider tests cover GOOGL,
  SOXL and BITX through primary, cached, uncached and batch paths, including
  failure fallback and unchanged provenance/cache reuse.
- Non-pre-market quote values and complete provider call order are compared to
  fixed revision `6cdefff4`. An AST contract permits only the reviewed routing
  assignment in the three existing selectors. No golden files were regenerated.
- GOOGL source times 17:59:37 KST overnight and 23:28:35 KST pre-market came from
  separate Nov 20 exports. Tests combining those times are a fixed-input replay,
  not evidence of simultaneous provider responses in production.
- Focused verification: 382 passed before the final three replay cases; final
  pre-market + source diagnostics check: 169 passed in 9.97s. The focused summary
  test double now forwards optional `build_signal_basis` keyword arguments added
  in the previous change; production summary logic is untouched.
- Fixed-candidate GOOGL replay selects 273.02/overnight on `6cdefff4` and
  274.91/pre-market on the new code in all three routing paths. These are observed
  public quote values combined from separate captures, not a matched live price
  experiment. SOXL/BITX replay prices are synthetic.
- Frozen selected-all gate: **2,353 passed**, zero failures/errors/skips,
  232.959s; `cache/refactor_checks/all_jrek51xw`. Source/test hashes did not change
  during the run. This is selected regression coverage, not the full repository
  suite or a live performance benchmark. Production verification is pending.

## Remaining limits

Actual production pre-market testing requires a future open pre-market session;
current-session verification and frozen pre-market replay must remain distinct.
Unknown domestic/provider timestamps and the legacy use of partial daily bars
are unchanged. This task is a correctness fix, not a speed benchmark.
