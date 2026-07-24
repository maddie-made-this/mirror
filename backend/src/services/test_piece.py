"""
Early test pieces (B9 / §5E).

A hesitant user can't always *articulate* what pulls at them but can *react* to something
concrete — recognition beats recall. After early exchanges yield a sparse outline,
the engine offers 1-2 short pieces that target the THINNEST / most-uncertain
dimension (a probe, not random), framed as an experience ("here's a piece…") rather
than a test. The reaction is read via the cheap check/x signal (B3): a check is
positive coverage; an x is a boundary — equally valuable.

The piece is saved as a turn that RECORDS its target (input_node_ids +
steering_objective), so the check/x credits/discredits the right dimension.
"""
from uuid import UUID

from schemas.graph import GraphContext
from services import graph_service, steering
from services.response_gen import generate_response

# Offer a test piece only while the conversation is still young (recognition beats
# recall is most useful before the user has laid out an outline themselves).
_EARLY_TURN_LIMIT = 6


async def should_offer(user_id: UUID, conversation_id: UUID, turn_count: int) -> bool:
    """Gate: early in the conversation and the graph has *some* material to target."""
    if turn_count > _EARLY_TURN_LIMIT:
        return False
    target = await steering.select_objective(user_id, session_number=0)
    return target is not None


async def generate(user_id: UUID, session_number: int) -> dict | None:
    """
    Build a short test piece targeting the thinnest dimension. Returns
    {"piece": str, "tag": str, "node_ids": list[str]} or None if there's nothing
    worth probing yet.
    """
    steer = await steering.select_objective(user_id, session_number)

    node_ids: list[str] = []
    if steer:
        target_desc = steer["objective"]
        tag = f"test_piece:{steer['tag']}"
        if steer.get("node_id"):
            node_ids = [steer["node_id"]]
    else:
        # Sparse graph: a broad, inviting opener still draws a reaction.
        target_desc = "something open-ended — a short sample to see what resonates"
        tag = "test_piece:broad"

    instruction = (
        "Offer the user a SHORT piece — under 120 words — that gently explores "
        f"{target_desc}. Present it as an experience to react to, not a question: "
        "no preamble, no asking, no framing it as a test — just the piece itself, "
        "enough to spark a quick yes/no. Keep it a probe, not a full build."
    )

    pref_nodes = await graph_service.get_preference_nodes(user_id)
    piece, _brief, _timings = await generate_response(
        instruction, GraphContext(relevant_nodes=[], relevant_edges=[]), [], pref_nodes
    )
    return {"piece": piece.strip(), "tag": tag, "node_ids": node_ids}
