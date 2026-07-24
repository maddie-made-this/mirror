-- P1.4 review hardening (2026-07-05).
--
-- (1) Beat groups key on message_id, so a duplicate message_id would silently corrupt
--     variant compare. message_id is a fresh server-side uuid4 per PROCESSED turn (one
--     row per exchange — the paired-row model is LOCKED; retries replay via idempotency
--     and never re-insert; no path mutates message_id), so it is already unique by
--     construction. This unique index makes that invariant DB-enforced — a collision
--     becomes an impossible state instead of an assumption. (If it fails to apply, that
--     itself surfaces a real duplicate worth investigating.)
--
-- (2) Take-group cap eviction must NEVER destroy content: rejected takes ARE the
--     supersede-pair (DPO) training dataset for the future fine-tune — a locked strategic
--     decision. Evicted takes are ARCHIVED (dropped from the active group + hidden from
--     the stream) but retained in full, reachable from their supersede_pair. Canon is
--     never archived.

create unique index if not exists conversation_turns_message_id_key
  on public.conversation_turns (message_id);

alter table public.conversation_turns
  add column if not exists archived boolean not null default false;
