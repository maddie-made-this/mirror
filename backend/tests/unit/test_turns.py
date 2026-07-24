"""Variant compare (P1.4) + edit-as-canon (P1.5).

Covers the beat-group regeneration path in save_turn (share group / supersede priors /
cap eviction) and the turn-level services (pick flips canon + reports the rejected take;
edit updates in place, reports prev_text, never enqueues extraction).
"""
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from services import history


class _FakeTxn:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _FakeConn:
    """Records every query + args; fetchrow/fetch replay a scripted queue (FIFO)."""

    def __init__(self, fetchrow=None, fetch=None):
        self.calls = []                      # (kind, query, args)
        self._fetchrow = list(fetchrow or [])
        self._fetch = list(fetch or [])

    def transaction(self):
        return _FakeTxn()

    async def execute(self, query, *args):
        self.calls.append(("execute", query, args))
        return "OK"

    async def fetchrow(self, query, *args):
        self.calls.append(("fetchrow", query, args))
        return self._fetchrow.pop(0) if self._fetchrow else None

    async def fetch(self, query, *args):
        self.calls.append(("fetch", query, args))
        return self._fetch.pop(0) if self._fetch else []


class _FakeAcquire:
    def __init__(self, conn):
        self._c = conn

    async def __aenter__(self):
        return self._c

    async def __aexit__(self, *a):
        return False


class _FakePool:
    def __init__(self, conn):
        self._c = conn

    def acquire(self):
        return _FakeAcquire(self._c)


def _patch(monkeypatch, conn):
    async def fake_get_pool():
        return _FakePool(conn)
    monkeypatch.setattr("services.history.get_pool", fake_get_pool, raising=False)


def _queries(conn):
    return [q for _, q, _ in conn.calls]


# ── save_turn regeneration (P1.4) ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_regen_shares_beat_group_and_supersedes(monkeypatch):
    group = uuid4()
    conn = _FakeConn(fetchrow=[{"bg": group}])   # prior beat's resolved group
    _patch(monkeypatch, conn)
    regenerate_of = uuid4()
    new_msg = uuid4()

    await history.save_turn(
        uuid4(), uuid4(), new_msg, uuid4(), "u", "regenerated",
        regenerate_of=regenerate_of,
    )

    execs = [(q, a) for kind, q, a in conn.calls if kind == "execute"]
    # the prior takes were knocked out of canon for the shared group
    assert any("is_canon = false" in q for q, _ in execs)
    # the new turn INSERT carries the inherited beat_group_id (not its own message_id)
    ins = next((a for q, a in execs if "INSERT INTO conversation_turns" in q), None)
    assert ins is not None and str(group) in ins and str(group) != str(new_msg)


@pytest.mark.asyncio
async def test_regen_archives_oldest_beyond_cap_never_deletes(monkeypatch):
    conn = _FakeConn(fetchrow=[{"bg": uuid4()}])
    _patch(monkeypatch, conn)
    await history.save_turn(
        uuid4(), uuid4(), uuid4(), uuid4(), "u", "r", regenerate_of=uuid4(),
    )
    # eviction ARCHIVES (retains content for the supersede-pair training set) — it must
    # never DELETE a rejected take.
    evict = next(
        (a for kind, q, a in conn.calls if kind == "execute" and "archived = true" in q),
        None,
    )
    assert evict is not None
    assert history.TAKE_GROUP_CAP - 1 in evict   # keep newest cap-1 active non-canon
    assert not any("DELETE" in q for _, q, _ in conn.calls)


@pytest.mark.asyncio
async def test_fresh_turn_is_its_own_group(monkeypatch):
    conn = _FakeConn()
    _patch(monkeypatch, conn)
    msg = uuid4()
    await history.save_turn(uuid4(), uuid4(), msg, uuid4(), "u", "beat")
    # no regeneration → no group-resolution fetchrow, no supersede, no cap delete
    assert not any(kind == "fetchrow" for kind, _, _ in conn.calls)
    ins = next(a for k, q, a in conn.calls if "INSERT INTO conversation_turns" in q)
    assert str(msg) in ins            # beat_group_id defaults to the turn's own message_id


