import logging
from typing import Annotated, Any
from uuid import UUID

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from core.settings import Settings, get_settings

logger = logging.getLogger(__name__)

_bearer = HTTPBearer()

# Supabase signs user access tokens with an asymmetric ES256 key. The public
# half is published as a JWKS; cache it so we fetch it at most once per process
# (plus a refresh if a token presents an unknown kid — i.e. key rotation).
_jwks_cache: dict[str, Any] | None = None


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def _get_jwks(settings: Settings, *, force_refresh: bool = False) -> dict[str, Any]:
    global _jwks_cache
    if _jwks_cache is not None and not force_refresh:
        return _jwks_cache

    url = f"{settings.supabase_url}/auth/v1/.well-known/jwks.json"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        _jwks_cache = resp.json()
    return _jwks_cache


def _has_kid(jwks: dict[str, Any], kid: str | None) -> bool:
    return any(k.get("kid") == kid for k in jwks.get("keys", []))


async def get_current_user_id(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> UUID:
    """
    FastAPI dependency. Verifies the Supabase JWT and returns the user's UUID.
    Raises 401 if the token is missing, expired, or invalid.
    """
    token = credentials.credentials

    try:
        kid = jwt.get_unverified_header(token).get("kid")
    except JWTError:
        raise _unauthorized()

    try:
        jwks = await _get_jwks(settings)
        # Token presents a kid we have not seen — the signing key may have
        # rotated, so refetch the JWKS once before giving up.
        if kid and not _has_kid(jwks, kid):
            jwks = await _get_jwks(settings, force_refresh=True)
    except httpx.HTTPError:
        logger.exception("Could not fetch Supabase JWKS")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Auth verification temporarily unavailable",
        )

    try:
        payload = jwt.decode(
            token,
            jwks,
            algorithms=["ES256"],
            options={"verify_aud": False, "verify_iss": False},
        )
        user_id: str | None = payload.get("sub")
        if not user_id:
            raise ValueError("Missing sub claim")
        return UUID(user_id)
    except (JWTError, ValueError):
        raise _unauthorized()
