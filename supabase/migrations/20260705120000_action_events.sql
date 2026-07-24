-- Action-events log (product reshape §6.1 / P0.2). A typed, queryable stream of the
-- user's per-beat actions — the preference/telemetry signal that length adaptation
-- (#10a), retry diagnostics, chip weighting, and supersede-pair labels read. UI
-- telemetry + preference signal is relational, not graph. Cheap to write, expensive
-- to retrofit — hence a first-class table now.

create table if not exists public.action_events (
  id              uuid primary key default gen_random_uuid(),
  user_id         uuid not null,
  conversation_id uuid not null,
  target_turn_id  uuid,             -- conversation_turns.id acted on (nullable)
  action          text not null check (action in
    ('longer','shorter','retry','edit','accept_chip','canonize','decanonize')),
  render_mode     text,             -- 'conversational' | 'piece'
  payload         jsonb not null default '{}',
  created_at      timestamptz not null default now()
);

create index if not exists action_events_user_conv
  on public.action_events (user_id, conversation_id, created_at desc);

alter table public.action_events enable row level security;

create policy "own_action_events" on public.action_events
  using (auth.uid() = user_id);
