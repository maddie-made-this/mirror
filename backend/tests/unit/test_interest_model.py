"""
Interest-model acceptance tests (build_interest_model.md §9), exercised over the
pure logic cores + schema + parsers — the parts that encode the model's laws.
"""
from uuid import uuid4

from schemas.interest import GatePosition, DepthRamp
from schemas.interpretation import Interpretation, InterpretationKind
from services.consolidation import motif_score
from services.dynamics import ema, gate_from, ramp_from
from services.interpretation import _parse_motif_readings, departure_score
from services.uptake import judge_uptake, should_gate


# --------------------------------------------------------------------------- #
# §9.1 — even-baseline / intense-exception: the exception is function-likely
# BECAUSE it departs from the user's own baseline. (Two regions are two nodes by
# construction — extraction never averages distinct configurations.)
# --------------------------------------------------------------------------- #

def test_departure_flags_the_exception():
    # User's norm: warm, mildly-salient everyday interest.
    user_salience, user_valence = 0.25, 0.6
    # The exception: intense and affectively departing from the norm.
    exception = departure_score(0.85, -0.2, user_salience, user_valence)
    # An on-baseline node: barely departs.
    on_norm = departure_score(0.3, 0.55, user_salience, user_valence)
    assert exception > on_norm
    assert exception > 0.5  # clearly prioritized for function reflection


# --------------------------------------------------------------------------- #
# §9.2 — "let's revisit that topic I said I wasn't into": gates are conditions, not
# traits. Uptake on the gated node reads as taken (the lift path); gates only
# form from non-uptake WHILE ENGAGED — a guarded session proves nothing.
# --------------------------------------------------------------------------- #

def test_uptake_taken_by_node_overlap():
    assert judge_uptake("chasing the anomaly", "trigger:anomaly", "yes, that one", {"trigger:anomaly"}) == "taken"


def test_uptake_taken_by_phrase_and_word_overlap():
    assert judge_uptake("a first-principles derivation", None, "the first-principles idea — yes", set()) == "taken"
    # Half the content words is enough ("worked", "example").
    assert (
        judge_uptake(
            "an explicit worked example", None,
            "I want the worked example, step by step", set(),
        )
        == "taken"
    )


def test_uptake_passed_when_ignored():
    assert judge_uptake("a first-principles derivation", None, "tell me more about the history angle", set()) == "passed"
    assert judge_uptake("", None, "anything", set()) == "passed"


def test_gate_requires_three_passes_and_engagement():
    assert should_gate(3, clearly_engaged=True)
    assert not should_gate(2, clearly_engaged=True)
    # Disengagement is not evidence about the element — no gate from a guarded session.
    assert not should_gate(5, clearly_engaged=False)


def test_aversion_moves_only_on_the_users_own_explicit_reversal():
    from services.gates import is_explicit_reversal

    # Their words, strongly positive → the excluded_topic can be lifted.
    assert is_explicit_reversal("user_stated", 0.7)
    # Engine inference can NEVER move an excluded_topic, however positive it looks.
    assert not is_explicit_reversal("llm_inferred", 0.95)
    # Mild warmth toward an averted region is not a reversal.
    assert not is_explicit_reversal("user_stated", 0.3)


# --------------------------------------------------------------------------- #
# §9.3 — consolidation: repetition (deep-ramp weighted) makes an autonomous
# motif; the reframing link survives in the reading set (parser keeps both
# the belief and the mechanism, linked).
# --------------------------------------------------------------------------- #

def test_motif_score_floor_and_growth():
    assert motif_score(3, 0, 1, 0.9) == 0.0          # too few repetitions
    assert motif_score(6, 0, 2, 0.3) == 0.0          # not charged enough
    grown = motif_score(6, 0, 2, 0.6)
    assert 0 < grown <= 0.95
    deeper = motif_score(6, 3, 2, 0.6)               # same node, deep-ramp reps
    assert deeper > grown                               # §2.2: deep moments stamp harder
    assert motif_score(40, 20, 30, 1.0) <= 0.95       # only the user saturates anything


