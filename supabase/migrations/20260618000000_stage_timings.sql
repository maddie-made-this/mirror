-- Per-stage latency instrumentation (Architecture & Orchestration, Change 5):
-- alongside the single response_latency_ms, persist a per-stage breakdown so the
-- three-architecture comparison (single-model / standard split / dual-model) is
-- legible and the run dump can print where each turn spent its time.
--
-- jsonb shape (sparse — only the stages that ran for this turn appear):
--   single-model : {"generate_ms", "output_guard_ms", "input_guard_ms"?}
--   split        : {"director_ms", "render_ms", "output_guard_ms", "input_guard_ms"?}
--   dual-model   : adds {"render_primary_ms", "render_secondary_ms"} (future)
-- input_guard_ms is present only when the input guard actually ran (it is dropped
-- on the split path — Change 4). Null on legacy turns recorded before this column.

alter table public.conversation_turns
  add column if not exists stage_timings jsonb;
