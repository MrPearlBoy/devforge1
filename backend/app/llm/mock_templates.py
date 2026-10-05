"""Deterministic content generators for the offline mock LLM provider.

Each generator takes the agent's ``CONTEXT_JSON`` dict and returns a
schema-conformant Python dict. The templates are intentionally compact but
real: the generated codebase is a complete, runnable, stdlib-only service
that passes its own pytest suite and comes back clean from the security
scanner, so the entire 6-layer pipeline can be demonstrated with zero
external API calls.
"""
from __future__ import annotations

import re
from typing import Any


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug or "project"


# --------------------------------------------------------------------------
# Requirement Agent
# --------------------------------------------------------------------------
def mock_requirement(ctx: dict[str, Any]) -> dict[str, Any]:
    task = (ctx.get("task") or "a focused software service").strip()
    name = ctx.get("project_name") or slugify(task)
    feedback = ctx.get("feedback")

    functional = [
        "FR-01: the system shall implement the core capability — " + task.lower().rstrip(".") + ".",
        "FR-02: the system shall create, read, update and delete domain records through a single service layer.",
        "FR-03: the system shall expose every operation through a consistent HTTP-style API (JSON in / JSON out).",
        "FR-04: the system shall validate all inputs and return structured error responses (400/404-class) for invalid operations.",
        "FR-05: the system shall persist records across restarts using a lightweight embedded database.",
        "FR-06: the system shall provide a command-line interface for basic record operations.",
    ]
    if feedback:
        functional.append("FR-07: the system shall address the reviewer feedback: " + str(feedback)[:300])

    stories = [
        {
            "id": "US-01",
            "title": "Create a record",
            "story": "As a user, I want to create a new record with a title and metadata, so that I can manage my data.",
            "acceptance_criteria": [
                "a valid create returns a record with id, timestamps and a default status",
                "an empty or oversized title is rejected with a 400-class error",
                "an invalid status value is rejected with a 400-class error",
            ],
        },
        {
            "id": "US-02",
            "title": "List and filter records",
            "story": "As a user, I want to list records filtered by status, so that I can focus on the subset I care about.",
            "acceptance_criteria": [
                "the list is ordered by creation time",
                "the status filter returns only matching records",
                "records are returned as JSON-serializable dicts",
            ],
        },
        {
            "id": "US-03",
            "title": "Update and delete records",
            "story": "As an operator, I want to update or delete a record, so that the data stays accurate.",
            "acceptance_criteria": [
                "a partial update changes only the provided fields",
                "updating a missing record returns a 404-class error",
                "deleting a missing record returns a 404-class error",
            ],
        },
    ]
    nfrs = [
        "NFR-01: the core library must depend only on the Python standard library so it can be tested in an isolated environment.",
        "NFR-02: all SQL statements must be parameterized; no string-interpolated queries.",
        "NFR-03: the system must not embed secrets or credentials in source code.",
        "NFR-04: the API layer must be framework-agnostic so it can be mounted in FastAPI, Flask or plain WSGI.",
        "NFR-05: the test suite must run in under 30 seconds without network access.",
    ]
    scope = [
        "Billing and payment processing",
        "Authentication, authorization and multi-tenancy",
        "Deployment automation (handled by DevForge's delivery stage)",
    ]
    return {
        "project_name": name,
        "overview": (
            f"{name} is a focused software service: {task} It is delivered as a modular, "
            "well-tested Python codebase with a service layer, a framework-agnostic "
            "HTTP-style API, embedded persistence and a CLI."
        ),
        "functional_requirements": functional,
        "user_stories": stories,
        "non_functional_requirements": nfrs,
        "out_of_scope": scope,
    }