def test_parser_links_subversion_to_belief_and_keeps_both():
    uid, node = uuid4(), "dynamic:tracing-to-foundations"
    items = [
        {
            "kind": "belief",
            "statement": "understanding a thing requires taking it apart first",
            "category": "",
            "confidence": 0.6,
            "what_would_change_this": "grasping something whole without dismantling it",
            "presses_on": ["accepting a summary", "trusting a black box"],
            "context_sensitivity": 0.8,
        },
        {
            "kind": "reframing",
            "statement": "a teardown makes the structure explicit — the mechanism shows itself",
            "confidence": 0.55,
            "what_would_change_this": "the interest surviving cases where nothing is taken apart",
            "reframes_belief": "understanding a thing requires taking it apart first",
        },
        {
            "kind": "origin",
            "statement": "likely grew from the workaround, now autonomous",
            "confidence": 0.5,
            "what_would_change_this": "an early formative memory surfacing",
            "origin_distribution": {
                "instinctual": 0.1,
                "learned_episodic": 0.2,
                "reframing_consolidated": 0.7,
            },
            "origin_episode": "",
        },
    ]
    readings = _parse_motif_readings(items, uid, node, ["m1"], [], {}, set())
    by_kind = {r.kind: r for r in readings}

    belief = by_kind[InterpretationKind.BELIEF]
    sub = by_kind[InterpretationKind.REFRAMING]
    origin = by_kind[InterpretationKind.ORIGIN]

    assert sub.reframes_belief_id == str(belief.id)        # the link survives
    assert belief.presses_on == ["accepting a summary", "trusting a black box"]
    assert belief.context_sensitivity == 0.8
    assert origin.origin_reframing == 0.7                  # distribution, flat-stored
    assert origin.origin_episode == ""                      # never invented
    assert all(r.what_would_change_this for r in readings)  # §7 required


def test_parser_creates_implied_belief_for_orphan_subversion():
    uid = uuid4()
    items = [
        {
            "kind": "reframing",
            "statement": "the counterexample disproves that the rule is universal",
            "confidence": 0.5,
            "what_would_change_this": "x",
            "reframes_belief": "the rule holds in every case without exception",
        }
    ]
    readings = _parse_motif_readings(items, uid, "n1", [], [], {}, set())
    kinds = [r.kind for r in readings]
    assert InterpretationKind.BELIEF in kinds and InterpretationKind.REFRAMING in kinds
    belief = next(r for r in readings if r.kind == InterpretationKind.BELIEF)
    sub = next(r for r in readings if r.kind == InterpretationKind.REFRAMING)
    assert sub.reframes_belief_id == str(belief.id)


def test_parser_skips_kinds_the_node_already_has():
    items = [
        {"kind": "function", "statement": "s", "confidence": 0.5, "what_would_change_this": "x"},
    ]
    assert _parse_motif_readings(items, uuid4(), "n1", [], ["function"], {}, set()) == []


def test_parser_dedupes_function_against_existing():
    """C1: a 'function' duplicating one the user already has (cross-node) is dropped;
    a distinct function is kept and registered so the next node can't re-add it."""
    from services import interpretation as I
    uid = uuid4()
    items = [
        {"kind": "function", "statement": "Lets them feel the frame click.", "confidence": 0.6,
         "what_would_change_this": "x"},
    ]
    existing = {I._norm_statement("lets them feel the frame click")}  # already on another node
    assert _parse_motif_readings(items, uid, "n1", [], [], {}, existing) == []

    fresh: set[str] = set()
    out = _parse_motif_readings(items, uid, "n2", [], [], {}, fresh)
    assert len(out) == 1 and out[0].kind == InterpretationKind.FUNCTION
    assert I._norm_statement("lets them feel the frame click") in fresh  # registered for next node


def test_canonical_category_drops_hallucinations():
    """C3: model categories are canonicalized to a configured entry (exact or head
    match) or dropped to '' — a hallucinated or off-list category never persists."""
    from services.interpretation import _canonical_category
    cats = ["reductive-analysis", "completionism (needing every gap closed)"]
    assert _canonical_category("reductive-analysis", cats) == "reductive-analysis"   # exact
    assert _canonical_category("COMPLETIONISM", cats).startswith("completionism") # head, normalized
    assert _canonical_category("made-up-family", cats) == ""                        # dropped
    assert _canonical_category("reductive-analysis", []) == ""                      # no list configured


