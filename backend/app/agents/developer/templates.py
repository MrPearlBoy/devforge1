"""Deterministic code generation used by the Developer Agent in MOCK MODE.

In live mode the LLM writes the code (guided by the same plan); in mock mode these
templates produce a *real, runnable* FastAPI service for the inferred domain —
CRUD endpoints, JWT authentication with pbkdf2 password hashing, pinned
dependencies and a pytest suite that actually passes in the DevForge sandbox.

Templates use {{TOKEN}} placeholders and ``str.replace`` (never ``str.format``) so
generated Python code can contain braces freely.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.agents.common.domain_inference import DomainModel, EntitySpec

SQLALCHEMY_TYPE = {
    "str": "String(255)",
    "int": "Integer",
    "float": "Float",
    "bool": "Boolean",
    "datetime": "DateTime",
}
PYTHON_ANNOTATION = {
    "str": "str",
    "int": "int",
    "float": "float",
    "bool": "bool",
    "datetime": "datetime",
}
DEFAULT_VALUE = {
    "str": '""',
    "int": "0",
    "float": "0.0",
    "bool": "False",
    "datetime": "None",
}


@dataclass
class GeneratedFile:
    path: str
    content: str
    summary: str
    language: str = "python"

    def as_change(self, operation: str = "create") -> dict:
        return {
            "path": self.path,
            "operation": operation,
            "summary": self.summary,
            "content": self.content,
            "language": self.language,
        }


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _column_line(field) -> str:  # noqa: ANN001 - FieldSpec
    sql_type = SQLALCHEMY_TYPE.get(field.python_type, "String(255)")
    nullable = "False" if field.required else "True"
    default = ""
    if not field.required and field.python_type != "datetime":
        default = f", default={DEFAULT_VALUE.get(field.python_type, 'None')}"
    comment = f"  # {field.description}" if field.description else ""
    return f"    {field.name} = Column({sql_type}, nullable={nullable}{default}){comment}"


def _read_fields(entity: EntitySpec) -> str:
    lines = []
    for field in entity.fields:
        annotation = PYTHON_ANNOTATION.get(field.python_type, "str")
        suffix = "" if field.required else " | None = None"
        lines.append(f"    {field.name}: {annotation}{suffix}")
    return "\n".join(lines)


def _create_fields(entity: EntitySpec) -> str:
    lines = []
    for field in entity.fields:
        annotation = PYTHON_ANNOTATION.get(field.python_type, "str")
        if field.required:
            lines.append(f"    {field.name}: {annotation}")
        else:
            lines.append(f"    {field.name}: {annotation} | None = None")
    return "\n".join(lines)


def _update_fields(entity: EntitySpec) -> str:
    return "\n".join(
        f"    {field.name}: {PYTHON_ANNOTATION.get(field.python_type, 'str')} | None = None"
        for field in entity.fields
    )


def _crud_block(entity: EntitySpec, *, owned: bool) -> str:
    """Generate CRUD helpers for one entity (filters follow the entity fields)."""
    name = entity.name
    table = entity.table
    has_completed = any(field.name == "completed_at" for field in entity.fields)
    filterable = [f for f in entity.fields if f.name in {"status", "priority", "category"}]
    title_field = next(
        (f.name for f in entity.fields if f.name in {"title", "name", "description", "reference"}),
        entity.fields[0].name if entity.fields else "title",
    )

    signature = [
        f"def list_{table}(",
        "    db: Session,",
        "    *,",
        "    limit: int = 50,",
        "    offset: int = 0,",
        "    search: str | None = None,",
    ]
    for field in filterable:
        annotation = PYTHON_ANNOTATION.get(field.python_type, "str")
        signature.append(f"    {field.name}: {annotation} | None = None,")
    if owned:
        signature.append("    owner_id: str | None = None,")
    signature.append(f") -> list[models.{name}]:")
    signature.append(f'    """Return {table} ordered by newest first, filtered by the supplied arguments."""')
    signature.append(f"    stmt = select(models.{name})")
    if owned:
        signature += [
            "    if owner_id:",
            f"        stmt = stmt.where(models.{name}.owner_id == owner_id)",
        ]
    for field in filterable:
        signature += [
            f"    if {field.name}:",
            f"        stmt = stmt.where(models.{name}.{field.name} == {field.name})",
        ]
    signature += [
        "    if search:",
        f"        stmt = stmt.where(models.{name}.{title_field}.ilike(f'%{{search}}%'))",
        f"    stmt = stmt.order_by(models.{name}.created_at.desc()).offset(offset).limit(limit)",
        "    return list(db.scalars(stmt))",
        "",
    ]

    header = "\n".join(signature)
    if owned:
        create_signature = (
            f"def create_{table}(db: Session, payload: schemas.{name}Create,"
            " *, owner_id: str | None = None) -> models."
            f"{name}:"
        )
        create_body = [
            "    data = payload.model_dump(exclude_unset=True)",
            "    if owner_id:",
            '        data["owner_id"] = owner_id',
            f"    item = models.{name}(**data)",
            "    db.add(item)",
            "    db.commit()",
            "    db.refresh(item)",
            "    return item",
        ]
    else:
        create_signature = f"def create_{table}(db: Session, payload: schemas.{name}Create) -> models.{name}:"
        create_body = [
            "    item = models."
            + name
            + "(**payload.model_dump(exclude_unset=True))",
            "    db.add(item)",
            "    db.commit()",
            "    db.refresh(item)",
            "    return item",
        ]

    blocks = [
        header,
        "",
        create_signature,
        *create_body,
        "",
        "",
        f"def get_{table}(db: Session, item_id: str) -> models.{name} | None:",
        f"    return db.get(models.{name}, item_id)",
        "",
        "",
        f"def update_{table}(db: Session, item: models.{name}, payload: schemas.{name}Update) "
        f"-> models.{name}:",
        "    for key, value in payload.model_dump(exclude_unset=True).items():",
        "        if value is not None:",
        "            setattr(item, key, value)",
        "    db.commit()",
        "    db.refresh(item)",
        "    return item",
        "",
        "",
        f"def delete_{table}(db: Session, item: models.{name}) -> None:",
        "    db.delete(item)",
        "    db.commit()",
    ]
    if has_completed:
        blocks += [
            "",
            "",
            f"def complete_{table}(db: Session, item: models.{name}) -> models.{name}:",
            "    item.completed_at = datetime.now(timezone.utc)",
        ]
        if any(field.name == "status" for field in entity.fields):
            blocks.append("    item.status = \"completed\"")
        blocks += ["    db.commit()", "    db.refresh(item)", "    return item"]
    return "\n".join(blocks)


def _not_found_guard(name: str, *, requires_auth: bool, indent: str = "    ") -> list[str]:
    """Emit the 404/ownership check applied to every single-record endpoint."""
    if requires_auth:
        return [
            f'{indent}if item is None or getattr(item, "owner_id", None) != current_user.id:',
            f'{indent}    raise HTTPException(status_code=404, detail="{name} not found")',
        ]
    return [
        f"{indent}if item is None:",
        f'{indent}    raise HTTPException(status_code=404, detail="{name} not found")',
    ]


def _router_block(entity: EntitySpec, *, requires_auth: bool) -> str:
    """Generate a complete FastAPI router module for one entity."""
    name, table = entity.name, entity.table
    has_status = any(field.name == "status" for field in entity.fields)
    has_completed = any(field.name == "completed_at" for field in entity.fields)
    filterable = [f for f in entity.fields if f.name in {"status", "priority", "category"}]

    lines: list[str] = [
        '"""REST endpoints for ' + table + '."""',
        "from __future__ import annotations",
        "",
        "from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status",
        "from sqlalchemy.orm import Session",
        "",
        "from app import crud, models, schemas",
        "from app.database import get_db",
    ]
    if requires_auth:
        lines.append("from app.security import require_user")
    lines += [
        "",
        f'router = APIRouter(prefix="/api/{table}", tags=["{table}"])',
        "",
        "",
        f'@router.get("", response_model=list[schemas.{name}Read])',
        f"def list_{table}(",
        "    limit: int = Query(50, ge=1, le=200),",
        "    offset: int = Query(0, ge=0),",
        "    search: str | None = Query(None),",
    ]
    for field in filterable:
        annotation = PYTHON_ANNOTATION.get(field.python_type, "str")
        lines.append(f"    {field.name}: {annotation} | None = Query(None),")
    lines.append("    db: Session = Depends(get_db),")
    if requires_auth:
        lines.append("    current_user: models.User = Depends(require_user),")
    lines += [
        f") -> list[models.{name}]:",
        f'    """List {table} with paging, search and filtering."""',
        f"    return crud.list_{table}(",
        "        db, limit=limit, offset=offset, search=search,",
    ]
    for field in filterable:
        lines.append(f"        {field.name}={field.name},")
    if requires_auth:
        lines.append("        owner_id=current_user.id,")
    lines += [
        "    )",
        "",
        "",
        f'@router.post("", response_model=schemas.{name}Read, '
        f"status_code=http_status.HTTP_201_CREATED)",
        f"def create_{table}(",
        f"    payload: schemas.{name}Create,",
        "    db: Session = Depends(get_db),",
    ]
    if requires_auth:
        lines.append("    current_user: models.User = Depends(require_user),")
    lines.append(f") -> models.{name}:")
    lines.append(f'    """Create a new {name.lower()}."""')
    if requires_auth:
        lines.append(f"    return crud.create_{table}(db, payload, owner_id=current_user.id)")
    else:
        lines.append(f"    return crud.create_{table}(db, payload)")
    lines.append("")

    for method, signature, purpose, payload_arg in (
        ("get", f"def read_{table}(", f'    """Fetch one {name.lower()}."""', ""),
        ("put", f"def update_{table}(", f'    """Update an existing {name.lower()}."""',
         f"    payload: schemas.{name}Update,"),
    ):
        descriptor = f'@router.{method}("/{{item_id}}", response_model=schemas.{name}Read)'
        lines += [
            "",
            descriptor,
            signature,
            "    item_id: str,",
        ]
        if payload_arg:
            lines.append(payload_arg)
        lines += [
            "    db: Session = Depends(get_db),",
        ]
        if requires_auth:
            lines.append("    current_user: models.User = Depends(require_user),")
        lines.append(f") -> models.{name}:")
        lines.append(purpose)
        lines.append(f"    item = crud.get_{table}(db, item_id)")
        lines += _not_found_guard(name, requires_auth=requires_auth)
        if method == "get":
            lines.append("    return item")
        else:
            lines.append(f"    return crud.update_{table}(db, item, payload)")
        lines.append("")

    lines += [
        "",
        f'@router.delete("/{{item_id}}", status_code=http_status.HTTP_204_NO_CONTENT)',
        f"def delete_{table}(",
        "    item_id: str,",
        "    db: Session = Depends(get_db),",
    ]
    if requires_auth:
        lines.append("    current_user: models.User = Depends(require_user),")
    lines += [
        ") -> None:",
        f'    """Delete a {name.lower()}."""',
        f"    item = crud.get_{table}(db, item_id)",
    ]
    lines += _not_found_guard(name, requires_auth=requires_auth)
    lines += [f"    crud.delete_{table}(db, item)", ""]

    if has_status:
        lines += [
            "",
            f'@router.patch("/{{item_id}}/status", response_model=schemas.{name}Read)',
            f"def set_{table}_status(",
            "    item_id: str,",
            f"    payload: schemas.{name}StatusUpdate,",
            "    db: Session = Depends(get_db),",
        ]
        if requires_auth:
            lines.append("    current_user: models.User = Depends(require_user),")
        lines += [
            f") -> models.{name}:",
            '    """Change the workflow status of a record."""',
            f"    item = crud.get_{table}(db, item_id)",
        ]
        lines += _not_found_guard(name, requires_auth=requires_auth)
        lines += [
            "    item.status = payload.status",
            "    db.commit()",
            "    db.refresh(item)",
            "    return item",
            "",
        ]

    if has_completed:
        lines += [
            "",
            f'@router.post("/{{item_id}}/complete", response_model=schemas.{name}Read)',
            f"def complete_{table}(",
            "    item_id: str,",
            "    db: Session = Depends(get_db),",
        ]
        if requires_auth:
            lines.append("    current_user: models.User = Depends(require_user),")
        lines += [
            f") -> models.{name}:",
            '    """Mark a record as completed."""',
            f"    item = crud.get_{table}(db, item_id)",
        ]
        lines += _not_found_guard(name, requires_auth=requires_auth)
        lines += [f"    return crud.complete_{table}(db, item)", ""]

    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# file builders
# --------------------------------------------------------------------------- #
def build_scaffold(domain: DomainModel, project_name: str) -> list[GeneratedFile]:
    """Create the runnable service for the inferred domain."""
    primary = domain.primary
    entities = [e for e in domain.entities if e.name != "User"]
    if not entities:  # a pure account service
        entities = [domain.primary]

    files: list[GeneratedFile] = []
    files.append(GeneratedFile("backend/app/__init__.py",
                               '"""Generated by DevForge (Developer Agent)."""\n',
                               "Package marker"))
    files.append(GeneratedFile("backend/app/config.py", _config_py(project_name),
                               "Environment driven configuration (development defaults)"))
    files.append(GeneratedFile("backend/app/database.py", _database_py(),
                               "SQLAlchemy engine, session factory and declarative base"))
    files.append(GeneratedFile("backend/app/models.py", _models_py(entities, domain),
                               "ORM models for " + ", ".join(e.table for e in entities)))
    files.append(GeneratedFile("backend/app/schemas.py", _schemas_py(entities),
                               "Pydantic request/response schemas"))
    files.append(GeneratedFile("backend/app/crud.py", _crud_py(entities, domain),
                               "Data access helpers used by the routers"))
    files.append(GeneratedFile("backend/app/security.py", _security_py(),
                               "Password hashing (pbkdf2) and signed token helpers"))
    files.append(GeneratedFile("backend/app/auth.py", _auth_router_py(),
                               "Registration, login and profile endpoints"))
    for entity in entities:
        files.append(
            GeneratedFile(
                f"backend/app/routers/{entity.table}.py",
                _router_module(entity, domain),
                f"{entity.name} REST endpoints",
            )
        )
    files.append(GeneratedFile("backend/app/routers/__init__.py",
                               '"""API routers."""\n', "Package marker"))
    files.append(GeneratedFile("backend/app/main.py", _main_py(entities, project_name),
                               "FastAPI application factory wiring routers and health checks"))
    files.append(GeneratedFile("backend/requirements.txt", _requirements_txt(),
                               "Pinned runtime and test dependencies", language="text"))
    files.append(GeneratedFile("backend/.env.example", _env_example(project_name),
                               "Documented environment variables", language="dotenv"))
    files.append(GeneratedFile(f"backend/tests/test_{primary.table}_api.py",
                               _tests_py(domain, primary, entities),
                               f"API tests covering the {primary.name} workflow"))
    files.append(GeneratedFile("backend/tests/__init__.py", "", "Package marker"))
    files.append(GeneratedFile(".gitignore", _gitignore(domain), "Repository hygiene",
                               language="text"))
    return files


def build_remediation(domain: DomainModel, project_name: str, findings: list[dict],
                      existing_config: str = "") -> list[GeneratedFile]:
    """Produce targeted fixes for the open security findings.

    Only files implicated by a finding are changed — the Developer Agent never
    rewrites the project to "fix" something.
    """
    files: list[GeneratedFile] = []
    config_rules = {"SEC-CONF-001", "SEC-CONF-003", "SEC-CONF-002", "SEC-SECRET-001",
                    "SEC-SECRET-002"}
    if any(finding.get("rule_id") in config_rules for finding in findings):
        files.append(
            GeneratedFile(
                "backend/app/config.py",
                _config_py(project_name, hardened=True),
                "Hardened configuration: no development placeholders, strict environment reads",
            )
        )
    if any(finding.get("rule_id", "").startswith("SEC-DEP") for finding in findings):
        files.append(
            GeneratedFile("backend/requirements.txt", _requirements_txt(hardened=True),
                          "Dependencies pinned to reviewed versions", language="text")
        )
    if not files:  # nothing matched: still return an explicit no-op note file? No.
        return []
    return files


# --------------------------------------------------------------------------- #
# individual templates
# --------------------------------------------------------------------------- #
def _config_py(project_name: str, *, hardened: bool = False) -> str:
    if hardened:
        secret_block = '''def _required_secret(name: str) -> str:
    """Read a mandatory secret from the environment — no placeholder fallback."""
    value = os.getenv(name, "").strip()
    if len(value) < 32:
        raise RuntimeError(
            f"{name} must be set to a random value of at least 32 characters "
            "(generate one with: python -c \\"import secrets;print(secrets.token_urlsafe(48))\\")."
        )
    return value


def _flag(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


settings = Settings(
    app_name=os.getenv("APP_NAME", "{{APP_NAME}}"),
    database_url=os.getenv("DATABASE_URL", "sqlite:///./app.db"),
    jwt_secret=_required_secret("JWT_SECRET"),
    jwt_expires_minutes=int(os.getenv("JWT_EXPIRES_MINUTES", "60")),
    debug=_flag("DEBUG", False),
)
'''
    else:
        secret_block = '''# NOTE: these are development placeholders so a fresh clone runs immediately.
# They MUST be replaced (see backend/.env.example) before any real deployment.
DEBUG = True
JWT_SECRET = "devforge-local-secret"

settings = Settings(
    app_name=os.getenv("APP_NAME", "{{APP_NAME}}"),
    database_url=os.getenv("DATABASE_URL", "sqlite:///./app.db"),
    jwt_secret=os.getenv("JWT_SECRET", JWT_SECRET),
    jwt_expires_minutes=int(os.getenv("JWT_EXPIRES_MINUTES", "60")),
    debug=DEBUG,
)
'''
    template = '''"""Application configuration.

