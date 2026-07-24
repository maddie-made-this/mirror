import json
import logging
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator

from config.loader import APP_CONFIG
from schemas.enums import CausalClass, KnowledgeSource, MemoryType, RelationType, SubjectKind, Valence

logger = logging.getLogger(__name__)


class SourceQuote(BaseModel):
    """
    DEPRECATED. Provenance now lives on first-class :Mention nodes (see Mention).
    Retained only so old GraphNode.source_quotes data still deserialises cleanly.
    """
    text: str
    conversation_id: UUID
    message_id: UUID
    session_number: int
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MentionRole(str, Enum):
    SUBJECT = "subject"
    OBJECT = "object"


class Mention(BaseModel):
    """
    A first-class record of one proposition mentioning one or two Nodes.
    Replaces the unbounded source_quotes list on GraphNode and is the basis for
    the mention timeline and co-occurrence views.
    """
    id: UUID = Field(default_factory=uuid4)
    user_id: UUID
    conversation_id: UUID
    message_id: UUID
    proposition_id: UUID
    session_number: int

    text: str                          # verbatim source_span
    predicate: str                     # the predicate from the SPO

    valence: Valence = Valence.NEUTRAL
    valence_score: float = Field(ge=-1.0, le=1.0, default=0.0)
    salience_score: float = Field(ge=-1.0, le=1.0, default=0.0)
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    knowledge_source: KnowledgeSource = KnowledgeSource.USER_STATED

    # Provenance spine (reshape §1.2): HOW this was learned, distinct from confidence —
    # gates what the evidence may do. Nullable so legacy reads survive; the write-path
    # stamps them, and scripts/backfill_provenance.py defaults legacy rows.
    prov_source: str | None = None       # conversation|import|offered_chip|feedback|retry_correction
    prov_authorship: str | None = None   # user_wrote|other_wrote
    prov_format: str | None = None       # journal|fiction|social_post|essay|other
    prov_elicited: str | None = None     # volunteered|offered_and_accepted|asked_and_answered

    # Depth-ramp position when this was said ('early'|'mid'|'deep'; '' = unknown,
    # legacy). High-ramp mentions are motif-formation moments — the
    # consolidation rule (§2.2) weights them heavier.
    depth_ramp: str = ""

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class GraphNode(BaseModel):
    """
    A canonical concept in the user's mind map.

    Node IDs follow the slug convention:
        "{entity_type}:{normalized-name}"
        e.g. "tension:autonomy-vs-security"

    Vectors are stored in Qdrant only. Never here.
    """
    id: str = Field(description="Canonical slug: '{entity_type}:{normalized-name}'")
    name: str
    entity_type: str

    # Assigned by the background clustering job (community detection). None until
    # the user has been clustered. Groups nodes into the Cluster zoom tier.
    cluster_id: str | None = None

    valence: Valence = Valence.NEUTRAL

    # Valence — four aggregates maintained per mention.
    valence_score: float = Field(
        ge=-1.0, le=1.0, default=0.0,
        description="Compat alias for valence_score_last (current feeling).",
    )
    valence_score_last: float = Field(
        ge=-1.0, le=1.0, default=0.0,
        description="Valence on the most recent mention. Drives display colour.",
    )
    valence_score_mean: float = Field(
        ge=-1.0, le=1.0, default=0.0,
        description="Incremental mean valence across all mentions.",
    )
    valence_score_min: float = Field(
        ge=-1.0, le=1.0, default=0.0,
        description="Most negative valence ever recorded (the floor).",
    )
    valence_score_max: float = Field(
        ge=-1.0, le=1.0, default=0.0,
        description="Most positive valence ever recorded (the ceiling).",
    )

    # Salience — last and mean only (range adds little beyond valence range).
    salience_score: float = Field(
        ge=-1.0, le=1.0, default=0.0,
        description="Compat alias for salience_score_last.",
    )
    salience_score_last: float = Field(
        ge=-1.0, le=1.0, default=0.0,
        description="Salience on the most recent mention (-1=deactivated, +1=activated).",
    )
    salience_score_mean: float = Field(
        ge=-1.0, le=1.0, default=0.0,
        description="Incremental mean salience across all mentions.",
    )

    memory_type: MemoryType = MemoryType.SEMANTIC

    # Consolidation (§2.2): set by the background rule when repeated high-salience
    # mentions (deep-ramp weighted) mark this configuration as an autonomous
    # motif. motif_confidence is the future learned-weight slot.
    motif: bool = False
    motif_confidence: float = Field(ge=0.0, le=1.0, default=0.0)

    mention_count: int = Field(default=1)
    spontaneous_mention_count: int = Field(default=0)

    knowledge_source: KnowledgeSource = Field(default=KnowledgeSource.USER_STATED)

    # Provenance spine (reshape §1.2): HOW this was learned, distinct from confidence —
    # gates what the evidence may do. Nullable so legacy reads survive; the write-path
    # stamps them, and scripts/backfill_provenance.py defaults legacy rows.
    prov_source: str | None = None       # conversation|import|offered_chip|feedback|retry_correction
    prov_authorship: str | None = None   # user_wrote|other_wrote
    prov_format: str | None = None       # journal|fiction|social_post|essay|other
    prov_elicited: str | None = None     # volunteered|offered_and_accepted|asked_and_answered

    # Subject-attribution firewall (extraction redesign §2/§7). A node carries the
    # kind of subject it belongs to: USER (the default — the self-model), or a
    # REAL_PERSON / CHARACTER firewalled OFF the self-model. subject_ref names the
    # person/character; based_on_ref records a character's real-person origin
    # (provenance only — no live identity bridge back to that person).
    subject_kind: SubjectKind = Field(default=SubjectKind.USER)
    subject_ref: str | None = None
    based_on_ref: str | None = None

    stability_score: float = Field(
        default=0.1,
        ge=0.0,
        le=1.0,
        description=(
            "How entrenched this concept is. Updated by a periodic job based on "
            "mention_count, session spread, and recency. "
            "ALGORITHM NOT YET IMPLEMENTED — all nodes currently hold the default 0.1."
        ),
    )

    # Stored in Neo4j as a list of JSON-serialised SourceQuote strings.
    source_quotes: list[SourceQuote] = Field(default_factory=list)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_mentioned_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    first_session: int
    last_session: int

    @field_validator("entity_type")
    @classmethod
    def validate_entity_type(cls, v: str) -> str:
        # Descriptive field — do NOT raise on an unrecognized type. Reads must
        # survive across deployment configs: a deployment may define a superset of
        # entity types (e.g. 'dynamic', 'motif'), and a node read under a config
        # that lacks them must not crash the whole query. The
        # ingest path already maps genuinely-invalid LLM output to 'concept' via
        # services.extraction._sanitize_entity_type before any write.
        if v and v not in APP_CONFIG.entity_types:
            logger.warning("Unrecognized entity_type for current config", extra={"entity_type": v})
        return v

    @field_validator("source_quotes", mode="before")
    @classmethod
    def parse_source_quotes(cls, v: object) -> list[SourceQuote]:
        """
        Neo4j returns source_quotes as a list of JSON strings.
        Accept str (JSON), dict, or already-parsed SourceQuote objects.
        """
        if not isinstance(v, list):
            return []
        result: list[SourceQuote] = []
        for item in v:
            if isinstance(item, SourceQuote):
                result.append(item)
            elif isinstance(item, dict):
                result.append(SourceQuote(**item))
            elif isinstance(item, str):
                try:
                    result.append(SourceQuote(**json.loads(item)))
                except Exception:
                    pass  # skip malformed entries from old data
        return result


