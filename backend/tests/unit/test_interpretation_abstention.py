"""Tier-3 abstention (three-tier engine model §4): empty readings parse to zero
writes, and the gate short-circuits the tier-3 reflection before any LLM
call when a node is under-grounded."""
from uuid import uuid4

import pytest

from services import interpretation as interp


def test_parse_empty_readings_writes_nothing():
    # The abstention output ({"readings": []}) must produce zero Interpretation rows.
    out = interp._parse_motif_readings(
        [], uuid4(), "emotion:burnout", [], [], {}, set()
    )
    assert out == []


@pytest.mark.asyncio
async def test_reflect_motifs_abstains_when_gate_false(monkeypatch):
    chat_calls = {"n": 0}

    async def fake_targets(uid):
        return [{"id": "emotion:burnout", "name": "burnout", "etype": "emotion",
                 "salience": 0.8, "valence": -0.5, "have": []}]

    async def fake_is_grounded(uid, nid):
        return False  # gate abstains for every node

    async def fake_chat(*a, **kw):
        chat_calls["n"] += 1
        return '{"readings": []}'

    # The pre-loop dedup helpers hit Neo4j; stub them so the unit test needs no stack.
    async def _empty_dict(uid):
        return {}

    async def _empty_set(uid):
        return set()

    async def _empty_list(uid):
        return []

    monkeypatch.setattr("services.interpretation._motif_targets", fake_targets, raising=False)
    monkeypatch.setattr("services.interpretation._existing_belief_ids", _empty_dict, raising=False)
    monkeypatch.setattr("services.interpretation._existing_function_statements", _empty_set, raising=False)
    monkeypatch.setattr("services.interpretation._existing_function_embeddings", _empty_list, raising=False)
    monkeypatch.setattr("services.tier_3_gate.is_grounded", fake_is_grounded, raising=False)
    monkeypatch.setattr("services.interpretation.chat", fake_chat, raising=False)

    created = await interp.reflect_motifs(uuid4())
    assert created == 0
    # the gate abstained BEFORE the reflection LLM call
    assert chat_calls["n"] == 0
