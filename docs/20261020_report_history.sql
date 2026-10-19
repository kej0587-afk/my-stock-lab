-- Prepared only; this migration has NOT been applied by the app or agent.
-- Source: app.py require_login() and get_supabase_client_cached().
-- Streamlit Google OIDC/password auth supplies a verified owner_email to the
-- server. It is NOT a Supabase Auth session and provides no auth.uid()/user JWT.
-- The existing server-only service_role/secret client bypasses RLS. Therefore
-- owner isolation for that client is enforced by SupabaseReportHistoryStore:
-- every read filters owner_email; every upsert has that owner in its key.
-- Never inject a browser client or use an owner taken from arbitrary UI input.
-- https://supabase.com/docs/guides/database/postgres/row-level-security
-- No suitable dedicated JSON store exists: settings has typed scalar columns;
-- signal_journal.snapshot belongs to ticker/signal rows, not report sessions.
-- Running this once adds one private table for the shared Supabase project.
-- Existing tables/rows are untouched. No retention deletion is performed.

begin;

create table if not exists public.report_history (
    owner_email text not null
        check (owner_email <> '' and owner_email = lower(btrim(owner_email))),
    us_session date not null,
    kr_session date not null,
    payload jsonb not null
        check (jsonb_typeof(payload) = 'object')
        check ((jsonb_typeof(payload -> 'rows') = 'array') is true)
        check ((payload -> 'dates' ->> 'US') is not null
               and (payload -> 'dates' ->> 'KR') is not null)
        check ((payload -> 'dates' ->> 'US') = to_char(us_session, 'YYYY-MM-DD')
               and (payload -> 'dates' ->> 'KR') = to_char(kr_session, 'YYYY-MM-DD')),
    primary key (owner_email, us_session, kr_session)
);

alter table public.report_history enable row level security;
alter table public.report_history force row level security;

-- Deny direct client access even if another permissive policy is later added.
drop policy if exists report_history_no_client_access on public.report_history;
create policy report_history_no_client_access
    on public.report_history as restrictive for all to anon, authenticated
    using (false) with check (false);

revoke all on table public.report_history from public, anon, authenticated;
revoke all on table public.report_history from service_role;
grant select, insert, update on table public.report_history to service_role;

commit;
