"""Action-events log (reshape §6.1 / P0.2): record_action inserts valid actions and
drops unknown ones without raising (telemetry never breaks a turn)."""
from uuid import uuid4

import pytest

from services import actions


class _FakeConn:
    def __init__(self):
        self.calls = []

    async def execute(self, *args):
        self.calls.append(args)


class _FakeAcquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *a):
        return False


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _FakeAcquire(self._conn)


def _patch_pool(monkeypatch, conn):
    async def fake_get_pool():
        return _FakePool(conn)
    monkeypatch.setattr("services.actions.get_pool", fake_get_pool, raising=False)


@pytest.mark.asyncio
async def test_record_action_inserts_valid(monkeypatch):
    conn = _FakeConn()
    _patch_pool(monkeypatch, conn)
    uid, cid, tid = uuid4(), uuid4(), uuid4()
    await actions.record_action(uid, cid, "longer", target_turn_id=tid,
                                render_mode="piece", payload={"x": 1})
    assert len(conn.calls) == 1
    args = conn.calls[0]
    assert uid in args and cid in args and tid in args and "longer" in args and "piece" in args


@pytest.mark.asyncio
async def test_record_action_drops_unknown(monkeypatch):
    conn = _FakeConn()
    _patch_pool(monkeypatch, conn)
    await actions.record_action(uuid4(), uuid4(), "bogus")
    assert conn.calls == []


class _FakeConnWithConsent(_FakeConn):
    def __init__(self, consent):
        super().__init__()
        self._consent = consent

    async def fetchval(self, *args):
        return self._consent


@pytest.mark.asyncio
async def test_record_supersede_snapshots_consent_true(monkeypatch):
    conn = _FakeConnWithConsent(consent=True)
    _patch_pool(monkeypatch, conn)
    uid, cid, k, r = uuid4(), uuid4(), uuid4(), uuid4()
    await actions.record_supersede_pair(uid, cid, k, r, render_mode="piece", retry_note="more rigorous")
    assert len(conn.calls) == 1                       # one INSERT
    args = conn.calls[0]
    assert True in args and "more rigorous" in args and k in args and r in args


@pytest.mark.asyncio
async def test_record_supersede_consent_null_defaults_false(monkeypatch):
    conn = _FakeConnWithConsent(consent=None)
    _patch_pool(monkeypatch, conn)
    await actions.record_supersede_pair(uuid4(), uuid4(), uuid4(), uuid4())
    assert False in conn.calls[0]                     # None consent -> snapshot False
