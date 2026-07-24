"""Retry-note classifier + router (reshape §6.2 / P0.3B): four-way bucketing with a
bias-to-content, and graph-feeding routed only on the content bucket."""
import json
from uuid import uuid4

import pytest

from services import retry_note_classifier as rn
from services.retry_note_classifier import RetryRouting


def _chat(payload):
    async def _fake(messages, **kw):
        return json.dumps(payload)
    return _fake


@pytest.mark.asyncio
async def test_classify_content(monkeypatch):
    monkeypatch.setattr("services.retry_note_classifier.chat",
                        _chat({"content": "make it more rigorous", "delivery": None, "discard": False}),
                        raising=False)
    r = await rn.classify("more rigorous", "write a piece", "the beat")
    assert r.content == "make it more rigorous" and r.delivery is None and r.discard is False


@pytest.mark.asyncio
async def test_classify_delivery(monkeypatch):
    monkeypatch.setattr("services.retry_note_classifier.chat",
                        _chat({"content": None, "delivery": "too long", "discard": False}),
                        raising=False)
    r = await rn.classify("too long", "x", "y")
    assert r.delivery == "too long" and r.content is None


@pytest.mark.asyncio
async def test_classify_both(monkeypatch):
    monkeypatch.setattr("services.retry_note_classifier.chat",
                        _chat({"content": "more rigorous", "delivery": "shorter", "discard": False}),
                        raising=False)
    r = await rn.classify("shorter and more rigorous", "x", "y")
    assert r.content == "more rigorous" and r.delivery == "shorter"


@pytest.mark.asyncio
async def test_classify_discard(monkeypatch):
    monkeypatch.setattr("services.retry_note_classifier.chat",
                        _chat({"content": None, "delivery": None, "discard": True}),
                        raising=False)
    r = await rn.classify("asdfgh", "x", "y")
    assert r.discard is True and r.content is None and r.delivery is None


@pytest.mark.asyncio
async def test_classify_empty_note_discards_without_call(monkeypatch):
    called = []

    async def spy(*a, **k):
        called.append(1)
        return "{}"
    monkeypatch.setattr("services.retry_note_classifier.chat", spy, raising=False)
    r = await rn.classify("   ", "x", "y")
    assert r.discard is True and called == []          # no LLM call on an empty note


@pytest.mark.asyncio
async def test_classify_failure_biases_to_content(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("llm down")
    monkeypatch.setattr("services.retry_note_classifier.chat", boom, raising=False)
    r = await rn.classify("more rigorous", "x", "y")
    assert r.content == "more rigorous" and r.discard is False  # recoverable > lost


@pytest.mark.asyncio
async def test_route_content_calls_extraction(monkeypatch):
    calls = []

    async def fake_classify(*a, **k):
        return RetryRouting(content="make it more rigorous")

    async def fake_extract(*a, **k):
        calls.append((a, k))
    monkeypatch.setattr("services.retry_note_classifier.classify", fake_classify, raising=False)
    monkeypatch.setattr("services.extraction.extract_from_retry_correction", fake_extract, raising=False)
    await rn.route_retry_note(uuid4(), uuid4(), uuid4(), "more rigorous", "orig", "beat", session_number=3)
    assert len(calls) == 1
    assert "make it more rigorous" in calls[0][0]       # content text passed to extraction


@pytest.mark.asyncio
async def test_route_delivery_skips_extraction(monkeypatch):
    calls = []

    async def fake_classify(*a, **k):
        return RetryRouting(delivery="too long")

    async def fake_extract(*a, **k):
        calls.append(1)
    monkeypatch.setattr("services.retry_note_classifier.classify", fake_classify, raising=False)
    monkeypatch.setattr("services.extraction.extract_from_retry_correction", fake_extract, raising=False)
    await rn.route_retry_note(uuid4(), uuid4(), uuid4(), "too long", "orig", "beat", session_number=3)
    assert calls == []                                 # delivery never feeds the graph
