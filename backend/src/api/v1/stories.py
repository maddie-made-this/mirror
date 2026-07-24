from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from api.deps import CurrentUserID
from schemas.story import StoryCreate, StoryDetail, StoryMetaPatch, StorySummary
from services import stories as stories_service

router = APIRouter(prefix="/stories", tags=["stories"])


@router.post("", response_model=StorySummary)
async def create_story(body: StoryCreate, current_user_id: CurrentUserID) -> StorySummary:
    """'Save as story' — compile a conversation's canon into a titled, continuable
    document. It auto-updates as beats canonize (content is DERIVED, never copied)."""
    return await stories_service.create_story(
        current_user_id, body.source_conversation_id, body.title
    )


@router.get("", response_model=list[StorySummary])
async def list_stories(current_user_id: CurrentUserID) -> list[StorySummary]:
    """The Library — the retention surface (the reason to come back tomorrow)."""
    return await stories_service.list_stories(current_user_id)


@router.get("/{story_id}", response_model=StoryDetail)
async def get_story(story_id: UUID, current_user_id: CurrentUserID) -> StoryDetail:
    summary = await stories_service.get_story(story_id, current_user_id)
    if summary is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Story not found")
    beats = await stories_service.render_story(story_id, current_user_id)
    return StoryDetail(**summary.model_dump(), beats=beats)


@router.patch("/{story_id}", response_model=StorySummary)
async def patch_story(
    story_id: UUID, body: StoryMetaPatch, current_user_id: CurrentUserID
) -> StorySummary:
    updated = await stories_service.update_story_meta(
        story_id, current_user_id,
        title=body.title, pinned=body.pinned, cover_state=body.cover_state,
    )
    if updated is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Story not found")
    return updated
