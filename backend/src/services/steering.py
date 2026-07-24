"""
Steering selection (B5 flows 3 & 4, interest-model §5-§6) — "what does the graph
tell me to do next that the user hasn't raised?"

Retrieval (build_graph_context) is REACTIVE; steering lets the engine LEAD. Each
turn we rank candidates from graph state and return ONE soft objective. The
intelligence lives in the graph query, not the model: a mediocre renderer can
*execute* an objective it could never *generate* (§5C).

v2, per the checkpoint model:
- The prediction engines feed it: function-probe candidates first (§5.1 —
  same-need/different-surface, error-corrected by uptake), similarity probes for
  motifs with no credible function (§5.2). Probes carry an `element` so the
  uptake loop can judge them.
- Gates filter everything: excluded_topic regions and active soft gates are never
  targeted (§3); a guarded session (§4 gate position) suspends steering entirely —
  follow and soothe.
- Elicitation routes by origin suspicion (§6): a conditioned-leaning motif
  gets an EPISODIC probe ("when did you first notice…"), a function-shaped one
  gets a PROPOSITIONAL probe ("what does it let them stop worrying about").

The objective is injected wrapped in the narrative-appropriateness gate (B6,
llm/layers/steering.py) — a standing curiosity, pursued only at natural openings, never
mid-thought. Selection is cheap: Neo4j/Postgres reads, no LLM call.
"""
import logging
from uuid import UUID

from services import gates, graph_service, uptake

logger = logging.getLogger(__name__)


async def _first_unoffered(user_id: UUID, candidates: list[str]) -> str | None:
    """The first candidate never yet offered to this user (passed ones stay retired)."""
    if not candidates:
        return None
    try:
        offered = await uptake.get_offered_elements(user_id, candidates)
    except Exception:
        logger.warning("offer history unavailable; offering first candidate")
        offered = set()
    for c in candidates:
        if c not in offered:
            return c
    return None


async def select_objective(
    user_id: UUID,
    session_number: int,
    *,
    gate_position: str = "neutral",
) -> dict | None:
    """
    Rank steering candidates and return the top one, or None when the graph
    offers nothing worth leading on (or the session doesn't want leading).

    Returns {"objective": <soft objective text for the prompt>,
             "tag": <compact type:ref for the turn record + feedback linkage>,
             "element": <concrete offered element, when a probe>          (optional),
             "node_id": <graph node the element maps to>                  (optional),
             "interpretation_id": <function reading under test>           (optional)}.

    Priority:
      1. function probe (§5.1 — the primary engine; tests a credible hypothesis)
      2. high-salience unknown — elicitation, probe-type routed by origin (§6)
      3. an available bridge (flow 4 — the uncanny structural surprise)
      4. similarity probe (§5.2 — neighborhood for the conditioned accidents)
      5. an untested low-confidence interpretation (confirm/refine it)
      6. a dormant node that once mattered (resurface it)
    """
    # §4: below their own baseline this session → no leading at all.
    if gate_position == "guarded":
        return None

    try:
        gated = await gates.get_active_gate_node_ids(user_id)
    except Exception:
        logger.warning("gate read failed; steering with empty gate set")
        gated = set()

    # 1. Function probe — same need, different surface; the reaction loop judges.
    probes = await graph_service.get_function_probe_candidates(user_id)
    for p in probes:
        node_ids = [n for n in p.get("node_ids") or []]
        if any(n in gated for n in node_ids):
            continue
        element = await _first_unoffered(user_id, list(p.get("candidates") or []))
        if not element:
            continue
        return {
            "tag": f"function_probe:{p['id']}",
            "element": element,
            "node_id": node_ids[0] if node_ids else None,
            "interpretation_id": p["id"],
            "objective": (
                f"A standing hypothesis about them: {p['statement']} An adjacent "
                f'probe could test it — weave in "{element}": a different surface '
                f"for the same need. If they take it up, the hypothesis is right; "
                f"if it passes by, that is signal too."
            ),
        }

    # 2. High-salience unknown — elicitation, probe-type routed by origin suspicion.
    highs = await graph_service.get_high_salience_unknowns(user_id)
    highs = [n for n in highs if n.id not in gated]
    if highs:
        n = highs[0]
        origin = await graph_service.get_node_origin_reading(user_id, n.id)
        episodic_leaning = bool(
            origin
            and origin["conditioned"] > max(origin["instinctual"], origin["reframing"])
        )
        if episodic_leaning:
            objective = (
                f'The user returns repeatedly to "{n.name}", and its origin looks '
                f"learned from experience. At a natural opening, a soft EPISODIC "
                f"probe could help: when did they first notice this — was there "
                f"a moment or an image it began with?"
            )
        else:
            objective = (
                f'The user returns repeatedly to "{n.name}", but what it really does '
                f"for them isn't understood yet. A PROPOSITIONAL probe at a "
                f"natural opening: what does it let them stop carrying or stop "
                f"worrying about — what feeling is underneath?"
            )
        return {
            "tag": f"high_salience_unknown:{n.id}",
            "element": n.name,
            "node_id": n.id,
            "objective": objective,
        }

    # 3. Bridge-informed surprise (flow 4).
    overlays = await graph_service.get_overlay_interpretations(
        user_id, min_confidence=0.6, limit=5
    )
    bridges = [o for o in overlays if o.get("kind") == "bridge"]
    if bridges:
        b = bridges[0]
        return {
            "tag": f"bridge:{b['id']}",
            "objective": (
                f"Two parts of them are secretly connected — {b['statement']} "
                f"Weaving an element of one into a piece rooted in the other could "
                f"land uncannily."
            ),
        }

    # 4. Similarity probe — neighborhood prediction for the no-function motifs.
    sim_nodes = await graph_service.get_similarity_probe_nodes(user_id)
    for s in sim_nodes:
        if s["id"] in gated:
            continue
        element = await _first_unoffered(user_id, list(s.get("candidates") or []))
        if not element:
            continue
        return {
            "tag": f"similarity_probe:{s['id']}",
            "element": element,
            "node_id": s["id"],
            "objective": (
                f'"{s["name"]}" reliably engages them, and its neighborhood is '
                f'unmapped. Weaving in "{element}" — adjacent in feel — would show '
                f"whether the interest extends there."
            ),
        }

    # 5. Untested "maybe" — a gentle opening could confirm or refine the read.
    maybes = await graph_service.get_untested_maybe_interpretations(user_id)
    if maybes:
        m = maybes[0]
        return {
            "tag": f"untested_maybe:{m['id']}",
            "interpretation_id": m["id"],
            "objective": (
                f"An untested read about them: {m['statement']} A light, natural "
                f"opening could confirm or refine it."
            ),
        }

    # 6. Dormant-but-salient — resurface something that mattered.
    dormant = await graph_service.get_dormant_nodes(user_id, session_number)
    dormant = [
        n for n in dormant
        if (n.salience_score_mean or n.salience_score or 0) > 0.3 and n.id not in gated
    ]
    if dormant:
        n = dormant[0]
        return {
            "tag": f"dormant:{n.id}",
            "element": n.name,
            "node_id": n.id,
            "objective": (
                f'"{n.name}" mattered to them before but hasn\'t come up lately — '
                f"there's an opening to revisit it."
            ),
        }

    return None
