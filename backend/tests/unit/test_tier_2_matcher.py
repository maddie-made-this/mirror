"""Tier-2 matcher (three-tier engine model §3): classification, audit-trail
enforcement, NO_MATCH handling, and the persist shape."""
import json
import logging
from uuid import uuid4

import pytest

from schemas.interpretation import Interpretation, InterpretationKind
from services import tier_2_matcher as m


def _cluster(**over):
    base = dict(
        cid="cluster:abc", label="systems thinking",
        names=["systems", "architecture"],
        node_ids=["concept:systems", "concept:architecture"],
        mentions=["I keep noticing the same shape in different fields"],
        angle_id=None, angle_key=None, angle_updated_at=None,
    )
    base.update(over)
    return base


@pytest.mark.asyncio
async def test_classify_accepts_valid_key(monkeypatch):
    async def fake_chat(messages, **kw):
        return json.dumps({"angle_key": "grasping_a_whole_system",
                           "matched_evidence": "they said 'the same shape in different fields'",
                           "confidence": 0.7})
    monkeypatch.setattr("services.tier_2_matcher.chat", fake_chat, raising=False)
    out = await m._classify_cluster(_cluster())
    assert out is not None
    key, _evidence, conf = out
    assert key == "grasping_a_whole_system"
    assert 0.4 <= conf <= 0.9


@pytest.mark.asyncio
async def test_classify_no_match_returns_none(monkeypatch):
    async def fake_chat(messages, **kw):
        return json.dumps({"angle_key": "NO_MATCH", "matched_evidence": "", "confidence": 0.5})
    monkeypatch.setattr("services.tier_2_matcher.chat", fake_chat, raising=False)
    assert await m._classify_cluster(_cluster()) is None


@pytest.mark.asyncio
async def test_classify_rejects_key_not_in_vocabulary(monkeypatch):
    # Audit-trail enforcement: an LLM key absent from the vocabulary cannot persist —
    # it's treated as NO_MATCH and logged as a vocabulary-expansion candidate.
    async def fake_chat(messages, **kw):
        return json.dumps({"angle_key": "not_in_vocabulary",
                           "matched_evidence": "x", "confidence": 0.85})
    monkeypatch.setattr("services.tier_2_matcher.chat", fake_chat, raising=False)
    assert await m._classify_cluster(_cluster()) is None


@pytest.mark.asyncio
async def test_classify_malformed_json_is_noop(monkeypatch):
    async def fake_chat(messages, **kw):
        return "this is not json at all"
    monkeypatch.setattr("services.tier_2_matcher.chat", fake_chat, raising=False)
    assert await m._classify_cluster(_cluster()) is None


@pytest.mark.asyncio
async def test_match_clusters_persists_angle_interpretation(monkeypatch):
    saved = []

    async def fake_candidates(uid):
        return [_cluster()]

    async def fake_chat(messages, **kw):
        return json.dumps({"angle_key": "grasping_a_whole_system",
                           "matched_evidence": "the same shape again", "confidence": 0.65})

    async def fake_save(interp):
        saved.append(interp)

    async def fake_find(*a, **k):
        return None      # no prior angle -> create path

    async def fake_prune(uid):
        return 0

    monkeypatch.setattr("services.tier_2_matcher._candidate_clusters", fake_candidates, raising=False)
    monkeypatch.setattr("services.tier_2_matcher.chat", fake_chat, raising=False)
    monkeypatch.setattr("services.tier_2_matcher.save_interpretation", fake_save, raising=False)
    monkeypatch.setattr("services.tier_2_matcher._find_existing_angle", fake_find, raising=False)
    monkeypatch.setattr("services.tier_2_matcher._prune_orphan_angles", fake_prune, raising=False)
    monkeypatch.setattr("services.tier_2_matcher._reject_superseded_angles", _azero, raising=False)

    n = await m.match_clusters(uuid4())
    assert n == 1
    assert len(saved) == 1
    interp = saved[0]
    assert interp.kind == InterpretationKind.ANGLE
    assert interp.angle_key == "grasping_a_whole_system"
    # statement is the vocabulary's canonical NAME, never LLM-generated prose
    assert interp.statement == "grasping a whole system"
    assert interp.attached_cluster_ids == ["cluster:abc"]
    assert "concept:systems" in interp.attached_node_ids
    # the falsifier is the neighbor angle (felt_distinction_from_neighbors)
    assert interp.what_would_change_this


# --- Churn fix (SPEC_tier_2_churn_fix.md §7.1): stable-identity dedup + orphan prune ---


def _angle(node_ids, key="grasping_a_whole_system", **over):
    base = dict(
        user_id=uuid4(), statement="grasping a whole system",
        kind=InterpretationKind.ANGLE, angle_key=key, attached_node_ids=list(node_ids),
    )
    base.update(over)
    return Interpretation(**base)


async def _azero(uid):
    """Async no-op (count 0) — stubs match_clusters' prune/supersede cleanup calls."""
    return 0


def test_select_best_overlap_respects_threshold():
    # overlap = |new ∩ existing| / max(|new|, |existing|); existing has {a,b,c,d}
    a = _angle(["a", "b", "c", "d"])
    # 2/5 = 0.4 < 0.6 -> no match
    assert m._select_best_overlap(["a", "b", "e", "f", "g"], [a], 0.6) is None
    # 3/4 = 0.75 >= 0.6 -> match
    assert m._select_best_overlap(["a", "b", "c"], [a], 0.6) is a
    # best-of-several: full overlap beats partial
    b = _angle(["a", "b"])
    assert m._select_best_overlap(["a", "b", "c", "d"], [a, b], 0.6) is a
    # empty member set -> None
    assert m._select_best_overlap([], [a], 0.6) is None


