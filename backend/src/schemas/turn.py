"""Turn-level operation schemas (product reshape §3.2/§3.3 — P1.4 variant compare +
P1.5 edit-as-canon). Turns are identified by message_id (the app-facing serverId), the
same key supersede/feedback use."""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class EditTextRequest(BaseModel):
    """Edit-as-canon (P1.5): the user's edited text becomes the kept beat in place."""
    text: str = Field(max_length=20000)


class PickRequest(BaseModel):
    """Variant pick (P1.4): choose which take in a beat group is canon."""
    turn_id: UUID  # message_id of the chosen take
    retry_note: str | None = None  # the note that drove the reroll (its canonical home, P0.4)


class TakeItem(BaseModel):
    """One take (sibling) within a beat group, for the '‹ 1/3 ›' variant picker."""
    turn_id: UUID  # message_id
    text: str
    is_canon: bool
    created_at: datetime | None = None
