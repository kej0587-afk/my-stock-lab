# Per-symbol short-strategy validation

## Scope

Extend the isolated SOXL replay infrastructure to KR/US listed stocks and ETFs.
Not a profitable-strategy claim, classifier trained on future returns, automatic
entry approval, order system or change to the existing investment criteria.
Other exchanges, cash crypto and futures require separate calendars/execution
models and are explicitly unsupported. Available data does not mean every symbol
has enough observations to calculate evidence.

## Architecture and assumptions

- `short_trade_research.py`: shared prefix-only channel/simulation/statistics.
  `soxl_trade_research.py` becomes a compatibility facade with unchanged outputs.
- `short_trade_data.py`: bounded opt-in per-symbol hourly history/current batch,
  success caches 24h/5min and failure cache 30s. Never called by today-queue scoring.
- `short_trade_evidence.py`: per-symbol input fingerprint, current completed
  signal context, descriptive evidence quality and fixed ex-ante condition bins.
- `short_trade_view.py`: common precision panel. Existing SOXL desk delegates its
  research section to this renderer. Other precision symbols get one panel.

SOXL retains SOXX reference / SOXL actual OHLC. Other stocks and ETFs use their
own price for BOTH signal and execution. RAM, BITX, QLD and 418660.KS do not inherit
SOXL's benchmark or a multiplied return. In particular no 24h BTC vs US ETF or
KR ETF vs overnight US price mixing. This tests a declared generic long-channel
rule, not the app's existing scores, every trading strategy or an underlying
asset investment thesis. Regular opening-anchored completed 60m candles only;
final partial session bars can execute but never signal. Price/stop/1R and
next-open execution rules are inherited without optimizing against test results.

Per-side aggregate cost is explicit, default 10bp, user editable; it is NOT a
claim of each market's actual fees/tax/spread. Double-cost sensitivity uses the
same trades. No automatic tax assumptions or equal-sample claims across markets.

Evidence states: no trades -> unavailable; nonpositive net mean -> no edge;
positive mean but fewer than 30 full/20 latter-half trades -> small sample;
nonpositive early/late/double-cost mean -> unstable; otherwise forward-validation
candidate, NEVER validated buy/profitability. 30/20 are reporting heuristics, not
investment thresholds. Time halves are descriptive, not independent held-out
testing. Wilson ranges do not correct serial dependence or regime changes.

Current comparison requires a valid current completed-hour signal and trades
closed strictly before that signal. Predeclared bins: own signal-close-to-low
risk <=1%, 1-2%, >2%; reference 5-bar direction positive/nonpositive. No search
over entry prices, no cross-symbol pooling, no rate shown below 20 matched cases.
This is a historical conditional frequency, NOT probability at today's price.
Manual price changes, extra 5m confirmations and market-gate filtering are not
covered. Missing paths/censored trades and missing-gate history stay explicit.
Missing data and selection among many tested symbols can bias results.

## Verification

Base a5c80464. Baseline decision regression: 1369 passed /138.667s.
Shared-engine gate: 1369 passed /136.795s (decision_ar8wmh7r).
Final revision gate: 1369 passed /128.605s (decision_3l9f_9lv).
Frozen SOXL comparison: same 64/63 trades, every statistic unchanged, CSV hashes
identical before/after:

- day: 86d24c6b73ec04206be85eb36383fa24411b8452ca1c6931ebba200d7f0d07a1
- overnight: 6023dcbb028ce73da4dc52d4ab519b7318af20c152af0a9c6243b754c07ae8b7

Replay 11.449s before /11.925s after, same frozen inputs. No speedup claimed.
Private evidence: cache/short_research_before and cache/short_research_after.
Focused regression: 141 passed /8.32s. Tests cover per-market arithmetic, no future information, finite/OHLC
missing checks, symbol-scoped loading, no rerender I/O, explicit unsupported
markets, immutable investment decisions, sample floors and cost invalidation.

Local real renderer with public live requests verified MSFT and Samsung.
MSFT snapshot: 59 day trades /37.3% wins /-0.14% mean; 59 overnight /39.0%
/-0.29%. Both no edge; Samsung also no positive full-sample expectancy.
US EST vs KR KST calendars/currency and latest reference times differ correctly.
These provider snapshots are not stable cross-run performance guarantees.
No private account data is committed. Production deployment verification follows.

## Next Bounded Task

Collect genuinely forward, same-clock signal/executable-price observations for
one preselected rule and symbol, including the actual market gate, before any
profitability or current-entry probability claim. Do not optimize all tickers
until a high win rate appears.
