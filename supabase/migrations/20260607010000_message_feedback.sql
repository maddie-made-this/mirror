-- Per-message feedback (B3 / handoff A1.2). The dominant direct-signal channel:
-- 'check' = "this is right for me", 'x' = "not right for me" (+ optional note).
-- Feedback links to message_id; the turn's input_node_ids/input_interpretation_ids
-- (B2) tell the service WHICH graph elements to credit/discredit.
--
-- HARD BOUNDARY (A1.5): an 'x' note is delivery-tuning signal only. It is NEVER
-- extracted, never becomes graph content, never routed to the interpretation layer.

create table if not exists public.message_feedback (
  id              uuid primary key default gen_random_uuid(),
  user_id         uuid not null,
  conversation_id uuid not null,
  message_id      uuid not null,      -- the turn being reacted to
  reaction        text not null check (reaction in ('check', 'x')),
  note            text,               -- freeform comment, on 'x' only
  created_at      timestamptz not null default now()
);

create index if not exists message_feedback_msg
  on public.message_feedback (user_id, message_id);

alter table public.message_feedback enable row level security;

create policy "own_feedback" on public.message_feedback
  using (auth.uid() = user_id);
