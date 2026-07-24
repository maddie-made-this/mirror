from llm.prompts import (
    build_conversational_renderer_messages,
    build_extraction_messages,
    build_reflection_messages,
    build_response_messages,
    build_response_messages_debug,
)
from config.loader import APP_CONFIG
from config.personas import get_active_persona
from schemas.graph import GraphContext
from schemas.response_stance import ResponseStance


def _empty_ctx():
    return GraphContext(relevant_nodes=[], relevant_edges=[])


def test_response_messages_layer_order():
    msgs = build_response_messages("hi", _empty_ctx(), [], [])
    assert msgs[0]["role"] == "system"
    assert msgs[-1] == {"role": "user", "content": "hi"}


def test_debug_breakdown_has_all_layers():
    msgs, breakdown = build_response_messages_debug("hi", _empty_ctx(), [], [])
    assert "system_layers" in breakdown
    for layer in ("core_identity", "safety_rules", "capability_rules",
                  "format_rules", "graph_context", "user_preferences"):
        assert layer in breakdown["system_layers"]
    assert breakdown["user_message"] == "hi"
    assert breakdown["model"]
    assert msgs[-1] == {"role": "user", "content": "hi"}


def test_extraction_messages_include_examples():
    msgs = build_extraction_messages("test", [], [])
    assert msgs[0]["role"] == "system"
    assert any(m["role"] == "assistant" for m in msgs)
    assert msgs[-1]["content"].endswith("test")


def test_extraction_messages_interpolate_entity_types():
    msgs = build_extraction_messages("test", [], [])
    # {entity_types} placeholder must be replaced; "self" is always a valid type.
    assert "{entity_types}" not in msgs[0]["content"]
    assert "self" in msgs[0]["content"]


def test_extraction_active_node_hint_conditional():
    without = build_extraction_messages("test", [], [])
    # No active nodes → final user turn is just the message block.
    assert without[-1]["content"].startswith("Message:")


def test_reflection_messages_built_when_configured():
    msgs = build_reflection_messages("the message", [{"subject": "x"}])
    # Default config has reflection enabled → system + user pair.
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert "Pass 1" in msgs[1]["content"]


def test_reflection_messages_empty_when_disabled(no_reflection):
    assert build_reflection_messages("msg", []) == []


# --- Conversational renderer: active-persona conv_note ---


def _conv_system(monkeypatch, persona_key="mirror_warm", move="engage", read=""):
    monkeypatch.setenv("MIRROR_PERSONA", persona_key)
    monkeypatch.setattr(APP_CONFIG, "use_identity_layer", True, raising=False)
    stance = ResponseStance(move=move, read=read)
    msgs = build_conversational_renderer_messages(stance, "hi", [], [])
    return msgs[0]["content"]


def test_conv_note_includes_active_persona_name(monkeypatch):
    assert "Mirror" in _conv_system(monkeypatch, "mirror_warm")


def test_conv_note_includes_example_turns(monkeypatch):
    sys = _conv_system(monkeypatch, "mirror_direct")
    persona = get_active_persona()
    assert any(t in sys for t in persona.example_turns)


def test_conv_note_swaps_with_persona(monkeypatch):
    # The env-var swap changes the rendered register (different example turns).
    direct = _conv_system(monkeypatch, "mirror_direct")
    playful = _conv_system(monkeypatch, "mirror_playful")
    assert "Tell me about the part that doesn't fit." in direct   # a mirror_direct example turn
    assert "Tell me about the part that doesn't fit." not in playful


def test_conv_render_carries_the_stance_read(monkeypatch):
    """A land_read stance must put the read itself into the prompt — the stance
    block is what makes the reply land the insight rather than restate it."""
    sys = _conv_system(monkeypatch, "mirror_warm", move="land_read",
                       read="the anomaly is the real subject here")
    assert "the anomaly is the real subject here" in sys


def test_conv_note_neutral_when_identity_off(monkeypatch):
    # Identity layer off: neutral note — no persona, no familiar register.
    monkeypatch.setattr(APP_CONFIG, "use_identity_layer", False, raising=False)
    sys = build_conversational_renderer_messages(
        ResponseStance(move="engage"), "hi", [], []
    )[0]["content"]
    assert "Mirror" not in sys
