-- PREPARED ONLY: not executed by the agent or application.
-- Adds one private table/index/policy in the shared Supabase project.
-- Existing tables, saved grades and account data are not modified.
-- The app uses verified Streamlit identity, not Supabase user JWTs.
-- service_role bypasses RLS: the server adapter must bind every operation to
-- verified owner + ticker, validate payloads, and verify returned identities.
-- No credentials, cron, backfill, retention deletion or automatic migration.
-- The table name must be unused: fail on an unexpected existing schema rather
-- than silently trusting CREATE TABLE IF NOT EXISTS. Execute once in a transaction.

begin;

create table public.financial_evidence_bundles (
    owner_email text not null
        check (length(owner_email) between 1 and 320 and owner_email = lower(btrim(owner_email))),
    ticker text not null check (ticker ~ '^[0-9A-Z]{6}\.(KS|KQ)$'),
    corp_code text not null check (corp_code ~ '^[0-9]{8}$'),
    bundle_sha256 text not null check (bundle_sha256 ~ '^[0-9a-f]{64}$'),
    scope_sha256 text not null check (scope_sha256 ~ '^[0-9a-f]{64}$'),
    schema_version integer not null check (schema_version = 1),
    source text not null check (source = 'dart'),
    collected_at timestamptz not null,
    imported_at timestamptz not null default now(),
    payload jsonb not null
        check (jsonb_typeof(payload) = 'object')
        -- JSONB adds whitespace compared with the 8 MiB canonical file limit.
        -- This 16 MiB DB guard is secondary; the adapter enforces the file limit.
        check (octet_length(payload::text) <= 16777216)
        check ((payload ->> 'ticker' = ticker) is true)
        check ((payload ->> 'corp_code' = corp_code) is true)
        check ((payload ->> 'source' = source) is true)
        check ((payload -> 'schema_version' = '1'::jsonb) is true)
        check ((payload ->> 'endpoint' = 'https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json') is true)
        check (((payload ->> 'collected_at')::timestamptz = collected_at) is true)
        check ((jsonb_typeof(payload -> 'requested_reports') = 'array') is true)
        check (jsonb_array_length(payload -> 'requested_reports') between 1 and 25)
        check ((jsonb_typeof(payload -> 'reports') = 'array') is true)
        check (jsonb_array_length(payload -> 'reports') between 1 and 25)
        check ((jsonb_typeof(payload -> 'attempts') = 'array') is true)
        check (jsonb_array_length(payload -> 'attempts') between 1 and 50),
    primary key (owner_email, ticker, bundle_sha256)
);

-- Scope hash is derived from sorted (year, report-code) pairs, not upload claims.
-- It prevents latest-for-other-periods searches and limits reads to one payload.
create index financial_evidence_scope_latest_idx
    on public.financial_evidence_bundles
    (owner_email, ticker, scope_sha256, collected_at desc, imported_at desc, bundle_sha256 desc);

alter table public.financial_evidence_bundles enable row level security;
alter table public.financial_evidence_bundles force row level security;
create policy financial_evidence_no_client_access
    on public.financial_evidence_bundles as restrictive for all to anon, authenticated
    using (false) with check (false);

revoke all on table public.financial_evidence_bundles from public, anon, authenticated;
revoke all on table public.financial_evidence_bundles from service_role;
grant select, insert on table public.financial_evidence_bundles to service_role;
-- No UPDATE/DELETE permissions: repeated imports verify an existing digest.
-- Hash authenticity and detailed row/coverage validation remain server duties;
-- SQL constraints alone do not authenticate uploaded financial statements.

commit;
