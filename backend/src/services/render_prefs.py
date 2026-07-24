"""Length adaptation (product reshape §6.4 / P4.1).

Repeated longer/shorter presses = the user correcting a length dial; stop making them
re-press. The target is stored PER render-mode bucket (piece vs conversational — never one
global number) in profiles.render_prefs, moved a damped fraction per press and clamped to a
sane range (no unbounded ratchet). The damped multiplicative step IS the accumulator — no
press counter. Reads/writes are node-free: this is pure delivery-tuning (Phase 4).
"""
import json
import logging
from uuid import UUID

from db.postgres import get_pool

logger = logging.getLogger(__name__)

# CONTESTABLE constants (change-doc §6.4 / registry).
DAMP = 0.15                                    # fractional move per press
BOUNDS = {"cowrite": (300, 2000), "conversational": (30, 400)}
# Starting point when a bucket has no learned target yet (first press bumps from here).
DEFAULT_TARGETS = {"cowrite": 800, "conversational": 120}


def _bucket(render_mode: str) -> str | None:
    """Map a render_mode to its length bucket. author + piece share the long-form bucket;
    analysis has its own length and is not adapted (None)."""
    if render_mode in ("cowrite", "author"):
        return "cowrite"
    if render_mode == "conversational":
        return "conversational"
    return None


def _clamp(value: int, bucket: str) -> int:
    lo, hi = BOUNDS[bucket]
    return max(lo, min(hi, value))


def _prefs_from_row(raw) -> dict:
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return {}
    return raw or {}


def target_words(prefs: dict, render_mode: str) -> int | None:
    """The learned target for this mode, or None when none is stored (→ no directive; the
    prompt's qualitative default stands). `prefs` is a loaded render_prefs dict."""
    bucket = _bucket(render_mode)
    if bucket is None:
        return None
    val = (prefs or {}).get(bucket, {}).get("target_words")
    return int(val) if isinstance(val, (int, float)) and val > 0 else None


async def get_render_prefs(user_id: UUID) -> dict:
    """Load a user's render_prefs (empty dict if unset)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchval(
            "SELECT render_prefs FROM profiles WHERE id = $1", user_id
        )
    return _prefs_from_row(row)


async def bump(user_id: UUID, render_mode: str, direction: str) -> int | None:
    """
    Move the mode's target one damped step toward the pressed direction and persist it.
    Returns the new target (so the reroll can use it immediately), or None when the mode
    isn't length-adapted (analysis) — the caller then regenerates with no length change.
    """
    bucket = _bucket(render_mode)
    if bucket is None:
        return None
    prefs = await get_render_prefs(user_id)
    current = prefs.get(bucket, {}).get("target_words") or DEFAULT_TARGETS[bucket]
    factor = 1 + DAMP if direction == "longer" else 1 - DAMP
    new_target = _clamp(round(current * factor), bucket)

    prefs[bucket] = {"target_words": new_target}
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE profiles SET render_prefs = $2::jsonb WHERE id = $1",
            user_id,
            json.dumps(prefs),
        )
    return new_target
