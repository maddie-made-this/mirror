"""Provenance spine (product reshape §1.2 / P0.1): the four prov_* fields default to
conversation+volunteered on a Proposition and travel to the write, are overridable (the
retry-correction path), and are nullable-by-default on GraphNode/Mention so legacy reads
survive. Neo4j persistence + the no-downgrade rule are exercised live (real graph)."""
from uuid import uuid4

from schemas.enums import ProvElicited, ProvSource
from schemas.extraction import Proposition
from schemas.graph import GraphNode, Mention


def _prop(**over):
    base = dict(subject="s", predicate="p", object="o", source_span="span")
    base.update(over)
    return Proposition(**base)


def test_proposition_prov_defaults_conversation_volunteered():
    p = _prop()
    assert p.prov_source == ProvSource.CONVERSATION.value == "conversation"
    assert p.prov_elicited == ProvElicited.VOLUNTEERED.value == "volunteered"
    assert p.prov_authorship is None
    assert p.prov_format is None


def test_proposition_prov_overridable():
    # The retry-correction / ingestion paths set a different provenance before ingest.
    p = _prop(prov_source="retry_correction", prov_elicited="asked_and_answered")
    assert p.prov_source == "retry_correction"
    assert p.prov_elicited == "asked_and_answered"


def test_graphnode_prov_nullable_default_none():
    # Legacy reads (nodes written before provenance existed) must not break.
    n = GraphNode(id="concept:x", name="x", entity_type="concept",
                  first_session=1, last_session=1)
    assert n.prov_source is None
    assert n.prov_authorship is None
    assert n.prov_format is None
    assert n.prov_elicited is None


def test_mention_prov_nullable_default_none():
    m = Mention(user_id=uuid4(), conversation_id=uuid4(), message_id=uuid4(),
                proposition_id=uuid4(), session_number=1, text="t", predicate="p")
    assert m.prov_source is None
    assert m.prov_elicited is None
