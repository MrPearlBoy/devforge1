# DevForge — AI-Assisted Software Engineering Platform

DevForge turns a plain-language product idea into a reviewed, tested, documented and
deliverable software repository. Six specialist AI agents — **Requirement, Architecture,
Developer, Testing, Security and Documentation** — work over a shared workflow state
orchestrated with **LangGraph**, and a human approves every stage before the pipeline moves
on. Every artefact is stored, versioned and traceable from requirement to documentation.

> Final-year academic project. DevForge is an original implementation; it is not derived
> from any existing repository.

---

## 1. What it does

```
 idea ─▶ Requirement ─▶ [approval] ─▶ Architecture ─▶ [approval] ─▶ Developer ─▶ [approval]
                                                                                   │
       Documentation ◀─ [approval] ◀─ Security ◀─ [approval] ◀─ Testing ◀───────────┘
              │
              ▼
        Delivery (GitHub connect → branch → commit → push, always human-confirmed)
```

* **Six agents**, each with its own prompt, output schema and artefact type.
* **Human-in-the-loop at every major stage** — `PENDING / APPROVED / REJECTED /
  CHANGES_REQUESTED`, recorded with the deciding user, comments, instruction and timestamp.
* **Traceability** — `REQ-001 → ARCH-003 → CODE app/routers/tasks.py → TEST …::test_list_tasks
  → SEC-… → DOC README.md`, with a coverage and gap report.
* **Sandboxed execution** — AI-generated code is never executed directly on the host: a
  restricted subprocess (allow-listed binaries, no shell, CPU/memory/time limits, process
  group kill) or Docker when a daemon is available.
* **Chat with any agent** — proposals become change sets behind an approval gate; chat can
  never write to your workspace on its own.
* **Mock and live modes** — `DEVFORGE_MODE=mock` gives deterministic, obviously-labelled
  outputs (no API key, perfect for demos and grading); `live` routes every call through a
  provider-agnostic `LLMGateway`.
* **GitHub delivery** with explicit human confirmation before any remote write; tokens are
  encrypted at rest and never returned by the API.

---

## 2. Architecture

| Layer | Technology | Notes |
|---|---|---|
| Orchestration | LangGraph 1.x (`StateGraph`, `interrupt`, `Command`, SQLite checkpointer) | durable runs, bounded revision loops |
| API | FastAPI + Pydantic v2 | one router per bounded area under `/api` |
| Services | SQLAlchemy 2.x services (agents, artifacts, approvals, traceability, knowledge, git) | no business logic in routes |
| Agents | Provider-agnostic `LLMGateway` (`generate`, `generate_structured`, `stream`, `embed`) | mock and live share one contract |
| Database | PostgreSQL (production) / SQLite (dev, tests, demo) | Alembic migrations |
| Frontend | React 19 + TypeScript + Vite + Tailwind | Monaco editor for code review |
| Execution | Restricted subprocess or Docker sandbox | never on the host |

```
devforge/
├── backend/
│   ├── app/
│   │   ├── agents/          # requirement, architecture, developer, testing, security, documentation
│   │   ├── api/routes/      # auth, projects, workflow, agents, approvals, artifacts,
│   │   │                    # execution(tests/security/sandbox), repositories(github), trace, activity
│   │   ├── core/            # config, database, security, crypto, errors, events, logging
│   │   ├── models/          # 20 SQLAlchemy tables (UUID PKs, UTC timestamps, FKs, JSON)
│   │   ├── schemas/         # request/response contracts
│   │   ├── services/        # project, agent runtime, artifacts, approvals, change sets,
│   │   │                    # traceability, knowledge/vector store, github, audit
│   │   ├── tools/           # llm gateway, sandbox executors, test runner, static analyzer, git
│   │   ├── workflows/       # state, nodes (6 agents + gates + delivery), graph, engine
│   │   └── main.py          # application factory
│   ├── migrations/          # Alembic
│   ├── scripts/             # smoke_*, seed_demo, run_workflow
│   └── tests/               # pytest suite
├── frontend/                # React + TS + Vite + Tailwind + Monaco
├── docs/
├── workspace/               # generated project files (one directory per project)
├── docker-compose.yml
└── .env.example
```

