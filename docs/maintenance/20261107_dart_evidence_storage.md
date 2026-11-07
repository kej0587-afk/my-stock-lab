# Private DART evidence storage adapter — prepared integration

Date: 2026-11-07 KST. Base `9054d62b`.
Implements the storage phase of the [bridge design](20261107_dart_evidence_bridge_design.md).

## Delivered / not deployed

- `stock_lab_core/dart_evidence_store.py`: injected server-client adapter;
  immutable insert, duplicate verification and latest matching-scope lookup.
- [Prepared SQL](../20261107_dart_evidence.sql): one dedicated private table,
  lookup index and access policy. **Not executed.**
- Tests use the installed PostgREST request builder with `httpx.MockTransport`.
  No credentials, API requests or real database connections are used.

The app does not import the new adapter yet. No existing runtime/scoring/provider
files or dependencies were changed. Saved scores, thresholds, account data and
decision text remain unchanged. No Cloud restart is needed for these isolated
additions; Cloud DART transport remains unresolved.

## Contract

Construct `SupabaseDartEvidenceStore(existing_server_client, owner_scope=verified_owner)`
per authenticated owner. Both `insert_bundle` and `load_latest` require that same
owner again, an explicit ticker and a currently usable official corporate map.
The map's freshness and listing suffix are the calling UI's responsibility; a raw
uploaded claim is not an acceptable map. No new client or credential is created.

`insert_bundle` validates a deep copy with the existing version-1 validator. It
rejects missing identity, partial/empty/expired/future data and ticker disagreement
before any database call. It derives owner, content digest and scope digest on
the server; import time comes from the database. Recent and explicitly stale
(24h–7d) evidence are allowed with their original collection age preserved.

The only write operation is INSERT. PostgreSQL duplicate code23505 triggers a
read of the exact owner+ticker+digest; the returned payload/digest/scope must match
before reporting `inserted=false`. This also handles concurrent identical imports.
There is no update, delete or merge-upsert, and repeated imports never renew age.
A corrected filing produces a new digest/row. An ambiguous write response reports
`write_unconfirmed`; a manual retry can verify the same digest without overwriting.

`load_latest` filters owner+ticker+scope and collection time, then fetches at most
one payload. It orders by collection time, import time and digest for deterministic
ties. Scope hash is derived from sorted (year, report-code) pairs; order within the
request list does not matter. Scope must match exactly: half-year-only evidence
cannot silently satisfy a request that also includes Q3. This additional indexed
column avoids scanning many potentially large JSON files for another period.

Every returned row is revalidated for owner, ticker, corporate ID, payload hash,
scope, source, schema and timestamps. Corrupt/ineligible rows produce an error,
not a silent healthy result. Empty eligible history returns `None`; connection,
permission and missing-schema errors stay distinct from empty history. Schema
failures use `schema_unavailable`; arbitrary DB messages/URLs are never exposed.
The adapter contains no global personal cache or automatic score refresh.

## SQL impact and limitations

Running the prepared SQL once would add `financial_evidence_bundles` to the shared
Supabase project. Existing tables/data are untouched. It is a transaction and
deliberately fails if the table already exists, so an unexpected schema is not
silently reused. Inspect an existing table rather than dropping it or rerunning
partial statements. The table has owner+ticker+digest primary key and an index
for exact-scope recent lookup; no backfill, scheduled job or retention deletion.

RLS is enabled/forced, direct anon/authenticated access is denied, and service_role
receives SELECT/INSERT only. The current app login is not a Supabase user JWT;
service credentials bypass RLS, making server owner checks essential. See
[Supabase RLS documentation](https://supabase.com/docs/guides/database/postgres/row-level-security).
The adapter uses insert responses and SQLSTATE duplicate handling rather than an
update-capable upsert; see the [Python insert API](https://supabase.com/docs/reference/python/insert).

SQL adds basic JSON shape/metadata/size guards. Detailed row/accounting validation
and canonical hashes remain server responsibilities. The JSONB text-size ceiling
is16MiB to allow its extra whitespace; the existing package validator still enforces
8MiB canonical input. Neither a digest nor an uploaded DART label authenticates the
original issuer. Future UI must retain the local-upload/source-verification label.

## Verification

- Storage + collector + financial review/refresh contracts: **131 passed**, 15.01s.
- Actual installed PostgREST request construction verified with mock HTTP responses,
  including representation headers, exact duplicate retrieval and owner filtering.
- Coverage includes two owners, cross-owner returned rows, corrected filings,
  mismatched scope/ticker/metadata, expired/partial/empty evidence, failure handling,
  unconfirmed writes, input immutability and preserved import/collection times.
- Prepared SQL parsed successfully as **10 PostgreSQL statements** using `pglast`
  installed only under ignored `cache/sql_validation/`; no app dependency added.
  Syntax parsing is not database execution or an RLS/privilege integration test.
- Fixed-source decision gate: **1,327 passed**, 100.682s; no failures, skips or
  source changes during the run. Evidence `cache/refactor_checks/decision_9gnax73k`.
  No golden baselines regenerated. This is selected regression coverage, not
  full-suite/live-UI/performance validation.

No live schema application, owner isolation against the production DB or UI
roundtrip is claimed. Those require the later UI integration and one-time setup.

## Next bounded task

Wire the precision observatory's explicit file preview/import and read-only stored
evidence panel using this adapter. Use existing authenticated owner, verify selected
ticker and listing identity, show coverage/age/source, and keep saved grades untouched.
Handle a missing table with a clear setup state and link to the prepared SQL; do not
run migrations automatically. Test locally before any production roundtrip. Actual
storage verification follows only after the table has been set up.
