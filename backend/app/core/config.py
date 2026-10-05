"""DevForge configuration.

All runtime configuration is environment driven (12-factor).  Nothing in the
application hard-codes providers, credentials or paths: everything flows through
``Settings`` so deployments can be reconfigured without touching code.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    """Strongly typed application settings."""

    model_config = SettingsConfigDict(
        env_file=(REPO_DIR / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- application -------------------------------------------------------
    app_name: str = "DevForge"
    app_version: str = "0.1.0"
    environment: str = "development"
    debug: bool = False
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    #: Optional regex for dynamic preview/demo origins (empty = disabled).
    cors_origin_regex: str = ""
    #: Create tables on startup — development convenience only; Alembic owns the
    #: real schema (set AUTO_CREATE_SCHEMA=false in production).
    auto_create_schema: bool = True

    # ---- security ----------------------------------------------------------
    secret_key: str = "devforge-insecure-development-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 720

    # ---- database ----------------------------------------------------------
    database_url: str = f"sqlite:///{BACKEND_DIR / 'devforge.db'}"

    # ---- AI mode -----------------------------------------------------------
    devforge_mode: str = "auto"  # mock | live | auto
    llm_provider: str = "mock"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_base_url: str = ""
    llm_temperature: float = 0.2
    llm_max_tokens: int = 4096
    llm_timeout_seconds: int = 120

    # ---- embeddings / knowledge -------------------------------------------
    embedding_provider: str = "auto"
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536
    vector_backend: str = "auto"  # auto | pgvector | json

    # ---- workspace ---------------------------------------------------------
    workspace_root: str = str(REPO_DIR / "workspace")

    # ---- orchestration -----------------------------------------------------
    max_stage_iterations: int = 3
    max_total_steps: int = 60
    checkpoint_backend: str = "sqlite"  # sqlite | memory | postgres
    checkpoint_path: str = str(BACKEND_DIR / "devforge.checkpoints.sqlite")

    # ---- execution sandbox -------------------------------------------------
    execution_enabled: bool = True
    execution_provider: str = "subprocess"  # docker | subprocess | disabled
    execution_timeout_seconds: int = 120
    execution_memory_mb: int = 512
    execution_cpu_seconds: int = 60
    execution_allowed_commands: str = "python,python3,pytest,node,npm,git"
    docker_execution_image: str = "python:3.12-slim"

    # ---- github ------------------------------------------------------------
    github_token: str = ""
    github_api_url: str = "https://api.github.com"
    github_client_id: str = ""
    github_client_secret: str = ""
    git_author_name: str = "DevForge Bot"
    git_author_email: str = "devforge@example.com"

    # ---- validators --------------------------------------------------------
    @field_validator("devforge_mode")
    @classmethod
    def _validate_mode(cls, value: str) -> str:
        allowed = {"mock", "live", "auto"}
        value = (value or "auto").strip().lower()
        if value not in allowed:
            raise ValueError(f"DEVFORGE_MODE must be one of {sorted(allowed)}")
        return value

    @field_validator("execution_provider")
    @classmethod
    def _validate_execution(cls, value: str) -> str:
        allowed = {"docker", "subprocess", "disabled"}
        value = (value or "subprocess").strip().lower()
        if value not in allowed:
            raise ValueError(f"EXECUTION_PROVIDER must be one of {sorted(allowed)}")
        return value

    # ---- derived helpers ---------------------------------------------------
    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def allowed_commands(self) -> set[str]:
        return {c.strip() for c in self.execution_allowed_commands.split(",") if c.strip()}

    @property
    def resolved_ai_mode(self) -> str:
        """Resolve ``auto`` into a concrete mode: ``live`` when a key exists."""
        if self.devforge_mode in {"mock", "live"}:
            return self.devforge_mode
        if self.llm_provider == "mock":
            return "mock"
        if self.llm_provider in {"ollama"} or self.llm_api_key.strip():
            return "live"
        return "mock"

    @property
    def is_live_ai(self) -> bool:
        return self.resolved_ai_mode == "live"

    @property
    def workspace_path(self) -> Path:
        path = Path(self.workspace_root)
        if not path.is_absolute():
            path = (REPO_DIR / path).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def repository_root(self) -> Path:
        return REPO_DIR

    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() in {"production", "prod"}

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor (safe to import anywhere)."""
    return Settings()


settings = get_settings()
