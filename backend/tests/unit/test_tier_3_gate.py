"""Tier-3 evidence-threshold gate (three-tier engine model §Tier 3)."""
from uuid import uuid4

import pytest

from services import tier_3_gate


@pytest.mark.asyncio
async def test_is_grounded_placeholder_returns_true():
    # PLACEHOLDER behavior: tier-3 still fires on every node until the threshold
    # formula lands. This test keeps the suite honest about scope.
    # TODO: expand when the tier-3 firing-rule formula is implemented.
    assert await tier_3_gate.is_grounded(uuid4(), "emotion:burnout") is True
