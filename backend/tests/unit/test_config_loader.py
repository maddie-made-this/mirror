"""
Guards the default config — the only config in this repo. Verifies it loads
correctly and that the loader always resolves to it.
"""
from config.default import DEFAULT_CONFIG
from config.loader import APP_CONFIG, load_config


def test_loader_returns_default_config():
    cfg = load_config()
    assert cfg.entity_types == DEFAULT_CONFIG.entity_types
    # Mirror's persona IS the conversational layer, so the identity layer must be
    # ON — with it off, all of config/personas.py is dead in the shipped build and
    # the README describes a layer that never renders. Safety stays off: the base
    # model's own training covers it.
    assert cfg.use_identity_layer is True
    assert cfg.use_safety_layer is False


def test_app_config_is_default():
    assert APP_CONFIG.entity_types == DEFAULT_CONFIG.entity_types


def test_default_config_has_reflection_prompt():
    # Two-pass extraction is enabled.
    assert DEFAULT_CONFIG.reflection_system_prompt
    assert "Pass 2" in DEFAULT_CONFIG.reflection_system_prompt


def test_default_extraction_prompt_has_subject_discipline():
    assert "SUBJECT DISCIPLINE" in DEFAULT_CONFIG.extraction_system_prompt
