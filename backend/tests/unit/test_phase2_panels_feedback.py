"""Phase 2 — panels, feedback comments, Mirror's-thinking assembly.

Service-level coverage with the fake-pool idiom: P2.3 note-on-any-reaction (+ hard
boundary), P2.4 thinking view assembles real artifacts (+ summary stays off by default),
P2.1 top-angles / active-concepts shaping.
"""
from datetime import datetime, timezone
from uuid import uuid4

import pytest


# ── Fake Postgres pool ─────────────────────────────────────────────────────

class _FakeConn:
    def __init__(self, fetchrow=None, fetch=None):
        self.calls = []
        self._fetchrow = list(fetchrow or [])
        self._fetch = list(fetch or [])

    async def execute(self, q, *a):
        self.calls.append(("execute", q, a))
        return "OK"

    async def fetchrow(self, q, *a):
        self.calls.append(("fetchrow", q, a))
        return self._fetchrow.pop(0) if self._fetchrow else None

    async def fetch(self, q, *a):
        self.calls.append(("fetch", q, a))
        return self._fetch.pop(0) if self._fetch else []


class _Acquire:
    def __init__(self, c): self._c = c
    async def __aenter__(self): return self._c
    async def __aexit__(self, *a): return False


class _FakePool:
    def __init__(self, c): self._c = c
    def acquire(self): return _Acquire(self._c)


def _patch_pool(monkeypatch, module, conn):
    async def fake_get_pool():
        return _FakePool(conn)
    monkeypatch.setattr(f"services.{module}.get_pool", fake_get_pool, raising=False)


# ── P2.3 feedback comments ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_note_stored_on_check(monkeypatch):
    from services import feedback
    conn = _FakeConn(fetchrow=[{
        "conversation_id": uuid4(), "input_node_ids": [], "input_interpretation_ids": [],
    }])
    _patch_pool(monkeypatch, "feedback", conn)
    # 'check' with a note: the note must be persisted (P2.3 — note on any reaction)
    await feedback.record_feedback(uuid4(), uuid4(), "check", note="loved the pacing")
    insert = next(a for k, q, a in conn.calls if k == "execute" and "INSERT INTO message_feedback" in q)
    assert "loved the pacing" in insert and "check" in insert


@pytest.mark.asyncio
async def test_voteless_note_no_reinforcement(monkeypatch):
    from services import feedback
    called = {"reinforce": False}

    async def _no_reinforce(*a, **k):
        called["reinforce"] = True
        return 0
    conn = _FakeConn(fetchrow=[{
        "conversation_id": uuid4(), "input_node_ids": ["x"], "input_interpretation_ids": [],
    }])
    _patch_pool(monkeypatch, "feedback", conn)
    monkeypatch.setattr("services.feedback.graph_service.reinforce_nodes", _no_reinforce)
    res = await feedback.record_feedback(uuid4(), uuid4(), "note", note="a thought")
    # 'note' is voteless: stored, but never reinforces the graph (hard boundary A1.5)
    assert res["analytic_available"] is False
    assert called["reinforce"] is False


# ── P2.4 Mirror's thinking ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_thinking_assembles_real_artifacts(monkeypatch):
    from services import thinking
    turn_row = {
        "input_node_ids": ["concept:x"], "input_interpretation_ids": ["i1"],
        "steering_objective": "deepen-x", "piece_brief": {"function_to_serve": "the frame clicking",
        "beat_history": ["a", "b"], "next_beat": "name the assumption"},
        "thinking_summary": None,
    }
    _patch_pool(monkeypatch, "thinking", _FakeConn(fetchrow=[turn_row]))

    async def _names(uid, ids): return {"concept:x": "the thing"}
    async def _interps(uid, ids): return [{"id": "i1", "statement": "s", "kind": "angle", "confidence": 0.8}]
    async def _offers(uid, mid): return [{"element": "e", "source_tag": "t", "uptake": None}]
    monkeypatch.setattr("services.thinking.graph_service.get_node_names", _names)
    monkeypatch.setattr("services.thinking.graph_service.get_interpretation_statements", _interps)
    monkeypatch.setattr("services.thinking.uptake.get_offers_for_message", _offers)

    view = await thinking.get_thinking(uuid4(), uuid4())
    assert view["input_nodes"] == [{"id": "concept:x", "name": "the thing"}]
    assert view["interpretations"][0]["statement"] == "s"
    assert view["steering_objective"] == "deepen-x"
    # curated brief slice keeps real reasoning fields, drops raw logs (beat_history)
    assert view["piece_brief"]["function_to_serve"] == "the frame clicking"
    assert "beat_history" not in view["piece_brief"]
    assert view["element_offers"][0]["element"] == "e"
    # summary is OFF by default (cost-gated) — never auto-generated
    assert view["summary"] is None


@pytest.mark.asyncio
async def test_thinking_unknown_turn_returns_none(monkeypatch):
    from services import thinking
    _patch_pool(monkeypatch, "thinking", _FakeConn(fetchrow=[None]))
    assert await thinking.get_thinking(uuid4(), uuid4()) is None


# ── P2.5 composer chips ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_blank_beat_serves_composer_chips():
    from services import chips
    out = await chips.generate_chips("", uuid4(), 1)
    assert [c.kind for c in out] == ["composer", "composer", "composer"]
    assert any("Start a piece" == c.label for c in out)
