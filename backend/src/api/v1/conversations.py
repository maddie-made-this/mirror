from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from api.deps import CurrentUserID
from schemas.message import (
    ConversationCreate,
    ConversationPatch,
    ConversationSummary,
    ConversationTurn,
)
from schemas.panels import PieceFramePatch
from schemas.turn import TakeItem
from services import graph_service
from services import history as history_service

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("", response_model=list[ConversationSummary])
async def list_conversations(
    current_user_id: CurrentUserID,
) -> list[ConversationSummary]:
    """All conversations for the authenticated user, newest first."""
    rows = await history_service.list_conversations(current_user_id)
    return [ConversationSummary(**r) for r in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_conversation(
    body: ConversationCreate,
    current_user_id: CurrentUserID,
) -> dict:
    """
    Create a parent conversation explicitly. Used for the analytic branch
    (session_type='analytic', parent_conversation_id set) and any flow that
    needs the row before the first turn.
    """
    conv_id = await history_service.create_conversation(
        current_user_id,
        session_type=body.session_type,
        parent_conversation_id=body.parent_conversation_id,
        title=body.title,
    )
    return {"conversation_id": str(conv_id)}


@router.patch("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def patch_conversation(
    conversation_id: UUID,
    body: ConversationPatch,
    current_user_id: CurrentUserID,
) -> None:
    """Pin/unpin or rename a conversation owned by the caller."""
    updated = await history_service.update_conversation(
        current_user_id,
        conversation_id,
        pinned=body.pinned,
        title=body.title,
    )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )


@router.get("/{conversation_id}/turns", response_model=list[ConversationTurn])
async def get_turns(
    conversation_id: UUID,
    current_user_id: CurrentUserID,
    limit: int = 50,
) -> list[ConversationTurn]:
    """Chronological chat history for one conversation, scoped to the caller."""
    return await history_service.get_recent_turns(
        conversation_id, current_user_id, limit
    )


@router.get(
    "/{conversation_id}/beat/{beat_group_id}/takes",
    response_model=list[TakeItem],
)
async def get_beat_takes(
    conversation_id: UUID,
    beat_group_id: UUID,
    current_user_id: CurrentUserID,
) -> list[TakeItem]:
    """P1.4: all takes in a beat group (oldest first) for the '‹ 1/3 ›' variant picker."""
    takes = await history_service.get_beat_takes(
        current_user_id, conversation_id, beat_group_id
    )
    return [TakeItem(**t) for t in takes]


@router.get("/{conversation_id}/piece-state")
async def get_piece_frame(
    conversation_id: UUID,
    current_user_id: CurrentUserID,
) -> dict:
    """'This story' panel (P2.1): the conversation's piece_frame (who/where/beat), or an
    empty shape before it's established. Read-only companion to the PATCH below."""
    state = await history_service.get_conversation_piece_frame(
        conversation_id, current_user_id
    )
    return {"piece_frame": state or {}}


@router.patch("/{conversation_id}/piece-state", status_code=status.HTTP_204_NO_CONTENT)
async def patch_piece_frame(
    conversation_id: UUID,
    body: PieceFramePatch,
    current_user_id: CurrentUserID,
) -> None:
    """
    Correct the 'This story' panel (P2.1): write piece_frame back AND, when the client
    names the concepts the correction touched, stamp them as a volunteered correction
    (high-value signal). NOTE: piece_frame is free text with no node handles, so the slugs
    must be supplied by the client — auto-derivation is intentionally not attempted.
    """
    await history_service.set_conversation_piece_frame(
        conversation_id, current_user_id, body.piece_frame
    )
    if body.concept_slugs:
        await graph_service.stamp_provenance(
            current_user_id, body.concept_slugs,
            source="conversation", elicited="volunteered",
        )
        await graph_service.reinforce_nodes(current_user_id, body.concept_slugs)
