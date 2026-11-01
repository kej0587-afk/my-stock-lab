# 2026-11-01 Portfolio Connection Audit

## Scope

Audit the actual linkage of holdings, today-check signals, money-flow context,
cash/reserves, and portfolio risk analysis after the UI-only renderer split.
Trading thresholds, grades, primary verdict text, authentication, and stored
holdings are unchanged. No transactions or account records are rewritten.

## Confirmed Corrections

1. Cached technical decisions previously matched only on ticker. After an
   account-filter/cost/quantity/target change, a different account's decision
   could be reused. New in-session signatures cover owner, selected accounts,
   structural holdings, cash, reserve target, financial score map, and logic
   version. Live price/FX ticks do not invalidate manual calculation results.
   Legacy unscoped signals are not attached; a new calculation reconnects them.
2. The first nonempty source previously won, even if old and partial. Verified
   sources are now combined by latest calculation time per normalized ticker.
   Today-check contributes its post-gate table, not its earlier raw table.
   It preserves original measurement/time metadata and is not stamped anew on
   a passive rerender. Data is kept within the same Streamlit user session.
3. Missing/pre-listing returns were padded and finally set to zero. The report
   now explicitly disables implicit pct_change padding and uses jointly
   available observations. The existing explicit three-observation holiday
   fill remains. The common period, sample size and excluded days are visible.
4. Portfolio wealth curves omitted the initial 1.0 baseline, so a loss on the
   first return day could disappear from MDD. The real preceding price date
   now anchors the curve. No fictitious date or return is introduced.
5. Historical stress proxy identity now reuses the portfolio scenario
   multiplier, recognizing RAM, BITX and 418660. Existing proxy scaling
   factors (1.85/2.8/inverse -1.5) remain unchanged. Actual ETF history is
   preferred and is never multiplied twice.
6. Cash displays no longer count all non-operating/reserve assets as cash.
   Both the target-weight section and detailed evaluation use the same
   reserve_summary.cash_value as the asset overview and scenario tools.
7. The green curve was a percentage-point change in cumulative cost return,
   not a time-weighted investment return. Its label, hover and axis now say
   so. Its difference from the fixed-weight price curve is not alpha.

## Verified Existing Contracts

- build_holdings_table already aggregates same-ticker quantities and weighted
  acquisition cost across selected accounts before risk calculations. No
  duplicate-weight fix was needed on this normal path.
- Asset overview, scenario and portfolio share append_cash_rows,
  calc_reserve_summary and get_active_portfolio_rows policies. Synthetic mixed
  KRW/USD cash plus reserve holdings verify identical denominators and reserves.
- Money-flow evidence is market-wide rather than account-specific, intentionally.
  Attaching that context does not grant execution permission.
- Existing renderer parity tests remain, with an explicit narrow allowlist for
  the audited labels and true-cash calculation changes. Unrelated UI values,
  figures, keys, states and early-return behavior remain covered.

## Remaining Design Limits

This is a current-weight, local-price risk model, not a reconstructed account
NAV or certified total-return record. Historical FX changes, reserve-asset
returns and cash interest are not modeled. The UI discloses these exclusions.
Selected accounts filter holdings, but cash and monthly logs have no
account dimension and remain whole-owner values; that scope is now explicit.
True per-account performance needs dated external flows, account valuations,
dividend/reinvestment policy and a consistent currency/time basis before TWR
or money-weighted returns can be claimed. Do not infer those inputs or silently
change existing records. See the primary methodology reference:

https://www.gipsstandards.org/standards/gips-standards-for-firms/gips-standards-handbook-for-firms/

The structural portfolio risk score and the market regime are distinct. Score
weights and saturation/calibration have not been changed or claimed to be
empirically validated. Broad recalibration needs a separate replay/backtest.

## Verification

Offline synthetic regressions are in tests/test_portfolio_connection_audit.py.
Full regression coverage: 4,466 passed, 1 skipped, 18 subtests passed across
two contiguous collection segments. The first run reached 4,304 passes before
two AST-isolated queue fixtures lacked the newly called stamp helper. Only
that fixture namespace was updated, then the remaining 162 tests passed
(37.00 seconds); the runtime source was unchanged between the two segments.
The 72-test focused portfolio run and 26-test renderer/calculation run also
passed before the final persistence/lifecycle additions.
No private portfolio amounts or credentials are stored in this document.
