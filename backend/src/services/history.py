import logging
from uuid import UUID, uuid4

from config.loader import APP_CONFIG
from core import request_context
from core.settings import get_settings
from db.postgres import get_pool
from schemas.message import ConversationTurn

logger = logging.getLogger(__name__)

# Variant-compare cap (product reshape §3.2 / P1.4, CONTESTABLE): at most this many takes
# per beat group. On regeneration beyond the cap, the oldest non-canon take is evicted
# (COGS + clutter). One take is always canon, so cap-1 non-canon siblings are retained.
TAKE_GROUP_CAP = 5

# Short names for the per-conversation model-loadout indicator (chat-list badge).
_KNOWN_MODELS = (
    "haiku", "sonnet", "opus", "grok", "qwen", "mistral", "nemo", "llama",
    "gemma", "phi", "command",
)


def _short_model(model_id: str) -> str:
    """Map a full model id ('anthropic/claude-haiku-4.5') to a short loadout
    fragment ('haiku'); fall back to the trailing path/tag segment."""
    if not model_id:
        return "?"
    m = model_id.lower()
    for name in _KNOWN_MODELS:
        if name in m:
            return name
    tail = m.rsplit("/", 1)[-1].split(":")[0]
    return tail[:16] or "?"


def _renderer_model_label() -> str:
    """The renderer's ACTUAL model short-name, mirroring the client's model-override
    precedence (llm.client.chat): a pinned provider's renderer_model, else the config
    renderer_model — what TRULY renders, so the chat-list badge never shows the
    misleading OpenRouter default."""
    s = get_settings()
    if s.renderer_base_url and s.renderer_model:
        return _short_model(s.renderer_model)
    return _short_model(APP_CONFIG.renderer_model_resolved)


def _loadout_label() -> str:
    """Short director-renderer loadout label for the conversations row, e.g.
    'sonnet-llama' (split on) or 'sonnet-only' (single model). Reflects the
    DEPLOYMENT config at write time — per-conversation model selection is a
    future feature, so this pins whatever loadout actually generated the turn."""
    cfg = APP_CONFIG
    if cfg.use_director_split or cfg.use_dual_render:
        return f"{_short_model(cfg.director_model_resolved)}-{_renderer_model_label()}"
    active = request_context.get_response_model() or cfg.response_model_resolved
    return f"{_short_model(active)}-only"


async def get_recent_turns(
    conversation_id: UUID,
    user_id: UUID,
    limit: int = 10,
    *,
    canon_only: bool = False,
) -> list[ConversationTurn]:
    """
    Return the last `limit` turns in chronological order.
    Fetches latest-first then reverses, so older turns come first.

    canon_only=True excludes beats superseded by a regeneration — used for the
    canon view and for prompt history injection (so discarded beats don't
    pollute the model's context). Default False returns the full stream.
    """
    pool = await get_pool()
    canon_clause = "AND is_canon" if canon_only else ""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            # Archived takes (cap-evicted variant siblings) are retained for training but
            # hidden from the stream and history injection.
            f"""
            -- A turn is generative if it was RENDERED in a generative register.
            -- Deriving that from piece_brief instead fails twice: a cowrite turn
            -- stores no brief at all when the director split is off, and a
            -- conversational ResponseStance lands in the same column. Rows
            -- written before render_mode existed fall back to the brief shape
            -- (arc_position is on every PieceBrief and no stance).
            SELECT user_message, response_text, created_at, message_id,
                   COALESCE(
                     render_mode IN ('author', 'cowrite'),
                     (piece_brief->>'arc_position') IS NOT NULL
                   ) AS is_piece
            FROM conversation_turns
            WHERE user_id = $1 AND conversation_id = $2 {canon_clause}
              AND NOT archived
            ORDER BY created_at DESC
            LIMIT $3
            """,
            str(user_id),
            str(conversation_id),
            limit,
        )
    return list(reversed([
        ConversationTurn(
            user_message=r["user_message"],
            response_text=r["response_text"],
            created_at=r["created_at"],
            message_id=r["message_id"],
            is_piece=bool(r["is_piece"]),
        )
        for r in rows
    ]))


