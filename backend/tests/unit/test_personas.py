"""Mirror persona system: the registry, the env-var-driven active selector, and the
core_identity layer assembled from the active persona."""
from config.loader import APP_CONFIG
from config.personas import PERSONAS, _DEFAULT_PERSONA_KEY, get_active_persona
from llm.layers import core_identity


def test_default_persona_when_no_env(monkeypatch):
    monkeypatch.delenv("MIRROR_PERSONA", raising=False)
    assert get_active_persona().key == _DEFAULT_PERSONA_KEY


def test_env_var_selects_persona(monkeypatch):
    monkeypatch.setenv("MIRROR_PERSONA", "mirror_direct")
    assert get_active_persona().key == "mirror_direct"


def test_unknown_key_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("MIRROR_PERSONA", "nope_not_a_persona")
    assert get_active_persona().key == _DEFAULT_PERSONA_KEY


def test_every_persona_has_required_fields():
    for p in PERSONAS.values():
        assert p.identity.strip(), p.key
        assert p.conversational_register.strip(), p.key
        assert p.example_turns, p.key
        assert p.rules, p.key


def test_mirror_variants_share_name_and_rules():
    mirrors = [p for p in PERSONAS.values() if p.name == "Mirror"]
    assert len(mirrors) >= 3
    assert {p.name for p in mirrors} == {"Mirror"}
    first = mirrors[0].rules
    for p in mirrors[1:]:
        assert p.rules == first          # identity consistency: one shared rule list


def test_core_identity_render_assembles_active_persona(monkeypatch):
    monkeypatch.setenv("MIRROR_PERSONA", "mirror_direct")
    monkeypatch.setattr(APP_CONFIG, "use_identity_layer", True, raising=False)
    out = core_identity.render()
    assert out and "Mirror" in out
    assert "HOW YOU OPERATE" in out      # the hard-rules block is included


def test_core_identity_render_none_when_layer_off(monkeypatch):
    # Identity layer off -> the persona never reaches the prompt.
    monkeypatch.setattr(APP_CONFIG, "use_identity_layer", False, raising=False)
    assert core_identity.render() is None