# --------------------------------------------------------------------------
# Architecture Agent
# --------------------------------------------------------------------------
def mock_architecture(ctx: dict[str, Any]) -> dict[str, Any]:
    name = ctx.get("project_name") or "project"
    slug = slugify(name)
    return {
        "summary": (
            f"Modular Python architecture for {name}: a stdlib-only core (domain model + "
            "service + sqlite3 persistence), a framework-agnostic API dispatch layer and a "
            "thin argparse CLI. Tests run under pytest from the workspace root."
        ),
        "tech_stack": {
            "language": "Python 3.11+ (standard library only in generated code)",
            "persistence": "sqlite3 (stdlib) with parameterized queries",
            "api": "framework-agnostic dispatcher (JSON in/out), mountable in FastAPI/Flask",
            "testing": "pytest",
            "security": "bandit when available, built-in AST/regex scanner otherwise",
            "ci": "GitHub Actions workflow generated at delivery",
        },
        "directory_structure": f"""{slug}/
├── conftest.py            # puts the workspace root on sys.path for tests
├── src/
│   ├── __init__.py        # package marker
│   ├── core.py            # Item model + ItemService (CRUD, validation, sqlite3 persistence)
│   ├── api.py             # API dispatcher: routes → handlers, structured errors
│   └── cli.py             # argparse CLI over ItemService
├── tests/
│   ├── test_core.py       # unit tests for model + service
│   └── test_api.py        # API dispatch + error-path tests
├── requirements/
├── docs/
└── README.md""",
        "api_endpoints": [
            {
                "method": "GET",
                "path": "/health",
                "description": "Liveness probe.",
                "request_body": "",
                "response": '{"status": "ok"}',
            },
            {
                "method": "GET",
                "path": "/items",
                "description": "List items; optional status filter.",
                "request_body": '{"status": "active"} (optional)',
                "response": '{"items": [Item, ...]}',
            },
            {
                "method": "POST",
                "path": "/items",
                "description": "Create an item.",
                "request_body": '{"title": str, "status": "active" (default), "payload": {}}',
                "response": '{"item": Item}',
            },
            {
                "method": "GET",
                "path": "/items/{id}",
                "description": "Fetch one item by id.",
                "request_body": "",
                "response": '{"item": Item} or 404',
            },
            {
                "method": "PATCH",
                "path": "/items/{id}",
                "description": "Partially update an item.",
                "request_body": '{"title"?, "status"?, "payload"?}',
                "response": '{"item": Item} or 404/400',
            },
            {
                "method": "DELETE",
                "path": "/items/{id}",
                "description": "Delete an item.",
                "request_body": "",
                "response": '{"deleted": true} or 404',
            },
        ],
        "modules": [
            {
                "name": "core",
                "responsibility": "domain model (Item), input validation, CRUD service with optional sqlite3 persistence",
                "files": ["src/core.py"],
            },
            {
                "name": "api",
                "responsibility": "route matching and JSON request/response handling over core, structured APIError",
                "files": ["src/api.py"],
            },
            {
                "name": "cli",
                "responsibility": "command-line interface (add / list / get) over the service",
                "files": ["src/cli.py"],
            },
        ],
        "data_model": (
            "Item(id: str, title: str, status: 'active'|'archived'|'deleted', payload: dict, "
            "created_at: ISO-8601, updated_at: ISO-8601) persisted as JSON columns in a single "
            "`items` table."
        ),
    }