---

## 3. Quick start (local, SQLite — fastest path)

```bash
git clone <your-repo> devforge && cd devforge

# 1. backend
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt

# 2. configure (SQLite needs no server; a strong SECRET_KEY keeps stored tokens decryptable)
cp ../.env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"   # paste into SECRET_KEY
# in .env set:  DATABASE_URL=sqlite:///./devforge.db   and   DEVFORGE_MODE=mock

# 3. schema + demo data (creates demo@devforge.dev / devforge123 and a completed demo project)
python scripts/seed_demo.py --run-workflow

# 4. API
uvicorn app.main:app --reload --port 8000     # docs at http://localhost:8000/docs

# 5. frontend (second terminal)
cd ../frontend
npm install
npm run dev                                    # http://localhost:5173
```

Sign in with **demo@devforge.dev / devforge123**, open *Student Task Management System* and
walk the stages, artifacts, tests, security findings, traceability matrix and delivery tab.

---

## 4. Configuration

All configuration is environment-driven; copy `.env.example` to `.env` (never commit it).

| Variable | Purpose | Default |
|---|---|---|
| `SECRET_KEY` | signs JWTs **and** derives the Fernet key that encrypts stored GitHub tokens | dev placeholder — always change |
| `DATABASE_URL` | `postgresql+psycopg2://user:pass@host:5432/devforge` or `sqlite:///./devforge.db` | SQLite file |
| `DEVFORGE_MODE` | `mock` \| `live` \| `auto` | `auto` |
| `LLM_PROVIDER` / `LLM_API_KEY` / `LLM_MODEL` | provider-agnostic LLM access (openai, azure_openai, anthropic, openai_compatible, ollama, mock) | `mock` |
| `EMBEDDING_PROVIDER` / `VECTOR_BACKEND` | retrieval for project memory (`auto` → pgvector when available, JSON fallback) | `auto` |
| `WORKSPACE_ROOT` | where generated projects are written | `./workspace` |
| `MAX_STAGE_ITERATIONS` | revision budget per stage before the workflow escalates to a human | `3` |
| `MAX_TOTAL_STEPS` | hard guard against runaway workflows | `60` |
| `EXECUTION_PROVIDER` | `subprocess` \| `docker` \| `disabled` | `subprocess` |
| `EXECUTION_ALLOWED_COMMANDS` | executables the sandbox may run | `python,python3,pytest,node,npm,git` |
| `GITHUB_TOKEN` | fallback token when a project has none stored | empty |
| `CORS_ORIGINS` | frontend origins | `http://localhost:5173` |

**Mock vs live.** `mock` never contacts a provider: every agent returns deterministic,
context-derived output and marks it clearly as mock (API responses, UI badges, artefact
metadata). `live` uses the configured provider and real embeddings. `auto` picks live only
when a provider other than `mock` is configured **and** a key (or Ollama) is present.
Mock mode cannot reason through arbitrary test failures. To enable the Developer Agent's
test-fix reasoning, configure a live provider and set `DEVFORGE_MODE=live` (or use
`DEVFORGE_MODE=auto` with a supported provider and credentials). After changing `.env`,
restart the backend. The agent receives the failing test file and failure output alongside
the implementation files, then returns a reviewable code change set for approval.

---

## 5. Database & migrations

```bash
cd backend
alembic upgrade head                      # apply migrations
alembic revision --autogenerate -m "add x"  # create a migration from model changes
alembic downgrade -1                      # roll back one revision
```

* 20 tables, UUID primary keys (stored as portable UUIDs), UTC timestamps, real foreign
  keys with `ON DELETE` rules and JSON columns — the same schema runs on SQLite and
  PostgreSQL.
