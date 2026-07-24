"""Account endpoints (product reshape P5.1): flags for debug gating, the training-consent
toggle, and the irreversible delete-my-account job."""
from fastapi import APIRouter, HTTPException, status

from api.deps import CurrentUserID
from schemas.account import (
    AccountFlags,
    AccountSettingsPatch,
    DeleteAccountRequest,
    WipeModelRequest,
)
from services import account as account_service
from services import account_delete
from services import models

router = APIRouter(prefix="/account", tags=["account"])


@router.get("/models")
async def list_models() -> dict:
    """The selectable response models. Server-owned so the picker can never offer
    an id the backend would reject — see services/models.py."""
    return {"models": models.catalogue()}


@router.get("/me", response_model=AccountFlags)
async def get_me(current_user_id: CurrentUserID) -> AccountFlags:
    """Per-user flags: is_dev (gates the debug panel) + training_consent."""
    return AccountFlags(**await account_service.get_account_flags(current_user_id))


@router.patch("/settings", response_model=AccountFlags)
async def patch_settings(
    body: AccountSettingsPatch, current_user_id: CurrentUserID
) -> AccountFlags:
    """Set the cross-user-training consent (opt-in). Per-user learning is always on."""
    await account_service.set_training_consent(current_user_id, body.training_consent)
    return AccountFlags(**await account_service.get_account_flags(current_user_id))


@router.post("/wipe-model")
async def wipe_model(
    body: WipeModelRequest, current_user_id: CurrentUserID
) -> dict:
    """
    Erase the user's MODEL — their Neo4j subgraph and Qdrant vectors — while keeping
    conversations, feedback, telemetry, and the account itself. The graph rebuilds
    from future conversation (the self-node re-bootstraps on the next message).
    Irreversible for the graph; requires confirm='WIPE'.
    """
    if body.confirm != "WIPE":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Confirmation phrase required to wipe the model."
        )
    result = await account_delete.wipe_model(current_user_id)
    return {"wiped": all(v == "ok" for v in result.values()), "stores": result}


@router.post("/delete")
async def delete_account(
    body: DeleteAccountRequest, current_user_id: CurrentUserID
) -> dict:
    """
    Hard-delete the account across Postgres, Neo4j, Qdrant, and the Supabase auth identity
    (P5.1). Irreversible. Requires confirm='DELETE'. Backups expire ≤30 days.
    """
    if body.confirm != "DELETE":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Confirmation phrase required to delete the account."
        )
    result = await account_delete.delete_user(current_user_id)
    return {"deleted": True, "stores": result}
