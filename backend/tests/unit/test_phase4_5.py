"""Phase 4 (length adaptation, retry diagnostics) + Phase 5 (crypto, delete job, account,
warming, model swaps)."""
import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest


# ── Fake pool ──────────────────────────────────────────────────────────────

class _Conn:
    def __init__(self, fetchval=None, fetchrow=None):
        self.calls = []
        self._fetchval = fetchval
        self._fetchrow = fetchrow

    def transaction(self):
        conn = self
        class _T:
            async def __aenter__(self): return conn
            async def __aexit__(self, *a): return False
        return _T()

    async def execute(self, q, *a): self.calls.append(("execute", q, a)); return "OK"
    async def fetchval(self, q, *a): self.calls.append(("fetchval", q, a)); return self._fetchval
    async def fetchrow(self, q, *a): self.calls.append(("fetchrow", q, a)); return self._fetchrow


class _Pool:
    def __init__(self, c): self._c = c
    def acquire(self):
        c = self._c
        class _A:
            async def __aenter__(self): return c
            async def __aexit__(self, *a): return False
        return _A()


def _patch(monkeypatch, module, conn):
    async def fake(): return _Pool(conn)
    monkeypatch.setattr(f"services.{module}.get_pool", fake, raising=False)


# ── P4.1 length adaptation ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bump_longer_is_damped_and_persisted(monkeypatch):
    from services import render_prefs
    conn = _Conn(fetchval={"conversational": {"target_words": 100}})
    _patch(monkeypatch, "render_prefs", conn)
    new = await render_prefs.bump(uuid4(), "conversational", "longer")
    assert new == 115                                 # 100 × 1.15, damped
    assert any(k == "execute" and "render_prefs" in q for k, q, _ in conn.calls)


@pytest.mark.asyncio
async def test_bump_clamps_to_bounds(monkeypatch):
    from services import render_prefs
    conn = _Conn(fetchval={"cowrite": {"target_words": 1950}})
    _patch(monkeypatch, "render_prefs", conn)
    new = await render_prefs.bump(uuid4(), "cowrite", "longer")
    assert new == 2000                                # clamped to piece hi bound


@pytest.mark.asyncio
async def test_bump_analysis_mode_not_adapted(monkeypatch):
    from services import render_prefs
    conn = _Conn(fetchval={})
    _patch(monkeypatch, "render_prefs", conn)
    assert await render_prefs.bump(uuid4(), "analysis", "longer") is None


def test_target_words_resolution_and_mode_independence():
    from services import render_prefs
    prefs = {"cowrite": {"target_words": 900}, "conversational": {"target_words": 80}}
    assert render_prefs.target_words(prefs, "author") == 900        # author shares piece
    assert render_prefs.target_words(prefs, "conversational") == 80
    assert render_prefs.target_words(prefs, "analysis") is None
    assert render_prefs.target_words({}, "cowrite") is None           # unset → no directive


def test_format_rules_length_directive_only_when_set():
    from llm.layers import format_rules
    assert format_rules._length_directive(None) is None
    assert format_rules._length_directive(0) is None
    out = format_rules._length_directive(500)
    assert "500 words" in out and "soft target" in out


# ── P4.2 retry diagnostics ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_retry_rate_derived_from_action_events(monkeypatch):
    from services import actions
    conn = _Conn(fetchrow={"retries": 3, "beat_actions": 12})
    _patch(monkeypatch, "actions", conn)
    out = await actions.retry_rate_7d(uuid4())
    assert out["retries"] == 3 and out["beat_actions"] == 12
    assert out["rate"] == pytest.approx(0.25)


# ── P5.1 crypto ────────────────────────────────────────────────────────────

def test_crypto_roundtrip(monkeypatch):
    from cryptography.fernet import Fernet
    from core import crypto
    key = Fernet.generate_key().decode()
    monkeypatch.setattr("core.crypto.get_settings",
                        lambda: SimpleNamespace(mirror_field_key=key))
    crypto._fernet.cache_clear()
    token = crypto.encrypt("a private note")
    assert isinstance(token, bytes)
    assert crypto.decrypt(token) == "a private note"
    crypto._fernet.cache_clear()


