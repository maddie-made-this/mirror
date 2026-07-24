"""Field-level encryption for the crown-jewel columns (product reshape §10.1 / P5.1).

App-layer Fernet (AES-128-CBC + HMAC) applied to the MOST sensitive free text — the
timeline / origin episodes (Phase 6) — while everything else rides at-rest encryption.
App-layer everywhere would break queryability (no Cypher filters or embeddings over
ciphertext), so this is deliberately scoped to columns the graph never traverses.

The key comes from env MIRROR_FIELD_KEY (urlsafe-base64 32 bytes). It is loaded lazily so
the app boots without it; encrypt/decrypt raise a clear error only when actually used —
which does not happen until the timeline feature (Phase 6) is enabled. Plaintext is never
logged.
"""
from functools import lru_cache

from cryptography.fernet import Fernet

from core.settings import get_settings


@lru_cache
def _fernet() -> Fernet:
    key = get_settings().mirror_field_key
    if not key:
        raise RuntimeError(
            "MIRROR_FIELD_KEY is not set — required to encrypt/decrypt crown-jewel "
            "fields. Generate one with Fernet.generate_key()."
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt(plaintext: str) -> bytes:
    """Encrypt a string to ciphertext bytes (for a bytea column). Never logged."""
    return _fernet().encrypt(plaintext.encode("utf-8"))


def decrypt(ciphertext: bytes) -> str:
    """Decrypt ciphertext bytes back to the string. Call only in the owning service."""
    return _fernet().decrypt(bytes(ciphertext)).decode("utf-8")
