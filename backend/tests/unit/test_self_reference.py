import pytest

from services.extraction import is_self_reference


@pytest.mark.parametrize("name,display,expected", [
    ("I", "Maddie", True),
    ("me", "Maddie", True),
    ("myself", "Maddie", True),
    ("the user", "Maddie", True),
    ("self", "Maddie", True),
    ("Maddie", "Maddie", True),       # matches display name
    ("maddie", "Maddie", True),       # case-insensitive display match
    ("  ME  ", "Maddie", True),       # whitespace + case tolerant
    ("my dad", "Maddie", False),
    ("coffee", "Maddie", False),
    ("Maddie", "", False),            # no display name → no name match
])
def test_is_self_reference(name, display, expected):
    assert is_self_reference(name, display) is expected
