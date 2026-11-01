# 2026-11-01 Account Performance Ledger

Storage follow-up: see 20261101_account_performance_storage.md. The session-only
description below records the initial delivery; optional owner-bound server
storage was added afterward and requires its separate table setup.

## Boundary

This adds a separate, on-demand account-performance workspace ahead of the
heavy current-holdings price analysis. It never changes trading grades,
execution thresholds, holdings, cash balances, financial scores or old monthly
rows. A subsequent user-confirmed dividend-accounting correction is documented
below. There is no market fetch or database write on the new calculation path.
The new ledger is a per-owner Streamlit session draft, not durable storage.
JSON export/import makes this limitation explicit instead of silently using
ephemeral Cloud disk files. No new Supabase table or policy is created.

## Accounting Contract

- End-of-day NAV is the complete account value in KRW, including retained
  dividends, cash and the valuation-date currency translation. Internal
  dividends, trades and FX conversions are not external contributions.
- Contributions are positive and withdrawals negative. A transfer between
  accounts is external for an individual account, but internal for an
  aggregate-account ledger. No automatic averaging of account returns exists.
- USD external flows require an explicit transaction-date KRW/USD rate.
  A current FX quote is never substituted. KRW rates are 1 (blank defaults to 1).
- Dates, finite non-boolean numeric values, unique NAV dates and unique
  transaction IDs are validated. Inputs are not silently repaired or deduped.
- A flow exactly on the opening NAV date is already included in that anchor;
  each consecutive interval uses flows in (start, end]. End-date flows have
  zero time weight under the consistent end-of-day convention.
- Returns require explicit confirmation that the chosen account's external
  flow history is complete, even when the table is empty. Upload/import never
  preserves or supplies this confirmation automatically.
- Mid-interval cash flows use Modified Dietz and the result is labeled an
  estimate. Other intervals subtract end-date flows from NAV change. Period
  returns are geometrically linked only when every interval is valid. Missing
  inputs, nonpositive denominators and invalid losses do not become zero
  returns. No annualization, Sharpe, IRR or certified TWR claim is added.

Reference (CFA Institute primary methodology):
https://www.gipsstandards.org/standards/gips-standards-for-firms/gips-standards-handbook-for-firms/

## Existing Monthly Records

Legacy records contain only month, cumulative capital, evaluated value and
dividend. They lack actual NAV dates and dated external flows. The app also
has an intra-month snapshot shortcut, so month-end dates cannot be invented.
These rows are not converted into a supposedly exact performance ledger.
The user confirmed that legacy monthly evaluated values EXCLUDE dividends.
Their existing formula (ex-dividend value + cumulative monthly dividends -
cumulative capital) is therefore retained, without changing historical rows.
The monthly dividend field is that month's KRW receipt, not a cumulative sum.
The separately maintained dividends table is not joined into this calculation.
Receipt-date FX, rather than a current quote, is the basis for new manually
confirmed KRW dividend entries; existing amounts are not translated again.

This is a legacy return-on-capital record, not a flow-adjusted return. Historical
external-flow dates are unavailable; the user will record them prospectively.
The new account ledger uses actual dividend-inclusive NAV and external flows,
and explicitly warns that the two valuation conventions are different. No
missing past dates, amounts or historic FX rates are manufactured.

The monthly rebalancing shortcut previously added planned contributions to
capital and could save selected-account NAV as whole-owner monthly NAV.
The shortcut now labels the plan as unconfirmed, defaults actual capital from
the existing month or prior record (not the plan), and requires an actual
cumulative net-contribution confirmation and full account scope before saving.
Negative net contributions remain valid. A subsequent dividend-convention audit
found that this shortcut still wrote current total assets (holdings plus cash)
into legacy ex-dividend records while preserving their dividends. This could
mix conventions and double count retained distributions. It now requires a
confirmed ex-dividend value AND a confirmed monthly dividend amount, rather
than copying current assets or inferring dividends from a separate FX path.
New-month fields start blank; an explicit zero represents no dividend. Existing
month defaults are preserved, but editing replaces that month's dividend rather
than adding it again. A new confirmation key prevents the prior checkbox from
authorizing a different accounting convention. Finite inputs and nonnegative
valuation/dividend checks also run inside the write branch, including stale
clicks. Prior rows remain unchanged. No actual database records were saved or
repaired during verification. The manual table keeps its existing columns and
save/delete semantics, with Korean column labels describing the convention.