# --------------------------------------------------------------------------
# Coding Agent (deterministic, runnable, security-clean codebase)
# --------------------------------------------------------------------------
_CORE_PY = '''"""Core domain model and service layer for __NAME__ (generated by DevForge)."""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VALID_STATUSES = ("active", "archived", "deleted")


def _utcnow() -> str:
    """Current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


class ValidationError(ValueError):
    """Raised when a domain operation violates a validation rule."""


@dataclass
class Item:
    """A single domain record managed by the service."""

    id: str
    title: str
    status: str = "active"
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_utcnow)
    updated_at: str = field(default_factory=_utcnow)

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable representation."""
        return asdict(self)


class ItemService:
    """CRUD service for Item records with optional sqlite3 persistence."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path: str | None = None if db_path is None else str(db_path)
        self._lock = threading.Lock()
        self._items: dict[str, Item] = {}
        if self._db_path:
            self._migrate()
            self._load()

    # -- persistence -----------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        if self._db_path is None:
            raise RuntimeError("no database path configured")
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _migrate(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS items (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )"""
            )

    def _load(self) -> None:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, title, status, payload, created_at, updated_at FROM items"
            ).fetchall()
        for row in rows:
            item = Item(
                id=row["id"],
                title=row["title"],
                status=row["status"],
                payload=json.loads(row["payload"]),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            self._items[item.id] = item

    # -- validation ------------------------------------------------------
    @staticmethod
    def _validate(title: str, status: str) -> None:
        if title is None or not str(title).strip():
            raise ValidationError("title must be a non-empty string")
        if len(str(title)) > 200:
            raise ValidationError("title must be at most 200 characters")
        if status not in VALID_STATUSES:
            raise ValidationError(f"status must be one of {list(VALID_STATUSES)}")

    # -- CRUD ------------------------------------------------------------
    def create(
        self,
        title: str,
        status: str = "active",
        payload: dict[str, Any] | None = None,
    ) -> Item:
        """Create and store a new item."""
        self._validate(title, status)
        item = Item(
            id=uuid.uuid4().hex[:12],
            title=str(title).strip(),
            status=status,
            payload=dict(payload or {}),
        )
        with self._lock:
            self._items[item.id] = item
            if self._db_path:
                with self._connect() as conn:
                    conn.execute(
                        "INSERT INTO items (id, title, status, payload, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            item.id,
                            item.title,
                            item.status,
                            json.dumps(item.payload),
                            item.created_at,
                            item.updated_at,
                        ),
                    )
        return item

    def get(self, item_id: str) -> Item | None:
        """Fetch one item by id (or None)."""
        return self._items.get(item_id)

    def list(self, status: str | None = None) -> list[Item]:
        """List items ordered by creation time, optionally filtered."""
        items = sorted(self._items.values(), key=lambda i: (i.created_at, i.id))
        if status:
            items = [i for i in items if i.status == status]
        return items

    def update(
        self,
        item_id: str,
        title: str | None = None,
        status: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Item:
        """Partially update an existing item."""
        with self._lock:
            item = self._items.get(item_id)
            if item is None:
                raise ValidationError(f"item {item_id} does not exist")
            new_title = title if title is not None else item.title
            new_status = status if status is not None else item.status
            self._validate(new_title, new_status)
            item.title = str(new_title).strip()
            item.status = new_status
            if payload is not None:
                item.payload = dict(payload)
            item.updated_at = _utcnow()
            if self._db_path:
                with self._connect() as conn:
                    conn.execute(
                        "UPDATE items SET title = ?, status = ?, payload = ?, updated_at = ? "
                        "WHERE id = ?",
                        (item.title, item.status, json.dumps(item.payload), item.updated_at, item.id),
                    )
        return item

    def delete(self, item_id: str) -> bool:
        """Delete an item. Returns False when the id is unknown."""
        with self._lock:
            item = self._items.pop(item_id, None)
            if item is None:
                return False
            if self._db_path:
                with self._connect() as conn:
                    conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
        return True

    def count(self, status: str | None = None) -> int:
        """Number of items, optionally filtered by status."""
        return len(self.list(status))

    def summary(self) -> dict[str, int]:
        """Per-status counts plus the total."""
        counts: dict[str, int] = {s: 0 for s in VALID_STATUSES}
        for item in self._items.values():
            counts[item.status] = counts.get(item.status, 0) + 1
        counts["total"] = len(self._items)
        return counts
'''

