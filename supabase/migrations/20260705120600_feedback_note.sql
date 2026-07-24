-- Feedback comments (product reshape §3.5 / P2.3). Two changes to message_feedback:
-- (1) a note is now allowed on ANY reaction (was 'x'-only by convention), and
-- (2) a third voteless option 'note' — a comment with no up/down judgment.
--
-- HARD BOUNDARY (A1.5) UNCHANGED: notes are delivery-tuning signal only. They are never
-- extracted, never become graph content, never routed to the interpretation layer. This
-- migration only widens what the UI may attach; the extraction wall stays exactly where
-- it is (the feedback service still reinforces on 'check' alone).

alter table public.message_feedback
  drop constraint if exists message_feedback_reaction_check;

alter table public.message_feedback
  add constraint message_feedback_reaction_check
  check (reaction in ('check', 'x', 'note'));