The monthly status display no longer presents current dividend-inclusive total
assets minus a historical ex-dividend valuation as a profit delta. The helper's
existing output contract is preserved for other callers.

The user separately confirmed that LIVE holdings/cash are actual broker balances
INCLUDING dividends. Live asset-summary profit incorrectly added the separate
dividends history to those assets again. calc_portfolio_summary now uses current
assets minus configured capital, without adding receipts. This applies to all
live-summary consumers while keeping their keys, cash/stock values, balances
and dividend-history data unchanged. The receipts total remains informational;
USD receipt references use current FX and the display discloses that this is NOT
their receipt-date KRW value. Historical monthly ex-dividend formulas are not
changed by this live correction. No inference is made about historical deposits
or withdrawals, so live return on configured capital is not relabeled TWR.

## Portable Format And UI

See docs/examples/account_performance_example.json. File schema version 1:
currency_basis=KRW, flow_timing=end_of_day, valuations and flows. Each table
supports at most 5,000 rows; files at most 1 MB. Dates are ISO dates. Invalid
imports do not replace the draft; imports replace instead of appending, so a
reimport does not multiply events. IDs retain leading zeros. Nested cells,
duplicate JSON object keys, malformed dates and nonfinite numeric values are
rejected before rendering editable tables.

Form application stores independent copies and clears old results. Owner,
account, draft revision and completeness isolate displayed results. Account
selection and import both require a new completeness confirmation. Existing
portfolio charts and metrics stay unchanged outside the newly added panel.

## Verification

Offline engine, I/O, Streamlit widget and monthly-save regression tests are
provided. tests/ui_account_performance_app.py is a no-secret, no-market-call
visual fixture. Its two explicitly synthetic example accounts show a 50,000
end-date deposit excluded from profit (10% rather than a naive 60%), and the
primary-method example's approximately 15.3061% Modified Dietz result.

Production must still be supplied with real dated records before a user's
actual return can be reported. Existing legacy rows are insufficient.

Full regression run: 4,589 passed, 1 skipped, 18 subtests passed in 331.11s.
After the final display-only formatting and upload/form size guards, the
123 targeted engine, portable-file, real Streamlit widget and save-guard
tests passed again in 9.56s. No score/price/risk formulas changed afterward.
Desktop browser checks used only synthetic local fixture data: both example
accounts, account switch, missing confirmation, upload, explicit reimport and
reconfirmation. Reimport did not append duplicate transactions. Results
show comma-formatted money, two-decimal percentages and explicit estimate
labels. The widget-level upload limit is 1 MB in addition to parser limits.

The first production precision ZIP used the new app entrypoint, but omitted
the account-performance module hashes. A cached older metadata-name list was
a candidate cause, not a demonstrated financial-code mismatch. The separate
portfolio page rendered successfully; real ledger data was not supplied.
get_precision_build_info now idempotently adds the account-performance names
already in the real import registry to that metadata list. This changes only
coverage configuration: no module reload, no replacement of an original loaded
hash with a current disk hash. A stale-code regression proves real mismatches
still warn. No user reboot is requested for this metadata-only list drift.
The 104 affected provenance, precision export, app-import and portfolio-renderer
tests passed after this metadata bridge (46.67s); no financial formulas changed.

Final production precision ZIP: completed, entrypoint matches local commit
0e32a544, restart_required=false, stale_modules=[]. The account-performance
hashes were still absent from this observatory-only snapshot. Therefore this
ZIP is NOT evidence of all portfolio modules' loaded hashes, and no extra
reboot was requested on the basis of absence alone. Production verification
here is the new panel's presence, session-only storage disclosure, legacy-data
non-conversion and missing-data state. Calculation examples and file roundtrip
were verified in the separate local browser fixture and tests, not against
the user's actual account records. Cross-view provenance coverage is a
remaining audit-design limitation, separate from the verified math engine.

## Dividend Confirmation Follow-Up

After the two user confirmations above, 191 focused tests passed (39.59s),
followed by the entire suite: 4,628 passed, 1 skipped, 18 subtests in 239.15s.
New coverage exercises retained/reinvested dividends, cash-only USD translation,
unchanged ex-dividend monthly arithmetic, explicit zero versus missing monthly
receipts, repeated-month replacement, stale invalid clicks and real Streamlit
input/editor widgets. Independent read-only review found no actionable issue
in the bounded patch; database concurrency remains outside this verification.
Before deployment, a read-only production arithmetic check confirmed that
displayed live profit matched the old dividend-added formula. No personal
balances or receipt-history records are included in this repository.