class GraphEdge(BaseModel):
    """
    A relationship between two nodes.

    The edge is keyed by a closed-taxonomy `relation_type` (RelationType): edges
    dedup by exact match — no embedding-similarity dedup needed. The natural
    phrase the user/LLM produced is preserved on the :Mention
    (Proposition.predicate), not here.
    """
    id: UUID = Field(default_factory=uuid4)
    source_id: str
    target_id: str

    relation_type: RelationType = Field(
        default=RelationType.RELATES_TO,
        description="Canonical edge verb from the closed RelationType taxonomy.",
    )

    causal_class: CausalClass = CausalClass.ASSOCIATIVE
    is_directional: bool = True
    is_negated: bool = Field(
        default=False,
        description="Kept in graph and included in LLM context with [NEGATED] prefix.",
    )

    weight: float = Field(ge=0.0, default=1.0)

    proposition_id: UUID
    knowledge_source: KnowledgeSource = KnowledgeSource.USER_STATED

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_seen_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    first_session: int
    last_session: int


class ClusterInfo(BaseModel):
    """A detected community (Cluster tier) with its LLM-generated theme label."""
    id: str
    label: str
    size: int


class GraphContext(BaseModel):
    """
    Assembled by the backend from Neo4j BEFORE the LLM call.
    Never constructed or sent by the client. Never serialised into a response.
    """
    relevant_nodes: list[GraphNode] = Field(
        description="Fetched via vector similarity to current message."
    )
    relevant_edges: list[GraphEdge] = Field(
        description="Edges between relevant_nodes, including negated ones."
    )
    dormant_nodes: list[GraphNode] = Field(
        default_factory=list,
        description="High mention_count nodes not seen in N sessions.",
    )
    active_cluster_ids: list[str] = Field(default_factory=list)

    # Flow 2 (B5): idiographic interpretation statements relevant to this turn,
    # injected into the response prompt to drive understanding-led generation.
    # Each: {"id": str, "statement": str}. The category is NOT injected.
    interpretations: list[dict] = Field(default_factory=list)

    # Flow 3 (B5, Phase 3b): the steering objective that fired, if any.
    steering_objective: str | None = None

    # The session layer (§4): {depth_ramp, gate_position, frame, active_region,
    # turn_count} computed per turn by services/dynamics.py. Feeds the dynamics
    # prompt layer (pacing/depth guidance) and ingest's mention stamping.
    # Never persisted; None when dynamics are unavailable.
    session_state: dict | None = None
