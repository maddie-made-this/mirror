from services.safety import (
    SafetyDecision,
    _parse_guardrail_output,
    check_input,
    check_output,
)


def test_parse_safe():
    result = _parse_guardrail_output("safe")
    assert result.decision == SafetyDecision.SAFE
    assert result.categories == []


def test_parse_unsafe_with_categories():
    result = _parse_guardrail_output("unsafe\nS1,S5")
    assert result.decision == SafetyDecision.UNSAFE
    assert result.categories == ["S1", "S5"]


def test_parse_tolerates_whitespace_and_case():
    result = _parse_guardrail_output("  SAFE \n")
    assert result.decision == SafetyDecision.SAFE


async def test_check_input_toggle_off_skips_llm(mock_llm):
    # Default config has use_input_guardrail=False.
    result = await check_input("anything at all")
    assert result.decision == SafetyDecision.SAFE
    mock_llm.assert_not_awaited()


async def test_check_output_toggle_off_skips_llm(mock_llm):
    result = await check_output("a response", "a message")
    assert result.decision == SafetyDecision.SAFE
    mock_llm.assert_not_awaited()


def _enable_reasoning(monkeypatch):
    from config.loader import APP_CONFIG
    monkeypatch.setattr(APP_CONFIG, "use_input_guardrail", True)
    monkeypatch.setattr(APP_CONFIG, "use_output_guardrail", True)
    monkeypatch.setattr(APP_CONFIG, "use_reasoning_moderation", True)
    monkeypatch.setattr(APP_CONFIG, "moderation_model", "judge")
    monkeypatch.setattr(APP_CONFIG, "moderation_rubric", "rubric")


async def test_reasoning_refuse(mock_llm, monkeypatch):
    _enable_reasoning(monkeypatch)
    mock_llm.return_value = '{"decision":"refuse","category":"floor","reasoning":"no"}'
    result = await check_input("something")
    assert result.decision == SafetyDecision.UNSAFE
    assert result.categories == ["floor"]
    assert result.reasoning == "no"


async def test_reasoning_allow(mock_llm, monkeypatch):
    _enable_reasoning(monkeypatch)
    mock_llm.return_value = '{"decision":"allow","category":"","reasoning":"good faith"}'
    result = await check_output("a piece", "make the critique harsher")
    assert result.decision == SafetyDecision.SAFE


async def test_reasoning_malformed_errs_open(mock_llm, monkeypatch):
    _enable_reasoning(monkeypatch)
    mock_llm.return_value = "not json"
    result = await check_input("something")
    # Parse failure must not manufacture an spurious refusal.
    assert result.decision == SafetyDecision.SAFE


def _enable_floor_and_reasoning(monkeypatch):
    from config.loader import APP_CONFIG
    _enable_reasoning(monkeypatch)
    # Configure the Tier-1 binary hard floor too.
    monkeypatch.setattr(APP_CONFIG, "guardrail_model", "floor-classifier")
    monkeypatch.setattr(APP_CONFIG, "input_guardrail_prompt", "floor prompt")
    monkeypatch.setattr(APP_CONFIG, "output_guardrail_prompt", "floor prompt")


async def test_hard_floor_trips_short_circuits_reasoning(mock_llm, monkeypatch):
    _enable_floor_and_reasoning(monkeypatch)
    # Binary floor returns unsafe; reasoning must NOT be consulted.
    mock_llm.side_effect = ["unsafe\nS1"]
    result = await check_input("an always-refuse request")
    assert result.decision == SafetyDecision.UNSAFE
    assert result.categories == ["S1"]
    assert mock_llm.await_count == 1  # reasoning judge never called


async def test_hard_floor_passes_then_reasoning_refuses(mock_llm, monkeypatch):
    _enable_floor_and_reasoning(monkeypatch)
    mock_llm.side_effect = ["safe", '{"decision":"refuse","reasoning":"borderline"}']
    result = await check_output("a piece", "steer it")
    assert result.decision == SafetyDecision.UNSAFE
    assert mock_llm.await_count == 2


async def test_hard_floor_passes_then_reasoning_allows(mock_llm, monkeypatch):
    _enable_floor_and_reasoning(monkeypatch)
    mock_llm.side_effect = ["safe", '{"decision":"allow","reasoning":"ok"}']
    result = await check_input("an ordinary request")
    assert result.decision == SafetyDecision.SAFE
    assert mock_llm.await_count == 2