async def get_last_piece_brief(conversation_id: UUID, user_id: UUID) -> dict | None:
    """
    The most recent persisted PieceBrief for this conversation (Part B), or None.
    Used as the carry-forward base when a director call fails to parse, so the
    fallback keeps the established piece_frame / do_not_repeat instead of resetting.
    The pool's json codec decodes the jsonb column straight to a dict.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT piece_brief FROM conversation_turns
            WHERE user_id = $1 AND conversation_id = $2 AND piece_brief IS NOT NULL
            ORDER BY created_at DESC
            LIMIT 1
            """,
            str(user_id),
            str(conversation_id),
        )
    return row["piece_brief"] if row and row["piece_brief"] else None


async def get_conversation_piece_frame(
    conversation_id: UUID, user_id: UUID
) -> dict | None:
    """
    The LOCKED piece-state for this conversation (Change 2), or None if not yet
    established. Fed to the director as fixed invariants so subject/pronoun/frame
    don't drift mid-piece. The pool's json codec decodes the jsonb to a dict.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT piece_frame FROM conversations
            WHERE id = $1 AND user_id = $2 AND piece_frame IS NOT NULL
            """,
            str(conversation_id),
            str(user_id),
        )
    return row["piece_frame"] if row and row["piece_frame"] else None


async def set_conversation_piece_frame(
    conversation_id: UUID, user_id: UUID, piece_frame: dict | None
) -> None:
    """
    Persist/refresh the conversation's locked piece-state (Change 2). Called after a
    piece turn with the director's emitted piece_frame — establishes it on turn one
    and absorbs a user re-frame thereafter (Change 4, piece-only). No-op on an empty
    state (all fields blank), so a director that emitted nothing doesn't wipe the lock.
    The row is guaranteed to exist (save_turn upserts it before this runs).
    """
    if not piece_frame or not any(str(v or "").strip() for v in piece_frame.values()):
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE conversations SET piece_frame = $3 WHERE id = $1 AND user_id = $2",
            str(conversation_id),
            str(user_id),
            piece_frame,  # jsonb — encoded by the pool's json codec
        )


async def get_session_type(conversation_id: UUID, user_id: UUID) -> str:
    """
    Return the conversation's session_type ('primary' or 'analytic') from the
    parent conversations table — the register selector for the prompt stack (B10).
    Defaults to 'primary' when the row doesn't exist yet (e.g. a brand-new primary
    chat whose first turn hasn't been saved); analytic branches are created
    explicitly with session_type='analytic' before their first turn.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT session_type FROM conversations
            WHERE id = $1 AND user_id = $2
            """,
            str(conversation_id),
            str(user_id),
        )
    return (row["session_type"] if row and row["session_type"] else "primary")


async def list_conversations(user_id: UUID) -> list[dict]:
    """
    Return one summary row per conversation for this user, ordered by most
    recent activity. Reads the parent `conversations` table (the source of
    truth for session_type/title/pinned/parent link) and joins per-conversation
    turn aggregates. Used to hydrate the frontend chat list on login.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                c.id                      AS conversation_id,
                c.session_type            AS session_type,
                c.parent_conversation_id  AS parent_conversation_id,
                c.title                   AS title,
                c.pinned                  AS pinned,
                c.model_loadout           AS model_loadout,
                c.created_at              AS first_at,
                c.updated_at              AS last_at,
                coalesce(t.turn_count, 0) AS turn_count,
                coalesce(t.first_user_message, '') AS first_user_message,
                coalesce(t.last_response_text, '') AS last_response_text
            FROM conversations c
            LEFT JOIN LATERAL (
                SELECT
                    count(*) AS turn_count,
                    (array_agg(user_message ORDER BY created_at ASC))[1]  AS first_user_message,
                    (array_agg(response_text ORDER BY created_at DESC))[1] AS last_response_text
                FROM conversation_turns ct
                WHERE ct.user_id = c.user_id AND ct.conversation_id = c.id
            ) t ON true
            WHERE c.user_id = $1
            ORDER BY c.updated_at DESC
            """,
            str(user_id),
        )
    return [dict(r) for r in rows]


