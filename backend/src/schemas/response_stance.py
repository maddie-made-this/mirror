"""
ResponseStance (master spec C3) — the conversational-mode analogue of PieceBrief, but
tiny. On a non-generation conversational turn the lightweight director emits one of these (tens of
tokens, not the PieceBrief's thousands): what to react to, whether to land a read /
ask / just engage, the read or question itself, register cues, what to avoid, and
whether the user is early (assert lightly, earn depth) or accumulated (you know them).

Defensive parse mirrors PieceBrief: a partial/malformed director response still yields
a usable stance rather than crashing the turn.
"""
from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, Field

from schemas.piece_brief import _first_json_object, _strip_fence

logger = logging.getLogger(__name__)


class ResponseStance(BaseModel):
    engagement_target: str = ""      # what in the user's message to react to
    move: Literal["land_read", "ask_targeted", "engage"] = "engage"
    read: str = ""                   # move==land_read: the grounded observation to land
    question: str = ""               # move==ask_targeted: ONE in-register question
    register_notes: str = ""         # delivery cues (register, density)
    # what to steer clear of — drift-to-analysis, strain, generic warmth, flattery
    avoid: list[str] = Field(default_factory=list)
    # assert lightly + earn depth when early; lean on what you know when accumulated
    user_knowledge_level: Literal["early", "accumulated"] = "early"

    @classmethod
    def parse(cls, raw: str) -> "ResponseStance | None":
        if not raw or not raw.strip():
            return None
        obj = _first_json_object(_strip_fence(raw))
        if obj is None:
            logger.warning("ResponseStance.parse: no JSON object found")
            return None
        v = obj.get("avoid")
        if isinstance(v, str):
            obj["avoid"] = [v] if v.strip() else []
        elif v is None:
            obj["avoid"] = []
        try:
            return cls.model_validate(obj)
        except Exception:
            logger.warning("ResponseStance.parse: validation failed", exc_info=True)
            return None
