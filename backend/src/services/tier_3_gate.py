"""
Tier-3 evidence-threshold gate (three-tier engine model §Tier 3).

Tier-3 readings are the deeper kinds (function / belief / reframing /
origin) — psychological, history-grounded claims about the user. The concept
doc requires "history to be psychologically accurate", so a node without enough
grounding should make tier-3 *abstain* rather than guess.

This module is the gating SITE. The actual evidence-threshold FORMULA is deferred
to the tier-3 firing-rule spec — it can only be tuned against ground-truth
personas (#4+5 harness), so any threshold written before that harness exists is
arbitrary. The placeholder returns True unconditionally, preserving current
behavior (tier-3 still fires) while making the call site real, so the migration
to the formula is a one-function change.
"""

import logging
from uuid import UUID

logger = logging.getLogger(__name__)


async def is_grounded(user_id: UUID, node_id: str) -> bool:
    """
    Tier-3 evidence-threshold check. Returns True if there is enough grounding to
    attempt a tier-3 reading on this node; False if tier-3 should abstain.

    PLACEHOLDER: returns True unconditionally for now (preserves current behavior).
    The real formula is deferred to the tier-3 firing-rule spec. When it lands it
    will count:
      - origin episodes attached to the node (via #9 timeline cross-store edges),
      - belief-disclosures attached (existing kind=belief Interpretations),
      - explicit user authorization (analysis-mode bid).

    For now the function exists so the call sites are real and migrating to the
    actual formula is a one-function change.
    """
    return True  # PLACEHOLDER — see tier-3 firing-rule spec for the real formula