* Development convenience: `AUTO_CREATE_SCHEMA=true` (default) creates tables on startup.
  In production set it to `false` and run Alembic.
* Test suites use a temporary SQLite database; nothing touches your development data.

---

## 6. Docker

```bash
cp .env.example .env         # set SECRET_KEY (and LLM keys if you want live mode)
docker compose up --build    # db (pgvector) + api + frontend
docker compose exec api alembic upgrade head
docker compose exec api python scripts/seed_demo.py
```

* Services: `db` (PostgreSQL 16 + pgvector), `api` (uvicorn), `frontend` (Vite dev server or
  built image), optional `sandbox` image for `EXECUTION_PROVIDER=docker`.
* The compose file is verified for syntax and service wiring; the application itself is also
  fully runnable without Docker (section 3).

---

## 7. GitHub integration

1. **Connect** — `Projects → Delivery → Connect repository`, paste a URL and (optionally) a
   fine-grained token with `contents: write`.
   * the token is encrypted with a Fernet key derived from `SECRET_KEY` **before** it is
     stored; the API returns only a masked hint and never the token itself;
   * DevForge works on a dedicated branch (`devforge/<slug>`); your default branch is never
     pushed to implicitly.
2. **Review** — `GET /api/projects/{id}/repository/plan` shows exactly what would be
   committed (branch, files, suggested message). Nothing runs.
3. **Confirm** — commit / push require `confirm: true`, which the UI only sends after you
   accept an explicit confirmation dialog. Every remote operation is written to
   `git_operations` with the confirming user and to the audit log. Force-push and history
   rewriting are not implemented anywhere in the codebase.
4. **Pull requests** — optional on push: `create_pull_request: true` opens a PR from the
   working branch to the base branch using your token.

---

## 8. Testing

```bash
cd backend
pytest -q                                    # full backend suite
python scripts/smoke_pipeline.py --stages all  # 6-agent pipeline in mock mode
python scripts/smoke_api.py                  # 60 HTTP checks across the whole API
python scripts/run_workflow.py               # LangGraph workflow driven from the CLI
npm run build && npm run lint                # frontend (in frontend/)
```

* `pytest` covers authentication, project ownership boundaries, the full workflow with its
  human gates, artefact production, sandbox restrictions (allow-list, path traversal,
  shell metacharacters), traceability and the GitHub confirmation rules.
* `smoke_pipeline.py` proves the agents end-to-end: 6 agents produce artefacts, the
  generated project's own test suite runs in the sandbox (**16/16 passing**), the security
  agent scans 25 files and the documentation agent writes six documents.
* `smoke_api.py` drives the real HTTP surface with a `TestClient` and a temporary database
  (60 assertions: auth, workflow, artefacts, tests, security, traceability, audit, git).
* Results from the last full run are recorded in [`docs/VERIFICATION.md`](docs/VERIFICATION.md).

---

## 9. Security notes

* **No generated code touches the host directly.** Execution goes through the sandbox
  abstraction: allow-listed binaries only, no shell, arguments containing shell
  metacharacters are rejected, paths are confined to `WORKSPACE_ROOT`, and there are
  wall-clock, memory and CPU limits with process-group termination.
* **Secrets**: nothing is hard-coded; `.env` is git-ignored; GitHub tokens are encrypted at
  rest; JWTs are signed with `SECRET_KEY`; passwords are hashed with PBKDF2-HMAC-SHA256
  (240 000 iterations).
* **Human authority**: no stage advances without a recorded decision, no remote git write
  happens without explicit confirmation, and the workflow has bounded revision budgets so it
  can never loop forever.
* **Honesty about limits**: the security agent's report states plainly that automated
  static analysis plus model review complements, but does not replace, a professional audit.
  Mock mode is always labelled as mock.

---

## 10. API overview

