"""Deterministic domain inference shared by the Architecture and Developer agents.

Given approved requirements (or the raw human input), this module derives:

* the **domain entities** the application manipulates, with typed fields;
* the **technology stack** that fits the requested application type;
* the **REST API surface** implied by the requirements;
* the **project file layout** the Developer Agent should create.

It contains no project-specific hard-coding: everything is driven by keyword and
capability analysis of the requirement text, so the same code paths serve any
project a user types in. Live mode lets the LLM refine this structure; mock mode
uses these derivations directly (and marks the output as MOCK MODE).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# --------------------------------------------------------------------------- #
# Entity seeds: conventional field sets for common domains
# --------------------------------------------------------------------------- #


@dataclass
class FieldSpec:
    name: str
    python_type: str = "str"
    sql_type: str = "TEXT"
    required: bool = False
    description: str = ""
    example: str = ""

    @property
    def ts_type(self) -> str:
        return {"str": "string", "int": "number", "float": "number", "bool": "boolean",
                "datetime": "string"}.get(self.python_type, "string")


@dataclass
class EntitySpec:
    name: str                      # PascalCase singular, e.g. "Task"
    table: str                     # snake_case plural, e.g. "tasks"
    description: str = ""
    fields: list[FieldSpec] = field(default_factory=list)
    requirement_refs: list[str] = field(default_factory=list)
    keywords: tuple[str, ...] = ()

    @property
    def route(self) -> str:
        return f"/api/{self.table}"

    @property
    def module(self) -> str:
        return self.table


@dataclass
class DomainModel:
    entities: list[EntitySpec]
    primary: EntitySpec
    application_type: str
    roles: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    requires_auth: bool = True

    def to_dict(self) -> dict:
        return {
            "application_type": self.application_type,
            "primary_entity": self.primary.name,
            "roles": self.roles,
            "requires_auth": self.requires_auth,
            "entities": [
                {
                    "name": entity.name,
                    "table": entity.table,
                    "description": entity.description,
                    "requirement_refs": entity.requirement_refs,
                    "fields": [
                        {
                            "name": f.name, "type": f.python_type, "sql_type": f.sql_type,
                            "required": f.required, "description": f.description, "example": f.example,
                        }
                        for f in entity.fields
                    ],
                }
                for entity in self.entities
            ],
        }


# Word -> entity template. `keywords` drive detection from the requirement text.
ENTITY_TEMPLATES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("Task", "tasks", ("task", "todo", "to-do", "assignment", "chore", "activity", "item")),
    ("User", "users", ("user", "student", "account", "member", "employee", "customer",
                       "patient", "admin", "teacher", "client")),
    ("Project", "projects", ("project", "workspace", "initiative")),
    ("Course", "courses", ("course", "subject", "class", "module")),
    ("Product", "products", ("product", "item", "goods", "catalog", "catalogue", "inventory")),
    ("Order", "orders", ("order", "purchase", "checkout", "cart", "invoice")),
    ("Appointment", "appointments", ("appointment", "booking", "schedule", "slot", "session")),
    ("Expense", "expenses", ("expense", "transaction", "payment", "budget", "cost")),
    ("Note", "notes", ("note", "memo", "journal", "diary", "entry")),
    ("Event", "events", ("event", "meeting", "conference", "webinar")),
    ("Document", "documents", ("document", "file", "attachment", "report", "paper")),
    ("Ticket", "tickets", ("ticket", "issue", "bug", "complaint", "request")),
    ("Patient", "patients", ("patient", "prescription")),
    ("Book", "books", ("book", "library", "borrow")),
    ("Recipe", "recipes", ("recipe", "ingredient", "meal")),
)

BASE_FIELDS: dict[str, list[FieldSpec]] = {
    "Task": [
        FieldSpec("title", required=True, description="Short description of the task",
                  example="Submit assignment"),
        FieldSpec("description", description="Optional longer detail", example="Chapter 4 exercises"),
        FieldSpec("status", description="Workflow state", example="pending"),
        FieldSpec("priority", description="Relative importance", example="medium"),
        FieldSpec("due_date", python_type="datetime", description="Deadline for the task",
                  example="2026-01-15T17:00:00"),
    ],
    "User": [
        FieldSpec("full_name", required=True, description="Display name", example="Asha Rao"),
        FieldSpec("email", required=True, description="Unique sign-in identifier",
                  example="asha@example.com"),
        FieldSpec("role", description="Authorisation role", example="student"),
        FieldSpec("is_active", python_type="bool", description="Whether the account can sign in",
                  example="true"),
    ],
    "Project": [
        FieldSpec("name", required=True, description="Project name", example="Capstone"),
        FieldSpec("description", description="Summary of the project", example="Final year project"),
        FieldSpec("status", description="Lifecycle state", example="active"),
    ],
    "Course": [
        FieldSpec("title", required=True, description="Course title", example="Data Structures"),
        FieldSpec("code", description="Course code", example="CS201"),
        FieldSpec("credits", python_type="int", description="Credit value", example="4"),
    ],
    "Product": [
        FieldSpec("name", required=True, description="Product name", example="Wireless mouse"),
        FieldSpec("price", python_type="float", required=True, description="Unit price",
                  example="799.00"),
        FieldSpec("stock", python_type="int", description="Units available", example="25"),
    ],
    "Order": [
        FieldSpec("reference", required=True, description="Human readable order reference",
                  example="ORD-1001"),
        FieldSpec("total", python_type="float", description="Order total", example="1598.00"),
        FieldSpec("status", description="Fulfilment state", example="placed"),
    ],
    "Appointment": [
        FieldSpec("title", required=True, description="Purpose of the appointment", example="Checkup"),
        FieldSpec("scheduled_at", python_type="datetime", required=True,
                  description="Date and time of the appointment", example="2026-02-01T10:30:00"),
        FieldSpec("status", description="Booking state", example="booked"),
    ],
    "Expense": [
        FieldSpec("description", required=True, description="What the money was spent on",
                  example="Lab equipment"),
        FieldSpec("amount", python_type="float", required=True, description="Amount spent",
                  example="1450.75"),
        FieldSpec("category", description="Expense category", example="equipment"),
        FieldSpec("spent_on", python_type="datetime", description="Date of the expense",
                  example="2026-01-20T00:00:00"),
    ],
    "Note": [
        FieldSpec("title", required=True, description="Note title", example="Sprint retro"),
        FieldSpec("body", description="Note content", example="What went well..."),
    ],
    "Event": [
        FieldSpec("title", required=True, description="Event name", example="Project review"),
        FieldSpec("starts_at", python_type="datetime", required=True, description="Start time",
                  example="2026-03-05T09:00:00"),
        FieldSpec("location", description="Where the event happens", example="Seminar hall"),
    ],
    "Document": [
        FieldSpec("title", required=True, description="Document title", example="Design spec"),
        FieldSpec("content", description="Document body", example="..."),
        FieldSpec("version", python_type="int", description="Revision number", example="1"),
    ],
    "Ticket": [
        FieldSpec("title", required=True, description="Issue summary", example="Login fails"),
        FieldSpec("description", description="Details and reproduction steps", example="..."),
        FieldSpec("severity", description="Impact level", example="high"),
    ],
    "Patient": [
        FieldSpec("full_name", required=True, description="Patient name", example="Ravi Kumar"),
        FieldSpec("age", python_type="int", description="Age in years", example="34"),
    ],
    "Book": [
        FieldSpec("title", required=True, description="Book title", example="Clean Code"),
        FieldSpec("author", description="Author name", example="Robert Martin"),
        FieldSpec("available", python_type="bool", description="Whether the book can be borrowed",
                  example="true"),
    ],
    "Recipe": [
        FieldSpec("name", required=True, description="Recipe name", example="Masala dosa"),
        FieldSpec("ingredients", description="Ingredient list", example="rice, urad dal"),
    ],
}

# Extra fields implied by capability keywords in the requirements.
CONDITIONAL_FIELDS: tuple[tuple[tuple[str, ...], FieldSpec], ...] = (
    (("completed", "complete", "done", "finish"), FieldSpec(
        "completed_at", python_type="datetime", description="When the item was completed",
        example="2026-01-16T12:00:00")),
    (("assign", "assigned", "owner", "responsible"), FieldSpec(
        "assigned_to", description="Person responsible", example="asha@example.com")),
    (("reminder", "notify", "notification"), FieldSpec(
        "reminder_at", python_type="datetime", description="When to send a reminder",
        example="2026-01-14T09:00:00")),
    (("tag", "tags", "label", "category"), FieldSpec(
        "tags", description="Comma separated labels", example="college,urgent")),
    (("search", "filter", "sort", "query"), FieldSpec(
        "search_index", description="Denormalised text used for filtering and search",
        example="submit assignment chapter 4")),
)

AUTH_KEYWORDS = ("login", "sign in", "sign-in", "register", "sign up", "sign-up", "auth",
                 "password", "account", "session", "jwt", "role", "permission")

MOBILE_KEYWORDS = ("android", "ios", "mobile app", "react native", "flutter")
AI_KEYWORDS = ("machine learning", "ml model", "artificial intelligence", " ai ", "prediction",
               "recommendation", "classifier", "llm")
REALTIME_KEYWORDS = ("real time", "real-time", "live update", "websocket", "chat", "notification")
ANALYTICS_KEYWORDS = ("report", "analytics", "dashboard", "chart", "statistics", "insight")
PAYMENT_KEYWORDS = ("payment", "checkout", "invoice", "razorpay", "stripe", "billing")

KNOWN_ROLES = {
    "student": "Student", "teacher": "Teacher", "faculty": "Faculty", "admin": "Administrator",
    "administrator": "Administrator", "customer": "Customer", "client": "Client",
    "user": "End User", "manager": "Manager", "employee": "Employee", "patient": "Patient",
    "doctor": "Doctor", "seller": "Seller", "vendor": "Vendor", "member": "Member",
    "moderator": "Moderator", "instructor": "Instructor", "librarian": "Librarian",
}


def _singularise(word: str) -> str:
    if word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith("ses") or word.endswith("xes") or word.endswith("ches"):
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _pluralise(word: str) -> str:
    if word.endswith("y") and not word.endswith(("ay", "ey", "oy", "uy")):
        return word[:-1] + "ies"
    if word.endswith(("s", "x", "ch", "sh")):
        return word + "es"
    return word + "s"


def detect_application_type(text: str) -> str:
    lowered = f" {text.lower()} "
    if any(keyword in lowered for keyword in MOBILE_KEYWORDS):
        return "mobile application with web API backend"
    if any(keyword in lowered for keyword in REALTIME_KEYWORDS):
        return "real-time web application"
    if "cli" in lowered or "command line" in lowered or "terminal" in lowered:
        return "command line application"
    if any(keyword in lowered for keyword in ("web application", "website", "web app", "portal",
                                              "web-based", "browser")):
        return "web application"
    if "api" in lowered and "ui" not in lowered and "interface" not in lowered:
        return "REST API service"
    return "web application"


def detect_roles(text: str) -> list[str]:
    lowered = text.lower()
    roles: list[str] = []
    for keyword, label in KNOWN_ROLES.items():
        if re.search(rf"\b{re.escape(keyword)}s?\b", lowered) and label not in roles:
            roles.append(label)
    if not roles:
        roles = ["End User"]
    if "Administrator" not in roles and any(
        word in lowered for word in ("admin", "manage users", "roles", "permission")
    ):
        roles.append("Administrator")
    return roles


def detect_capabilities(text: str) -> list[str]:
    lowered = text.lower()
    capabilities: list[str] = []
    checks = (
        (("create", "add"), "create"),
        (("view", "list", "display", "see"), "read"),
        (("update", "edit", "modify"), "update"),
        (("delete", "remove"), "delete"),
        (("search", "filter", "sort"), "search"),
        (("login", "sign in", "register", "auth"), "authentication"),
        (("report", "dashboard", "analytics", "statistics"), "reporting"),
        (("upload", "attach"), "file-upload"),
        (("notify", "notification", "email", "reminder"), "notifications"),
        (("payment", "checkout", "invoice", "billing"), "payments"),
        (("export", "download", "csv", "pdf"), "export"),
    )
    for keywords, capability in checks:
        if any(keyword in lowered for keyword in keywords):
            capabilities.append(capability)
    return capabilities or ["create", "read", "update", "delete"]


def infer_entities(text: str, functional_requirements: list[dict] | None = None) -> list[EntitySpec]:
    """Detect the domain entities referenced by the requirements."""
    functional_requirements = functional_requirements or []
    haystack = " ".join(
        [text]
        + [f"{item.get('title', '')} {item.get('description', '')}" for item in functional_requirements]
    )
    lowered = haystack.lower()

    entities: list[EntitySpec] = []
    for name, table, keywords in ENTITY_TEMPLATES:
        pattern = "|".join(rf"\b{re.escape(keyword)}s?\b" for keyword in keywords)
        if re.search(pattern, lowered):
            refs = [
                item["id"]
                for item in functional_requirements
                if re.search(pattern, f"{item.get('title', '')} {item.get('description', '')}".lower())
            ]
            fields = [FieldSpec(**vars(field)) for field in BASE_FIELDS.get(name, [])]
            entities.append(
                EntitySpec(
                    name=name,
                    table=table,
                    description=f"{name} records managed by the application.",
                    fields=fields,
                    requirement_refs=refs,
                    keywords=keywords,
                )
            )

    if not entities:
        # Fall back to the most frequent meaningful noun in the requirement text.
        tokens = [t.lower() for t in re.findall(r"[A-Za-z]{4,}", text)]
        stop = {"build", "create", "application", "system", "users", "should", "where", "must",
                "able", "with", "that", "their", "them", "this", "from", "have", "will",
                "page", "view", "data", "list", "each", "other", "manage", "using"}
        counts: dict[str, int] = {}
        for token in tokens:
            if token in stop:
                continue
            counts[token] = counts.get(token, 0) + 1
        candidate = max(counts.items(), key=lambda kv: kv[1])[0] if counts else "record"
        singular = _singularise(candidate)
        entities.append(
            EntitySpec(
                name=singular.capitalize(),
                table=_pluralise(singular),
                description=f"{singular.capitalize()} records managed by the application.",
                fields=[
                    FieldSpec("title", required=True, description="Short name",
                              example=f"{singular.capitalize()} one"),
                    FieldSpec("description", description="Details", example="..."),
                    FieldSpec("status", description="Current state", example="active"),
                ],
            )
        )

    # Always model the account/authorisation entity when the app is authenticated.
    if any(keyword in lowered for keyword in AUTH_KEYWORDS) and not any(
        entity.name == "User" for entity in entities
    ):
        entities.append(
            EntitySpec(
                name="User",
                table="users",
                description="Application accounts used for sign-in and authorisation.",
                fields=[FieldSpec(**vars(field)) for field in BASE_FIELDS["User"]],
                keywords=("user", "account"),
            )
        )

    # Conditional fields derived from capability keywords.
    for entity in entities:
        existing = {f.name for f in entity.fields}
        for keywords, extra in CONDITIONAL_FIELDS:
            if any(keyword in lowered for keyword in keywords) and extra.name not in existing:
                entity.fields.append(FieldSpec(**vars(extra)))
                existing.add(extra.name)

    # The primary entity is the domain object the application is *about*: the most
    # referenced non-account entity. "User" is a supporting entity and only becomes
    # primary when the project is genuinely an identity service.
    domain_entities = [entity for entity in entities if entity.name != "User"]
    candidates = domain_entities or entities
    primary = max(candidates, key=lambda entity: len(entity.requirement_refs))
    return [primary] + [entity for entity in entities if entity is not primary]


def infer_domain(text: str, functional_requirements: list[dict] | None = None,
                 roles: list[str] | None = None) -> DomainModel:
    entities = infer_entities(text, functional_requirements)
    capabilities = detect_capabilities(text)
    resolved_roles = roles or detect_roles(text)
    lowered = text.lower()
    # An application needs identity handling when credentials, roles or accounts
    # are mentioned, or when several user roles share the same system.
    requires_auth = (
        any(keyword in lowered for keyword in AUTH_KEYWORDS)
        or "authentication" in capabilities
        or len(resolved_roles) >= 2
        or any(entity.name == "User" for entity in entities)
    )
    return DomainModel(
        entities=entities,
        primary=entities[0],
        application_type=detect_application_type(text),
        roles=resolved_roles,
        capabilities=capabilities,
        requires_auth=requires_auth,
    )


def infer_tech_stack(text: str) -> dict[str, str]:
    """Recommended stack for the requested application type (deterministic)."""
    lowered = f" {text.lower()} "
    stack = {
        "frontend": "React 18 + TypeScript + Vite + Tailwind CSS",
        "backend": "Python 3.11+ with FastAPI (Pydantic v2 for validation)",
        "database": "PostgreSQL 16 (SQLite for local development and automated tests)",
        "orm": "SQLAlchemy 2.0",
        "authentication": "JWT bearer tokens with hashed passwords (bcrypt/pbkdf2)",
        "testing": "pytest (backend) + Vitest + React Testing Library (frontend)",
        "deployment": "Docker + Docker Compose (single host)",
        "api_style": "REST with OpenAPI documentation generated by FastAPI",
    }
    if any(keyword in lowered for keyword in MOBILE_KEYWORDS):
        stack["frontend"] = "React Native (Expo) for Android/iOS with the same REST API"
    if any(keyword in lowered for keyword in AI_KEYWORDS):
        stack["ml"] = "scikit-learn model served through a FastAPI inference endpoint"
    if any(keyword in lowered for keyword in REALTIME_KEYWORDS):
        stack["realtime"] = "Server-Sent Events for one-way updates (WebSocket if bidirectional)"
    if any(keyword in lowered for keyword in ANALYTICS_KEYWORDS):
        stack["reporting"] = "SQL aggregate queries exposed through dedicated report endpoints"
    if any(keyword in lowered for keyword in PAYMENT_KEYWORDS):
        stack["payments"] = "Hosted checkout provider (no card data stored by the application)"
    return stack


def crud_endpoints(entity: EntitySpec, *, requires_auth: bool = True) -> list[dict]:
    """REST surface for an entity, following conventional resource design."""
    secured = "Bearer JWT required" if requires_auth else "Public"
    endpoints = [
        {"method": "GET", "path": entity.route, "purpose": f"List {entity.table} with paging, "
                                                           "filtering and sorting",
         "auth": secured, "returns": f"list[{entity.name}]"},
        {"method": "POST", "path": entity.route, "purpose": f"Create a {entity.name.lower()}",
         "auth": secured, "returns": entity.name},
        {"method": "GET", "path": f"{entity.route}/{{id}}", "purpose": f"Fetch one {entity.name.lower()}",
         "auth": secured, "returns": entity.name},
        {"method": "PUT", "path": f"{entity.route}/{{id}}", "purpose": f"Update a {entity.name.lower()}",
         "auth": secured, "returns": entity.name},
        {"method": "DELETE", "path": f"{entity.route}/{{id}}", "purpose": f"Delete a {entity.name.lower()}",
         "auth": secured, "returns": "204 No Content"},
    ]
    field_names = {f.name for f in entity.fields}
    if "status" in field_names:
        endpoints.append(
            {"method": "PATCH", "path": f"{entity.route}/{{id}}/status",
             "purpose": f"Change the workflow status of a {entity.name.lower()}",
             "auth": secured, "returns": entity.name}
        )
    if "completed_at" in field_names:
        endpoints.append(
            {"method": "POST", "path": f"{entity.route}/{{id}}/complete",
             "purpose": f"Mark a {entity.name.lower()} as completed",
             "auth": secured, "returns": entity.name}
        )
    return endpoints


def project_layout(domain: DomainModel) -> list[dict]:
    """Files the Developer Agent creates for the inferred domain (mock mode plan)."""
    primary = domain.primary
    layout = [
        {"path": "backend/app/__init__.py", "purpose": "Package marker", "component_ref": "ARCH-002"},
        {"path": "backend/app/main.py",
         "purpose": "FastAPI application factory and router wiring", "component_ref": "ARCH-002"},
        {"path": "backend/app/config.py",
         "purpose": "Environment driven settings", "component_ref": "ARCH-002"},
        {"path": "backend/app/database.py",
         "purpose": "Engine, session factory and base model", "component_ref": "ARCH-004"},
        {"path": "backend/app/models.py",
         "purpose": f"SQLAlchemy models ({', '.join(e.name for e in domain.entities)})",
         "component_ref": "ARCH-004"},
        {"path": "backend/app/schemas.py",
         "purpose": "Pydantic request/response schemas", "component_ref": "ARCH-002"},
        {"path": "backend/app/crud.py",
         "purpose": "Data access functions used by the routers", "component_ref": "ARCH-004"},
        {"path": f"backend/app/routers/{primary.table}.py",
         "purpose": f"{primary.name} REST endpoints", "component_ref": "ARCH-003"},
        {"path": "backend/requirements.txt",
         "purpose": "Pinned runtime dependencies", "component_ref": "ARCH-002"},
        {"path": f"backend/tests/test_{primary.table}_api.py",
         "purpose": "API tests for the primary workflow", "component_ref": "ARCH-002"},
        {"path": ".gitignore", "purpose": "Repository hygiene", "component_ref": "ARCH-002"},
    ]
    if domain.requires_auth:
        layout.insert(8, {"path": "backend/app/security.py",
                          "purpose": "Password hashing and signed token helpers",
                          "component_ref": "ARCH-006"})
        layout.insert(9, {"path": "backend/app/auth.py",
                          "purpose": "Registration, login and profile endpoints",
                          "component_ref": "ARCH-006"})
    return layout