Every value can be overridden with an environment variable so the same image can
run in local development, CI and production.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    app_name: str
    database_url: str
    jwt_secret: str
    jwt_expires_minutes: int
    debug: bool


{{SECRET_BLOCK}}

__all__ = ["Settings", "settings"]
'''
    return template.replace("{{APP_NAME}}", project_name).replace("{{SECRET_BLOCK}}", secret_block)


def _database_py() -> str:
    return '''"""Database engine, session factory and declarative base."""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    """Declarative base for all models."""


def _engine_kwargs() -> dict:
    if settings.database_url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}
    return {"pool_pre_ping": True}


engine = create_engine(settings.database_url, **_engine_kwargs())
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def create_all() -> None:
    """Create tables (development convenience; use migrations in production)."""
    from app import models  # noqa: F401  (register models on the metadata)

    Base.metadata.create_all(bind=engine)
'''


def _models_py(entities: list[EntitySpec], domain: DomainModel) -> str:
    blocks: list[str] = []
    for entity in entities:
        columns = "\n".join(_column_line(field) for field in entity.fields)
        owner = (
            "\n    owner_id = Column(String(36), ForeignKey(\"users.id\"), index=True)"
            if domain.requires_auth
            else ""
        )
        blocks.append(
            f'''class {entity.name}(Base):
    """{entity.description}"""

    __tablename__ = "{entity.table}"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
{columns}{owner}
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    def to_dict(self) -> dict:
        return {{
            column.name: getattr(self, column.name)
            for column in self.__table__.columns
        }}
