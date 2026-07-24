-- Variant compare on the last beat (product reshape §3.2 / P1.4). Regenerations of a
-- single beat share a beat_group_id; each take is an is_canon sibling and exactly one
-- (the picked one) is canon. "‹ 1/3 ›" queries siblings by beat_group_id; "pick" flips
-- is_canon within the group. Backfilled so every existing turn stands alone in its own
-- group.
--
-- Identity note: the group is keyed by message_id (the app-facing turn identity the chat
-- client tracks as serverId and that supersede/feedback already target), NOT the internal
-- `id` surrogate the spec's backfill text named — the frontend never sees `id`.

alter table public.conversation_turns
  add column if not exists beat_group_id uuid;

update public.conversation_turns
  set beat_group_id = message_id
  where beat_group_id is null;

create index if not exists conversation_turns_beat_group
  on public.conversation_turns (user_id, conversation_id, beat_group_id, created_at);