async def supersede_turn(user_id: UUID, message_id: UUID) -> bool:
    """
    Mark a turn non-canon (it was regenerated away). It remains visible in the
    full stream but drops out of the canon view and prompt history. Returns True
    if a row was updated.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE conversation_turns SET is_canon = false
            WHERE user_id = $1 AND message_id = $2
            """,
            str(user_id),
            str(message_id),
        )
    return result.endswith("1")


async def get_turn_for_retry(user_id: UUID, message_id: UUID) -> dict | None:
    """The context a retry-note reroll needs (P0.3B): {conversation_id, user_message,
    response_text (the rejected beat), render_mode}. None if not owned by the user."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT conversation_id, user_message, response_text, piece_brief
            FROM conversation_turns
            WHERE user_id = $1 AND message_id = $2
            """,
            str(user_id),
            str(message_id),
        )
    if not row:
        return None
    return {
        "conversation_id": row["conversation_id"],
        "user_message": row["user_message"],
        "response_text": row["response_text"],
        "render_mode": "cowrite" if row["piece_brief"] else "conversational",
    }


async def edit_turn_text(
    user_id: UUID, message_id: UUID, text: str
) -> dict | None:
    """
    Edit-as-canon (P1.5): replace a beat's response_text IN PLACE on its row (same beat =
    same row). Returns {conversation_id, prev_text, render_mode} for the action-event log,
    or None if the turn isn't owned by this user. Does NOT touch the graph — extraction
    reads user_message only, never response_text (verified) — so an edit is a delivery/
    uptake signal, not an interest-extraction source.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                SELECT conversation_id, response_text, piece_brief
                FROM conversation_turns
                WHERE user_id = $1 AND message_id = $2
                """,
                str(user_id),
                str(message_id),
            )
            if not row:
                return None
            await conn.execute(
                """
                UPDATE conversation_turns SET response_text = $3
                WHERE user_id = $1 AND message_id = $2
                """,
                str(user_id),
                str(message_id),
                text,
            )
    return {
        "conversation_id": row["conversation_id"],
        "prev_text": row["response_text"],
        "render_mode": "cowrite" if row["piece_brief"] else "conversational",
    }