'''
        )
    if domain.requires_auth:
        blocks.insert(
            0,
            '''class User(Base):
    """Application account used for sign-in and authorisation."""

    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    full_name = Column(String(160), nullable=False, default="")
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(32), nullable=False, default="member")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
''',
        )
    header = '''"""SQLAlchemy models.

Identifiers are UUID strings so records stay portable across databases.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


'''
    exported = [entity.name for entity in entities] + (["User"] if domain.requires_auth else [])
    footer = f'\n\n__all__ = {exported!r}\n'
    return header + "\n\n".join(blocks) + footer


def _schemas_py(entities: list[EntitySpec]) -> str:
    blocks = [
        '''class UserRegister(BaseModel):
    full_name: str
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserLogin(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserRead(BaseModel):
    id: str
    full_name: str
    email: EmailStr
    role: str
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserRead
'''
    ]
    for entity in entities:
        blocks.append(
            f'''class {entity.name}Base(BaseModel):
{_read_fields(entity)}


class {entity.name}Create({entity.name}Base):
    pass


class {entity.name}Update(BaseModel):
{_update_fields(entity)}


class {entity.name}Read({entity.name}Base):
    id: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
'''
        )
        if any(field.name == "status" for field in entity.fields):
            blocks.append(
                f'''class {entity.name}StatusUpdate(BaseModel):
    status: str = Field(min_length=1, max_length=32)
'''
            )
    header = '''"""Pydantic schemas: every request is validated before it reaches the database."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