| Area | Endpoints |
|---|---|
| Platform | `GET /api/health`, `/api/config`, `/api/stats`, `GET /api/projects/{id}/events` (SSE) |
| Auth | `POST /api/auth/register`, `/api/auth/login`, `GET /api/auth/me` |
| Projects | `GET/POST /api/projects`, `GET/PUT/DELETE /api/projects/{id}`, `…/dashboard`, `…/tasks` |
| Workflow | `POST …/workflow/start`, `GET …/workflow`, `POST …/workflow/resume`, `…/runs`, `…/runs/{id}/steps` |
| Agents | `GET /api/agents`, `/api/agents/specs`, `…/agents/status`, `…/executions`, chat: `POST/GET …/chat` |
| Approvals | `GET …/approvals`, `/pending`, `POST /api/approvals/{id}/approve\|reject\|changes` |
| Artefacts | `GET …/artifacts`, `/api/artifacts/{id}` (+ `/versions`), workspace tree/file |
| Execution | `…/tests`, `…/tests/latest`, `POST …/tests/run`, `…/security/findings`, `…/security/summary`, `…/sandbox` |
| GitHub | `…/repository` (status/connect/disconnect), `/plan`, `/commit`, `/push`, `/commits`, `/operations`, `/delivery` |
| Traceability | `GET …/trace`, `…/trace/links`, `…/trace/ref/{ref}`, `…/trace/coverage` |
| Activity | `GET …/activity`, `…/activity/summary`, `/api/activity/labels` |

Interactive documentation: `http://localhost:8000/docs`.

---

## 11. Demo script (viva / evaluation)

1. `python scripts/seed_demo.py --run-workflow` — or start from an empty project to show the
   gates live.
2. Create a project with the §37 scenario: *students create/update/delete/complete tasks,
   filter by deadline; an administrator manages accounts.*
3. **Start workflow** → the Requirement Agent drafts a specification → open the **approval
   card**, click **Request changes** with a note, and watch the agent rework it (the revision
   budget is visible).
4. Approve → Architecture → approve → Developer proposes a change set (review the diff in the
   approval card) → approve → the code lands in the workspace (see the **Code** tab).
5. Testing Agent plans, writes and runs the suite in the sandbox (16/16) → approve →
   Security Agent reports findings (triage one as *false positive*) → approve →
   Documentation Agent writes README + five documents.
6. Show **Traceability** (REQ-001 chain), **Activity** (audit log), **Agents** (executions and
   durations) and **Delivery** (checklist, plan, confirmed commit; push is disabled until you
   connect a repository and confirm).
7. Switch `DEVFORGE_MODE=live` (with a key) to show the same workflow with a real model, and
   point out the mock badge disappearing.

The fast path for a live demo: `python scripts/seed_demo.py --run-workflow`, then open the UI,
sign in as `demo@devforge.dev / devforge123` and walk the tabs — the project is already at
100 % with artefacts, a passing suite, findings, a trace matrix and a delivery checklist.

---

## 12. Project status & known limits

* Verified natively on Python 3.13 + SQLite: backend suite (**51 passing**), pipeline smoke
  (**16/16 generated tests passing**), API smoke (**60 checks, all green**) and the CLI
  workflow (COMPLETED). Full evidence log: [`docs/VERIFICATION.md`](docs/VERIFICATION.md).
* Frontend: `tsc --noEmit` is clean under strict mode and `vite build` produces a 371 kB
  bundle (112 kB gzipped). Monaco is loaded lazily; if the editor assets are unreachable the
  code view falls back to a read-only block instead of failing.
* Docker Compose is syntax-checked but was not executed in the development environment used
  for this report (no Docker daemon available there).
* Vector retrieval falls back to a deterministic local embedding backend when no embedding
  provider is configured — good enough for a demo, marked as such in the UI.
* The task sandbox is a restricted subprocess by default; set `EXECUTION_PROVIDER=docker` for
  container-level isolation.

---

"# devforge1" 
"# devforge1" 
