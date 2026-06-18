# syntax=docker/dockerfile:1

# ---- builder ----
FROM python:3.12-slim-bookworm AS builder
COPY --from=ghcr.io/astral-sh/uv:0.7.3 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0
WORKDIR /app

# Extras to install. Defaults to the FastAPI service image; the Dagster image overrides
# this (orchestration+storage+quality+graph) via --build-arg. arcticdb (storage extra)
# ships only x86_64 linux wheels, so the Dagster image must be built linux/amd64.
ARG EXTRAS="--extra service --extra sentiment"

# 1) deps-only layer (cached unless lock/pyproject/EXTRAS change)
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-editable ${EXTRAS}

# 2) project layer
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-editable ${EXTRAS}

# ---- runtime ----
FROM python:3.12-slim-bookworm AS runtime
RUN groupadd --system --gid 999 nonroot \
 && useradd  --system --gid 999 --uid 999 --create-home nonroot \
 && mkdir -p /data /backups /opt/dagster/home \
 && chown nonroot:nonroot /data /backups /opt/dagster/home

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