_API_PY = '''"""Framework-agnostic HTTP-style API layer for __NAME__ (generated by DevForge)."""
from __future__ import annotations

from typing import Any

from .core import ItemService, ValidationError


class APIError(Exception):
    """Structured API error with an HTTP-style status code."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class API:
    """Dispatches (method, path, body) tuples to service-backed handlers."""

    ROUTES: tuple[tuple[str, str], ...] = (
        ("GET", "/health"),
        ("GET", "/items"),
        ("GET", "/items/{id}"),
        ("POST", "/items"),
        ("PATCH", "/items/{id}"),
        ("DELETE", "/items/{id}"),
    )

    def __init__(self, service: ItemService | None = None) -> None:
        self.service = service or ItemService()

    def dispatch(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Route a request to its handler and return the JSON body."""
        method = (method or "GET").upper()
        body = body or {}
        parts = [p for p in path.split("/") if p != ""]
        for route_method, pattern in self.ROUTES:
            if route_method != method:
                continue
            params = self._match(pattern, parts)
            if params is None:
                continue
            return self._handle(route_method, pattern, params, body)
        raise APIError(404, f"no route for {method} {path}")

    @staticmethod
    def _match(pattern: str, parts: list[str]) -> dict[str, str] | None:
        p_parts = [p for p in pattern.split("/") if p != ""]
        if len(p_parts) != len(parts):
            return None
        params: dict[str, str] = {}
        for p, g in zip(p_parts, parts):
            if p.startswith("{") and p.endswith("}"):
                params[p[1:-1]] = g
            elif p != g:
                return None
        return params

    # -- handlers ---------------------------------------------------------
    def _handle(
        self,
        method: str,
        pattern: str,
        params: dict[str, str],
        body: dict[str, Any],
    ) -> dict[str, Any]:
        if pattern == "/health":
            return {"status": "ok"}
        if pattern == "/items" and method == "GET":
            items = self.service.list(body.get("status"))
            return {"items": [i.to_dict() for i in items]}
        if pattern == "/items" and method == "POST":
            try:
                item = self.service.create(
                    title=body.get("title"),
                    status=body.get("status", "active"),
                    payload=body.get("payload"),
                )
            except ValidationError as exc:
                raise APIError(400, str(exc)) from exc
            return {"item": item.to_dict()}
        if pattern == "/items/{id}":
            item_id = params["id"]
            if method == "GET":
                item = self.service.get(item_id)
                if item is None:
                    raise APIError(404, f"item {item_id} not found")
                return {"item": item.to_dict()}
            if method == "PATCH":
                try:
                    item = self.service.update(
                        item_id,
                        title=body.get("title"),
                        status=body.get("status"),
                        payload=body.get("payload"),
                    )
                except ValidationError as exc:
                    code = 404 if "does not exist" in str(exc) else 400
                    raise APIError(code, str(exc)) from exc
                return {"item": item.to_dict()}
            if method == "DELETE":
                if not self.service.delete(item_id):
                    raise APIError(404, f"item {item_id} not found")
                return {"deleted": True}
        raise APIError(404, "not found")


def create_api(service: ItemService | None = None) -> API:
    """Factory for the API dispatcher."""
    return API(service)
'''

_CLI_PY = '''"""Command-line interface for __NAME__ (generated by DevForge)."""
from __future__ import annotations

import argparse
import json
import sys

from .core import ItemService, ValidationError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="devforge-app",
        description="DevForge-generated application CLI",
    )
    sub = parser.add_subparsers(dest="command")
    add_p = sub.add_parser("add", help="create a new item")
    add_p.add_argument("title")
    add_p.add_argument("--status", default="active", choices=["active", "archived", "deleted"])
    sub.add_parser("list", help="list all items")
    get_p = sub.add_parser("get", help="fetch one item by id")
    get_p.add_argument("id")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    service = ItemService()
    if args.command == "add":
        try:
            item = service.create(args.title, status=args.status)
        except ValidationError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(item.to_dict(), indent=2))
        return 0
    if args.command == "list":
        print(json.dumps([i.to_dict() for i in service.list()], indent=2))
        return 0
    if args.command == "get":
        item = service.get(args.id)
        if item is None:
            print("item not found", file=sys.stderr)
            return 1
        print(json.dumps(item.to_dict(), indent=2))
        return 0
    build_parser().print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

_INIT_PY = '''"""__NAME__ — generated by the DevForge multi-agent platform."""

