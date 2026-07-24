from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class InterpretationKind(str, Enum):
    # --- Orthogonal observations (NOT tier-bound) ---
    PATTERN = "pattern"        # recurring theme within a cluster (graph fact)
    TENSION = "tension"        # two things held in conflict (graph fact)
    BRIDGE = "bridge"          # a connection spanning two clusters (graph fact)
    BEHAVIORAL = "behavioral"  # from the observational signal stream
    STYLISTIC = "stylistic"

    # --- TIER 2 — local angle (the psychological angle this cluster takes for THIS user) ---
    # Derived from cluster members + curated angle vocabulary via the matcher pipeline
    # (services/tier_2_matcher.py). NEVER extracted directly from utterances. NEVER
    # produced as free-text — always classified into an entry in the vocabulary.
    ANGLE = "angle"

    # --- TIER 3 — tier-3 readings (psychological function, history-grounded) ---
    # All four are gated by tier_3_gate.is_grounded(); the reflection prompt MUST be
    # capable of returning "insufficient evidence" (no reading produced).
    FUNCTION = "function"      # the work an motif does NOW (the need it satisfies)
    BELIEF = "belief"          # a limiting belief (idiographic proposition that suppresses)
    REFRAMING = "reframing"  # how this motif reframes or sidesteps a limiting belief
    ORIGIN = "origin"          # where the motif came from — a DISTRIBUTION, never a verdict

    # --- Trait/dial reading (orthogonal to tiers; not a tier-3 reading) ---
    DYNAMICS = "dynamics"      # how it sits with the user's dials/pacing


class InterpretationStatus(str, Enum):
    CANDIDATE = "candidate"    # generated; below surface threshold or not yet shown
    SURFACED = "surfaced"      # shown to the user, awaiting a response
    AFFIRMED = "affirmed"
    REJECTED = "rejected"
    QUALIFIED = "qualified"


class UserResponse(str, Enum):
    AFFIRMED = "affirmed"
    REJECTED = "rejected"
    QUALIFIED = "qualified"


class Interpretation(BaseModel):
    """
    A sourced, rejectable hypothesis the system forms about the user from their
    graph. Confidence is updated by accumulation, cross-domain recurrence, and —
    dominantly — the user's affirm/reject/qualify response. That response loop is
    the only valid efficacy test (offline testing is contaminated), so it runs
    continuously in production.
    """
    id: UUID = Field(default_factory=uuid4)
    user_id: UUID

    statement: str             # IDIOGRAPHIC: the user's own specifics, never a bare
                               # category. This is the generative payload (A3).
    kind: InterpretationKind = InterpretationKind.PATTERN

    # Nomothetic category (A3): a small, provisional index over the idiographic
    # statement (the deployment's configured nomothetic families). Used
    # for traversal + cross-user learning; does almost no generative work by
    # itself. Empty when no taxonomy is configured, and whenever no category fits.
    category: str = ""

    # Names the raw-detail -> functional-claim leap explicitly, so the
    # interpretation never looks more certain than the evidence supports (§5).
    inferential_step: str = ""

    attached_node_ids: list[str] = Field(default_factory=list)
    attached_cluster_ids: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)   # node/mention ids

    confidence: float = Field(ge=0.0, le=1.0, default=0.55)
    contradicts: list[UUID] = Field(default_factory=list)

    # --- Uncertainty machinery (§7) — required on surfaced readings ---
    # Honesty in the panel AND the steering system's next-evidence pointer: a
    # reading must know what would revise it. Enforced in the reflection prompt;
    # "" only on legacy rows and kinds where it is not meaningful.
    what_would_change_this: str = ""

    # --- ORIGIN reading payload (kind=origin) ---
    # Acquisition-route mass, stored flat (Neo4j properties can't nest maps).
    # A distribution, never a verdict: the three need not sum to 1; they are
    # relative weightings the panel renders as tentative.
    origin_innate: float = Field(ge=0.0, le=1.0, default=0.0)
    origin_learned: float = Field(ge=0.0, le=1.0, default=0.0)
    origin_reframing: float = Field(ge=0.0, le=1.0, default=0.0)
    # The recovered episodic record ("a teacher told me I asked too many questions"),
    # if one exists.
    # Feeds EXPLANATION ONLY — never injected into generation (it doesn't generalize).
    origin_episode: str = ""

    # --- REFRAMING reading payload (kind=reframing) ---
    # statement = the mechanism ("X disproves 'this interest is self-indulgent'").
    # Links to the kind=belief reading it works around. Retained even after the
    # motif consolidates — the explanation product references BOTH.
    reframes_belief_id: str = ""

    # --- BELIEF payload (kind=belief, a LimitingBelief) ---
    presses_on: list[str] = Field(default_factory=list)   # node ids/regions it suppresses
    context_sensitivity: float = Field(
        ge=0.0, le=1.0, default=0.5,
        description="How much fictional framing lifts this press (1 = fully lifted in fiction).",
    )

    # --- FUNCTION payload (kind=function) ---
    # Same-need candidate configurations from the function-generalization engine
    # (§5.1), generated at maintenance time, consumed by steering as probes.
    candidates: list[str] = Field(default_factory=list)

    # --- TIER 2 ANGLE payload (kind=angle) ---
    # The canonical key from the angle vocabulary (services/angle_vocabulary.py). This
    # is the audit trail: every angle interpretation traces to a curated entry, never
    # to a free-text LLM output. Empty on legacy/non-angle rows.
    angle_key: str = ""

    status: InterpretationStatus = InterpretationStatus.CANDIDATE
    user_response: UserResponse | None = None
    user_note: str = ""

    surfaced_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def origin_distribution(self) -> dict[str, float]:
        """The §3 origin distribution view over the flat-stored masses."""
        return {
            "innate": self.origin_innate,
            "learned_episodic": self.origin_learned,
            "reframing_consolidated": self.origin_reframing,
        }


class InterpretationRespond(BaseModel):
    """Body for POST /interpretations/{id}/respond — the live efficacy loop."""
    response: UserResponse
    note: str = ""