async def pick_take(
    user_id: UUID, beat_group_id: UUID, turn_id: UUID
) -> dict | None:
    """
    Variant pick (P1.4): make `turn_id` the canon take in its beat group and drop the
    siblings out of canon. Returns {conversation_id, kept, rejected, render_mode} — where
    `rejected` is the previously-canon take (or None if the pick is a no-op / the group had
    none) — so the caller can log the supersede pair + action events. None if the group is
    empty or the chosen take isn't a member (ownership + membership enforced).
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            rows = await conn.fetch(
                """
                SELECT message_id, is_canon, conversation_id, piece_brief
                FROM conversation_turns
                WHERE user_id = $1 AND beat_group_id = $2
                """,
                str(user_id),
                str(beat_group_id),
            )
            if not rows:
                return None
            members = {r["message_id"] for r in rows}
            if turn_id not in members:
                return None
            prev_canon = next(
                (r["message_id"] for r in rows if r["is_canon"] and r["message_id"] != turn_id),
                None,
            )
            conversation_id = rows[0]["conversation_id"]
            render_mode = "cowrite" if any(r["piece_brief"] for r in rows) else "conversational"
            await conn.execute(
                # The picked take becomes canon AND is un-archived (defensive: a pick can
                # only reach an active take via the UI, but never leave a canon+archived
                # row); siblings drop out of canon, archive flags otherwise untouched.
                """
                UPDATE conversation_turns
                SET is_canon = (message_id = $3),
                    archived = archived AND (message_id <> $3)
                WHERE user_id = $1 AND beat_group_id = $2
                """,
                str(user_id),
                str(beat_group_id),
                str(turn_id),
            )
    return {
        "conversation_id": conversation_id,
        "kept": turn_id,
        "rejected": prev_canon,
        "render_mode": render_mode,
    }


async def get_beat_takes(
    user_id: UUID, conversation_id: UUID, beat_group_id: UUID
) -> list[dict]:
    """
    All takes (siblings) in a beat group, oldest first — the '‹ 1/3 ›' variant picker.
    Each: {turn_id (message_id), text, is_canon, created_at}.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            # Active takes only — archived (cap-evicted) siblings are retained for training
            # but out of the '‹ 1/3 ›' rotation.
            """
            SELECT message_id, response_text, is_canon, created_at
            FROM conversation_turns
            WHERE user_id = $1 AND conversation_id = $2 AND beat_group_id = $3
              AND NOT archived
            ORDER BY created_at
            """,
            str(user_id),
            str(conversation_id),
            str(beat_group_id),
        )
    return [
        {
            "turn_id": r["message_id"],
            "text": r["response_text"] or "",
            "is_canon": r["is_canon"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]


async def create_conversation(
    user_id: UUID,
    *,
    session_type: str = "primary",
    parent_conversation_id: UUID | None = None,
    title: str | None = None,
    conversation_id: UUID | None = None,
) -> UUID:
    """
    Explicitly create a parent conversation row. Used for branch creation (sets
    parent_conversation_id + session_type='analytic') and any flow that needs
    the row before the first turn is saved. Returns the conversation id.
    """
    conv_id = conversation_id or uuid4()
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO conversations
                (id, user_id, session_type, parent_conversation_id, title)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (id) DO NOTHING
            """,
            str(conv_id),
            str(user_id),
            session_type,
            str(parent_conversation_id) if parent_conversation_id else None,
            title,
        )
    return conv_id


async def update_conversation(
    user_id: UUID,
    conversation_id: UUID,
    *,
    pinned: bool | None = None,
    title: str | None = None,
) -> bool:
    """
    Patch a conversation's pinned/title. Only provided fields change. Returns
    True if a row was updated (i.e. owned by this user). Always bumps nothing
    extra — updated_at is left to reflect activity, not metadata edits.
    """
    sets: list[str] = []
    args: list[object] = []
    if pinned is not None:
        args.append(pinned)
        sets.append(f"pinned = ${len(args)}")
    if title is not None:
        args.append(title)
        sets.append(f"title = ${len(args)}")
    if not sets:
        return False

    args.extend([str(user_id), str(conversation_id)])
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            f"""
            UPDATE conversations
            SET {", ".join(sets)}
            WHERE user_id = ${len(args) - 1} AND id = ${len(args)}
            """,
            *args,
        )
    # asyncpg returns e.g. "UPDATE 1"
    return result.endswith("1")


async def save_turn(
    conversation_id: UUID,
    user_id: UUID,
    message_id: UUID,
    client_message_id: UUID,
    user_message: str,
    response_text: str,
    *,
    input_node_ids: list[str] | None = None,
    input_interpretation_ids: list[str] | None = None,
    steering_objective: str | None = None,
    msg_char_len: int | None = None,
    msg_token_len: int | None = None,
    response_latency_ms: int | None = None,
    piece_brief: dict | None = None,
    stage_timings: dict | None = None,
    regenerate_of: UUID | None = None,
    render_mode: str | None = None,
) -> None:
    """
    Persist one completed exchange so future calls can inject it as history, and
    upsert the parent conversations row (create-on-first-turn with a title from
    the opening message; bump updated_at thereafter). Both writes are one
    transaction so the parent row never lags behind its turns.

    Generation-input tracking (B2): input_node_ids / input_interpretation_ids /
    steering_objective record what the graph contributed to THIS generation, so
    per-message feedback (check/x) can credit/discredit the right elements.
    Observational signal (B4): msg_char_len / msg_token_len / response_latency_ms.
    Per-stage latency (Change 5): stage_timings is the sub-timing breakdown
    (director_ms/render_ms or generate_ms, plus the guard timings); response_latency_ms
    stays the single end-to-end number.

    Variant compare (P1.4): regenerate_of is the message_id of the beat this turn
    replaces. When set, the new take joins that beat's beat_group_id, the prior takes
    drop out of canon (retained as siblings for the '‹ 1/3 ›' picker), and the group is
    trimmed to TAKE_GROUP_CAP. When None, the turn stands alone (beat_group_id =
    message_id) — the ordinary path.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO conversations
                    (id, user_id, session_type, title, model_loadout, created_at, updated_at)
                VALUES ($1, $2, 'primary', left($3, 60), $4, now(), now())
                ON CONFLICT (id) DO UPDATE SET updated_at = now(), model_loadout = $4
                """,
                str(conversation_id),
                str(user_id),
                user_message,
                _loadout_label(),
            )

            # P1.4: resolve the beat group. A regeneration inherits the superseded
            # beat's group and knocks its prior takes out of canon; a fresh beat is its
            # own group (beat_group_id = message_id).
            beat_group_id = message_id
            if regenerate_of is not None:
                prior = await conn.fetchrow(
                    """
                    SELECT coalesce(beat_group_id, message_id) AS bg
                    FROM conversation_turns
                    WHERE user_id = $1 AND message_id = $2
                    """,
                    str(user_id),
                    str(regenerate_of),
                )
                if prior and prior["bg"]:
                    beat_group_id = prior["bg"]
                    await conn.execute(
                        """
                        UPDATE conversation_turns SET is_canon = false
                        WHERE user_id = $1 AND beat_group_id = $2
                        """,
                        str(user_id),
                        str(beat_group_id),
                    )

            await conn.execute(
                """
                INSERT INTO conversation_turns
                    (user_id, conversation_id, message_id, client_message_id,
                     user_message, response_text, beat_group_id,
                     input_node_ids, input_interpretation_ids, steering_objective,
                     msg_char_len, msg_token_len, response_latency_ms, piece_brief,
                     stage_timings, render_mode)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
                """,
                str(user_id),
                str(conversation_id),
                str(message_id),
                str(client_message_id),
                user_message,
                response_text,
                str(beat_group_id),
                input_node_ids or [],
                input_interpretation_ids or [],
                steering_objective,
                msg_char_len,
                msg_token_len,
                response_latency_ms,
                piece_brief,  # jsonb — encoded transparently by the pool's json codec
                stage_timings,  # jsonb — per-stage latency (Change 5)
                render_mode,  # the register this turn was rendered in
            )

            # P1.4 cap: keep at most TAKE_GROUP_CAP takes ACTIVE in the group — the new
            # canon take plus the newest cap-1 non-canon siblings. Older non-canon takes
            # are ARCHIVED, never deleted: a rejected take is supersede-pair training data
            # (the DPO dataset), so its content must stay reachable from its supersede_pair.
            # Archiving drops it from the active group + the stream while retaining the row.
            # Already-archived rows are ignored (not re-counted, not re-touched).
            if regenerate_of is not None:
                await conn.execute(
                    """
                    UPDATE conversation_turns SET archived = true
                    WHERE user_id = $1 AND beat_group_id = $2
                      AND is_canon = false AND archived = false
                      AND message_id NOT IN (
                        SELECT message_id FROM conversation_turns
                        WHERE user_id = $1 AND beat_group_id = $2
                          AND is_canon = false AND archived = false
                        ORDER BY created_at DESC
                        LIMIT $3
                      )
                    """,
                    str(user_id),
                    str(beat_group_id),
                    TAKE_GROUP_CAP - 1,
                )

    # Observational signal stream — also logged for ad-hoc analysis.
    logger.info(
        "message_signal",
        extra={
            "user_id": str(user_id),
            "conversation_id": str(conversation_id),
            "user_chars": msg_char_len if msg_char_len is not None else len(user_message),
            "user_words": len(user_message.split()),
            "response_chars": len(response_text),
            "input_node_count": len(input_node_ids or []),
            "steering_objective": steering_objective,
        },
    )