__version__ = "1.0.0"
'''

_CONFTEST_PY = '''"""Pytest configuration: make the workspace root importable as a package."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
'''

_GITIGNORE = """__pycache__/
*.pyc
.pytest_cache/
*.db
.env
"""


def mock_code(ctx: dict[str, Any]) -> dict[str, Any]:
    name = ctx.get("project_name") or "Generated Service"
    mode = ctx.get("mode", "initial")
    feedback = ctx.get("feedback") or ""

    def fill(tpl: str) -> str:
        return tpl.replace("__NAME__", name)

    files = [
        {
            "path": "src/__init__.py",
            "content": fill(_INIT_PY),
            "description": "package marker + version",
        },
        {
            "path": "src/core.py",
            "content": fill(_CORE_PY),
            "description": "Item model + ItemService (CRUD, validation, sqlite3 persistence)",
        },
        {
            "path": "src/api.py",
            "content": fill(_API_PY),
            "description": "framework-agnostic API dispatcher with structured errors",
        },
        {
            "path": "src/cli.py",
            "content": fill(_CLI_PY),
            "description": "argparse CLI over ItemService",
        },
        {
            "path": "conftest.py",
            "content": _CONFTEST_PY,
            "description": "pytest path configuration",
        },
        {
            "path": ".gitignore",
            "content": _GITIGNORE,
            "description": "ignore caches, databases and env files",
        },
    ]
    if mode == "initial":
        summary = (
            f"Modular stdlib-only implementation of {name}: core service, "
            "API dispatcher, CLI. Parameterized SQL, no secrets, no unsafe calls."
        )
    elif mode == "security":
        summary = (
            f"Security remediation pass on {name}: verified parameterized SQL, removed any "
            "hardcoded secrets/unsafe constructs, kept the public API stable."
        )
    else:
        summary = (
            f"Self-heal pass on {name}: adjusted the code to satisfy the failing tests "
            f"(context: {str(feedback)[:200]}); public API kept stable."
        )
    return {
        "summary": summary,
        "files": files,
        "run_instructions": (
            "From the project root: run the CLI with `python -m src.cli add \"demo\"`; "
            "run the test suite with `python -m pytest tests -q`; use the API in-process "
            "via `from src.api import create_api`."
        ),
    }


# --------------------------------------------------------------------------
# Testing Agent
# --------------------------------------------------------------------------
_TEST_CORE_PY = '''"""Unit tests for the core domain model and service (generated by DevForge TA)."""
import pytest

from src.core import VALID_STATUSES, Item, ItemService, ValidationError


@pytest.fixture()
def service() -> ItemService:
    return ItemService()


def test_create_item_defaults(service: ItemService) -> None:
    item = service.create("first")
    assert item.id
    assert item.title == "first"
    assert item.status == "active"
    assert item.payload == {}
    assert item.created_at and item.updated_at


def test_create_rejects_empty_title(service: ItemService) -> None:
    with pytest.raises(ValidationError):
        service.create("   ")


def test_create_rejects_missing_title(service: ItemService) -> None:
    with pytest.raises(ValidationError):
        service.create(None)  # type: ignore[arg-type]


def test_create_rejects_long_title(service: ItemService) -> None:
    with pytest.raises(ValidationError):
        service.create("x" * 201)


def test_create_rejects_bad_status(service: ItemService) -> None:
    with pytest.raises(ValidationError):
        service.create("t", status="bogus")


def test_get_missing_returns_none(service: ItemService) -> None:
    assert service.get("does-not-exist") is None


def test_update_title_and_status(service: ItemService) -> None:
    item = service.create("a")
    updated = service.update(item.id, title="b", status="archived")
    assert updated.title == "b"
    assert updated.status == "archived"
    assert updated.updated_at >= item.updated_at


def test_update_missing_raises(service: ItemService) -> None:
    with pytest.raises(ValidationError):
        service.update("missing")


def test_delete_flow(service: ItemService) -> None:
    item = service.create("a")
    assert service.delete(item.id) is True
    assert service.delete(item.id) is False


def test_list_filter(service: ItemService) -> None:
    service.create("a")
    service.create("b", status="archived")
    assert service.count() == 2
    assert service.count(status="archived") == 1
    assert [i.title for i in service.list(status="active")] == ["a"]


def test_summary_counts(service: ItemService) -> None:
    service.create("a")
    service.create("b", status="archived")
    s = service.summary()
    assert s["total"] == 2
    assert s["active"] == 1
    assert s["archived"] == 1


def test_persistence_roundtrip(tmp_path) -> None:
    db = tmp_path / "items.db"
    s1 = ItemService(db)
    item = s1.create("persisted", payload={"k": "v"})
    s2 = ItemService(db)
    loaded = s2.get(item.id)
    assert loaded is not None
    assert loaded.title == "persisted"
    assert loaded.payload == {"k": "v"}


def test_item_to_dict(service: ItemService) -> None:
    item = service.create("a", payload={"k": "v"})
    d = item.to_dict()
    assert d["payload"] == {"k": "v"}
    assert "created_at" in d and "updated_at" in d


def test_valid_statuses_constant() -> None:
    assert "active" in VALID_STATUSES
    assert "archived" in VALID_STATUSES
    assert "deleted" in VALID_STATUSES
'''

_TEST_API_PY = '''"""Tests for the framework-agnostic API layer (generated by DevForge TA)."""
import pytest

from src.api import API, APIError
from src.cli import main as cli_main
from src.core import ItemService


@pytest.fixture()
def api() -> API:
    return API(ItemService())


def test_health(api: API) -> None:
    assert api.dispatch("GET", "/health") == {"status": "ok"}


def test_create_and_get(api: API) -> None:
    created = api.dispatch("POST", "/items", {"title": "hello"})
    item_id = created["item"]["id"]
    got = api.dispatch("GET", f"/items/{item_id}")
    assert got["item"]["title"] == "hello"
    assert got["item"]["id"] == item_id


def test_list_filters_by_status(api: API) -> None:
    api.dispatch("POST", "/items", {"title": "a"})
    api.dispatch("POST", "/items", {"title": "b", "status": "archived"})
    res = api.dispatch("GET", "/items", {"status": "archived"})
    assert len(res["items"]) == 1
    assert res["items"][0]["title"] == "b"


def test_create_validation_error_is_400(api: API) -> None:
    with pytest.raises(APIError) as ei:
        api.dispatch("POST", "/items", {"title": "   "})
    assert ei.value.status_code == 400


def test_get_missing_is_404(api: API) -> None:
    with pytest.raises(APIError) as ei:
        api.dispatch("GET", "/items/missing")
    assert ei.value.status_code == 404


def test_patch_missing_is_404(api: API) -> None:
    with pytest.raises(APIError) as ei:
        api.dispatch("PATCH", "/items/missing", {"title": "x"})
    assert ei.value.status_code == 404


def test_patch_invalid_status_is_400(api: API) -> None:
    cid = api.dispatch("POST", "/items", {"title": "a"})["item"]["id"]
    with pytest.raises(APIError) as ei:
        api.dispatch("PATCH", f"/items/{cid}", {"status": "bogus"})
    assert ei.value.status_code == 400


def test_patch_update(api: API) -> None:
    cid = api.dispatch("POST", "/items", {"title": "a"})["item"]["id"]
    out = api.dispatch("PATCH", f"/items/{cid}", {"status": "archived"})
    assert out["item"]["status"] == "archived"


def test_delete_flow(api: API) -> None:
    cid = api.dispatch("POST", "/items", {"title": "a"})["item"]["id"]
    assert api.dispatch("DELETE", f"/items/{cid}") == {"deleted": True}
    with pytest.raises(APIError):
        api.dispatch("DELETE", f"/items/{cid}")


def test_unknown_route_is_404(api: API) -> None:
    with pytest.raises(APIError) as ei:
        api.dispatch("GET", "/nope")
    assert ei.value.status_code == 404


def test_cli_smoke() -> None:
    assert cli_main(["add", "cli-item"]) == 0
    assert cli_main(["list"]) == 0
'''


def mock_tests(ctx: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": "Deterministic pytest suite covering core service, API dispatch and CLI.",
        "strategy": (
            "Unit tests for Item/ItemService (happy paths, validation errors, edge cases, "
            "sqlite persistence via tmp_path), API dispatch tests (routes, 400/404 error paths, "
            "filters) and a CLI smoke test."
        ),
        "files": [
            {"path": "tests/test_core.py", "content": _TEST_CORE_PY, "description": "core service unit tests"},
            {"path": "tests/test_api.py", "content": _TEST_API_PY, "description": "API + CLI tests"},
        ],
    }


# --------------------------------------------------------------------------
# Documentation Agent
# --------------------------------------------------------------------------
def mock_docs(ctx: dict[str, Any]) -> dict[str, Any]:
    name = ctx.get("project_name") or "Generated Service"
    req = ctx.get("requirements") or {}
    arch = ctx.get("architecture") or {}
    files = ctx.get("files") or []
    tests = ctx.get("tests") or {}
    sec = ctx.get("security") or {}
    run_instructions = ctx.get("run_instructions") or ""
    feedback = ctx.get("feedback")

    frs = req.get("functional_requirements") or []
    endpoints = arch.get("api_endpoints") or []
    tree = arch.get("directory_structure") or ""
    modules = arch.get("modules") or []
    tech = arch.get("tech_stack") or {}

    readme = f"""# {name}