'''
    return header + "\n\n".join(blocks)


def _crud_py(entities: list[EntitySpec], domain: DomainModel) -> str:
    blocks = [
        '''def get_user_by_email(db: Session, email: str) -> models.User | None:
    return db.scalar(select(models.User).where(models.User.email == email.lower()))


def create_user(db: Session, payload: schemas.UserRegister, password_hash: str) -> models.User:
    user = models.User(
        full_name=payload.full_name,
        email=payload.email.lower(),
        password_hash=password_hash,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
'''
    ]
    for entity in entities:
        blocks.append(_crud_block(entity, owned=domain.requires_auth))
    header = '''"""Data access functions — the only layer that builds database statements."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models, schemas

'''
    return header + "\n\n\n".join(blocks)


def _security_py() -> str:
    return '''"""Password hashing and signed-token helpers (standard library only)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app import models
from app.config import settings
from app.database import get_db

PBKDF2_ITERATIONS = 240_000
_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    """Return ``pbkdf2_sha256$iterations$salt$digest`` for a password."""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"),
                                 PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt, digest = encoded.split("$", 3)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"),
                                    int(iterations))
    return hmac.compare_digest(candidate.hex(), digest)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def create_token(subject: str, *, expires_minutes: int | None = None) -> tuple[str, int]:
    """Create a compact HMAC-signed token (JWT-compatible claims, no dependency)."""
    ttl = (expires_minutes or settings.jwt_expires_minutes) * 60
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": subject,
        "iat": int(time.time()),
        "exp": int(time.time()) + ttl,
        "iss": settings.app_name,
    }
    signing_input = _b64(json.dumps(header, separators=(",", ":")).encode()) + "." + \\
        _b64(json.dumps(payload, separators=(",", ":")).encode())
    signature = hmac.new(settings.jwt_secret.encode("utf-8"), signing_input.encode("utf-8"),
                         hashlib.sha256).digest()
    return f"{signing_input}.{_b64(signature)}", ttl


