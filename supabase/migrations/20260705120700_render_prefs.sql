-- Length adaptation (product reshape §6.4 / P4.1). Per-render-mode word target learned
-- from repeated longer/shorter presses — a damped, clamped dial, NOT one global number
-- (the same user wants 200-word replies and 1,200-word essays). Shape:
--   {"piece": {"target_words": int}, "conversational": {"target_words": int}}
-- null/absent per mode → the APP_CONFIG default (no directive injected).
--
-- Tree note: the reshape's "profile_settings" are COLUMNS on public.profiles (keyed by
-- id), not a table — same as enter_to_send / memory_paused / training_consent.

alter table public.profiles
  add column if not exists render_prefs jsonb not null default '{}';
