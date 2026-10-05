"""Symmetric encryption helpers for at-rest secrets (e.g. git access tokens).

The Fernet key is derived from ``SECRET_KEY`` using HKDF-SHA256, so rotating the
application secret invalidates previously stored tokens (they must be re-entered)
— which is the intended, fail-closed behaviour.
"""
from __future__ import annotations

import base64

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import settings
from app.core.errors import ConfigurationError

_INFO = b"devforge.secret-encryption.v1"


def _fernet() -> Fernet:
    if not settings.secret_key or settings.secret_key.startswith("change-me"):
        raise ConfigurationError(
            "SECRET_KEY is not configured; refusing to encrypt/decrypt stored secrets."
        )
    key = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=b"devforge", info=_INFO
    ).derive(settings.secret_key.encode("utf-8"))
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a secret for storage. Returns a URL-safe token."""
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(token: str) -> str:
    """Decrypt a stored secret. Raises ``ConfigurationError`` on tampering."""
    try:
        return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:  # pragma: no cover - defensive
        raise ConfigurationError(
            "Stored secret could not be decrypted (SECRET_KEY changed?)."
        ) from exc


def mask_secret(value: str | None, visible: int = 4) -> str:
    """Return a display-safe representation of a secret."""
    if not value:
        return ""
    if len(value) <= visible:
        return "*" * len(value)
    return f"{value[:visible]}{'*' * 8}"
