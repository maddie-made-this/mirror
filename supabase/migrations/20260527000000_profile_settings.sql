alter table public.profiles
  add column if not exists enter_to_send boolean default true,
  add column if not exists memory_paused boolean default false,
  add column if not exists preferred_language text default 'English',
  add column if not exists preferred_model text default 'Mirror General v1.2 (Fast)';