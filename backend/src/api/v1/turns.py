"""Turn-level operations (product reshape P1.4 variant compare + P1.5 edit-as-canon).

Turns are addressed by message_id (the app-facing serverId). Both surfaces — the document
editor and the chat editor — call the same PATCH endpoint; the variant picker flips canon
within a beat group and logs the kept-vs-rejected pair for the fine-tune dataset.
"""
from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from api.deps import CurrentUserID
from schemas.thinking import ThinkingView
from schemas.turn import EditTextRequest, PickRequest
from services import actions
from services import history as history_service
from services import thinking as thinking_service

router = APIRouter(prefix="/turns", tags=["turns"])


@router.patch("/{turn_id}/text", status_code=status.HTTP_204_NO_CONTENT)
async def edit_turn_text(
    turn_id: UUID,
    body: EditTextRequest,
    current_user_id: CurrentUserID,
) -> None:
    """
    Edit-as-canon (P1.5): the user's edited text becomes the kept beat, in place on the
    same row. Logs an 'edit' action carrying the pre-edit text (recoverable from the event;
    the hot turns table is not widened). Does NOT touch the interest graph.
    """
    result = await history_service.edit_turn_text(current_user_id, turn_id, body.text)
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Turn not found")
    await actions.record_action(
        current_user_id,
        result["conversation_id"],
        "edit",
        target_turn_id=turn_id,
        render_mode=result["render_mode"],
        payload={"prev_text": result["prev_text"]},
    )


@router.post("/{beat_group_id}/pick", status_code=status.HTTP_204_NO_CONTENT)
async def pick_take(
    beat_group_id: UUID,
    body: PickRequest,
    current_user_id: CurrentUserID,
) -> None:
    """
    Variant pick (P1.4): choose which take in a beat group is canon. Flips is_canon within
    the group, logs the supersede pair (kept vs the previously-canon take, with a
    training-consent snapshot) and the canonize/decanonize action events.
    """
    result = await history_service.pick_take(current_user_id, beat_group_id, body.turn_id)
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Take not found in beat group")

    conversation_id = result["conversation_id"]
    render_mode = result["render_mode"]
    rejected = result["rejected"]

    await actions.record_action(
        current_user_id, conversation_id, "canonize",
        target_turn_id=result["kept"], render_mode=render_mode,
    )
    # A pick that changes canon supersedes the prior take: log the pair + the decanonize.
    if rejected is not None:
        await actions.record_action(
            current_user_id, conversation_id, "decanonize",
            target_turn_id=rejected, render_mode=render_mode,
        )
        await actions.record_supersede_pair(
            current_user_id, conversation_id,
            kept_turn_id=result["kept"], rejected_turn_id=rejected,
            render_mode=render_mode, retry_note=body.retry_note,
        )


@router.get("/{turn_id}/thinking", response_model=ThinkingView)
async def get_thinking(
    turn_id: UUID,
    current_user_id: CurrentUserID,
) -> ThinkingView:
    """
    'Mirror's thinking' click-through (P2.4): the REAL artifacts behind a turn — nodes,
    interpretations, steering objective, a curated slice of the piece brief, and the
    elements it offered. The narrativized summary (if any) sits on top; never theater.
    """
    view = await thinking_service.get_thinking(current_user_id, turn_id)
    if view is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Turn not found")
    return ThinkingView(**view)
