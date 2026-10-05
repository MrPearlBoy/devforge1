"""Authentication endpoints."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.errors import AuthenticationError, ConflictError
from app.core.security import create_access_token, hash_password, verify_password
from app.models.enums import Role
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserRead
from app.schemas.common import Message
from app.services.audit import AuditService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED,
             summary="Create an account")
def register(payload: RegisterRequest, db: DbSession) -> TokenResponse:
    email = payload.email.lower()
    existing = db.scalar(select(User).where(User.email == email))
    if existing is not None:
        raise ConflictError("An account with this email already exists.")

    user = User(
        email=email,
        full_name=payload.full_name.strip(),
        hashed_password=hash_password(payload.password),
        role=payload.role.value if isinstance(payload.role, Role) else str(payload.role),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token, expires_in = create_access_token(user.id, role=user.role)
    AuditService(db).record(
        action="auth.registered",
        user=user,
        entity_type="user",
        entity_id=user.id,
        summary=f"New account created: {user.email}",
        publish=False,
    )
    return TokenResponse(
        access_token=token,
        expires_in=expires_in,
        user=UserRead.model_validate(user),
    )


@router.post("/login", response_model=TokenResponse, summary="Sign in and obtain a JWT")
def login(payload: LoginRequest, db: DbSession) -> TokenResponse:
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if user is None or not verify_password(payload.password, user.hashed_password):
        # identical message for both cases: never reveal whether an account exists
        raise AuthenticationError("Incorrect email or password.")
    if not user.is_active:
        raise AuthenticationError("This account has been disabled.")

    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)

    token, expires_in = create_access_token(user.id, role=user.role)
    AuditService(db).record(
        action="auth.login",
        user=user,
        entity_type="user",
        entity_id=user.id,
        summary=f"{user.email} signed in",
        publish=False,
    )
    return TokenResponse(
        access_token=token,
        expires_in=expires_in,
        user=UserRead.model_validate(user),
    )


@router.get("/me", response_model=UserRead, summary="Current profile")
def me(user: CurrentUser) -> UserRead:
    return UserRead.model_validate(user)


@router.post("/logout", response_model=Message, summary="Sign out (client discards the token)")
def logout(user: CurrentUser, db: DbSession) -> Message:
    AuditService(db).record(
        action="auth.logout",
        user=user,
        entity_type="user",
        entity_id=user.id,
        summary=f"{user.email} signed out",
        publish=False,
    )
    return Message(detail="Signed out. Discard the access token on the client.")
