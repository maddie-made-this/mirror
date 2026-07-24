-- Content model (build_content_model.md §3-§4): the trait dials + per-element uptake.
--
-- user_dynamics is the TRAIT layer (SalienceDynamics): slow-moving, per-user, moved
-- only by cross-session accumulation. The session layer (depth_ramp / gate_position /
-- frame / active_region) is computed per turn and deliberately NOT stored anywhere —
-- the strongest form of the "no session→trait write-back" rule.
--
-- element_offers is the per-element uptake instrumentation (§3/§6, extends B2):
-- every element the generation deliberately introduces (a steering probe, a
-- function/similarity candidate) gets an offer row; the user's NEXT message judges
-- uptake. ≥3 passes on the same element while clearly engaged → Sensitive (Neo4j).
-- Taken → the source reading's confidence rises. This loop is what makes
-- function-prediction error-corrected rather than confident guessing (§5.1).

create table if not exists public.user_dynamics (
  user_id                 uuid primary key,
  engagement_gain         real not null default 0.5,   -- how readily they lean in (0..1)
  reticence_gain          real not null default 0.5,   -- how readily they pull back (0..1)
  pacing_preference       text not null default '',    -- e.g. 'unhurried', 'direct'
  detail_tolerance        text not null default '',
  enablers                jsonb not null default '[]'::jsonb,  -- observed openers
  disablers               jsonb not null default '[]'::jsonb,  -- observed dead ends
  baseline_msg_chars      real not null default 0,     -- engagement baseline (gate deviation)
  sessions_observed       integer not null default 0,  -- traits move only after enough data
  confidence              real not null default 0.3,   -- the future learned-weight slot
  updated_at              timestamptz not null default now()
);

alter table public.user_dynamics enable row level security;

create policy "own_dynamics" on public.user_dynamics
  using (auth.uid() = user_id);

create table if not exists public.element_offers (
  id                bigserial primary key,
  user_id           uuid not null,
  conversation_id   uuid not null,
  message_id        uuid not null,      -- the AI turn that introduced the element
  element           text not null,      -- what was offered, short concrete phrase
  source_tag        text not null default '',  -- steering tag (function:/similar:/...)
  node_id           text,               -- graph node the element maps to, if known
  interpretation_id text,               -- function reading being tested, if any
  uptake            text check (uptake in ('taken', 'passed')),  -- null = pending
  judged_at         timestamptz,
  created_at        timestamptz not null default now()
);

create index if not exists element_offers_pending
  on public.element_offers (user_id, conversation_id) where uptake is null;

create index if not exists element_offers_node
  on public.element_offers (user_id, node_id);

alter table public.element_offers enable row level security;

create policy "own_offers" on public.element_offers
  using (auth.uid() = user_id);
