# Leveraged Comparison Session Alignment

Date: 2026-11-13. Base: `9e07a76e`. Scope: SOXL, RAM, BITX, 418660.KS.

## Finding

The watch builder divided a recent scalar quote by historical daily closes.
Those quotes carry no timestamp/session in this callback, so regular, extended
and overnight quotes could change the meaning of 1D/1W/1M. Short histories also
used the first available close while retaining the full-period label.
Cloud before edits showed this limitation and the legacy mixed-session values.

## Change

- `leveraged_comparison.py`: pure completed-session return inputs and explicit
  1/5/21-session start/end times. Existing exchange calendars supply holidays,
  DST and early closes; a 15-minute closing grace avoids just-closing candles.
- Same-market rows use exactly the same endpoint dates. Missing, duplicate,
  invalid or explicitly pending endpoints stay unavailable; no forward filling,
  live quote substitution or short-window substitution.
- Product rows are added with role `비교 상품`, outside the original recovery
  basket. Existing role membership, thresholds, DCA sizing and judgement code
  are unchanged. Shared profiles do not substitute BITX for BITU or 418660 for
  another Nasdaq fund: only the exact four products opt in.
- KR and US tables have separate completion clocks. BTC UTC daily candles are
  not NY-close observations, so the BTC comparison is unavailable. IBIT remains
  a same-session comparison ETF, not BITX's mandated underlying or futures NAV.
- Latest prices remain on the main screen, separate from the completed-close
  table. Comparison rows no longer request live quotes. One product history is
  additionally included using the existing history loaders/batch cache policy.
- Compact display tables plus endpoint audit expander replace mixed labels.
  Cold deployment with an old watch module defers comparison rather than raising
  a signature TypeError or silently returning old mixed values.

## Verification

- Before: decision gate 1367 passed, 123.217s.
- Intermediate: focused 206 passed; decision 1367 passed, 125.018s.
- Final focused 208 passed (18.64s), including Streamlit rendering and old-module
  deployment deferral. Final decision gate 1367 passed (125.282s), with source
  hashes unchanged throughout the run (`decision_hy_tw65b`).
- Commit/push and Cloud verification: pending below.
- Historical AST adapters remove only reviewed routing keywords/signature and
  the exact deployment guard; mutation tests still detect altered calculations.
- These are correctness checks, not an investment backtest or a full-account
  elapsed-time benchmark. Historical/live prices were not changed upstream.

## Limits

Calendar completion plus provider daily history is not an independent exchange
settlement feed. Provider corrections/splits remain the existing loader's job.
The existing five-minute watch cache can retain its explicitly shown prior
comparison window until expiry. No claim of simultaneous KR/US/BTC intraday
comparison is made. Corrected inputs can change recovery checks; no claim that
the formerly mixed numeric results are preserved.

Next bounded task: audit timestamped extended-session observations for these
same products. Do not invent missing same-clock data or change thresholds.