> Generated end-to-end by **DevForge** — an AI-assisted software engineering
> platform using multi-agent collaboration with human-in-the-loop approval gates.

{req.get("overview", "")}

## Quality gates passed

| Gate | Result |
|---|---|
| G1 — Requirement Approved? | ✅ approved |
| G2 — Architecture Approved? | ✅ approved |
| G3 — Code Approved? | ✅ approved |
| D4 — Tests Passed? | ✅ {tests.get("passed_count", 0)}/{tests.get("total", 0)} tests, {tests.get("duration_s", 0):.2f}s |
| D5 — Security Passed? | ✅ scanned with **{sec.get("tool", "scanner")}** |
| G6 — Docs Approved? | ✅ approved |
| GitSync — Delivery | ✅ committed, CI workflow configured |

## Features
{chr(10).join("- " + fr for fr in frs)}

## Quickstart
```bash
cd workspaces/<project-id>
python -m pytest tests -q        # run the test suite
python -m src.cli add "demo"     # use the CLI
```

{run_instructions}

## API

| Method | Path | Description |
|---|---|---|
{chr(10).join("| " + ep.get("method", "") + " | `" + ep.get("path", "") + "` | " + ep.get("description", "") + " |" for ep in endpoints)}

Full reference in [`docs/api.md`](docs/api.md).