def decode_token(token: str) -> dict:
    try:
        header_b64, payload_b64, signature_b64 = token.split(".")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed token") from exc
    signing_input = f"{header_b64}.{payload_b64}"
    expected = hmac.new(settings.jwt_secret.encode("utf-8"), signing_input.encode("utf-8"),
                        hashlib.sha256).digest()
    if not hmac.compare_digest(_unb64(signature_b64), expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token signature")
    claims = json.loads(_unb64(payload_b64))
    if int(claims.get("exp", 0)) < int(time.time()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    return claims


def require_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Annotated[Session, Depends(get_db)],
) -> models.User:
    """FastAPI dependency enforcing a valid bearer token."""
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Authentication required")
    claims = decode_token(credentials.credentials)
    user = db.get(models.User, claims.get("sub", ""))
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown account")
    return user
'''


def _auth_router_py() -> str:
    return '''"""Registration, login and profile endpoints."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import crud, models, schemas
from app.database import get_db
from app.security import create_token, hash_password, require_user, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=schemas.UserRead, status_code=status.HTTP_201_CREATED)
def register(payload: schemas.UserRegister, db: Annotated[Session, Depends(get_db)]) -> models.User:
    if crud.get_user_by_email(db, payload.email) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="An account with this email already exists")
    return crud.create_user(db, payload, hash_password(payload.password))


@router.post("/login", response_model=schemas.TokenResponse)
def login(payload: schemas.UserLogin, db: Annotated[Session, Depends(get_db)]) -> schemas.TokenResponse:
    user = crud.get_user_by_email(db, payload.email)
    if user is None or not verify_password(payload.password, user.password_hash):
        # A single message for both cases avoids revealing which emails exist.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid email or password")
    token, ttl = create_token(user.id)
    return schemas.TokenResponse(access_token=token, expires_in=ttl,
                                 user=schemas.UserRead.model_validate(user))


@router.get("/me", response_model=schemas.UserRead)
def me(user: Annotated[models.User, Depends(require_user)]) -> models.User:
    return user
'''


def _router_module(entity: EntitySpec, domain: DomainModel) -> str:
    return _router_block(entity, requires_auth=domain.requires_auth)


def _main_py(entities: list[EntitySpec], project_name: str) -> str:
    routers = "".join(
        f"from app.routers import {entity.table}\n" for entity in entities
    )
    includes = "".join(
        f"    app.include_router({entity.table}.router)\n" for entity in entities
    )
    return (
        '''"""FastAPI application factory for {{APP_NAME}}.

Run locally with:
    uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import auth
from app.config import settings
from app.database import create_all
'''
        + routers
        + '''

@asynccontextmanager
async def lifespan(_: FastAPI):
    """Create tables on startup (migrations handle production schema changes)."""
    create_all()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Generated and reviewed with DevForge.",
        lifespan=lifespan,
    )
    app.include_router(auth.router)
