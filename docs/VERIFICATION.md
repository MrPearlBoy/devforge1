# DevForge — verification log

Evidence produced while building the platform. Every command below is reproducible from a
clean checkout; run them from `backend/` unless stated otherwise.

Environment used for this log: Python 3.13.14, Node 20.20.2, git 2.47.3, SQLite (no Docker
daemon and no PostgreSQL server were available, so the container/PostgreSQL paths are
syntax-checked rather than executed — that limitation is stated in the README too).

---

## Latest re-check — 2026-10-05

The repository was re-run in this session with Python 3.11.2, Node 22.22.3, npm 10.9.8,
SQLite, and the built-in mock LLM provider:

| Check | Result |
|---|---|
| `python -m pytest tests -q` | **54 passed** |
| `python scripts/run_workflow.py --reject-first` | **COMPLETED**; one requirements change request was reworked, then the six approval gates were approved; generated suite **16/16 passed** |
| `python scripts/smoke_pipeline.py --stages all` | **PIPELINE OK**; 6 agents produced artifacts; generated suite **16/16 passed** |
| `python scripts/smoke_api.py` | **59 checks passed**; `API RESULT: OK` |
| `npm run build && npm run lint` | **passed**; latest Vite bundle 371.98 kB (112.85 kB gzip), no TypeScript errors |

The mock workflow requires no provider API key. The sample project still reported two HIGH
security findings and several traceability gaps; this is surfaced as human review work rather
than hidden by the workflow. The workflow and pipeline outputs are written to temporary
folders and were not added to the repository.

The Vercel Vite configuration was added and the frontend production build passed, but publishing
was blocked: `vercel deploy --temporary --yes` reported that temporary deployments were not
available for this attempt and required login. The CLI had no Vercel credentials, so **no remote
deployment URL was created** in this run.

## 1. Backend test suite

```bash
python -m pytest tests -q
```

```
51 passed in 11.14s
```

Coverage of the suite:

| Module | What it proves |
|---|---|
| `test_auth.py` | registration, duplicate email handling, login success/failure, JWT-protected routes, no account enumeration |
| `test_projects.py` | project CRUD, slug derivation, ownership boundaries (a stranger gets 403), dashboard payload, human-editable tasks |
| `test_workflow.py` | the LangGraph run reaches COMPLETED, six human gates recorded with the deciding user, all stage artefacts present and approved, workspace contains the generated project |
| `test_agents_and_chat.py` | six-agent catalogue, per-agent execution status, chat reply, code proposal opens an approval gate, unknown agent rejected |
| `test_execution_and_security.py` | sandboxed test execution (16/16 passing), manual re-run, confirmation required, sandbox allow-list and shell-metacharacter rejection, security findings + triage, traceability matrix and gap report, audit trail |
| `test_github_delivery.py` | token never returned, URL validation, local repo init, sync plan, unconfirmed commit/push refused, confirmed commit + audit entry, delivery checklist |

## 2. HTTP smoke test (whole API surface)

```bash
python scripts/smoke_api.py
```

```
checks passed: 60
API RESULT: OK
```

It boots the real application with a temporary database and walks: health/config → register →
login → duplicate/wrong-password rejections → project create → dashboard → agent catalogue →
workflow start → **6 approvals** → artefacts (7 types) → workspace read → test run (16/16) →
security summary + triage → sandbox limits → traceability (40 nodes / 75 links, coverage
100/70/40/60/80 %) → audit trail → approval history → repository status/connect/init/plan →
unconfirmed push refused → confirmed commit + git operations log → delivery checklist → events.

## 3. Multi-agent pipeline (agents only, no HTTP)

```bash
python scripts/smoke_pipeline.py --stages all
```

```
summary: 16/16 tests passed (0 failed, 0 errors, 3048 ms)
Security scan: 22 files, 2 findings
trace: nodes=40 links=75
PIPELINE OK
```

Requirement → Architecture → Developer → Testing → Security → Documentation, with the change
set withheld until approval and applied afterwards, the generated project's own suite executed
in the sandbox, and documentation generated from the verified facts.

## 4. Workflow CLI (LangGraph, human gates driven from the terminal)

```bash
python scripts/run_workflow.py
```

```
status        : COMPLETED
steps         : 7
test_results  : 16/16 passed (status PASSED)
security_results : 2 findings {'CRITICAL': 0, 'HIGH': 2, 'MEDIUM': 0, 'LOW': 0, 'INFO': 0}
WORKFLOW RESULT: COMPLETED
```

## 5. Database migrations

```bash
alembic upgrade head      # 20 DevForge tables (+ alembic_version)
alembic downgrade base    # reversible
```

## 6. Frontend

```bash
cd frontend
npx tsc --noEmit      # no type errors (strict mode, noUnusedLocals/Parameters)
npx vite build        # dist/index.html + CSS (33.7 kB) + JS (371 kB, 112 kB gzipped)
npm run dev           # dev server on :5173, proxying /api to the backend
```

Verified at runtime: the dev server serves the app (`200`), every page module transforms
without error, and `POST /api/auth/login` through the Vite proxy returns a token — i.e. the
browser only ever talks to one origin.

## 7. Generated project (the §37 demo scenario)

The Student Task Management System produced by the agents inside the workspace:

* `backend/app/main.py`, `config.py`, `database.py`, `models.py`, `crud.py`, `auth.py`,
  `security.py`, `schemas.py`, `routers/tasks.py`
* `backend/tests/test_tasks_api.py`, `test_tasks_rules.py` — **16 tests, all passing** under
  `pytest` inside the sandbox
* `requirements/requirements.md`, `architecture/architecture.md` (+ Mermaid diagram)
* `tests/test_plan.md`, `tests/test_results.json`
* `security/security_report.md` (2 HIGH findings with remediation guidance)
* `README.md`, `documentation/{INDEX,SETUP,API,ARCHITECTURE,TESTING,SECURITY}.md`
* `backend/.env.example`, `.gitignore`

## 8. Safety checks exercised

| Rule | Evidence |
|---|---|
| No generated code on the host | sandbox refuses a cwd outside `WORKSPACE_ROOT`, rejects `curl`, rejects shell metacharacters (tests + smoke) |
| Human approval at every stage | 6 gates per run, all recorded with user id, comments and timestamp |
| No autonomous remote writes | `push`/`commit` return 422 without `confirm: true`; every `git_operations` row carries `confirmed_by_user` |
| No plaintext GitHub tokens | `token_encrypted` only; API returns a masked hint; test asserts the token is absent from the response |
| Bounded workflows | per-stage revision budget (`MAX_STAGE_ITERATIONS`) and total step guard (`MAX_TOTAL_STEPS`); the approval node is side-effect free so a resume cannot file duplicate approvals |
| Mock mode is honest | API, UI badge and artefact metadata all report `mock`; no provider call is made |
