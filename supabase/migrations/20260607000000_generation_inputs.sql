-- Generation-input tracking (B2) + observational-signal columns (B4).
--
-- B2: record WHICH graph elements fed each generation, so per-message feedback
-- (check/x) can credit/discredit the *right* nodes/interpretations/steering choice,
-- not just the message. input_node_ids is populated now (from build_graph_context);
-- input_interpretation_ids and steering_objective fill in once generation flows 2/3
-- are wired (B5). text[] (not uuid[]) because node ids are slugs, not UUIDs.
--
-- B4: cheap per-message metadata for later behavioral/stylistic interpretation.

alter table public.conversation_turns
  add column if not exists input_node_ids           text[] not null default '{}',
  add column if not exists input_interpretation_ids text[] not null default '{}',
  add column if not exists steering_objective        text,
  add column if not exists msg_char_len             int,
  add column if not exists msg_token_len            int,
  add column if not exists response_latency_ms      int;
