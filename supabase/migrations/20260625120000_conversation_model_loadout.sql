-- Per-conversation model loadout label (e.g. 'small-large', 'single-model'), shown as a
-- small indicator on the chat sessions list. Written by save_turn from the deployment
-- config at write time and refreshed every turn, so it pins whatever loadout actually
-- generated the conversation — and stays correct once per-conversation model selection
-- lands. Null for conversations created before this column existed.

alter table public.conversations
  add column if not exists model_loadout text;
