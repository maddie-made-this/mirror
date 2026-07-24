import pytest
from pydantic import ValidationError

from schemas.enums import KnowledgeSource
from schemas.extraction import Proposition
from schemas.graph import GraphEdge, GraphNode
from schemas.message import MessageResponse
from uuid import uuid4


def _node(**over):
    base = dict(
        id="emotion:burnout", name="burnout", entity_type="emotion",
        first_session=1, last_session=1,
    )
    base.update(over)
    return GraphNode(**base)


def test_graphnode_accepts_unknown_entity_type_on_read():
    # Reads must survive a config that defines a superset of entity types (e.g.
    # 'dynamic'/'motif'); the validator warns but does not raise. Extraction
    # sanitizes genuinely-invalid LLM output to 'concept' before write.
    assert _node(entity_type="dynamic").entity_type == "dynamic"


def test_graphnode_accepts_known_entity_type():
    assert _node(entity_type="emotion").entity_type == "emotion"


def test_graphnode_valence_score_clamped_range():
    with pytest.raises(ValidationError):
        _node(valence_score=5.0)
    with pytest.raises(ValidationError):
        _node(valence_score=-5.0)


def test_graphnode_serializes_json_mode():
    dumped = _node().model_dump(mode="json")
    # round-trips back through the model without error
    GraphNode(**dumped)


def test_proposition_confidence_bounds():
    with pytest.raises(ValidationError):
        Proposition(subject="a", predicate="b", object="c",
                    source_span="s", confidence=1.5)


def test_proposition_knowledge_source_enum():
    p = Proposition(subject="a", predicate="b", object="c", source_span="s",
                    subject_knowledge_source="llm_inferred")
    assert p.subject_knowledge_source == KnowledgeSource.LLM_INFERRED
    with pytest.raises(ValidationError):
        Proposition(subject="a", predicate="b", object="c", source_span="s",
                    subject_knowledge_source="invented_value")


def test_message_response_round_trips():
    edge = GraphEdge(source_id="a", target_id="b", relation_type="causes",
                     proposition_id=uuid4(), first_session=1, last_session=1)
    resp = MessageResponse(
        conversation_id=uuid4(), session_number=1, response_text="hi",
        propositions=[], nodes_created=[_node()], nodes_updated=[],
        edges_created=[edge], edges_updated=[],
    )
    # The idempotency cache relies on this round-trip working.
    MessageResponse(**resp.model_dump(mode="json"))


def test_message_response_prompt_context_optional():
    resp = MessageResponse(
        conversation_id=uuid4(), session_number=1, response_text="hi",
        propositions=[], nodes_created=[], nodes_updated=[],
        edges_created=[], edges_updated=[],
    )
    assert resp.prompt_context is None


# --- Three-tier engine model: tier-2 angle kind + angle_key payload ---
from schemas.interpretation import Interpretation, InterpretationKind  # noqa: E402


def test_interpretation_kind_has_angle():
    assert InterpretationKind.ANGLE.value == "angle"
    assert InterpretationKind("angle") is InterpretationKind.ANGLE


def test_interpretation_angle_key_field():
    i = Interpretation(
        user_id=uuid4(), statement="grasping a whole system",
        kind=InterpretationKind.ANGLE, angle_key="grasping_a_whole_system",
    )
    assert i.angle_key == "grasping_a_whole_system"
    # default empty on legacy / non-angle rows
    assert Interpretation(user_id=uuid4(), statement="x").angle_key == ""
    # round-trips through json mode (the Neo4j persistence path)
    Interpretation(**i.model_dump(mode="json"))