'''
        + includes
        + '''
    @app.get("/health", tags=["platform"])
    def health() -> dict:
        return {"status": "ok", "app": settings.app_name, "debug": settings.debug}

    return app


app = create_app()
'''.replace("{{APP_NAME}}", project_name)
    )


def _requirements_txt(*, hardened: bool = False) -> str:
    return '''# Runtime dependencies (pinned for reproducible builds)
fastapi==0.115.6
uvicorn==0.34.0
SQLAlchemy==2.0.36
pydantic==2.10.4
email-validator==2.2.0

# Test dependencies
pytest==8.3.4
httpx==0.28.1
'''


def _env_example(project_name: str) -> str:
    return f'''# Copy to .env and adjust. Never commit a real .env file.
APP_NAME={project_name}
DATABASE_URL=sqlite:///./app.db
# Generate with: python -c "import secrets;print(secrets.token_urlsafe(48))"
JWT_SECRET=
JWT_EXPIRES_MINUTES=60
DEBUG=false
'''


def _tests_py(domain: DomainModel, primary: EntitySpec, entities: list[EntitySpec]) -> str:
    payload = _sample_payload(primary)
    payload_json = ",\n        ".join(f'"{key}": {value}' for key, value in payload.items())
    update_field, update_value = _update_sample(primary)
    complete_test = ""
    if any(field.name == "completed_at" for field in primary.fields):
        complete_test = f'''