# --------------------------------------------------------------------------- #
# §9.4 — deep-session depth: the ramp is functional, not stylistic. Content that
# fell flat early can land deep; deep introductions are motif-forming.
# --------------------------------------------------------------------------- #

def test_ramp_needs_both_length_and_sustained_salience():
    assert ramp_from(2, 0.9) == DepthRamp.EARLY    # high-salience but brand new — not deep
    assert ramp_from(9, 0.1) == DepthRamp.MID      # long but low-salience — engaged, not deep
    assert ramp_from(9, 0.6) == DepthRamp.DEEP     # sustained salience late = the deep zone
    assert ramp_from(4, 0.3) == DepthRamp.MID


def test_dynamics_layer_renders_a_line_per_dial():
    """The layer turns session state into prompt guidance, one line per dial that
    has a value, and drops out entirely when there is no state to read."""
    from llm.layers import dynamics as dynamics_layer
    from schemas.graph import GraphContext

    ctx = GraphContext(
        relevant_nodes=[], relevant_edges=[],
        session_state={"depth_ramp": "deep", "gate_position": "open", "frame": "real"},
    )
    text = dynamics_layer.render(ctx)
    assert text is not None
    assert "SESSION DIALS" in text
    # One bullet per dial: depth, receptivity, frame.
    assert text.count("\n- ") == 3
    assert "Deep in the session" in text

    # Guidance is about the CONVERSATION's depth — how much shared context exists —
    # never about how far the person can be pushed. These phrasings conflate the
    # two, so the layer must not reintroduce them.
    lowered = text.lower()
    for phrase in ("harder turn", "durable interest", "a step further",
                   "gratuitous", "hold every objective"):
        assert phrase not in lowered, phrase

    # No session state → the layer drops out entirely.
    empty = GraphContext(relevant_nodes=[], relevant_edges=[])
    assert dynamics_layer.render(empty) is None


def test_gate_reads_deviation_from_own_baseline():
    assert gate_from(150.0, 100.0) == GatePosition.OPEN      # above their norm
    assert gate_from(40.0, 100.0) == GatePosition.GUARDED    # well below it
    assert gate_from(100.0, 100.0) == GatePosition.NEUTRAL
    assert gate_from(150.0, 0.0) == GatePosition.NEUTRAL     # no baseline yet


async def test_guarded_session_suspends_steering():
    from services.steering import select_objective

    # Short-circuits before touching any store: a guarded session gets followed,
    # never led (§4) — no graph read, no candidate, no probe.
    assert await select_objective(uuid4(), 1, gate_position="guarded") is None


# --------------------------------------------------------------------------- #
# §7 — uncertainty machinery: schema round-trip for the typed readings
# --------------------------------------------------------------------------- #

def test_interpretation_v2_roundtrip():
    interp = Interpretation(
        user_id=uuid4(),
        statement="having the crux named for me is the compelling part",
        kind=InterpretationKind.FUNCTION,
        category="",
        what_would_change_this="a piece that builds to it and still lands",
        candidates=["a proof that closes every gap", "structure without scaffolding"],
        confidence=0.62,
    )
    dumped = interp.model_dump(mode="json", exclude={"id", "user_id"})
    # Neo4j property safety: flat primitives/arrays only — no nested dicts.
    assert all(not isinstance(v, dict) for v in dumped.values())
    restored = Interpretation(user_id=interp.user_id, **dumped)
    assert restored.candidates == interp.candidates
    assert restored.what_would_change_this == interp.what_would_change_this
    assert restored.origin_distribution == {
        "innate": 0.0, "learned_episodic": 0.0, "reframing_consolidated": 0.0,
    }


def test_trait_movement_is_ema_only():
    # One observation cannot jump the trait — a single session nudges, never sets.
    assert abs(ema(0.5, 1.0, alpha=0.2) - 0.6) < 1e-9
    assert abs(ema(0.5, 0.0, alpha=0.2) - 0.4) < 1e-9
