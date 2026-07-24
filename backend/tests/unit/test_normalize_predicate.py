import pytest

from services.extraction import normalize_predicate


@pytest.mark.parametrize("raw,expected", [
    ("  makes me feel  ", "makes me feel"),       # surrounding whitespace
    ("Makes Me Feel", "makes me feel"),            # case
    ("makes  me   feel", "makes me feel"),         # collapsed inner whitespace
    ("triggers.", "triggers"),                     # trailing punctuation
    ('"was hurt by"', "was hurt by"),              # surrounding quotes
    ("was hurt by", "was hurt by"),                # voice preserved
    ("used to fear", "used to fear"),              # tense preserved
])
def test_normalize_predicate(raw, expected):
    assert normalize_predicate(raw) == expected


def test_voice_and_tense_kept_distinct():
    assert normalize_predicate("hurt") != normalize_predicate("was hurt by")
    assert normalize_predicate("fears") != normalize_predicate("used to fear")


def test_never_returns_empty():
    # Punctuation-only input must not collapse to an empty string.
    assert normalize_predicate("...") != ""
