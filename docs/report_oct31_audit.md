# 2026-10-31 dawn report audit

## Price basis

The uploaded report was generated at 07:16 KST from `643190cb2b93`,
with no loaded/disk source mismatch. The SOXX -8.24% and DRAM -7.23%
regular-session returns agree with the attached broker screenshots.
Its +0.10% / +0.19% after-hours observations used the **same day's regular
close**, whereas the broker's -8.11% / -6.98% used the **prior day's close**.
The report was showing an unlabelled, different denominator, not evidence
that the full-session loss had recovered.

Keep `extended_prices[*].return` as the incremental extended-session leg.
Capture the verified regular comparison with the quote. After-hours display
now puts the prior-close-to-latest return first, with the incremental
after-close return separately labelled. Compound the two legs; never add
percentages or feed the displayed cumulative return back into the account.
Premarket/overnight quotes still compare directly to the last regular close.
Missing comparison evidence stays missing; delayed quotes stay excluded from
the current headline and account estimate. No trade grades/gates change.

## Reproduction

Historical screenshot inputs, **not live quotes**:

Symbol | Prior regular close 10/29 | Regular close 10/30 | Screenshot after-hours price | Prior close to screenshot | After-close leg
--- | --- | --- | --- | --- | ---
SOXX | 513.86 | 471.51 | 472.21 | -8.11% | +0.15%
DRAM | 51.75 | 48.01 | 48.14 | -6.98% | +0.27%

The report's earlier 472.00 / 48.10 observations correspond instead to
-8.15% / -7.05% from the prior close. Prices at different observation times
must not be described as identical quotes. Provider last-trade values can
also differ by venue. All calculations use actual prices, not rounded
broker percentage labels or hard-coded production corrections.

## Performance evidence

`4f3fa668564c45bba9d2049a5af89116` is the report's complete calculation:
95 calculated symbols, 105.174 seconds, standard refresh (not fully cold).
The separate `2861c6fe27e8453ca9d7d428c6a4e31e` is a 20.042-second rerender,
not a speed-improved full calculation. Active wall time: prices 72.556s,
indicators 21.737s, external data 29.550s, decision 10.650s. Categories overlap
and must not be summed. This report-only correction makes no speed claim.