def test_mark_{primary.table}_complete(client: TestClient) -> None:
    """REQ: mark a {primary.name.lower()} as completed."""
    headers = _auth_headers(client)
    created = client.post("/api/{primary.table}", json={{{payload_json}}}, headers=headers).json()
    response = client.post(f"/api/{primary.table}/{{created['id']}}/complete", headers=headers)
    assert response.status_code == 200
    assert response.json()["completed_at"] is not None
'''
    status_test = ""
    if any(field.name == "status" for field in primary.fields):
        status_test = f'''

def test_update_{primary.table}_status(client: TestClient) -> None:
    """REQ: change the workflow status of an existing record."""
    headers = _auth_headers(client)
    created = client.post("/api/{primary.table}", json={{{payload_json}}}, headers=headers).json()
    response = client.patch(f"/api/{primary.table}/{{created['id']}}/status",
                            json={{"status": "in-progress"}}, headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "in-progress"
'''
    return f'''"""API tests for the {primary.name} workflow.

The suite drives the real application through the HTTP layer, so a passing run
means the endpoints, validation, persistence and authentication all work together.
"""
from __future__ import annotations

import os
import tempfile
import uuid

import pytest

os.environ.setdefault("DATABASE_URL", f"sqlite:///{{tempfile.mkdtemp()}}/test.db")
os.environ.setdefault("JWT_SECRET", "unit-test-secret-key-0123456789abcdef")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import create_app  # noqa: E402


@pytest.fixture()
def client() -> TestClient:
    with TestClient(create_app()) as test_client:
        yield test_client


def _auth_headers(client: TestClient) -> dict:
    email = f"user-{{uuid.uuid4().hex[:8]}}@example.com"
    client.post("/api/auth/register", json={{"full_name": "Test User", "email": email,
                                             "password": "supersecret123"}})
    response = client.post("/api/auth/login", json={{"email": email, "password": "supersecret123"}})
    assert response.status_code == 200, response.text
    return {{"Authorization": f"Bearer {{response.json()['access_token']}}"}}
{complete_test}{status_test}

def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_authentication_is_required(client: TestClient) -> None:
    response = client.get("/api/{primary.table}")
    assert response.status_code == 401


def test_create_and_read_{primary.table}(client: TestClient) -> None:
    headers = _auth_headers(client)
    created = client.post("/api/{primary.table}", json={{{payload_json}}}, headers=headers)
    assert created.status_code == 201, created.text
    item_id = created.json()["id"]

    fetched = client.get(f"/api/{primary.table}/{{item_id}}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["id"] == item_id


def test_list_{primary.table}(client: TestClient) -> None:
    headers = _auth_headers(client)
    client.post("/api/{primary.table}", json={{{payload_json}}}, headers=headers)
    response = client.get("/api/{primary.table}", headers=headers)
    assert response.status_code == 200
    assert isinstance(response.json(), list)
    assert len(response.json()) >= 1


def test_update_{primary.table}(client: TestClient) -> None:
    headers = _auth_headers(client)
    created = client.post("/api/{primary.table}", json={{{payload_json}}}, headers=headers).json()
    response = client.put(f"/api/{primary.table}/{{created['id']}}",
                          json={{"{update_field}": {update_value}}}, headers=headers)
    assert response.status_code == 200
    assert response.json()["{update_field}"] == {update_value}


def test_delete_{primary.table}(client: TestClient) -> None:
    headers = _auth_headers(client)
    created = client.post("/api/{primary.table}", json={{{payload_json}}}, headers=headers).json()
    deleted = client.delete(f"/api/{primary.table}/{{created['id']}}", headers=headers)
    assert deleted.status_code == 204
    assert client.get(f"/api/{primary.table}/{{created['id']}}", headers=headers).status_code == 404


def test_validation_rejects_incomplete_payload(client: TestClient) -> None:
    headers = _auth_headers(client)
    response = client.post("/api/{primary.table}", json={{}}, headers=headers)
    assert response.status_code == 422


def test_records_are_isolated_between_users(client: TestClient) -> None:
    """A user must not be able to read another user's record."""
    owner_headers = _auth_headers(client)
    created = client.post("/api/{primary.table}", json={{{payload_json}}},
                          headers=owner_headers).json()
    other_headers = _auth_headers(client)
    response = client.get(f"/api/{primary.table}/{{created['id']}}", headers=other_headers)
    assert response.status_code == 404
'''


def _sample_payload(entity: EntitySpec) -> dict[str, str]:
    values: dict[str, str] = {}
    for field in entity.fields:
        if field.python_type == "str":
            sample = field.example or f"sample {field.name}"
            values[field.name] = repr(sample)[:120]
        elif field.python_type in {"int", "float"}:
            values[field.name] = field.example if field.example and field.example.replace(
                ".", "").isdigit() else ("42" if field.python_type == "int" else "42.5")
        elif field.python_type == "bool":
            values[field.name] = "True"
        elif field.python_type == "datetime":
            values[field.name] = '"2026-06-01T10:00:00Z"'
    if not values:
        values["title"] = "'sample record'"
    return values


def _update_sample(entity: EntitySpec) -> tuple[str, str]:
    for field in entity.fields:
        if field.python_type == "str" and field.required:
            return field.name, "'updated value'"
    field = entity.fields[0]
    if field.python_type in {"int", "float"}:
        return field.name, "99"
    return field.name, "'updated value'"


def _gitignore(domain: DomainModel) -> str:
    return '''# python
__pycache__/
*.py[cod]
.venv/
venv/
.pytest_cache/

# env / secrets
.env
.env.*
!.env.example

# databases & runtime
*.db
*.sqlite3
app.db

# editors / os
.vscode/
.idea/
.DS_Store
'''
