-- Story documents (product reshape §2.2 / P1.1). A story is a DERIVED view over a
-- conversation's canon turns — content is NEVER copied here; render_story reads
-- conversation_turns WHERE is_canon, so canonize/edit/variant reflow into the document
-- automatically (zero sync logic, one source of truth). The row holds only metadata:
-- title, cover, the character-color + piece-tint map, pinning. The Library of these is
-- the retention surface.

create table if not exists public.stories (
  id                     uuid primary key default gen_random_uuid(),
  user_id                uuid not null,
  source_conversation_id uuid not null,
  title                  text,
  cover_state            jsonb not null default '{}',
  color_map              jsonb not null default '{}',   -- speaker colors + piece tints
  pinned                 boolean not null default false,
  created_at             timestamptz not null default now(),
  updated_at             timestamptz not null default now()
);

create index if not exists stories_user_updated
  on public.stories (user_id, updated_at desc);

alter table public.stories enable row level security;

create policy "own_stories" on public.stories
  using (auth.uid() = user_id);
