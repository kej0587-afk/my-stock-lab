# Prospective Account Ledger Storage

## Scope

Add optional durable storage to the existing prospective account-performance
workspace. Trading grades, prices, indicators, performance math, holdings,
cash balances, dividends and legacy monthly records are unchanged. There is
no historical backfill, no conversion of ex-dividend monthly valuations, and
no automatic capture of unverified live prices as end-of-day NAV.

The user will record future valuations and external cash flows. The ledger's
NAV includes retained/reinvested dividends; dividend receipts and internal
trades/FX are not external contributions. These accounting rules are unchanged.

## Setup

The user chose to execute docs/20261101_account_performance.sql in Supabase SQL
Editor. The app and agent do not execute migrations. This adds ONE private
table, public.account_performance_ledgers, to the shared project. Each owner
has one versioned current draft containing all of their ledger accounts. It
does not change existing tables or migrate/delete any financial data.

This repository's Streamlit login is not Supabase Auth. The existing trusted
server-only service client bypasses RLS, so the adapter binds the verified
CURRENT_USER_EMAIL on construction. Every read/update filters that owner;
the initial insert embeds it. An owner from editor/upload fields is never
used for storage authorization. Direct anon/authenticated client access is
denied by RLS, a restrictive false policy and revoked table privileges.
Only SELECT, INSERT and UPDATE are granted to service_role; no DELETE.

Official references:
- https://supabase.com/docs/guides/database/postgres/row-level-security
- https://supabase.com/docs/reference/python/update
- https://supabase.com/docs/reference/python/insert

## Save Contract

- Constructor and screen rendering do not access the database. Only an
  explicit server-check or form-save action makes a request. No extra market
  data, LLM, credentials or network client is introduced.
- A successful empty-server check permits the first INSERT at revision 1.
  Existing records must be explicitly restored before they establish the
  editing baseline. Checking a newer record is not permission to overwrite it.
- Updates are atomic compare-and-swap: owner AND expected revision must match,
  then revision increments. There is no upsert or read-then-unconditional-write.
  A concurrent insert collision or zero-row update is a conflict, not success.
- Load preview never replaces applied local data. Restore requires a separate
  checkbox/action. Applying/restoring/importing data invalidates displayed
  results and completeness confirmations via the existing local draft revision.
- The form's explicit save submits current editor values, applies independent
  local copies, then saves. A network/schema/conflict error retains the applied
  local draft, blocks further saves until a server baseline is reestablished,
  and leaves JSON export available. It never retries or rebases silently.
- Save confirmation validates the returned owner, revision and canonical
  payload. Unconfirmed responses do not claim success, even if a write might
  have committed. Error displays contain fixed codes/messages, not DB URLs,
  raw exceptions, personal data or secrets.
- The same portable format, 1 MB limit, 5,000 rows/table, exact date/numeric
  parsing and leading-zero IDs are retained. Partial drafts may be stored;
  storing a draft is not a claim that it is valid for return calculation.
- Cash-flow completeness and calculated results are not stored. Each restored
  session must confirm flow completeness again. No exact TWR is claimed.

## Limits

This table stores the current owner draft, not a revision archive or immutable
transaction journal. Compare-and-swap prevents concurrent overwrites, not
recovery of every intentionally replaced earlier version. JSON exports remain
useful independent backups. Editing unsubmitted form contents is distinct from
applying a draft; only submitted values can be stored.

Public demo mode remains session/file-only. Older cached renderers without
the optional storage argument retain file-only operation with an explicit
status, instead of raising an unexpected-keyword exception. The existing
source registry includes the new adapter; metadata does not relabel loaded
hashes or reload running modules.

Real private DB records are not used as test fixtures. Offline fake clients
exercise owner isolation, compare-and-swap and response validation. Real
Streamlit widget tests exercise explicit restore, reconnect, owner switches,
error retention and form-save state. A schema-only production read can verify
connectivity after the user applies SQL, without inserting fabricated ledger
rows into their real account. Actual durable roundtrip verification is not
claimed unless performed with authorized real records.

## Verification

The complete regression suite passed: 4,773 tests, 1 skipped, 18 subtests in
249.04s. A final display-state correction then clears old cloud-success notices
on local apply/import; all 167 affected storage, form, wiring, source-provenance
and renderer tests passed again in 37.89s. No financial formulas changed.

The local browser fixture uses synthetic data and an explicitly labeled
in-memory fake database, not Supabase. It confirmed first-save gating, explicit
save, clearing the connection draft while retaining the fake server record,
non-destructive load preview, explicit restore and completeness reset. The
restored example still returns 15.31% Modified Dietz with KRW 17,000 investment
profit and KRW 18,000 net external flows. These are validation examples, not
the user's account performance. No real ledger row was inserted during tests.
