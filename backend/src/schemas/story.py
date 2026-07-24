"""Story document schemas (product reshape §2 / P1.1). The story row is metadata only;
its content is DERIVED from the source conversation's canon turns at read time."""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class StoryCreate(BaseModel):
    source_conversation_id: UUID
    title: str | None = None


class StoryMetaPatch(BaseModel):
    title: str | None = None
    pinned: bool | None = None
    cover_state: dict | None = None


class StoryBeat(BaseModel):
    """One canon beat, back-referencing its turn (for edit / reopen-in-chat)."""
    turn_id: UUID
    text: str


class StorySummary(BaseModel):
    id: UUID
    source_conversation_id: UUID
    title: str | None = None
    pinned: bool = False
    cover_state: dict = Field(default_factory=dict)
    color_map: dict = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class StoryDetail(StorySummary):
    beats: list[StoryBeat] = Field(default_factory=list)
