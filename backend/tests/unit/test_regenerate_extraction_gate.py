"""
A chip-driven turn must never feed the interest graph.

When the user taps a reaction chip, the message sent to the backend is the chip's
STEERING INSTRUCTION ("redo this beat but pick a specific track", "move to the
next phase"), not a disclosure about themselves. Extraction ran on it
unconditionally, so the user's own UI steering was written back into the graph as
self-report — the phrase "stop arguing in the abstract" became an `avoidance` node
claiming the user avoids abstract argumentation.

Two flags mark these turns: `regenerate_of` (a redo) and `continue_piece` (an
advance/wildcard chip, which redoes nothing). The gate lives inside
`_enqueue_extraction` rather than at its call sites, so a future caller cannot
reintroduce the bug by forgetting to check.
"""
from uuid import uuid4

import pytest

from api.v1 import messages as messages_api
from schemas.graph import GraphContext
from schemas.message import MessageRequest


def _args(regenerate_of=None, continue_piece=False):
    """The positional payload `_enqueue_extraction` takes, with only the fields
    that matter to the gate populated."""
    body = MessageRequest(
        message="Redo this beat but stop arguing in the abstract.",
        conversation_id=uuid4(),
        client_message_id=uuid4(),
        regenerate_of=regenerate_of,
        continue_piece=continue_piece,
    )
    return dict(
        body=body,
        user_id=uuid4(),
        session_number=1,
        message_id=uuid4(),
        graph_ctx=GraphContext(relevant_nodes=[], relevant_edges=[]),
        active_predicates=[],
        display_name="Tester",
        self_node_id="self:tester",
        steer=None,
    )


@pytest.mark.asyncio
async def test_regenerate_does_not_enqueue_extraction(monkeypatch):
    enqueued = []

    async def fake_enqueue(job):
        enqueued.append(job)

    monkeypatch.setattr(messages_api.extraction_queue, "enqueue", fake_enqueue)

    a = _args(regenerate_of=uuid4())
    await messages_api._enqueue_extraction(
        a["body"], a["user_id"], a["session_number"], a["message_id"],
        a["graph_ctx"], a["active_predicates"], a["display_name"],
        a["self_node_id"], a["steer"],
    )
    assert enqueued == [], "a regenerate's steering instruction reached extraction"


@pytest.mark.asyncio
async def test_advance_chip_does_not_enqueue_extraction(monkeypatch):
    """An advance/wildcard chip carries continue_piece but NOT regenerate_of — it
    redoes nothing, it moves the piece forward. Its instruction is still engine
    steering, so it must not reach extraction either."""
    enqueued = []

    async def fake_enqueue(job):
        enqueued.append(job)

    monkeypatch.setattr(messages_api.extraction_queue, "enqueue", fake_enqueue)

    a = _args(regenerate_of=None, continue_piece=True)
    await messages_api._enqueue_extraction(
        a["body"], a["user_id"], a["session_number"], a["message_id"],
        a["graph_ctx"], a["active_predicates"], a["display_name"],
        a["self_node_id"], a["steer"],
    )
    assert enqueued == [], "an advance chip's instruction reached extraction"


@pytest.mark.asyncio
async def test_ordinary_turn_still_enqueues_extraction(monkeypatch):
    """The other half of the invariant: gating the regenerate must not silently
    disable extraction for real user messages."""
    enqueued = []

    async def fake_enqueue(job):
        enqueued.append(job)

    monkeypatch.setattr(messages_api.extraction_queue, "enqueue", fake_enqueue)

    a = _args(regenerate_of=None)
    await messages_api._enqueue_extraction(
        a["body"], a["user_id"], a["session_number"], a["message_id"],
        a["graph_ctx"], a["active_predicates"], a["display_name"],
        a["self_node_id"], a["steer"],
    )
    assert len(enqueued) == 1