def test_crypto_requires_key(monkeypatch):
    from core import crypto
    monkeypatch.setattr("core.crypto.get_settings",
                        lambda: SimpleNamespace(mirror_field_key=""))
    crypto._fernet.cache_clear()
    with pytest.raises(RuntimeError):
        crypto.encrypt("x")
    crypto._fernet.cache_clear()


# ── P5.1 delete job ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_postgres_covers_all_tables_and_profiles(monkeypatch):
    from services import account_delete
    conn = _Conn()
    async def fake(): return _Pool(conn)
    monkeypatch.setattr("services.account_delete.get_pool", fake)
    uid = uuid4()
    await account_delete._delete_postgres(uid)
    deleted = " ".join(q for k, q, _ in conn.calls if k == "execute")
    for table in account_delete._USER_ID_TABLES:
        assert table in deleted
    assert "profiles" in deleted                       # profiles row (keyed by id) too


@pytest.mark.asyncio
async def test_delete_user_status_map_best_effort(monkeypatch):
    from services import account_delete
    async def ok(uid): return None
    async def boom(uid): raise RuntimeError("neo4j down")
    async def skipped(uid): return False
    monkeypatch.setattr(account_delete, "_delete_postgres", ok)
    monkeypatch.setattr(account_delete, "_delete_neo4j", boom)
    monkeypatch.setattr(account_delete, "_delete_qdrant", ok)
    monkeypatch.setattr(account_delete, "_delete_supabase_auth", skipped)
    status = await account_delete.delete_user(uuid4())
    assert status == {"postgres": "ok", "neo4j": "failed",
                      "qdrant": "ok", "supabase_auth": "skipped"}


# ── P5.1 account flags ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_account_flags_default_when_no_row(monkeypatch):
    from services import account
    _patch(monkeypatch, "account", _Conn(fetchrow=None))
    assert await account.get_account_flags(uuid4()) == {"is_dev": False, "training_consent": False}


# ── P5.3 model resolution ──────────────────────────────────────────────────

def test_small_model_settings_fall_back_to_utility():
    from config.loader import APP_CONFIG
    # unset by default → all fall back to the cheap utility tier
    assert APP_CONFIG.extraction_model_resolved == APP_CONFIG.utility_model_resolved
    assert APP_CONFIG.matcher_model_resolved == APP_CONFIG.utility_model_resolved
    assert APP_CONFIG.headline_model_resolved == APP_CONFIG.utility_model_resolved


# ── P5.4 warming-up stream ─────────────────────────────────────────────────

class _SlowIter:
    """Async iterator whose FIRST token is delayed; the rest are immediate."""
    def __init__(self, tokens, first_delay):
        self._tokens = list(tokens)
        self._first_delay = first_delay
        self._i = 0

    def __aiter__(self): return self

    async def __anext__(self):
        if self._i >= len(self._tokens):
            raise StopAsyncIteration
        if self._i == 0 and self._first_delay:
            await asyncio.sleep(self._first_delay)
        tok = self._tokens[self._i]
        self._i += 1
        return tok


@pytest.mark.asyncio
async def test_warming_emitted_when_first_token_slow():
    from api.v1.messages import _tokens_with_warming
    out = [k async for k, _ in _tokens_with_warming(_SlowIter(["a", "b"], 0.15), 0.03)]
    assert out == ["warming", "token", "token"]        # warming precedes the delayed token


@pytest.mark.asyncio
async def test_no_warming_when_fast_or_disabled():
    from api.v1.messages import _tokens_with_warming
    fast = [k async for k, _ in _tokens_with_warming(_SlowIter(["a", "b"], 0.0), 0.5)]
    assert fast == ["token", "token"]
    disabled = [k async for k, _ in _tokens_with_warming(_SlowIter(["a"], 0.1), 0)]
    assert disabled == ["token"]                       # threshold 0 disables the check
