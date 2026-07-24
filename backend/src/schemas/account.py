"""Account schemas (product reshape P5.1)."""
from pydantic import BaseModel, Field


class AccountFlags(BaseModel):
    is_dev: bool = False
    training_consent: bool = False


class AccountSettingsPatch(BaseModel):
    """Currently only the cross-user-training consent toggle is user-settable."""
    training_consent: bool


class DeleteAccountRequest(BaseModel):
    """Lightweight confirmation guard for the irreversible delete. The JWT already
    authenticates the caller; production should add a real re-auth step on top."""
    confirm: str = Field(description="Must equal 'DELETE' to proceed.")


class WipeModelRequest(BaseModel):
    """Confirmation guard for the model wipe (graph + vectors; account and chats
    kept). Distinct phrase from account deletion so the two destructive actions
    can never be confused at the call site."""
    confirm: str = Field(description="Must equal 'WIPE' to proceed.")
