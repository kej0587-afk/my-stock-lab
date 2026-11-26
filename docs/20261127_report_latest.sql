-- Prepared only; this migration has NOT been applied by the app or agent.
-- Stores each owner's last completed market report so a new session or a reboot can show it
-- first (with its generation time) while a new report is built. One row per owner; a new
-- report overwrites it. The text names holdings: owner isolation for the server-only
-- service_role client is enforced by SupabaseReportLatestStore (every read filters
-- owner_email; every upsert is keyed by that owner). Same pattern as report_history.
-- Until this runs the app keeps an owner-hashed local copy only (lost on reboot).
-- Existing tables/rows are untouched. No retention deletion is performed.

begin;

create table if not exists public.report_latest (
    owner_email text primary key
        check (owner_email <> '' and owner_email = lower(btrim(owner_email))),
    generated_at timestamptz not null,
    report_text text not null
        check (length(report_text) between 1 and 1000000)
);

alter table public.report_latest enable row level security;
alter table public.report_latest force row level security;

drop policy if exists report_latest_no_client_access on public.report_latest;
create policy report_latest_no_client_access
    on public.report_latest as restrictive for all to anon, authenticated
    using (false) with check (false);

revoke all on table public.report_latest from public, anon, authenticated;
revoke all on table public.report_latest from service_role;
grant select, insert, update on table public.report_latest to service_role;

commit;
