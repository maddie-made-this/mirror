from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from api.deps import CurrentUserID
from schemas.interpretation import Interpretation, InterpretationRespond
from services import interpretation as interp_service

router = APIRouter(prefix="/interpretations", tags=["interpretations"])


@router.get("", response_model=list[Interpretation])
async def list_surfaceable(
    current_user_id: CurrentUserID,
    limit: int = 5,
) -> list[Interpretation]:
    """
    Confident, not-yet-shown interpretations to surface to the user. Fetching
    marks them surfaced so they aren't re-shown on every poll.
    """
    return await interp_service.get_surfaceable(current_user_id, limit=limit)


@router.post("/{interpretation_id}/respond", status_code=status.HTTP_204_NO_CONTENT)
async def respond(
    interpretation_id: UUID,
    body: InterpretationRespond,
    current_user_id: CurrentUserID,
) -> None:
    """
    Record affirm/reject/qualify. This endpoint IS the production efficacy test
    for the interpretation layer — the dominant confidence signal.
    """
    ok = await interp_service.respond(
        current_user_id, interpretation_id, body.response, body.note
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Interpretation not found",
        )
