from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from schemas.extraction import Proposition
from schemas.graph import GraphEdge, GraphNode
from schemas.piece_brief import PieceBrief


class MessageRequest(BaseModel):
    message: str = Field(max_length=8000)
    conversation_id: UUID
    # user_id removed — derived from JWT only (A2).
    # session_number removed — derived server-side (B5).
    client_message_id: UUID = Field(
        ...,
        description="Stable per-message UUID generated client-side. "
                    "Retries reuse the same value; the server dedups on it.",
    )
    active_node_ids: list[str] = Field(
        default_factory=list,
        description="Canonical node IDs currently active in this session.",
    )
    user_display_name: str | None = Field(
        default=None,
        description=(
            "Display name of the user. Used to bootstrap the self-node and resolve "
            "self-references ('I', 'me', their actual name) to one canonical node."
        ),
    )
    regenerate_of: UUID | None = Field(
        default=None,
        description=(
            "P1.4 variant compare: when this turn is a regeneration of an existing "
            "beat, the message_id of that beat. The new take joins the same "
            "beat_group_id and the prior takes drop out of canon (kept as siblings)."
        ),
    )
    continue_piece: bool = Field(
        default=False,
        description=(
            "This turn continues a piece already in progress — a reaction chip or a "
            "retry of a generative beat. Register detection reads the message text "
            "alone, and a chip instruction ('Move to the next phase…') reads as "
            "ordinary conversation, so a piece would silently drop out of the "
            "generative register one turn in. Set by the client, which knows the "
            "turn it is continuing."
        ),
    )


class ConversationTurn(BaseModel):
    """One exchange stored for recent-history injection into the prompt."""
    user_message: str
    response_text: str
    created_at: datetime
    # The AI turn's message_id, so the client can wire per-message feedback
    # (check/x) onto loaded history, not just live beats. Optional: the
    # prompt-history injection path doesn't need it.
    message_id: UUID | None = None

    # True when this turn was rendered in the GENERATIVE register (the director
    # handed the renderer a PieceBrief) rather than the conversational one. The
    # client shows reaction chips on pieces, so it needs this on loaded history
    # and not just on the live turn — otherwise reopening a conversation drops
    # the chips off a piece that plainly has them.
    is_piece: bool = False


class ConversationSummary(BaseModel):
    """One summary row per conversation — used to hydrate the frontend chat list."""
    conversation_id: UUID
    session_type: str = "primary"
    parent_conversation_id: UUID | None = None
    title: str | None = None
    pinned: bool = False
    first_at: datetime
    last_at: datetime
    turn_count: int
    first_user_message: str
    last_response_text: str
    model_loadout: str | None = None  # 'sonnet-llama' / 'sonnet-only' — see history._loadout_label


class ConversationCreate(BaseModel):
    """Create a parent conversation explicitly (e.g. an analytic branch)."""
    session_type: str = "primary"
    parent_conversation_id: UUID | None = None
    title: str | None = None


class Chip(BaseModel):
    """
    One reaction chip for the single-stream cowriter. kind drives the icon and
    behaviour: advance (next beat), regenerate (replace last beat, don't advance),
    wildcard (a less-obvious graph-informed tonal/focus shift). `instruction` is
    the hidden steering text sent on tap; `label` is what the user sees.
    """
    kind: str            # "advance" | "regenerate" | "wildcard"
    label: str
    instruction: str


class ChipRequest(BaseModel):
    conversation_id: UUID
    beat: str = Field(max_length=8000, description="The current story beat to react to.")


class ChipResponse(BaseModel):
    chips: list[Chip]


class FeedbackRequest(BaseModel):
    """Per-message feedback (B3 / P2.3). 'check' / 'x' carry an up/down judgment; 'note'
    is the voteless third option. Any reaction may carry a delivery-tuning note — never
    graph content (hard boundary A1.5)."""
    reaction: str = Field(pattern="^(check|x|note)$")
    note: str | None = Field(default=None, max_length=2000)


class TestPieceRequest(BaseModel):
    """Ask the engine to offer a short coverage-probe piece (B9)."""
    conversation_id: UUID


class ChipAcceptRequest(BaseModel):
    """Directional-chip tap (P0.3A / P2.5). A tap is weaker evidence than a volunteered
    ask — reinforced at reduced weight, provenance offered_and_accepted."""
    conversation_id: UUID
    concept_slug: str
    chip_text: str = Field(default="", max_length=400)


class RetryNoteRequest(BaseModel):
    """Retry with an optional note (P0.3B / P2.5). The reroll consumes the whole note
    separately; this routes GRAPH-FEEDING only (content → extraction, delivery → later,
    discard → drop). Empty/absent note → just logs the retry action."""
    note: str | None = Field(default=None, max_length=2000)


class LengthRequest(BaseModel):
    """Longer/shorter reaction (P4.1). Adapts the per-mode word target (damped/clamped)
    and returns the new target so the reroll can use it."""
    direction: str = Field(pattern="^(longer|shorter)$")


class ConversationPatch(BaseModel):
    """Patch pin/title on a conversation. Omitted fields are left unchanged."""
    pinned: bool | None = None
    title: str | None = None


class MessageResponse(BaseModel):
    message_id: UUID = Field(default_factory=uuid4)
    conversation_id: UUID
    session_number: int

    response_text: str

    # Raw extractions — audit trail and graph debugging.
    # TODO (E12): gate behind a debug flag before production launch.
    propositions: list[Proposition]

    # Propositions extracted but not ingested because confidence < threshold (H).
    propositions_skipped: list[Proposition] = Field(default_factory=list)

    # Graph mutations this turn produced
    nodes_created: list[GraphNode]
    nodes_updated: list[GraphNode]
    edges_created: list[GraphEdge]
    edges_updated: list[GraphEdge]

    # Debug only — the full labeled prompt that produced this response.
    # Gated by AppConfig.expose_prompt_debug; None in production.
    prompt_context: dict | None = None

    # Part B: the director's PieceBrief for this turn (split mode only). Surfaced
    # for the debug panel under the same expose_prompt_debug gate; None in
    # production and on the single-model path.
    piece_brief: PieceBrief | None = None

    # Whether this turn was rendered in the generative register. Unlike
    # piece_brief above this is NOT debug-gated — the client needs it in
    # production to decide whether to offer reaction chips on the beat.
    is_piece: bool = False
