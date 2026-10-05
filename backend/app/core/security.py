"""Authentication primitives: password hashing, JWT issuing and API guards."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.errors import AuthenticationError, PermissionDeniedError
from app.models.enums import Role
from app.models.user import User

_bearer = HTTPBearer(auto_error=False)


# --------------------------------------------------------------------------- #
# Passwords
# --------------------------------------------------------------------------- #
def hash_password(password: str) -> str:
    """Hash a password with bcrypt (per-password salt, cost factor 12)."""
    if len(password) < 8:
        raise AuthenticationError("Password must be at least 8 characters long.")
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed_password.encode("utf-8"))
    except ValueError:
        return False


# --------------------------------------------------------------------------- #
# Tokens
# --------------------------------------------------------------------------- #
def create_access_token(subject: str, *, role: str, extra: dict | None = None) -> tuple[str, int]:
    """Return ``(jwt, expires_in_seconds)`` for the given user id."""
    expires_delta = timedelta(minutes=settings.access_token_expire_minutes)
    now = datetime.now(timezone.utc)
    payload: dict = {
        "sub": subject,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
        "iss": "devforge",
        **(extra or {}),
    }
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)
    return token, int(expires_delta.total_seconds())


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm],
                          options={"require": ["exp", "sub"]})
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Session expired. Please sign in again.") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError("Invalid authentication token.") from exc


# --------------------------------------------------------------------------- #
# Dependencies
# --------------------------------------------------------------------------- #
def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    """Resolve the authenticated user or raise 401."""
    if credentials is None or not credentials.credentials:
        raise AuthenticationError("Authentication required.")
    payload = decode_access_token(credentials.credentials)
    user = db.get(User, payload["sub"])
    if user is None or not user.is_active:
        raise AuthenticationError("Account not found or disabled.")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: Role):
    """Dependency factory enforcing that the caller holds one of ``roles``."""

    def _guard(user: CurrentUser) -> User:
        if user.role == Role.ADMIN or Role(user.role) in roles:
            return user
        raise PermissionDeniedError(
            "Your role does not permit this operation.",
            detail={"required_roles": [r.value for r in roles]},
        )

    return _guard


def bearer_from_header_or_401(credentials: Annotated[HTTPAuthorizationCredentials | None,
                                                     Depends(_bearer)]) -> str:
    """Used by endpoints that need the raw token (e.g. SSE via query param)."""
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")
    return credentials.credentials
