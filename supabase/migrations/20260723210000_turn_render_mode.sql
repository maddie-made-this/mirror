-- The register a turn was RENDERED in ('author' | 'cowrite' | 'analysis' |
-- 'conversational'), recorded per turn.
--
-- The client shows reaction chips on generative turns, and until now the only
-- way to tell one apart after the fact was "did this row store a piece_brief?".
-- That test is wrong twice over: a conversational ResponseStance lands in the
-- same column, and a cowrite turn stores NO brief at all when the director
-- split is disabled — so a co-writing turn looked identical to small talk.
--
-- Recording the mode makes the register a first-class fact instead of something
-- inferred from an artifact that may or may not exist.

alter table public.conversation_turns
  add column if not exists render_mode text;

-- Backfill what is recoverable: arc_position is a PieceBrief field with a
-- default, so it is present on every stored piece brief and on no stance.
-- Everything else stays null and falls back to the old inference at read time.
update public.conversation_turns
   set render_mode = 'author'
 where render_mode is null
   and (piece_brief->>'arc_position') is not null;
