from fastapi import Request
from slowapi import Limiter


def user_id_key(request: Request) -> str:
    """
    Rate-limit bucket key. Buckets per user when a Bearer token is present so one
    user can't be throttled by another sharing an IP; falls back to client IP for
    unauthenticated paths (e.g. health checks).

    The JWT signature segment is used as the bucket key — it is unique per token
    and needs no verification for bucketing purposes.
    """
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        return f"user:{auth.split('.')[-1][:32]}"
    return f"ip:{request.client.host if request.client else 'unknown'}"


# Shared limiter — imported by main.py (registration) and routers (decorators).
# Lives in its own module to avoid a circular import through main.py.
limiter = Limiter(key_func=user_id_key)
