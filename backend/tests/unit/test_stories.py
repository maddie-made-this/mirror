"""Story documents (reshape §2.2 / P1.1): create inserts metadata; render DERIVES the
document from canon turns (never copies content into the stories row)."""
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from services import stories


def _row(**over):
    base = dict(
        id=uuid4(), source_conversation_id=uuid4(), title="t", pinned=False,
        cover_state={}, color_map={}, created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    base.update(over)
    return base


class _FakeConn:
    def __init__(self, fetchrow=None, fetch=None):
        self._fetchrow = fetchrow
        self._fetch = fetch or []
        self.queries = []

    async def fetchrow(self, q, *a):
        self.queries.append(q)
        return self._fetchrow

    async def fetch(self, q, *a):
        self.queries.append(q)
        return self._fetch


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
    monkeypatch.setattr("services.stories.get_pool", fake_get_pool, raising=False)


@pytest.mark.asyncio
async def test_create_story_returns_summary(monkeypatch):
    row = _row(title="My Story")
    _patch(monkeypatch, _FakeConn(fetchrow=row))
    s = await stories.create_story(uuid4(), uuid4(), "My Story")
    assert s.title == "My Story" and s.id == row["id"]


@pytest.mark.asyncio
async def test_create_story_is_idempotent_per_conversation(monkeypatch):
    """A story is a pointer to a conversation's canon, so re-saving the same
    conversation must UPDATE the existing row, never INSERT a duplicate. Here the
    lookup finds an existing row, so the write must be an UPDATE."""
    conn = _FakeConn(fetchrow=_row(title="Existing"))
    _patch(monkeypatch, conn)
    await stories.create_story(uuid4(), uuid4(), "New title")
    writes = [q for q in conn.queries if "stories" in q and ("INSERT" in q or "UPDATE" in q)]
    assert any("UPDATE stories" in q for q in writes), writes
    assert not any("INSERT INTO stories" in q for q in writes), writes


@pytest.mark.asyncio
async def test_render_story_derives_canon(monkeypatch):
    conv = uuid4()
    t1, t2 = uuid4(), uuid4()
    conn = _FakeConn(
        fetchrow={"source_conversation_id": conv},
        fetch=[{"message_id": t1, "response_text": "beat one"},
               {"message_id": t2, "response_text": "beat two"}],
    )
    _patch(monkeypatch, conn)
    beats = await stories.render_story(uuid4(), uuid4())
    assert [b.text for b in beats] == ["beat one", "beat two"]
    # turn_id is the message_id (shared identity with the chat editor), not the PK id
    assert [b.turn_id for b in beats] == [t1, t2]
    # derives from conversation_turns WHERE is_canon — no stored content column
    assert any("is_canon" in q for q in conn.queries)


@pytest.mark.asyncio
async def test_render_story_missing_returns_empty(monkeypatch):
    _patch(monkeypatch, _FakeConn(fetchrow=None))
    assert await stories.render_story(uuid4(), uuid4()) == []
