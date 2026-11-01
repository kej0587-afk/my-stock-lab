-- Prepared only; NOT executed by the app or agent.
-- Streamlit supplies a verified owner via its existing login. This is not a
-- Supabase Auth session: no user JWT or auth.uid() is available on this path.
-- Inject only the existing server-only service_role client. It bypasses RLS;
-- SupabaseAccountPerformanceStore binds every read/update to that app owner
-- and embeds the owner in each first insert. Never trust an owner from UI input.
-- Running this once adds a private table for the shared Supabase project.
-- Existing tables and financial/history records are untouched. No data is
-- backfilled, deleted or inferred. Updates use owner + expected revision;
-- the server supplies updated_at on updates (the database defaults inserts).

begin;

create table if not exists public.account_performance_ledgers (
    owner_email text primary key
        check (owner_email <> '' and owner_email = lower(btrim(owner_email))),
    revision bigint not null check (revision > 0),
    payload jsonb not null
        check (jsonb_typeof(payload) = 'object')
        check ((jsonb_typeof(payload -> 'version') = 'number'
                and payload ->> 'version' = '1') is true)
        check ((payload ->> 'currency_basis' = 'KRW') is true)
        check ((payload ->> 'flow_timing' = 'end_of_day') is true)
        check ((jsonb_typeof(payload -> 'valuations') = 'array') is true)
        check ((jsonb_typeof(payload -> 'flows') = 'array') is true)
        check (jsonb_array_length(payload -> 'valuations') <= 5000)
        check (jsonb_array_length(payload -> 'flows') <= 5000),
    updated_at timestamptz not null default now()
);

alter table public.account_performance_ledgers enable row level security;
alter table public.account_performance_ledgers force row level security;

-- Deny direct clients even if a permissive policy is added later.
drop policy if exists account_performance_ledgers_no_client_access
    on public.account_performance_ledgers;
create policy account_performance_ledgers_no_client_access
    on public.account_performance_ledgers as restrictive for all to anon, authenticated
    using (false) with check (false);

revoke all on table public.account_performance_ledgers from public, anon, authenticated;
revoke all on table public.account_performance_ledgers from service_role;
grant select, insert, update on table public.account_performance_ledgers to service_role;

commit;
