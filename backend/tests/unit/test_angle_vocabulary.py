"""Tier-2 angle vocabulary loader (three-tier engine model §2)."""
from services import angle_vocabulary as av


def test_vocabulary_loads_and_parses():
    vocab = av.load_vocabulary()
    assert isinstance(vocab, dict)
    assert len(vocab) >= 15  # the placeholder demo list is 15 angles


def test_all_entries_have_required_fields():
    for entry in av.all_angles():
        assert entry.key and isinstance(entry.key, str)
        assert entry.name
        assert entry.definition
        assert entry.felt_distinction_from_neighbors
        assert isinstance(entry.trigger_phrasings, list) and entry.trigger_phrasings
        assert isinstance(entry.related_concepts, list) and entry.related_concepts


def test_keys_are_unique():
    keys = [e.key for e in av.all_angles()]
    assert len(keys) == len(set(keys))


def test_get_angle_hit():
    e = av.get_angle("grasping_a_whole_system")
    assert e is not None
    assert e.name == "grasping a whole system"


def test_get_angle_miss_returns_none():
    # A persisted angle_key MUST correspond to a vocabulary entry; absence is an
    # audit failure the caller is responsible for catching.
    assert av.get_angle("nonexistent_angle_key") is None
