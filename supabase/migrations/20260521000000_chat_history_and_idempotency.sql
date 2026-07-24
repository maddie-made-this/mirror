-- Chat history (K) and request idempotency (E).
-- The backend connects as the postgres role and enforces ownership in its
-- queries; RLS below is defense-in-depth for any future direct client reads.

-- ── Idempotency keys (E) ─────────────────────────────────────────────
-- One row per (user, client_message_id). A retry reuses the same
-- client_message_id; the server dedups on it and replays the cached response.
create table public.idempotency_keys (
  user_id           uuid not null,
  conversation_id   uuid not null,
  client_message_id uuid not null,
  status            text not null check (status in ('in_flight', 'complete')),
  response_json     jsonb,
  created_at        timestamptz not null default now(),
  completed_at      timestamptz,
  primary key (user_id, client_message_id)
);

-- Supports cleanup of stale in_flight rows (manual or cron).
create index idempotency_keys_status_age
  on public.idempotency_keys (status, created_at)
  where status = 'in_flight';

-- ── Conversation turns (K) ───────────────────────────────────────────
-- One row per completed exchange. Replaces the :ConversationTurn nodes
-- that previously lived in Neo4j.
create table public.conversation_turns (
  id                uuid primary key default gen_random_uuid(),
  user_id           uuid not null,
  conversation_id   uuid not null,
  message_id        uuid not null,
  client_message_id uuid not null,
  user_message      text not null,
  response_text     text not null,
  created_at        timestamptz not null default now()
);

create index conversation_turns_conv_time
  on public.conversation_turns (user_id, conversation_id, created_at desc);

alter table public.conversation_turns enable row level security;

create policy "own_turns" on public.conversation_turns
  using (auth.uid() = user_id);

alter table public.idempotency_keys enable row level security;

create policy "own_idempotency_keys" on public.idempotency_keys
  using (auth.uid() = user_id);