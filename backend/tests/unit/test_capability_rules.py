"""B10: the capability layer swaps register on the analytic branch."""
from config.loader import APP_CONFIG
from llm.layers import capability_rules


def test_primary_uses_capability_text(monkeypatch):
    monkeypatch.setattr(APP_CONFIG, "use_capability_layer", True)
    monkeypatch.setattr(APP_CONFIG, "capability_rules_text", "PRIMARY")
    monkeypatch.setattr(APP_CONFIG, "analytic_capability_text", "ANALYTIC")
    assert capability_rules.render("primary") == "PRIMARY"
    # The default (no arg) is the primary register.
    assert capability_rules.render() == "PRIMARY"


def test_analytic_swaps_when_configured(monkeypatch):
    monkeypatch.setattr(APP_CONFIG, "use_capability_layer", True)
    monkeypatch.setattr(APP_CONFIG, "capability_rules_text", "PRIMARY")
    monkeypatch.setattr(APP_CONFIG, "analytic_capability_text", "ANALYTIC")
    assert capability_rules.render("analytic") == "ANALYTIC"


def test_analytic_falls_back_when_unset(monkeypatch):
    # No separate analytic register configured → analytic branch reuses primary.
    monkeypatch.setattr(APP_CONFIG, "use_capability_layer", True)
    monkeypatch.setattr(APP_CONFIG, "capability_rules_text", "PRIMARY")
    monkeypatch.setattr(APP_CONFIG, "analytic_capability_text", "")
    assert capability_rules.render("analytic") == "PRIMARY"


def test_layer_disabled_returns_none(monkeypatch):
    monkeypatch.setattr(APP_CONFIG, "use_capability_layer", False)
    monkeypatch.setattr(APP_CONFIG, "analytic_capability_text", "ANALYTIC")
    assert capability_rules.render("analytic") is None
    assert capability_rules.render("primary") is None