# ── pick_take (P1.4) ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pick_flips_canon_and_reports_rejected(monkeypatch):
    conv, kept, rejected = uuid4(), uuid4(), uuid4()
    group = uuid4()
    conn = _FakeConn(fetch=[[
        {"message_id": kept, "is_canon": False, "conversation_id": conv, "piece_brief": None},
        {"message_id": rejected, "is_canon": True, "conversation_id": conv, "piece_brief": {"x": 1}},
    ]])
    _patch(monkeypatch, conn)
    res = await history.pick_take(uuid4(), group, kept)
    assert res["kept"] == kept and res["rejected"] == rejected
    assert res["conversation_id"] == conv
    assert res["render_mode"] == "cowrite"          # a sibling had a piece_brief
    assert any("SET is_canon = (message_id" in q for q in _queries(conn))


@pytest.mark.asyncio
async def test_pick_rejects_take_not_in_group(monkeypatch):
    conn = _FakeConn(fetch=[[
        {"message_id": uuid4(), "is_canon": True, "conversation_id": uuid4(), "piece_brief": None},
    ]])
    _patch(monkeypatch, conn)
    assert await history.pick_take(uuid4(), uuid4(), uuid4()) is None


@pytest.mark.asyncio
async def test_pick_empty_group_returns_none(monkeypatch):
    conn = _FakeConn(fetch=[[]])
    _patch(monkeypatch, conn)
    assert await history.pick_take(uuid4(), uuid4(), uuid4()) is None


@pytest.mark.asyncio
async def test_pick_already_canon_has_no_rejected(monkeypatch):
    conv, only = uuid4(), uuid4()
    conn = _FakeConn(fetch=[[
        {"message_id": only, "is_canon": True, "conversation_id": conv, "piece_brief": None},
    ]])
    _patch(monkeypatch, conn)
    res = await history.pick_take(uuid4(), uuid4(), only)
    assert res["rejected"] is None                # no supersede pair should be logged


# ── edit_turn_text (P1.5) ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_edit_updates_in_place_and_reports_prev(monkeypatch):
    conv = uuid4()
    conn = _FakeConn(fetchrow=[
        {"conversation_id": conv, "response_text": "old text", "piece_brief": None},
    ])
    _patch(monkeypatch, conn)
    msg = uuid4()
    res = await history.edit_turn_text(uuid4(), msg, "new text")
    assert res["prev_text"] == "old text"
    assert res["conversation_id"] == conv
    assert res["render_mode"] == "conversational"
    upd = next(a for k, q, a in conn.calls if k == "execute" and "UPDATE" in q)
    assert "new text" in upd and str(msg) in upd   # same row, in place


@pytest.mark.asyncio
async def test_edit_missing_turn_returns_none(monkeypatch):
    conn = _FakeConn(fetchrow=[None])
    _patch(monkeypatch, conn)
    assert await history.edit_turn_text(uuid4(), uuid4(), "x") is None


@pytest.mark.asyncio
async def test_edit_does_not_touch_graph(monkeypatch):
    """Edit is a canon/document op — it invokes no extraction/graph write path."""
    import inspect
    src = inspect.getsource(history.edit_turn_text)
    for call in ("enqueue", "extraction_queue", "ingest_propositions", "reinforce_nodes"):
        assert call not in src


# ── get_beat_takes (P1.4) ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_beat_takes_maps_message_id_to_turn_id(monkeypatch):
    a, b = uuid4(), uuid4()
    now = datetime.now(timezone.utc)
    conn = _FakeConn(fetch=[[
        {"message_id": a, "response_text": "take A", "is_canon": False, "created_at": now},
        {"message_id": b, "response_text": "take B", "is_canon": True, "created_at": now},
    ]])
    _patch(monkeypatch, conn)
    takes = await history.get_beat_takes(uuid4(), uuid4(), uuid4())
    assert [t["turn_id"] for t in takes] == [a, b]
    assert takes[1]["is_canon"] is True and takes[0]["text"] == "take A"
    # the picker feed excludes archived (cap-evicted) siblings
    assert any("archived" in q for q in _queries(conn))


@pytest.mark.asyncio
async def test_pick_unarchives_the_kept_take(monkeypatch):
    conv, kept = uuid4(), uuid4()
    conn = _FakeConn(fetch=[[
        {"message_id": kept, "is_canon": False, "conversation_id": conv, "piece_brief": None},
    ]])
    _patch(monkeypatch, conn)
    await history.pick_take(uuid4(), uuid4(), kept)
    flip = next(a for k, q, a in conn.calls if k == "execute" and "is_canon = (message_id" in q)
    # picking clears the archive flag on the kept take (no canon+archived state)
    assert any("archived = archived AND (message_id <>" in q for _, q, _ in conn.calls)
