# 2026-11-01 Account Performance Ledger

## Boundary

This adds a separate, on-demand account-performance workspace ahead of the
heavy current-holdings price analysis. It never changes trading grades,
execution thresholds, holdings, cash balances, financial scores or old monthly
rows. There is no market fetch or database write on the new calculation path.
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
Legacy dividend-inclusion conventions still require user confirmation; old
profit formulas and historic values are not silently restated.

The monthly rebalancing shortcut previously added planned contributions to
capital and could save selected-account NAV as whole-owner monthly NAV.
The shortcut now labels the plan as unconfirmed, defaults actual capital from
the existing month or prior record (not the plan), and requires an actual
cumulative net-contribution confirmation and full account scope before saving.
Negative net contributions remain valid; old dividends and prior rows remain
unchanged. Both UI disabling and a server-side guard block invalid saves.
The manually edited monthly table's existing save/delete semantics are untouched.

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
