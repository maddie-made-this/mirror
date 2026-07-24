-- Locked piece-state per conversation (Generation & Direction, Change 2). The
-- director establishes subject/POV/subjects/setting once, and from then on it
-- is fed back as FIXED invariants rather than re-guessed each turn — which is what
-- stops subject/pronoun/frame drift mid-piece. A conversation is treated as one
-- piece: a user re-frame ("make it second person this time") updates this lock for the
-- conversation (Change 4, piece-only); a fresh conversation re-derives from the
-- user's identity facts.
--
-- jsonb shape = PieceFrame: {subject_pov, subjects, context, current_section}.
-- Null until the first piece turn establishes it.

alter table public.conversations
  add column if not exists piece_frame jsonb;
