-- PREPARED ONLY: run once in the Supabase SQL editor; the app never creates schema.
-- Keeps the latest validated DART corporate identity list (stock code -> corp code)
-- so a transient DART outage after an app restart can still identify issuers.
-- Public identifiers only: no account data, credentials or financial statements.
-- Existing tables are not modified. Until this runs, the app reports
-- persist_status=schema_unavailable and keeps its previous behaviour.

begin;

create table public.dart_corporate_code_snapshots (
    source text primary key
        check (source = 'https://opendart.fss.or.kr/api/corpCode.xml'),
    version integer not null check (version = 1),
    retrieved_at timestamptz not null,
    mapped_count integer not null check (mapped_count between 1 and 200000),
    codes_sha256 text not null check (codes_sha256 ~ '^[0-9a-f]{64}$'),
    codes jsonb not null
        check (jsonb_typeof(codes) = 'object')
        check (octet_length(codes::text) <= 8388608),
    saved_at timestamptz not null default now()
);

alter table public.dart_corporate_code_snapshots enable row level security;
alter table public.dart_corporate_code_snapshots force row level security;
create policy dart_corporate_codes_no_client_access
    on public.dart_corporate_code_snapshots as restrictive for all to anon, authenticated
    using (false) with check (false);

revoke all on table public.dart_corporate_code_snapshots from public, anon, authenticated;
revoke all on table public.dart_corporate_code_snapshots from service_role;
-- One row per source, replaced only after the app validates a live download.
grant select, insert, update on table public.dart_corporate_code_snapshots to service_role;

commit;
