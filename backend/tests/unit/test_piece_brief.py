import re
from config.loader import APP_CONFIG
from llm.prompts import build_director_messages, build_renderer_messages
from schemas.graph import GraphContext
from schemas.piece_brief import PieceBrief
from services import response_gen


def _ctx():
    return GraphContext(relevant_nodes=[], relevant_edges=[])


# --------------------------------------------------------------------------- #
# PieceBrief.parse — defensive director-output parsing
# --------------------------------------------------------------------------- #

def test_parse_fenced_with_coercions():
    raw = (
        "Here is the brief:\n```json\n"
        '{"action":"ask_then_write","question":"which part is load-bearing?",'
        '"advance_directive":"move past the framing",'
        '"do_not_repeat":"the opening claim",'          # string -> list coercion
        '"register":{"vividness":"concrete"},'  # inbound alias -> delivery
        '"piece_frame":{"subjects":"a colleague"},'
        '"pacing":"mid","hard_avoid":["speculation about real people"]}\n```\ndone'
    )
    b = PieceBrief.parse(raw)
    assert b is not None
    assert b.action == "ask_then_write"
    assert b.do_not_repeat == ["the opening claim"]
    assert b.delivery.vividness == "concrete"
    assert b.piece_frame.subjects == "a colleague"
    assert b.hard_avoid == ["speculation about real people"]


def test_parse_prose_wrapped_object():
    raw = 'Sure, here you go: {"action":"write","advance_directive":"x"} hope that helps!'
    b = PieceBrief.parse(raw)
    assert b is not None
    assert b.action == "write"
    assert b.advance_directive == "x"


def test_parse_garbage_and_empty_return_none():
    assert PieceBrief.parse("no json object here at all") is None
    assert PieceBrief.parse("") is None
    assert PieceBrief.parse("   \n  ") is None


def test_parse_non_object_field_falls_back_to_default():
    # A bare string where an object is expected is dropped, not a crash.
    b = PieceBrief.parse('{"action":"write","delivery":"vivid"}')
    assert b is not None
    assert b.delivery.vividness == ""  # default factory won


def test_parse_round_trips_to_jsonable_dict():
    b = PieceBrief.parse('{"action":"write","delivery":{"prose_density":"rich"}}')
    dumped = b.model_dump(mode="json")
    assert isinstance(dumped["delivery"], dict)
    assert dumped["delivery"]["prose_density"] == "rich"


# --------------------------------------------------------------------------- #
# Prompt builders
# --------------------------------------------------------------------------- #

def test_director_prompt_carries_the_envelope():
    msgs = build_director_messages("write me something about the counterexample", _ctx(), [], [])
    assert msgs[0]["role"] == "system"
    assert "PIECE BRIEF" in msgs[0]["content"]      # output-contract envelope present
    assert msgs[-1] == {"role": "user", "content": "write me something about the counterexample"}


def test_renderer_prompt_carries_the_brief_block():
    b = PieceBrief(
        action="write",
        advance_directive="name the mechanism",
        function_to_serve="the click of a frame that fits",
        do_not_repeat=["the opening claim"],
    )
    msgs = build_renderer_messages(b, "write me something about the counterexample", [], [])
    sys = msgs[0]["content"]
    assert "MUST ADVANCE" in sys and "name the mechanism" in sys
    assert "the click of a frame that fits" in sys
    assert "the opening claim" in sys
    assert msgs[-1] == {"role": "user", "content": "write me something about the counterexample"}


# --------------------------------------------------------------------------- #
# Split routing
# --------------------------------------------------------------------------- #

def test_split_routing_respects_flag_and_excludes_analytic(monkeypatch):
    monkeypatch.setattr(APP_CONFIG, "use_director_split", False)
    assert response_gen._split_on("primary") is False

    monkeypatch.setattr(APP_CONFIG, "use_director_split", True)
    assert response_gen._split_on("primary") is True
    # The analytic branch is director-only (single-model on the frontier tier),
    # never the two-call split.
    assert response_gen._split_on("analytic") is False


def test_fallback_brief_still_advances():
    fb = response_gen._fallback_brief()
    assert fb.action == "write"
    assert fb.advance_directive.strip()  # non-empty anti-loop directive


def test_fallback_brief_carries_forward_prev():
    prev = {
        "action": "ask",
        "question": "which part is load-bearing?",
        "do_not_repeat": ["the opening claim", "the framing"],
        "piece_frame": {"subjects": "a colleague", "context": "a review meeting"},
    }
    fb = response_gen._fallback_brief(prev)
    # forces advancement...
    assert fb.action == "write"
    assert fb.question is None
    assert "do NOT restate" in fb.advance_directive
    # ...but keeps the established piece_frame + anti-loop list
    assert fb.piece_frame.subjects == "a colleague"
    assert fb.piece_frame.context == "a review meeting"
    assert fb.do_not_repeat == ["the opening claim", "the framing"]


# --------------------------------------------------------------------------- #
# Renderer anti-loop repetition detection
# --------------------------------------------------------------------------- #

def test_repetition_ratio_detects_verbatim_loop():
    beat = (
        "The argument doesn't hold. The premise doesn't hold. The whole thing collapses "
        "the moment you push on the one claim it was quietly resting its weight on."
    )
    # identical -> ~1.0 (well over threshold)
    assert response_gen._repetition_ratio(beat, beat) > 0.9
    # a genuinely new beat -> low overlap
    fresh = "She sets the counterexample down between them and waits for it to do the work."
    assert response_gen._repetition_ratio(fresh, beat) < response_gen._REPEAT_THRESHOLD


def test_repetition_ratio_empty_inputs():
    assert response_gen._repetition_ratio("", "anything") == 0.0
    assert response_gen._repetition_ratio("anything", "") == 0.0


def test_every_arc_position_the_prompt_offers_round_trips():
    """The director prompt enumerates arc_position values; the schema constrains
    them with a Literal. If the two drift, PieceBrief.parse raises, the exception
    is swallowed, and the ENTIRE brief is discarded — not just that one field —
    so the turn silently falls back. This asserts the two stay in sync."""
    import json as _json
    from config.loader import APP_CONFIG

    allowed = PieceBrief.model_fields["arc_position"].annotation.__args__
    for value in allowed:
        raw = _json.dumps({"action": "write", "advance_directive": "x",
                           "arc_position": value})
        parsed = PieceBrief.parse(raw)
        assert parsed is not None, f"{value!r} does not parse"
        assert parsed.arc_position == value

    # ...and every arc value the prompt text QUOTES is one the schema accepts.
    # Match quoted tokens only: a bare substring check trips on "speak"/"peak".
    envelope = APP_CONFIG.director_envelope_text + APP_CONFIG.author_director_envelope_text
    quoted = set(re.findall(r'"(\w+)"', envelope))
    stale = quoted & {"escalation", "peak"}
    assert not stale, f"prompt still offers {sorted(stale)}, which the schema rejects"