## Project structure
```
{tree.strip() if tree else "(see repository)"}
```

## Architecture
{arch.get("summary", "")}

| Layer | Choice |
|---|---|
{chr(10).join("| " + k + " | " + str(v) + " |" for k, v in tech.items())}

Details in [`docs/architecture.md`](docs/architecture.md).
"""
    if feedback:
        readme += f"\n> Last documentation revision incorporated reviewer feedback: {str(feedback)[:300]}\n"

    api_doc = f"""# {name} — API Reference

All endpoints speak JSON. The framework-agnostic dispatcher maps
`(method, path, body)` → handler and raises `APIError(status_code, message)`
for failures, which any HTTP adapter can translate 1:1.

| Method | Path | Description | Request | Response |
|---|---|---|---|---|
{chr(10).join("| " + ep.get("method", "") + " | `" + ep.get("path", "") + "` | " + ep.get("description", "") + " | `" + ep.get("request_body", "") + "` | `" + ep.get("response", "") + "`" for ep in endpoints)}

## Error model
```json
{{"status_code": 400, "message": "title must be a non-empty string"}}
```
* `400` — validation failure (bad/missing title, invalid status)
* `404` — unknown item id or unknown route

## In-process example
```python
from src.api import APIError, create_api

api = create_api()
created = api.dispatch("POST", "/items", {{"title": "hello"}})
print(api.dispatch("GET", f"/items/{{created['item']['id']}}"))
```
"""

    arch_doc = f"""# {name} — Architecture Summary

{arch.get("summary", "")}

## Modules
{chr(10).join("### " + m.get("name", "") + chr(10) + m.get("responsibility", "") + chr(10) + "Files: " + ", ".join("`" + f + "`" for f in m.get("files", [])) + chr(10) for m in modules)}
## Data model
{arch.get("data_model", "")}

## Design decisions
* **Standard library only** in `src/` so the generated code runs and tests in
  any isolated environment with zero installs.
* **Parameterized SQL** everywhere — no string-interpolated queries.
* **Framework-agnostic API layer** — the dispatcher can be mounted behind
  FastAPI/Flask/WSGI without changes.
* **Service owns concurrency** — a single lock guards the record map;
  persistence is best-effort per operation.
"""
    return {
        "readme": readme,
        "api_documentation": api_doc,
        "architecture_summary": arch_doc,
    }
