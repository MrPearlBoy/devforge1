# DevForge backend — FastAPI + LangGraph orchestration + sandbox tooling.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# git is required for the repository integration; nodejs is used by the sandbox when a
# generated project is a Node application.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl ca-certificates nodejs npm \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt requirements-dev.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

# The application never runs as root; generated code is executed by the sandbox provider.
RUN useradd --create-home --uid 10001 devforge \
    && mkdir -p /data/workspace \
    && chown -R devforge:devforge /app /data
USER devforge

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
