-- Supersede-pair logging + training-consent (product reshape §6.3 / P0.4). Every
-- pick-after-regenerate logs the kept-vs-rejected generation pair — the uptake signal
-- now, the DPO-style dataset for the future fine-tune (the moat flywheel starts at
-- launch, but only if logged, and only training-eligible with explicit consent). The
-- consent value is SNAPSHOT at write time so a later consent change can't retroactively
-- license old pairs. Write call-site is the variant-pick path (P1.4).

create table if not exists public.supersede_pairs (
  id               uuid primary key default gen_random_uuid(),
  user_id          uuid not null,
  conversation_id  uuid not null,
  kept_turn_id     uuid not null,
  rejected_turn_id uuid not null,
  render_mode      text,
  retry_note       text,
  training_consent boolean not null,      -- SNAPSHOT of the user's setting at write time
  created_at       timestamptz not null default now()
);

create index if not exists supersede_pairs_user
  on public.supersede_pairs (user_id, created_at desc);

alter table public.supersede_pairs enable row level security;

create policy "own_supersede_pairs" on public.supersede_pairs
  using (auth.uid() = user_id);

-- Training-consent lives on public.profiles (the reshape's "profile_settings" = columns
-- on public.profiles, keyed by id). Default OFF: per-user graph learning is always on
-- (the product), but cross-user model training on user content is the opt-in (L6.3).
alter table public.profiles
  add column if not exists training_consent boolean not null default false;
