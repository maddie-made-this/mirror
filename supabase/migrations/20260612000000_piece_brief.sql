-- Director→renderer split (Part B, §B2/C1): persist the PieceBrief the director
-- emitted for each piece turn, so the brief can be inspected in the debug panel
-- (Part D) and reconstructed in the full-run dump (Part C). jsonb holds the whole
-- structured brief (action, advance_directive, do_not_repeat, function_to_serve,
-- prerequisites, register, piece_frame, pacing, interest_anchor, hard_avoid).
--
-- Null on the single-model path and for analytic (director-only) turns.

alter table public.conversation_turns
  add column if not exists piece_brief jsonb;
