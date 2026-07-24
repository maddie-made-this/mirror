from typing import Annotated
from uuid import UUID

from fastapi import Depends

from core.auth import get_current_user_id

CurrentUserID = Annotated[UUID, Depends(get_current_user_id)]
