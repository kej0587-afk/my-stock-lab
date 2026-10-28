-- Dedicated manual trade journal; never used by order or signal verification paths.
create table if not exists public.event_swing_ledger (
    owner_email text not null,
    trade_id uuid not null,
    created_at timestamptz not null default now(),
    payload jsonb not null,
    primary key (owner_email, trade_id)
);
alter table public.event_swing_ledger enable row level security;
drop policy if exists event_swing_owner on public.event_swing_ledger;
create policy event_swing_owner on public.event_swing_ledger
    for all using (owner_email = coalesce(auth.jwt() ->> 'email', ''))
    with check (owner_email = coalesce(auth.jwt() ->> 'email', ''));
