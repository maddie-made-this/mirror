-- Parent conversations table.
-- Until now a conversation was implicit in a shared conversation_id on
-- conversation_turns. The branch-as-new-chat feature (analytic branch off a
-- primary chat) and robust history hydration both need a real parent row with
-- session_type, an optional parent link, a title, and a pinned flag.

create table public.conversations (
  id                      uuid primary key,
  user_id                 uuid not null,
  session_type            text not null default 'primary',
  parent_conversation_id  uuid,             -- set when this is an analytic branch
  title                   text,
  pinned                  boolean not null default false,
  created_at              timestamptz not null default now(),
  updated_at              timestamptz not null default now()
);

create index conversations_user_updated
  on public.conversations (user_id, updated_at desc);

alter table public.conversations enable row level security;

-- Defense-in-depth: the backend connects as the postgres role and enforces
-- ownership in its queries; this mirrors the policy on conversation_turns.
create policy "own_conversations" on public.conversations
  using (auth.uid() = user_id);

-- Backfill one parent row per existing (conversation_id, user_id) from turns,
-- titling each from its first user message so existing chats keep a label.
insert into public.conversations (id, user_id, session_type, title, created_at, updated_at)
select
  ct.conversation_id,
  ct.user_id,
  'primary',
  left((array_agg(ct.user_message order by ct.created_at asc))[1], 60),
  min(ct.created_at),
  max(ct.created_at)
from public.conversation_turns ct
group by ct.conversation_id, ct.user_id
on conflict (id) do nothing;
