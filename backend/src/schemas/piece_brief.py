import json
import logging
from typing import Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class PieceRegister(BaseModel):
    """
    Delivery DIALS (how it's said), not content (what's said). The director sets
    these from the dynamics layer + the user's demonstrated register so the
    renderer matches the voice instead of inventing one.
    """
    vividness: str = ""             # e.g. "plain" | "concrete" | "rich"
    prose_density: str = ""         # e.g. "terse" | "moderate" | "lush"
    person_tense: str = ""          # e.g. "second-present" | "first-past"
    emphasis: str = ""              # e.g. "light" | "building" | "strong"


class PieceFrame(BaseModel):
    """
    The piece's fixed frame — subject/subjects/setting — so the renderer can SHOW
    rather than restate. These are the irreducible facts the director treats as
    blocking prerequisites (A5).
    """
    subject_pov: str = ""     # the piece's subject / point-of-view frame
    subjects: str = ""               # other subjects in the piece
    context: str = ""               # the situation being written about
    current_section: str = ""          # the beat we are on right now


class PieceBrief(BaseModel):
    """
    The director→renderer hand-off (Part B, §B2). The director (frontier reasoning,
    the editorial MIND) emits this; the renderer (prose craft, the VOICE) consumes
    it. The brief carries DECISIONS and DIRECTIVES — never finished prose — so the
    reasoning model isn't asked to generate the content, only to plan it.

    Every field is optional with a safe default: a partial or slightly-malformed
    director response still yields a usable brief rather than crashing the turn.
    """

    # The director's top-level decision.
    action: Literal["ask", "write", "ask_then_write"] = "write"
    # The ONE in-register question, when asking (else null/empty).
    question: str | None = None

    # Anti-loop core: what must PROGRESS vs. the last turn, and
    # the beats/lines already used that must NOT be reused verbatim.
    advance_directive: str = ""
    do_not_repeat: list[str] = Field(default_factory=list)

    # The irreducible who/whom facts still missing — gather before writing (A5).
    prerequisites_to_establish: list[str] = Field(default_factory=list)

    # The idiographic interest to lean into (from flow-2). Rendered as experience on
    # the page, never named or explained to the user.
    function_to_serve: str = ""

    # Delivery dials (not content) and the who/where so prose can show, not tell.
    # Named `delivery` (not `register`) to avoid shadowing BaseModel's ABC
    # `register` classmethod — same concept, the delivery dials.
    delivery: PieceRegister = Field(default_factory=PieceRegister)
    piece_frame: PieceFrame = Field(default_factory=PieceFrame)

    # Narrative arc (Change 1) — distinct from `pacing` (the depth ramp). The global
    # structure the prose model won't supply on its own: the director sets it and
    # carries it across turns (read from the prior brief, advanced, re-emitted) so the
    # piece actually builds toward its claim instead of dwelling on one beat.
    arc_position: Literal["opening", "rising", "turning", "culmination", "resolution"] = "rising"
    # Rolling one-two-sentence trajectory the director REVISES each turn (Change 1 —
    # bounded memory). This, not the growing beat list, is what re-enters the prompt,
    # so director latency stays flat across a long piece.
    arc_synopsis: str = ""
    # Full played-beats log — grows in STORAGE (the system appends next_beat server-
    # side); never re-emitted by the director and only the tail re-enters the prompt.
    beat_history: list[str] = Field(default_factory=list)  # beats already played (compact)
    next_beat: str = ""  # the SPECIFIC move THIS turn makes (the editorial directive)

    # AUTHOR-MODE only: the full ordered beat skeleton (6-10 one-clause beats) the
    # author director hands the author renderer for one-shot expansion. EMPTY on the
    # turn-by-turn/dual paths — those use next_beat ("the move THIS turn makes") for the
    # turn-by-turn dance. Author-mode envelope requires this list; the renderer block
    # enumerates it as the numbered skeleton to expand.
    piece_beats: list[str] = Field(default_factory=list)

    # From the depth ramp.
    pacing: Literal["early", "mid", "deep"] = "mid"

    # Explicit reminder that the USER's interest stays central.
    interest_anchor: str = ""

    # Off-limits topics / registers — must never appear.
    hard_avoid: list[str] = Field(default_factory=list)

    @classmethod
    def parse(cls, raw: str) -> "PieceBrief | None":
        """
        Defensively parse a director completion into a PieceBrief.

        Tolerates: a leading ```json fence, prose before/after the object, and
        single trailing commas. Locates the OUTERMOST {...} and validates it.
        Returns None only when no JSON object can be recovered at all (caller
        falls back to a minimal brief so the turn still renders).
        """
        if not raw or not raw.strip():
            return None

        candidate = _strip_fence(raw)
        obj = _first_json_object(candidate)
        if obj is None:
            logger.warning("PieceBrief.parse: no JSON object found in director output")
            return None

        # Coerce the nested dicts/lists defensively before pydantic validation:
        # a frontier model occasionally returns a bare string where a list/object
        # is expected (e.g. do_not_repeat: "the opening line"). Normalise those shapes.
        obj = _normalize_shapes(obj)
        try:
            return cls.model_validate(obj)
        except Exception:
            logger.warning("PieceBrief.parse: validation failed", exc_info=True)
            return None