@pytest.mark.asyncio
async def test_stable_identity_dedup_across_cluster_id_change(monkeypatch):
    """A re-IDed cluster (new cid, no current-id angle) whose members still match an
    existing same-key angle refreshes it in place instead of minting a duplicate."""
    updated, saved = [], []
    existing = _angle(["concept:systems", "concept:architecture"], attached_cluster_ids=["cluster:OLD"])

    async def fake_candidates(uid):
        return [_cluster(cid="cluster:NEW", node_ids=["concept:systems", "concept:architecture"],
                         angle_id=None, angle_key=None)]

    async def fake_chat(messages, **kw):
        return json.dumps({"angle_key": "grasping_a_whole_system",
                           "matched_evidence": "x", "confidence": 0.7})

    async def fake_find(*a, **k):
        return existing

    async def fake_update(iid, cluster_ids, node_ids, conf):
        updated.append((iid, cluster_ids, node_ids, conf))

    async def fake_save(interp):
        saved.append(interp)

    async def fake_prune(uid):
        return 0

    monkeypatch.setattr("services.tier_2_matcher._candidate_clusters", fake_candidates, raising=False)
    monkeypatch.setattr("services.tier_2_matcher.chat", fake_chat, raising=False)
    monkeypatch.setattr("services.tier_2_matcher._find_existing_angle", fake_find, raising=False)
    monkeypatch.setattr("services.tier_2_matcher._update_angle_attachments", fake_update, raising=False)
    monkeypatch.setattr("services.tier_2_matcher.save_interpretation", fake_save, raising=False)
    monkeypatch.setattr("services.tier_2_matcher._prune_orphan_angles", fake_prune, raising=False)
    monkeypatch.setattr("services.tier_2_matcher._reject_superseded_angles", _azero, raising=False)

    n = await m.match_clusters(uuid4())
    assert n == 1                              # counted as refreshed
    assert saved == []                         # NOT duplicated
    assert len(updated) == 1
    assert updated[0][1] == ["cluster:NEW"]    # re-pointed at the current cluster id


@pytest.mark.asyncio
async def test_partial_member_overlap_below_threshold_creates_new(monkeypatch):
    """No same-key angle overlaps by >= threshold (find returns None) -> create a new
    angle rather than re-point an unrelated one."""
    saved = []

    async def fake_candidates(uid):
        return [_cluster(angle_id=None, angle_key=None)]

    async def fake_chat(messages, **kw):
        return json.dumps({"angle_key": "grasping_a_whole_system",
                           "matched_evidence": "x", "confidence": 0.7})

    async def fake_find(*a, **k):
        return None

    async def fake_save(interp):
        saved.append(interp)

    async def fake_prune(uid):
        return 0

    monkeypatch.setattr("services.tier_2_matcher._candidate_clusters", fake_candidates, raising=False)
    monkeypatch.setattr("services.tier_2_matcher.chat", fake_chat, raising=False)
    monkeypatch.setattr("services.tier_2_matcher._find_existing_angle", fake_find, raising=False)
    monkeypatch.setattr("services.tier_2_matcher.save_interpretation", fake_save, raising=False)
    monkeypatch.setattr("services.tier_2_matcher._prune_orphan_angles", fake_prune, raising=False)
    monkeypatch.setattr("services.tier_2_matcher._reject_superseded_angles", _azero, raising=False)

    n = await m.match_clusters(uuid4())
    assert n == 1
    assert len(saved) == 1                     # created new


@pytest.mark.asyncio
async def test_match_clusters_invokes_orphan_prune(monkeypatch, caplog):
    """The prune runs once per pass even when nothing matched, and logs its count.
    (The prune's Cypher logic is exercised end-to-end in the integration suite §1.7.)"""
    pruned_for = []

    async def fake_candidates(uid):
        return []                              # nothing to match this pass

    async def fake_prune(uid):
        pruned_for.append(uid)
        return 3

    monkeypatch.setattr("services.tier_2_matcher._candidate_clusters", fake_candidates, raising=False)
    monkeypatch.setattr("services.tier_2_matcher._prune_orphan_angles", fake_prune, raising=False)
    monkeypatch.setattr("services.tier_2_matcher._reject_superseded_angles", _azero, raising=False)

    with caplog.at_level(logging.INFO, logger="services.tier_2_matcher"):
        n = await m.match_clusters(uuid4())
    assert n == 0
    assert len(pruned_for) == 1                # prune still ran with an empty todo
    assert any(r.getMessage() == "tier_2_angles_pruned" for r in caplog.records)


@pytest.mark.asyncio
async def test_match_clusters_invokes_supersession_dedup(monkeypatch, caplog):
    """match_clusters runs the legacy supersession dedup every pass and logs its count.
    (The dedup's Cypher + overlap logic is exercised end-to-end in integration §1.8.)"""
    called = []

    async def fake_candidates(uid):
        return []

    async def fake_super(uid):
        called.append(uid)
        return 2

    monkeypatch.setattr("services.tier_2_matcher._candidate_clusters", fake_candidates, raising=False)
    monkeypatch.setattr("services.tier_2_matcher._prune_orphan_angles", _azero, raising=False)
    monkeypatch.setattr("services.tier_2_matcher._reject_superseded_angles", fake_super, raising=False)

    with caplog.at_level(logging.INFO, logger="services.tier_2_matcher"):
        n = await m.match_clusters(uuid4())
    assert n == 0
    assert len(called) == 1                    # supersession dedup ran with an empty todo
    assert any(r.getMessage() == "tier_2_angles_superseded" for r in caplog.records)
