"""
Interest-model objects (§3-§4) that are NOT interpretation
readings: the gates and the dials.

Readings (origin / function / dynamics / belief / reframing) live on the
Interpretation schema — same lifecycle (confidence, status, evidence, respond
loop), new kinds. The objects here have their OWN lifecycles, deliberately
distinct (§3):

- Excluded — a subject the user has said they don't want covered. Set and
  cleared by the user only; the engine never infers one and never overrides one.
- Sensitive — a REVISABLE low-interest reading derived from selective
  non-engagement (≥3 offers, zero uptake, while otherwise engaged). Deprioritized
  until they engage with it; never promoted to Excluded automatically.
- SalienceDynamics — the per-user TRAIT layer (engagement/reticence gains +
  pacing). Slow: moved only by cross-session accumulation (services/dynamics.py).
- SessionState — the per-conversation session layer (ramp / gate position /
  frame / active region). Coarse, low-confidence, computed each turn, and
  deliberately NEVER persisted — one quiet session never tightens the disposition.
"""
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ExclusionStatus(str, Enum):
    ACTIVE = "active"
    # Cleared ONLY by the user saying so themselves. The engine has no path here:
    # it never re-tests the topic, and uptake cannot clear it (nothing is offered
    # on an excluded subject in the first place).
    REVOKED = "revoked"


class Excluded(BaseModel):
    """A subject the user asked to keep off the table. Steering and prediction
    must never target it."""
    id: UUID = Field(default_factory=uuid4)
    user_id: UUID
    node_id: str = ""            # graph node anchoring the region, when one exists
    region: str                  # descriptive ("speculation about my colleagues' motives")
    evidence: list[str] = Field(default_factory=list)   # mention ids
    status: ExclusionStatus = ExclusionStatus.ACTIVE
    revoked_at: datetime | None = None
    revoked_by: list[str] = Field(default_factory=list)  # the reversal mention ids
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class GateStatus(str, Enum):
    ACTIVE = "active"
    LIFTED = "lifted"


class Sensitive(BaseModel):
    """A revisable low-interest reading — a condition, not a trait."""
    id: UUID = Field(default_factory=uuid4)
    user_id: UUID
    node_id: str = ""
    element: str                 # what was offered and passed over
    evidence_offer_ids: list[str] = Field(default_factory=list)  # element_offers rows
    status: GateStatus = GateStatus.ACTIVE
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    lifted_at: datetime | None = None


class SalienceDynamics(BaseModel):
    """Trait dials (§4). Content-neutral transducers — never content."""
    user_id: UUID
    engagement_gain: float = Field(ge=0.0, le=1.0, default=0.5)  # how readily they lean in
    reticence_gain: float = Field(ge=0.0, le=1.0, default=0.5)   # how readily they pull back
    pacing_preference: str = ""
    detail_tolerance: str = ""
    enablers: list[str] = Field(default_factory=list)
    disablers: list[str] = Field(default_factory=list)
    baseline_msg_chars: float = 0.0     # engagement baseline for gate deviation
    sessions_observed: int = 0          # traits move only after enough data
    confidence: float = Field(ge=0.0, le=1.0, default=0.3)  # future learned-weight slot
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DepthRamp(str, Enum):
    EARLY = "early"
    MID = "mid"
    DEEP = "deep"


class GatePosition(str, Enum):
    OPEN = "open"          # above their usual engagement — a good moment to go deeper
    NEUTRAL = "neutral"
    GUARDED = "guarded"    # below usual — follow their lead, don't push


class Frame(str, Enum):
    FICTION = "fiction"
    REAL = "real"


class SessionState(BaseModel):
    """
    The session layer (§4): coarse readings of THIS conversation right now.
    Computed per turn from cheap queries; modulates behavior NOW; never stored.
    """
    depth_ramp: DepthRamp = DepthRamp.EARLY
    gate_position: GatePosition = GatePosition.NEUTRAL
    frame: Frame = Frame.REAL
    active_region: str = ""    # cluster label the session is currently living in
    turn_count: int = 0
