"""SPEC_production_renderer_backend — the validated config + provider-agnostic backend run
through the ACTUAL production render path (`_render_author` / `_backend`), not a
standalone script. Proves: the validated sampler reaches the renderer call (3a), the
cap is 1400, the
banned-phrase instruction is wired (3c), leaked scaffolding is stripped and the output ends
on a complete sentence (3b), and the renderer routes to a generic OpenAI-compatible provider.
"""
from types import SimpleNamespace

import pytest

from config.loader import APP_CONFIG
from llm import client
from schemas.piece_brief import PieceBrief
from services import response_gen as rg


def test_trim_to_sentence_clips_mid_sentence():
    body = ("The argument has three parts. The first is uncontroversial. The second "
            "is where it breaks. Most readers stop there. The third part is the one "
            "that actually does the work.")
    clipped = body + " It rests on an assumption that nobody has"
    assert rg._trim_to_sentence(clipped) == body          # tail fragment trimmed off
    assert rg._trim_to_sentence(body) == body             # already clean -> unchanged


def test_backend_renderer_uses_generic_provider(monkeypatch):
    fake = SimpleNamespace(
        renderer_base_url="https://provider.example/v1/chat/completions",
        renderer_api_key="sk-provider",
        renderer_backend="", llm_backend="openrouter",
        openrouter_api_key="sk-or",
    )
    monkeypatch.setattr("llm.client.get_settings", lambda: fake)
    assert client._backend("renderer") == (
        "https://provider.example/v1/chat/completions", "sk-provider")
    # the director / non-renderer roles are unaffected by the renderer provider
    assert client._backend("default")[0] != "https://provider.example/v1/chat/completions"


@pytest.mark.asyncio
async def test_render_author_applies_validated_config(monkeypatch):
    # canned piece clears a low floor so there's no regen; it leaks a beat header and ends clean
    monkeypatch.setattr(APP_CONFIG, "author_render_word_floor", 5)
    captured: dict = {}

    async def fake_chat(messages, **kwargs):
        captured["messages"] = messages
        captured["kwargs"] = kwargs
        return "1. state the premise\nThe premise is narrow. It has to be, or the conclusion overreaches."

    monkeypatch.setattr("services.response_gen.chat", fake_chat, raising=False)

    brief = PieceBrief(action="write", piece_beats=["1. state the premise"])
    out = await rg._render_author(brief, "write me a piece", [], [], "primary")

    kw = captured["kwargs"]
    # 3a — the validated sampler + cap reached the renderer call
    assert kw["sampling"]["top_p"] == APP_CONFIG.author_render_top_p
    assert kw["sampling"]["repetition_penalty"] == APP_CONFIG.author_render_rep_penalty
    assert kw["max_tokens"] == APP_CONFIG.author_response_max_tokens == 1400
    assert kw["temperature"] == APP_CONFIG.author_render_temperature
    assert kw["role"] == "renderer"
    # 3c — the banned-phrase instruction is wired into the prompt
    assert any("In today's world" in m.get("content", "") for m in captured["messages"])
    # leaked beat-header scaffolding stripped; 3b — ends on terminal punctuation
    assert "1. state the premise" not in out
    assert out.rstrip()[-1] in '.!?"'
