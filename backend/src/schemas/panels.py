"""State-panel schemas (product reshape §5 / P2.1). 'This story' = per-conversation
piece_frame (engine-populated, user-correctable); 'You' = the global map summary. Their
bible is input; ours is output."""
from pydantic import BaseModel, Field


class PieceFramePatch(BaseModel):
    """Correct the 'This story' panel. `piece_frame` is written back; `concept_slugs` (if
    the client knows which concepts the correction touched) are stamped as a volunteered
    correction — high-value signal. Auto-deriving slugs from the free-text piece_frame is
    NOT done (no field→concept contract exists yet); the client must name them."""
    piece_frame: dict
    concept_slugs: list[str] = Field(default_factory=list)


class AngleSummary(BaseModel):
    id: str
    statement: str
    confidence: float | None = None


class ConceptSummary(BaseModel):
    id: str
    name: str


class GraphSummary(BaseModel):
    """The 'You' panel: top tier-2 angles + most-active concepts. Coverage links to the
    §P3.6 endpoint (Phase 3) — not inlined here."""
    top_angles: list[AngleSummary] = Field(default_factory=list)
    active_concepts: list[ConceptSummary] = Field(default_factory=list)
