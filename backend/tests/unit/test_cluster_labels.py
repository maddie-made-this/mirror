from services.bridges import _clean_bridge
from services.clustering import _unique_label, sanitize_label


def test_strips_type_prefix_and_inline_markdown():
    # 2.2: cheap models emit "Theme:** Phrase" — prefix + mid-label markdown.
    assert sanitize_label("Theme:** Recursive Structure") == "Recursive Structure"
    assert sanitize_label("Pattern: Hidden Mechanism") == "Hidden Mechanism"
    assert sanitize_label("- **Acceptance**") == "Acceptance"
    assert sanitize_label("**Self Discovery**") == "Self Discovery"


def test_clean_bridge_drops_placeholders_and_slashes():
    # 2.5: backstop for leaked template structure.
    assert "<" not in _clean_bridge("a (in <theme A>) and b — x / y. Worth it?")
    assert "/" not in _clean_bridge("the same thread / in tension")
    assert _clean_bridge("a or b") == "a or b"  # already-clean prose untouched


def test_strips_leading_bullets_and_numbering():
    assert sanitize_label("- Systems Thinking") == "Systems Thinking"
    assert sanitize_label("* Curiosity") == "Curiosity"
    assert sanitize_label("1. Structure") == "Structure"
    assert sanitize_label("2) Expression") == "Expression"
    assert sanitize_label("• Quiet Space") == "Quiet Space"


def test_strips_quotes_and_takes_first_line():
    assert sanitize_label('"Systems Thinking"') == "Systems Thinking"
    assert sanitize_label("Systems Thinking\n(the theme connecting them)") == "Systems Thinking"
    assert sanitize_label("  “Curiosity”  ") == "Curiosity"


def test_collapses_whitespace_and_caps_length():
    assert sanitize_label("systems   thinking") == "systems thinking"
    assert len(sanitize_label("x" * 200)) == 60


def test_unique_label_numeric_fallback():
    used = {"systems thinking"}
    assert _unique_label("Curiosity", used) == "Curiosity"     # free label untouched
    assert _unique_label("Systems Thinking", used) == "Systems Thinking (2)"
    used.add("systems thinking (2)")
    assert _unique_label("Systems Thinking", used) == "Systems Thinking (3)"
