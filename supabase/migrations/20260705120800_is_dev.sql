-- Log-hygiene / debug gating (product reshape §10.4 / P5.1). The dev debug panel (which
-- can surface prompt internals) is gated behind a per-user flag, default false, so it is
-- never exposed to a real user in prod. Read via GET /account/me; there is no self-serve
-- endpoint to set it (set out-of-band for dev accounts).
--
-- Tree note: a COLUMN on public.profiles, not a "profile_settings" table.

alter table public.profiles
  add column if not exists is_dev boolean not null default false;
