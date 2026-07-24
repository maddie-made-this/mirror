"""
Angle vocabulary loader (three-tier engine model §2 — tier-2).

The curated, finite set of psychological *angles* — the felt character a cluster
of interests takes for a user ("what KIND of pull this is"). Edited as DATA
(config/angle_vocabulary.json), not as a prompt blob, mirroring how the canonical
concept store (#3) will work. The tier-2 matcher classifies a cluster into ONE of
these entries (or NO_MATCH); it never produces free text. That is the audit-trail
property: every persisted angle traces to a curated key, never to a confabulation.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# services/ -> src/ -> config/angle_vocabulary.json
_VOCAB_PATH = Path(__file__).resolve().parent.parent / "config" / "angle_vocabulary.json"


@dataclass(frozen=True)
class AngleEntry:
    key: str
    name: str
    definition: str
    felt_distinction_from_neighbors: str
    trigger_phrasings: list[str]
    related_concepts: list[str]


_CACHE: dict[str, AngleEntry] | None = None


def load_vocabulary() -> dict[str, AngleEntry]:
    """
    Load and cache the seed vocabulary. Returns {key: AngleEntry}. Stable
    in-memory for the process lifetime; reload requires a service restart (hot-
    reload is a follow-up if curation pace requires it). Malformed entries are
    skipped + logged rather than crashing the loader.
    """
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    out: dict[str, AngleEntry] = {}
    try:
        raw = json.loads(_VOCAB_PATH.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("angle_vocabulary: failed to read %s", _VOCAB_PATH)
        _CACHE = out
        return out
    for a in raw.get("angles", []):
        try:
            entry = AngleEntry(
                key=a["key"],
                name=a["name"],
                definition=a["definition"],
                felt_distinction_from_neighbors=a.get("felt_distinction_from_neighbors", ""),
                trigger_phrasings=list(a.get("trigger_phrasings", [])),
                related_concepts=list(a.get("related_concepts", [])),
            )
        except (KeyError, TypeError):
            logger.warning("angle_vocabulary: skipping malformed entry", extra={"raw": a})
            continue
        if entry.key in out:
            logger.warning("angle_vocabulary: duplicate key", extra={"key": entry.key})
        out[entry.key] = entry
    _CACHE = out
    return out


def get_angle(key: str) -> AngleEntry | None:
    """
    Lookup by canonical key. Returns None if the key isn't in the vocabulary —
    the caller MUST treat that as an audit failure: a persisted angle_key must
    always correspond to a vocabulary entry.
    """
    return load_vocabulary().get(key)


def all_angles() -> list[AngleEntry]:
    """Return the full vocabulary list, for the matcher prompt."""
    return list(load_vocabulary().values())
