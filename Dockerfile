# syntax=docker/dockerfile:1

# ---- builder ----
FROM python:3.12-slim-bookworm AS builder
COPY --from=ghcr.io/astral-sh/uv:0.7.3 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0
WORKDIR /app

# 1) deps-only layer (cached unless lock/pyproject change)
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-editable --extra service --extra sentiment

# 2) project layer
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-editable --extra service --extra sentiment

# ---- runtime ----
FROM python:3.12-slim-bookworm AS runtime
RUN groupadd --system --gid 999 nonroot \
 && useradd  --system --gid 999 --uid 999 --create-home nonroot \
 && mkdir -p /data /backups && chown nonroot:nonroot /data /backups

COPY --from=builder --chown=nonroot:nonroot /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    ENERGEX_DB_PATH=/data/energy.db \
    TZ=America/Chicago \
    PYTHONUNBUFFERED=1
WORKDIR /app
USER nonroot
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/healthz').status==200 else 1)"

# exec-form CMD => Python is PID 1 (receives SIGTERM); workers=1 = single DuckDB writer.
CMD ["uvicorn", "energex.service.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
