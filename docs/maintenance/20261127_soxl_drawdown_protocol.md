# SOXL drawdown paired-exit protocol (frozen before fetching outcomes)

Date: 2026-11-27 KST. Research only; no production policy changes.
Base: ad5f6f1f06ba8b8a99c7ae05ca40a3ca9130dc90.

## Questions and fixed inputs

Compare two reference prices, separately:
1. Previous regular-session close.
2. Highest close in the previous 20 trading sessions (exclude signal day).

Trigger is 80% of that reference. Compare two signal modes, separately:
- Close-confirmed: completed daily close <= trigger; buy next regular open.
- Intraday touch: threshold known before the session; buy at open if open <=
  trigger, otherwise at trigger if the day's low reaches it. OHLC touch is only
  a simulation, not evidence of a particular intraday timestamp or execution.

For each reference/mode, +10% and +20% targets share exactly the same entries,
entry fills and cash amounts. Targets and stops use actual simulated entry fill,
not the reference or trigger. These are independent experimental portfolios.

## Fixed exit, costs and capital assumptions

- Stop: -10% from simulated entry fill, both target arms.
- Maximum holding: 10 trading sessions INCLUDING entry day. Exit remaining
  position at the tenth session's close, or final available close at dataset end
  (right-censored, separately labeled, included in primary results).
- Buy and sell adverse slippage: 10 basis points each. Commission: 5 basis
  points each on slipped execution notional. No tax, FX, interest or financing.
- Initial capital USD 100,000. Every entry uses USD 10,000 INCLUDING buy fee;
  fractional shares allowed. Fixed initial-capital 10% allocation, no reinvestment.
- Common lockout through entry day + nine sessions, regardless of early exit.
  A close signal on the final locked session may enter next open. Touch entries
  resume next session. One position, no overlapping lots. This deliberately
  prevents a fast target from acquiring different later entries.
- A condition still true after lockout may signal again (not crossing-only).
- Only dividends with ex-date after entry and on/before exit are credited.
  Ex-date credit is accrued cash, not assumed reinvestment; payment-date timing
  is not modeled. Price targets do not adjust for dividends.

## Unknown OHLC ordering and gaps

- At open: a stop gap exits at open; a target gap exits at target (no favorable
  price improvement). Apply sell slippage/commission afterward.
- If stop and target both touched in a later/open-entry session, stop first;
  report count per arm. Do not invent an intraday sequence.
- Threshold-touch entry below open: day's high may predate entry. Do NOT grant
  an entry-day target using high. A low reaching stop can stop the trade; otherwise
  hold. Count entry-day high/target ordering uncertainty separately. If the close
  confirms target after entry, this protocol still conservatively waits until
  next session; no favorable exception added after viewing outcomes.
- A next-open signal without a next bar is unfilled, not a fabricated trade.
- Missing/nonfinite OHLC, missing exchange sessions, invalid prices: fail data
  validation, not interpolate. No forward-looking indicators, future highs or
  dynamically optimized parameters.

## Data and reporting

Use SOXL split-adjusted, NOT dividend-back-adjusted daily regular OHLC from Yahoo
Finance via yfinance with auto_adjust=False, repair=False, actions=True. Yahoo
historical OHLC already applies splits; do not apply the split factor twice.
Retain Adj Close, splits and dividends for audit. Record any split-related
discontinuity checks and issuer source. Do not cap genuine crash returns.

Request inception through last completed NYSE session as of 2026-11-27 14:00 KST
(Thanksgiving 11/26 closed, therefore expected last session 11/25). Validate with
exchange-calendars. Save snapshot, source, UTC fetch time, versions, SHA-256 and
replay parameters. Frozen snapshot is the default rerun input; network refresh
is explicit and must use a new artifact directory.

Output all trades, daily equity, signals/entry ledger and summary for eight arms.
Target hit rate uses executed target exits; net win rate includes dividends,
fees, slippage and non-target exits. Include all stops, horizon and right-edge
exits. Report common signal exclusions and ambiguous-bar counts.

Strategy MDD uses daily closing marked equity (cash plus active position at close,
accrued dividends) with exit proceeds on exit day. Include initial capital as
first peak. It is NOT an intraday worst-case MDD or sum of closed trade losses.
Show actual data period and sample size; zero samples have no rate, not 0%.
No parameter selection, deployment, success-probability promise or extrapolation
to the user's present entry price. This is historical hypothesis comparison,
not validated investment advice. Historical market-defense rules are unchanged
and NOT retrospectively reconstructed or used to permit these hypothetical trades.

## Existing work preserved

Existing scripts/research_soxl_{hours,session_limits,stop_loss,five_minute,linked}.py
study SOXX hourly support/recovery and SOXL execution, not a fixed -20% reference.
Their one-R/upper targets and 18-hour windows are not overwritten or pooled here.
Repository/branch/worktree inspection found no unfinished implementation of the
new drawdown hypothesis. Files existing only on another PC cannot be verified.
