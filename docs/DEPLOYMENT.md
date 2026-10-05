# Deployment: Vercel frontend + persistent API backend

## Hosting boundary

Vercel is configured to build and serve the React/Vite frontend in `frontend/`. It does **not** run the complete DevForge backend in this setup. The FastAPI service owns the database, durable LangGraph checkpoints, generated project workspace, sandboxed subprocesses, and background workflow workers. Those need a persistent Python/container service and persistent storage; a Vercel serverless function's short-lived, ephemeral runtime is not an appropriate substitute.

A Vercel-only static deployment is useful as a UI preview, but sign-in, projects, and agent workflows are unavailable until the frontend is connected to a deployed backend.

## Required services and API keys

- **PostgreSQL (recommended for hosted use):** configure `DATABASE_URL` to a persistent PostgreSQL database. Apply migrations with `alembic upgrade head`. Do not use SQLite on an ephemeral filesystem for real user data.
- **Persistent Python API host:** deploy `backend/` using the included Dockerfile or a Python/container service. Start it with `uvicorn app.main:app --host 0.0.0.0 --port $PORT`. Keep `WORKSPACE_ROOT` on persistent storage. For durable LangGraph state across restarts, use a persistent `CHECKPOINT_PATH` volume or install/configure the optional PostgreSQL checkpoint backend as described in `backend/requirements.txt`.
- **LLM provider key (optional):** no external model API key is required in `DEVFORGE_MODE=mock`; all six agents use the built-in deterministic mock provider. For live AI, set `DEVFORGE_MODE=live`, `LLM_PROVIDER`, `LLM_MODEL`, and `LLM_API_KEY` on the **backend only**. The configured provider may be OpenAI-compatible, Anthropic, or Ollama. Embeddings have a local fallback for demo use.
- **GitHub token (optional):** needed only if users want DevForge to push generated work or create pull requests. GitHub delivery stays disabled until a repository is connected and the user confirms the operation.

Suggested backend environment (adapt the database URL and service paths):

```dotenv
ENVIRONMENT=production
SECRET_KEY=<generate-a-unique-random-secret>
DATABASE_URL=postgresql+psycopg2://<user>:<password>@<host>:5432/<database>
AUTO_CREATE_SCHEMA=false
DEVFORGE_MODE=mock
LLM_PROVIDER=mock
WORKSPACE_ROOT=/data/workspace
CHECKPOINT_PATH=/data/checkpoints.sqlite
CHECKPOINT_BACKEND=sqlite
EXECUTION_PROVIDER=subprocess
CORS_ORIGINS=https://<your-project>.vercel.app
```

Run migrations from `backend/` before routing traffic:

```bash
alembic upgrade head
```

Set `CORS_ORIGINS` to the exact production Vercel origin (and any approved custom domain). Do not use a broad wildcard for a credentialed production API. For preview deployments, add only the specific preview origins you intend to use. Never put `SECRET_KEY`, `LLM_API_KEY`, database credentials, or GitHub tokens in Vercel `VITE_*` variables.

## Configure and deploy the Vercel frontend

1. Create a Vercel project from this repository and set **Root Directory** to `frontend`.
2. `frontend/vercel.json` declares the Vite build, `npm ci`, `npm run build`, the `dist` output directory, and an SPA fallback for React Router.
3. Add the Vercel environment variable `VITE_API_BASE_URL` for the relevant environment. Its value is the public **origin** of the FastAPI service, for example `https://devforge-api.example.com` (no trailing slash and no `/api` suffix).
4. Deploy or redeploy the frontend. The Vite build bakes this URL into the browser bundle, so changing it requires a new build/deployment.
5. Verify `https://<your-project>.vercel.app/` loads and that `https://<your-backend>/api/health` returns healthy. Then register a user or seed a demo user on the backend and sign in from the Vercel page.

For local development, leave `VITE_API_BASE_URL` empty; the Vite development server continues to proxy `/api` to `http://127.0.0.1:8000`. `frontend/.env.example` documents this variable. The frontend shows a configuration notice and refuses API calls in a production build when the backend origin is unset, rather than making requests to the static Vercel site and appearing to work.

From `frontend/`, try a temporary deployment with the Vercel CLI:

```bash
npx vercel deploy --temporary --yes
```

Vercel advertises temporary deployments without login, but may still require authentication depending on the account or deployment environment; if the CLI refuses the attempt, authenticate Vercel and retry. A permanent project/deployment requires a Vercel account connection. A temporary deploy only proves the static frontend builds and serves; it is not a complete working DevForge instance without the separately hosted API and its database/workspace.

## Local workflow/API verification

No network provider key is needed for the mock-mode workflow:

```bash
cd backend
.venv/bin/python scripts/run_workflow.py --reject-first
.venv/bin/python scripts/smoke_pipeline.py --stages all
.venv/bin/python scripts/smoke_api.py
.venv/bin/python -m pytest tests -q
```

The CLI run accepts the first requirements change request, then approves each human gate and exercises the Developer → Testing → Security → Documentation path. A completed workflow may still report open security findings or traceability gaps; those reports remain review tasks for the human, not claims that every generated requirement is fully covered.
