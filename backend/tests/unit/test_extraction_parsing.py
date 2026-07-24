import json

import pytest

from core.errors import ExtractionError
from services.extraction import (
    _parse_propositions_json,
    _strip_code_fence,
    extract_propositions,
)


@pytest.mark.parametrize("raw,expected_contains", [
    ('```json\n{"propositions": []}\n```', '{"propositions": []}'),
    ('```\n{"propositions": []}\n```', '{"propositions": []}'),
    ('{"propositions": []}', '{"propositions": []}'),
    ('```\n```', ''),
])
def test_strip_code_fence(raw, expected_contains):
    assert expected_contains in _strip_code_fence(raw)


def test_parse_accepts_wrapped_object():
    assert _parse_propositions_json('{"propositions": [{"x": 1}]}') == [{"x": 1}]


def test_parse_accepts_bare_array():
    assert _parse_propositions_json('[{"x": 1}]') == [{"x": 1}]


def test_parse_malformed_raises():
    with pytest.raises(ExtractionError):
        _parse_propositions_json("not json at all")


def _good_prop(obj="tired"):
    return {
        "subject": "studying", "predicate": "triggers", "object": obj,
        "source_span": "studying triggers " + obj,
        "subject_entity_type": "goal", "object_entity_type": "emotion",
        "valence": "negative", "valence_score": -0.4, "salience_score": -0.3,
        "causal_class": "causal", "confidence": 0.9,
        "subject_knowledge_source": "user_stated",
        "object_knowledge_source": "user_stated",
    }


async def test_extract_empty_array(mock_llm, conversation_id, message_id):
    mock_llm.return_value = '{"propositions": []}'
    result = await extract_propositions(
        "hello", [], [], conversation_id=conversation_id, message_id=message_id,
    )
    assert result == []


async def test_extract_malformed_degrades_gracefully(mock_llm, conversation_id, message_id):
    # Extraction is best-effort: an unparseable Pass 1 must NOT raise (it used to
    # 422 the whole message). It degrades to no propositions for the turn.
    mock_llm.return_value = "not json at all"
    result = await extract_propositions(
        "x", [], [], conversation_id=conversation_id, message_id=message_id,
    )
    assert result == []


def test_parse_salvages_truncated_json():
    # A token-cap truncation: two complete proposition objects, third cut off.
    truncated = (
        '{"propositions":['
        '{"subject":"self","predicate":"likes","object":"recursive structures"},'
        '{"subject":"a worked example","predicate":"provides","object":"clarity"},'
        '{"subject":"deriva'
    )
    items = _parse_propositions_json(truncated)
    assert [i["object"] for i in items] == ["recursive structures", "clarity"]


async def test_extract_injects_provenance(mock_llm, conversation_id, message_id):
    # Pass 1 returns one prop; Pass 2 (reflection) returns nothing.
    mock_llm.side_effect = [
        json.dumps({"propositions": [_good_prop()]}),
        '{"propositions": []}',
    ]
    result = await extract_propositions(
        "studying triggers tired", [], [],
        conversation_id=conversation_id, message_id=message_id,
    )
    assert len(result) == 1
    assert result[0].source_conversation_id == conversation_id
    assert result[0].source_message_id == message_id


async def test_extract_drops_bad_item_keeps_good(mock_llm, conversation_id, message_id):
    # One valid proposition, one missing required fields.
    mock_llm.side_effect = [
        json.dumps({"propositions": [_good_prop(), {"subject": "only-subject"}]}),
        '{"propositions": []}',
    ]
    result = await extract_propositions(
        "msg", [], [], conversation_id=conversation_id, message_id=message_id,
    )
    assert len(result) == 1
    assert result[0].object == "tired"


async def test_extract_runs_second_pass(mock_llm, conversation_id, message_id):
    # Pass 1 + Pass 2 each contribute one proposition.
    mock_llm.side_effect = [
        json.dumps({"propositions": [_good_prop("tired")]}),
        json.dumps({"propositions": [_good_prop("avoidance of rest")]}),
    ]
    result = await extract_propositions(
        "msg", [], [], conversation_id=conversation_id, message_id=message_id,
    )
    assert len(result) == 2
    assert mock_llm.await_count == 2


async def test_extract_single_pass_when_reflection_disabled(
    mock_llm, no_reflection, conversation_id, message_id,
):
    mock_llm.return_value = json.dumps({"propositions": [_good_prop()]})
    result = await extract_propositions(
        "msg", [], [], conversation_id=conversation_id, message_id=message_id,
    )
    assert len(result) == 1
    assert mock_llm.await_count == 1
