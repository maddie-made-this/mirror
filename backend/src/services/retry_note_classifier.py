"""
Retry-note classifier + router (product reshape §6.2 / P0.3B).

When the retry chip's optional note box is populated, a cheap-model classifier buckets
the short string into content / delivery / discard (a note can be BOTH), then routes
GRAPH-FEEDING only:
  - content   -> an extraction pass (the ONE bounded case where a generated beat enters
               extraction, as RELATIVE reference), prov_source='retry_correction'.
  - delivery -> the length/param path (#10a, Phase 4) — never the graph (same wall as
               feedback notes).
  - discard  -> intent-free noise; nothing written (silent).

The classifier is DUMB by design (four-way bucket, no confidence scores). Under any
uncertainty it BIASES TO CONTENT — a low-weight noisy signal is recoverable
(provenance-gated, reaction-tested); a wrongly-dropped real correction is just lost. The
reroll itself always consumes the WHOLE note regardless of classification; only
graph-feeding is gated here, and it's fire-and-forget (the reroll never awaits it).
"""
import json
import logging
from dataclasses import dataclass
from uuid import UUID

from config.loader import APP_CONFIG
from llm.client import chat
from services.interpretation import _strip_fence

logger = logging.getLogger(__name__)


@dataclass
class RetryRouting:
    content: str | None = None      # a change to WHAT/the angle/the argument ("make it more rigorous")
    delivery: str | None = None    # a change to HOW it's written ("too long", "less flowery")
    discard: bool = False          # intent-free noise ONLY


_SYSTEM = (
    "You bucket a short 'what do you want done differently?' retry note by what it asks "
    "for. Return JSON only: "
    '{"content": <string|null>, "delivery": <string|null>, "discard": <bool>}.\n'
    "- content = a change to WHAT the piece argues / its angle / its focus "
    "(\"make it more rigorous\", \"focus on the counterexample\").\n"
    "- delivery = a change to HOW it is written: length, pacing, flowery-ness "
    "(\"too long\", \"less purple\", \"slow down\").\n"
    "- A note can be BOTH (\"too long AND more rigorous\") — fill both fields.\n"
    "- discard = true ONLY for genuinely intent-free text (accidental send, \"asdfgh\"). "
    "Terse-but-intentful (\"sharper\") is CONTENT, never discard.\n"
    "- Under any uncertainty, prefer CONTENT over discard.\n"
    "Copy the user's own words into the bucket strings; do not rewrite them."
)


async def classify(note: str, original_user_msg: str, rejected_beat: str) -> RetryRouting:
    """One cheap-model call. The rejected beat is RELATIVE CONTEXT (the correction is
    'sharper *than that*') — never itself extracted."""
    note = (note or "").strip()
    if not note:
        return RetryRouting(discard=True)
    user = (
        f"Original request: {original_user_msg}\n"
        f"[the attempt they're correcting, reference only]: {rejected_beat}\n"
        f"Their retry note: {note}"
    )
    try:
        raw = await chat(
            [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}],
            model=APP_CONFIG.extraction_model_resolved,  # P5.3 extraction tier (Haiku-class)
            response_format={"type": "json_object"},
            temperature=0.0,
        )
        data = json.loads(_strip_fence(raw))
    except Exception:
        logger.warning("retry-note classify failed; biasing to content", exc_info=True)
        return RetryRouting(content=note)  # bias-to-content on failure (recoverable)
    if not isinstance(data, dict):
        return RetryRouting(content=note)
    content = (data.get("content") or "").strip() or None
    delivery = (data.get("delivery") or "").strip() or None
    discard = bool(data.get("discard")) and not content and not delivery
    if not content and not delivery and not discard:
        content = note  # never silently drop an intentful note
    return RetryRouting(content=content, delivery=delivery, discard=discard)


async def route_retry_note(
    user_id: UUID,
    conversation_id: UUID,
    message_id: UUID,
    note: str,
    original_user_msg: str,
    rejected_beat: str,
    *,
    session_number: int,
    user_display_name: str = "",
) -> RetryRouting:
    """
    Classify the note and route GRAPH-FEEDING only (the reroll consumes the whole note
    separately). Fire-and-forget from the retry endpoint — never awaited by the reroll.
    Returns the routing (for logging/tests). The note BODY is stored once in
    supersede_pairs.retry_note (§P0.4); nothing is duplicated here.
    """
    routing = await classify(note, original_user_msg, rejected_beat)
    if routing.content:
        # HANDOFF: the content component leaves the retry classifier here and feeds the
        # MAIN extraction system (extraction.extract_from_retry_correction → the mindmap
        # graph). This classifier's job ends at routing; how a content becomes a node is
        # the main-extraction system's concern — and that system's internals are getting a
        # separate scaffold redesign in its own session. Route→extract are sequential and
        # share no code, so that redesign should not touch this classifier — but this is
        # one of its upstream feeders, so it's discoverable when that work happens.
        from services import extraction  # lazy import — avoid a cycle with extraction
        await extraction.extract_from_retry_correction(
            user_id, routing.content, original_user_msg, rejected_beat,
            conversation_id=conversation_id, message_id=message_id,
            session_number=session_number, user_display_name=user_display_name,
        )
    # delivery -> #10a length/param path (Phase 4); the action_events 'retry' row + the
    # note in supersede_pairs already capture it. discard -> nothing.
    return routing
