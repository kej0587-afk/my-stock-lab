# SOXL phase 2: frozen before intraday replay

Status: research only. Production decisions, monthly allocation and L3 unchanged.

## Fixed Rules

- Reuse ALL 332 phase-1 entries, both reference prices and both entry modes.
  Same dates, slipped entry prices, USD 10,000 amounts and fractional units for
  the +10% and +20% arms. Do not regenerate entries using exit results.
- Stop -10%, at most 10 exchange sessions including entry. At horizon sell at
  last regular close; incomplete end of phase-1 data remains `data_end`.
- Commission 5bp and slippage 10bp each side, dividends as phase 1. Initial
  capital USD 100,000; fixed USD 10,000 per trade and common 10-session lockout.
- Request public Yahoo 1m/8d, 5m/60d, 60m/730d, regular session only,
  auto_adjust=False, repair=False. Save actual coverage and hashes; request
  length is not evidence of returned coverage. Replay uses 5m, not hourly bars.
- Preserve phase-1 split-adjusted (not dividend-adjusted) price basis. Compare
  intraday daily OHLC with frozen phase-1 daily OHLC. More than max(USD .03,
  0.1% of daily price) discrepancy in any field makes that entry unverified.
  Do not silently rescale or repair price data.
- Require every expected 5m regular bar from entry day through common horizon
  (or phase-1 data end) for BOTH targets, using XNYS opens/closes/early closes.
  Missing bars, inconsistent OHLC or duplicate timestamps are not filled.
  Record missing coverage independently of returns. This intentionally strict
  common window can exclude trades which would have exited before a data gap.
- Open entries must match first 5m open on the same price basis. Touch entries
  start at the first 5m bar whose low reaches the frozen entry trigger; if its
  open is below that trigger, frozen execution is not reproducible: unverified.
- A touch-entry bar's high may precede entry: ignore its target; retain stop
  if low crosses stop. On later bars check open gaps first, then high/low.
  Both stop and target inside one 5m bar: stop first and count ambiguity.
  5m data resolve between-bar order, not tick order or actual fill availability.
- MDD: regular 5m close marked-to-market, entry/exit cash flows, including initial
  capital. This is not tick-level or intrabar worst drawdown; also report worst
  completed trade. No leverage or compounding of portfolio allocation.
- Historical guard: accept only archived timestamped decisions known at/before
  entry with explicit validity interval. Missing archives are UNKNOWN, never
  reconstructed from today's guard. No-guard and verified-guard cohorts must
  disclose different counts; no numerical guarded result if zero verified.

## Independent Forward Paper Cohort

- Phase 1 ended 2026-11-25. First eligible new session: 2026-11-27.
- Freeze above parameters; monitor SOXL only, previous-20-high close reference,
  close-confirmed and touch separately, paired +10/+20 exits, no live orders.
- Persist observations only when real source bars and contemporaneous guard
  have been captured. No scheduled collection is implied by this document.
- Review after at least 30 completed entries per mode AND 3 calendar months;
  neither is a statistical guarantee. Never pool training-period trades into
  an independent success probability. Missing live guard remains unknown.
- Collection requires an actively running recorder or a separately approved
  scheduler. A zero-row ledger is honest while no new eligible session closed.

## Next Decision

No operating signal until coverage, cost sensitivity, uncertainty intervals,
regime stability and independently collected results have been reviewed.
