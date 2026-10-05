"""Authentication schemas."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.models.enums import Role
from app.schemas.common import ORMModel


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(default="", max_length=160)
    role: Role = Role.DEVELOPER


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserRead(ORMModel):
    id: str
    email: str
    full_name: str
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserRead


class AIConfigRead(BaseModel):
    """Platform configuration surfaced to the UI."""

    mode: str
    provider: str
    model: str
    execution_provider: str
    execution_enabled: bool
    github_configured: bool
    vector_backend: str
    max_stage_iterations: int