class PlanSegment(BaseModel):
    """One ordered piece of the reply in dual-model mode (Change 6). The director
    decides the boundaries and each segment's `role`; a RULE (not the director) sets
    `model` in production — role=='expressive' -> stylist, 'connective' -> reasoner —
    so the reasoner can't quietly keep an expressive beat and flatten it. In the
    self-assignment probe (Change 7) the rule is OFF and the director's own `model`
    is observed. `directive` is STAGING (what this segment covers), never prose."""
    index: int = 0
    role: str = "connective"          # "connective" | "expressive"
    model: str = ""                   # "reasoner" | "stylist" — director's pick (probe) or rule-set
    directive: str = ""               # what THIS segment must cover (staging, not prose)


class SegmentedPlan(BaseModel):
    """
    The director's hand-off in DUAL-MODEL mode (Change 6): instead of one brief for
    one renderer, an ordered set of segments rendered CONCURRENTLY by different models
    and concatenated. The shared smoothing fields (tone, locked piece_frame, global
    do_not_repeat, todos) go to EVERY segment so the independently-rendered pieces
    cohere; segments never receive each other's prose (that independence is what keeps
    latency ~= max, not sum). Arc/beat/anchor/avoid carry as in PieceBrief so dual
    mode persists the arc + piece-state lock the same way.

    Defensive parse() mirrors PieceBrief: a partial/malformed plan still yields a
    usable object rather than crashing the turn.
    """
    # Shared smoothing — given to BOTH models.
    tone: str = ""                                    # unified voice/register for the whole reply
    piece_frame: PieceFrame = Field(default_factory=PieceFrame)  # locked invariants
    do_not_repeat: list[str] = Field(default_factory=list)       # global anti-loop
    todos: list[str] = Field(default_factory=list)               # what the reply must accomplish
    segments: list[PlanSegment] = Field(default_factory=list)    # ORDERED — concat by index

    # Carried as in PieceBrief (arc continuity + persistence + register).
    arc_position: str = "rising"
    arc_synopsis: str = ""  # rolling trajectory the director revises (Change 1)
    beat_history: list[str] = Field(default_factory=list)
    next_beat: str = ""
    function_to_serve: str = ""
    delivery: PieceRegister = Field(default_factory=PieceRegister)
    pacing: str = "mid"
    interest_anchor: str = ""
    hard_avoid: list[str] = Field(default_factory=list)

    @classmethod
    def parse(cls, raw: str) -> "SegmentedPlan | None":
        if not raw or not raw.strip():
            return None
        obj = _first_json_object(_strip_fence(raw))
        if obj is None:
            logger.warning("SegmentedPlan.parse: no JSON object found")
            return None
        for list_field in ("do_not_repeat", "todos", "beat_history", "hard_avoid"):
            v = obj.get(list_field)
            if isinstance(v, str):
                obj[list_field] = [v] if v.strip() else []
            elif v is None:
                obj[list_field] = []
        if not isinstance(obj.get("segments"), list):
            obj["segments"] = []
        for obj_field in ("delivery", "piece_frame"):
            if not isinstance(obj.get(obj_field), dict):
                obj.pop(obj_field, None)
        try:
            return cls.model_validate(obj)
        except Exception:
            logger.warning("SegmentedPlan.parse: validation failed", exc_info=True)
            return None


def _strip_fence(raw: str) -> str:
    s = raw.strip()
    if not s.startswith("```"):
        return s
    lines = s.splitlines()[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _first_json_object(s: str) -> dict | None:
    """
    Return the first balanced {...} parsed as JSON, scanning for the opening brace
    and matching depth (ignoring braces inside strings). Survives prose wrapped
    around the object — common when a reasoning model narrates before the JSON.
    """
    start = s.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                blob = s[start : i + 1]
                try:
                    return json.loads(blob)
                except json.JSONDecodeError:
                    return None
    return None


def _normalize_shapes(obj: dict) -> dict:
    """Coerce a few common shape drifts so validation doesn't reject a usable brief."""
    for list_field in ("do_not_repeat", "prerequisites_to_establish", "hard_avoid",
                       "beat_history", "piece_beats"):
        v = obj.get(list_field)
        if isinstance(v, str):
            obj[list_field] = [v] if v.strip() else []
        elif v is None:
            obj[list_field] = []
    # Accept "register" as an inbound alias for the delivery dials — the director
    # may still emit either key; map it onto the canonical field.
    if "delivery" not in obj and isinstance(obj.get("register"), dict):
        obj["delivery"] = obj.pop("register")
    for obj_field in ("delivery", "piece_frame"):
        if not isinstance(obj.get(obj_field), dict):
            obj.pop(obj_field, None)  # drop a non-object so the default factory wins
    return obj
