-- Canon tracking for the single-stream cowriter.
-- Every beat is a turn. Regenerating a beat replaces it: the superseded turn
-- stays in the full conversational stream (the user can scroll back / recover a
-- prior generation) but drops OUT of canon. The canon view filters to is_canon,
-- and prompt history injection uses canon-only so discarded beats don't pollute
-- context.

alter table public.conversation_turns
  add column if not exists is_canon boolean not null default true;

-- Fast canon-filtered history reads per conversation.
create index if not exists conversation_turns_canon
  on public.conversation_turns (user_id, conversation_id, created_at desc)
  where is_canon;
