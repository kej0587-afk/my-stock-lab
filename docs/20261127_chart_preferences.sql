-- Prepared only; this migration has NOT been applied by the app or agent.
-- Saves each owner's quick-chart settings (moving-average periods, which lines are on,
-- daily-MA overlay, interval) so they survive a new session or a reboot.
-- One row per owner. Display preferences only; no account data. Owner isolation for the
-- server-only service_role client is enforced by SupabaseChartPreferenceStore (every read
-- filters owner_email and re-checks it; every upsert is keyed by it). Same pattern as report_latest.
-- Until this runs the settings last for the current browser session and the screen says so.

begin;

create table if not exists public.chart_preferences (
    owner_email text primary key
        check (owner_email <> '' and owner_email = lower(btrim(owner_email))),
    prefs jsonb not null check (jsonb_typeof(prefs) = 'object' and length(prefs::text) <= 4000),
    updated_at timestamptz not null default now()
);

alter table public.chart_preferences enable row level security;
alter table public.chart_preferences force row level security;

drop policy if exists chart_preferences_no_client_access on public.chart_preferences;
create policy chart_preferences_no_client_access
    on public.chart_preferences as restrictive for all to anon, authenticated
    using (false) with check (false);

revoke all on table public.chart_preferences from public, anon, authenticated;
revoke all on table public.chart_preferences from service_role;
grant select, insert, update on table public.chart_preferences to service_role;

commit;
