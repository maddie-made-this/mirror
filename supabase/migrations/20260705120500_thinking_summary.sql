-- "Mirror's thinking" click-through (product reshape §3.6 / P2.4). The thinking view is
-- assembled from REAL pipeline artifacts already stored on the turn (input_node_ids,
-- input_interpretation_ids, steering_objective, piece_brief) + element_offers — costs
-- nothing. An OPTIONAL narrativized "its read" summary sits on top: generated lazily on
-- first open (one cheap-model call) and cached here, null until then. Never theater — the
-- artifacts are the truth; the summary is clearly a summary.
--
-- Note: the "generation_inputs" the spec names is not a table — those fields are columns
-- on conversation_turns (the 20260607000000_generation_inputs.sql migration ALTERs this
-- table), so the cache column lives here too.

alter table public.conversation_turns
  add column if not exists thinking_summary text;
