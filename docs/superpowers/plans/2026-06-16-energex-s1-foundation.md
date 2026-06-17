# Energex S1 Foundation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. This plan is executed via implementation workflows (multi-agent, TDD, phase-gated).

**Goal:** Build the Energex S1 foundation — a crash-safe bitemporal ArcticDB-on-MinIO store of record with a pandera quality gate, scaffolded behind a framework-agnostic `energex.core` and a Dagster `orchestration` layer — proven by a green CI gate suite and a loading Dagster UI.

**Architecture:** Hexagonal. Pure `energex.core` (zero Dagster/FastAPI/LangGraph imports, CI-enforced) owns storage, quality, symbology, connectors. `energex.orchestration` is the only Dagster importer. Vintages are addressed by a per-symbol version index read by integer version; the index append is the atomic commit point. Three revision modes (degenerate/merge/replace). One canonical `_to_polars` adapter bridges ArcticDB pandas to the existing Polars analytics.

**Tech Stack:** Python 3.10+ (3.12 in Docker), uv, ArcticDB 6.18.1 on MinIO, Dagster 1.13.9 + dedicated Postgres, pandera, pandas (core) + polars (analysis), Neo4j, pytest + respx.

**Spec:** `docs/superpowers/specs/2026-06-16-energex-unified-platform-design.md` (source of truth).

**Scope of THIS plan:** PRE-S1 + Phases 0–3 (infra/CI → discovery spikes → scaffold → bitemporal storage → quality gate). Phases 4–9 (connectors, futures→ArcticDB migration, Neo4j) are authored as separate plans **after Phase 0's discovery gates resolve** the external-API unknowns, plus a final **Phase F — cleanup & polish**.

---

## PRE-S1 — Infra, Deps & CI Groundwork

This section is purely additive and runs **before** any S1 code. It widens dependencies, stands up the always-on container topology (MinIO + dedicated Dagster Postgres + webserver + daemon + Neo4j) behind compose profiles, wires the Dagster instance config, preserves the `settings.database` alias for the existing test suite, and retires the two ad-hoc root `test_phase_*.py` scripts. Nothing here imports Dagster/ArcticDB at runtime yet, so the gate is resolution + config validation + the existing 122 tests staying green.

Baseline facts already verified in the repo:
- `settings.database` currently exists as a `DatabaseConfig` field exposing `db_path`; `tests/test_api_contract.py` and `tests/test_database_ergonomics.py` already pass against it. Task 4 keeps that contract while converting it to a property alias (the spec §5.1 / decision #8 design) so S1 phase 1 can later grow `ArcticDBConfig`/`Neo4jConfig`/`ConnectorConfig` without touching those tests.
- The root scripts `test_phase_1_3.py` / `test_phase_4.py` are `print`-based smoke scripts (not pytest). Every behavior they exercise is already covered under `tests/` (`test_config`, `test_llm_factory`, `test_rate_limiter`, `test_news_article`, `test_exceptions`, `test_sentiment`, `test_sentiment_hardening`), so there are no unique asserts to migrate — Task 5 confirms this by grep before deleting.

---

### Task 1 — Extend `pyproject.toml`: extras, deps, mypy overrides

**Files:**
- Modify: `/Users/marty/repos/energex/pyproject.toml`
- Test: `uv sync --all-extras` (resolution gate; no unit test for dependency metadata)

Steps:

- [ ] **Step 1: Add `tenacity` + `httpx` to base `dependencies`.** These are needed by `core/connectors` and `orchestration/resources` (httpx client + tenacity retry). Edit the `dependencies` list:

```toml
dependencies = [
    "polars>=0.20.0",
    "pyarrow>=14.0.0",
    "yfinance>=0.2.35",
    "duckdb>=0.9.0",
    "pytz>=2024.1",
    "plotly>=5.18.0",
    "numpy>=1.24.0",
    "requests>=2.31.0",
    "python-dotenv>=1.0.0",
    "pydantic>=2.5.0",
    "pydantic-settings>=2.1.0",
    "httpx>=0.26.0",
    "tenacity>=8.2.0"
]
```

- [ ] **Step 2: Add the four new optional-dependency groups, `respx` to `dev`, and roll them into `all`.** Replace the entire `[project.optional-dependencies]` block (from `dev = [` through the closing `]` of `all`) with:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "pytest-cov>=4.1.0",
    "pytest-mock>=3.12.0",
    "respx>=0.20.0",
    "black>=23.0.0",
    "isort>=5.0.0",
    "mypy>=1.0.0",
    "pre-commit>=3.5.0",
    "ruff>=0.1.0"
]

llm = [
    "openai>=1.10.0",
    "anthropic>=0.18.0",
    "httpx>=0.26.0"
]

sentiment = [
    "energex[llm]",
    "feedparser>=6.0.0",
    "beautifulsoup4>=4.12.0"
]

service = [
    "fastapi>=0.110.0",
    "uvicorn[standard]>=0.29.0",
    "apscheduler>=3.10.0,<4.0.0"
]

orchestration = [
    "dagster>=1.13.9,<1.14.0",
    "dagster-webserver>=1.13.9,<1.14.0",
    "dagster-postgres>=0.29.9,<0.30.0"
]

storage = [
    "arcticdb>=6.18.1,<7.0.0"
]

quality = [
    "pandera>=0.20.0"
]

graph = [
    "neo4j>=5.20.0"
]

all = [
    "energex[dev]",
    "energex[llm]",
    "energex[sentiment]",
    "energex[service]",
    "energex[orchestration]",
    "energex[storage]",
    "energex[quality]",
    "energex[graph]"
]
```

- [ ] **Step 3: Add mypy missing-import overrides for the new untyped deps.** Replace the `module = [...]` list inside the existing `[[tool.mypy.overrides]]` block with:

```toml
[[tool.mypy.overrides]]
module = [
    "yfinance.*",
    "plotly.*",
    "duckdb.*",
    "feedparser.*",
    "bs4.*",
    "pytz",
    "requests.*",
    "apscheduler.*",
    "arcticdb.*",
    "dagster.*",
    "pandera.*",
    "neo4j.*",
]
ignore_missing_imports = true
```

- [ ] **Step 4: Resolve the new dependency graph.** Run:

```bash
uv sync --all-extras
```

Expected (abridged) output — resolution succeeds and the new packages appear; no conflict errors:

```
Resolved 180+ packages in ...s
Installed XX packages in ...s
 + arcticdb==6.18.1
 + dagster==1.13.9
 + dagster-postgres==0.29.9
 + dagster-webserver==1.13.9
 + neo4j==5.x.x
 + pandera==0.x.x
 + respx==0.x.x
 + tenacity==8.x.x
```

Gate check: the command exits `0`. If `arcticdb==6.18.1` has no wheel for the local interpreter, re-run under 3.12 (`uv sync --all-extras --python 3.12`) — CI/Docker target 3.12 — and record which interpreter resolved.

- [ ] **Step 5: Confirm the existing suite still imports and passes under the widened env.** Run:

```bash
uv run --all-extras pytest -q
```

Expected: `122 passed` (no collection/import errors introduced by the new deps).

- [ ] **Step 6: Commit.**

```bash
git checkout -b feat/pre-s1-infra
git add pyproject.toml uv.lock
git commit -m "Add orchestration/storage/quality/graph extras + tenacity/httpx + respx"
```

---

### Task 2 — Extend `docker-compose.yml`: MinIO, Dagster Postgres, webserver, daemon, Neo4j, profiles

**Files:**
- Modify: `/Users/marty/repos/energex/docker-compose.yml`
- Test: `docker compose --profile dev config` (validation gate)

Steps:

- [ ] **Step 1: Put the existing `energex` service behind the `full` profile and give it explicit limits + a forward dep on `minio-init`.** This keeps it byte-for-byte runnable (`docker compose --profile full up energex`) while satisfying "limits on every service". Edit the `energex` service: add the `profiles`, `mem_limit`, `cpus`, and `depends_on` keys (leave everything else as-is):

```yaml
  energex:
    build: .
    image: ghcr.io/oldhero5/energex:local
    container_name: energex
    profiles: ["full"]
    init: true
    restart: unless-stopped
    stop_grace_period: 30s
    mem_limit: 1g
    cpus: 1.0
    env_file:
      - .env
    environment:
      ENERGEX_DB_PATH: /data/energy.db
      TZ: America/Chicago
      LOG_LEVEL: INFO
      ENERGEX_INGEST_CRON: "*/5 * * * *"
      DEFAULT_LLM_PROVIDER: ollama
      DEFAULT_LLM_MODEL: gemma3:4b
      OLLAMA_BASE_URL: http://host.docker.internal:11434
    extra_hosts:
      - "host.docker.internal:host-gateway"
    ports:
      - "8000:8000"
    volumes:
      - energex-data:/data
      - ./backups:/backups
    depends_on:
      minio-init:
        condition: service_completed_successfully
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/healthz').status==200 else 1)"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 30s
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "5"
```

- [ ] **Step 2: Add the MinIO service + idempotent `mc` init job.** Insert these two services after `energex:` (still inside `services:`):

```yaml
  minio:
    image: quay.io/minio/minio:RELEASE.2025-04-22T22-12-26Z
    container_name: energex-minio
    profiles: ["dev", "full"]
    init: true
    restart: unless-stopped
    command: server /data --console-address ":9001"
    mem_limit: 1g
    cpus: 1.0
    environment:
      MINIO_ROOT_USER: ${MINIO_ROOT_USER:-minioadmin}
      MINIO_ROOT_PASSWORD: ${MINIO_ROOT_PASSWORD:-minioadmin}
    ports:
      - "9000:9000"
      - "9001:9001"
    volumes:
      - minio-data:/data
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
      interval: 15s
      timeout: 5s
      retries: 5
      start_period: 10s
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "5"

  minio-init:
    image: quay.io/minio/mc:RELEASE.2025-04-16T18-13-26Z
    container_name: energex-minio-init
    profiles: ["dev", "full"]
    init: true
    restart: "no"               # one-shot provisioner; unless-stopped would loop forever
    mem_limit: 256m
    cpus: 0.5
    depends_on:
      minio:
        condition: service_healthy
    environment:
      MINIO_ROOT_USER: ${MINIO_ROOT_USER:-minioadmin}
      MINIO_ROOT_PASSWORD: ${MINIO_ROOT_PASSWORD:-minioadmin}
      ARCTIC_ACCESS_KEY: ${ARCTIC_ACCESS_KEY:-energex-arctic}
      ARCTIC_SECRET_KEY: ${ARCTIC_SECRET_KEY:-energex-arctic-secret}
    volumes:
      - ./deploy/minio:/policies:ro
    entrypoint: >
      /bin/sh -c "
      mc alias set local http://minio:9000 \"$$MINIO_ROOT_USER\" \"$$MINIO_ROOT_PASSWORD\" &&
      mc mb --ignore-existing local/arctic &&
      (mc admin policy create local arctic-rw /policies/arctic-rw.json || true) &&
      (mc admin user svcacct add --access-key \"$$ARCTIC_ACCESS_KEY\" --secret-key \"$$ARCTIC_SECRET_KEY\" --policy /policies/arctic-rw.json local \"$$MINIO_ROOT_USER\" || true)
      "
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "5"
```

- [ ] **Step 3: Add the dedicated Dagster Postgres.** Insert after `minio-init:`:

```yaml
  dagster-postgres:
    image: postgres:16.4
    container_name: energex-dagster-pg
    profiles: ["dev", "full"]
    init: true
    restart: unless-stopped
    mem_limit: 512m
    cpus: 0.5
    environment:
      POSTGRES_USER: ${DAGSTER_PG_USERNAME:-dagster}
      POSTGRES_PASSWORD: ${DAGSTER_PG_PASSWORD:-dagster}
      POSTGRES_DB: ${DAGSTER_PG_DB:-dagster}
    volumes:
      - dagster-pg-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $${POSTGRES_USER} -d $${POSTGRES_DB}"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 10s
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "5"
```

- [ ] **Step 4: Add the Dagster webserver + daemon (shared `DAGSTER_HOME` + `dagster.yaml`).** Both build the project image and mount the instance config from `deploy/dagster/` read-only into the shared home volume. Insert after `dagster-postgres:`:

```yaml
  dagster-webserver:
    build: .
    image: ghcr.io/oldhero5/energex:local
    container_name: energex-dagster-webserver
    profiles: ["dev", "full"]
    init: true
    restart: unless-stopped
    mem_limit: 1g
    cpus: 1.0
    command: ["dagster-webserver", "-h", "0.0.0.0", "-p", "3000", "-w", "/opt/dagster/home/workspace.yaml"]
    environment:
      DAGSTER_HOME: /opt/dagster/home
      DAGSTER_PG_HOST: dagster-postgres
      DAGSTER_PG_USERNAME: ${DAGSTER_PG_USERNAME:-dagster}
      DAGSTER_PG_PASSWORD: ${DAGSTER_PG_PASSWORD:-dagster}
      DAGSTER_PG_DB: ${DAGSTER_PG_DB:-dagster}
      TZ: UTC
    ports:
      - "3000:3000"
    volumes:
      - dagster-home:/opt/dagster/home
      - ./deploy/dagster/dagster.yaml:/opt/dagster/home/dagster.yaml:ro
      - ./deploy/dagster/workspace.yaml:/opt/dagster/home/workspace.yaml:ro
    depends_on:
      dagster-postgres:
        condition: service_healthy
      minio-init:
        condition: service_completed_successfully
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:3000/server_info || exit 1"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 30s
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "5"

  dagster-daemon:
    build: .
    image: ghcr.io/oldhero5/energex:local
    container_name: energex-dagster-daemon
    profiles: ["dev", "full"]
    init: true
    restart: unless-stopped
    mem_limit: 1g
    cpus: 1.0
    command: ["dagster-daemon", "run"]
    environment:
      DAGSTER_HOME: /opt/dagster/home
      DAGSTER_PG_HOST: dagster-postgres
      DAGSTER_PG_USERNAME: ${DAGSTER_PG_USERNAME:-dagster}
      DAGSTER_PG_PASSWORD: ${DAGSTER_PG_PASSWORD:-dagster}
      DAGSTER_PG_DB: ${DAGSTER_PG_DB:-dagster}
      TZ: UTC
    volumes:
      - dagster-home:/opt/dagster/home
      - ./deploy/dagster/dagster.yaml:/opt/dagster/home/dagster.yaml:ro
      - ./deploy/dagster/workspace.yaml:/opt/dagster/home/workspace.yaml:ro
    depends_on:
      dagster-postgres:
        condition: service_healthy
      minio-init:
        condition: service_completed_successfully
    healthcheck:
      test: ["CMD-SHELL", "dagster-daemon liveness-check"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "5"
```

- [ ] **Step 5: Add Neo4j (capped heap, `full` profile only).** Insert after `dagster-daemon:`:

```yaml
  neo4j:
    image: neo4j:5.26.0-community
    container_name: energex-neo4j
    profiles: ["full"]
    init: true
    restart: unless-stopped
    mem_limit: 2g
    cpus: 1.5
    environment:
      NEO4J_AUTH: ${NEO4J_AUTH:-neo4j/energex-neo4j}
      NEO4J_server_memory_heap_initial__size: "512m"
      NEO4J_server_memory_heap_max__size: "512m"
      NEO4J_server_memory_pagecache_size: "512m"
    ports:
      - "7474:7474"
      - "7687:7687"
    volumes:
      - neo4j-data:/data
    healthcheck:
      test: ["CMD-SHELL", "wget -qO- http://localhost:7474 >/dev/null 2>&1 || exit 1"]
      interval: 30s
      timeout: 5s
      retries: 5
      start_period: 30s
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "5"
```

- [ ] **Step 6: Declare the new named volumes.** Replace the `volumes:` block at the bottom of the file with:

```yaml
volumes:
  energex-data:                      # survives `compose down` / OrbStack restart (only `down -v` deletes it)
  minio-data:                        # ArcticDB store of record (separate volume from Postgres)
  dagster-pg-data:                   # Dagster instance storage (separate volume from MinIO)
  dagster-home:                      # shared DAGSTER_HOME (instance config + compute logs)
  neo4j-data:                        # entity graph
# OrbStack notes: enable "Start at login" and prevent Mac sleep (caffeinate / stay plugged in) for true 24/7.
# Do NOT put energy.db on a macOS bind mount — VirtioFS breaks DuckDB advisory locks/fsync (DuckDB#13017).
```

- [ ] **Step 7: Validate the `dev` profile composition.** Run:

```bash
docker compose --profile dev config >/dev/null && echo "dev profile OK"
```

Expected output:

```
dev profile OK
```

(`docker compose config` resolves YAML, anchors, env substitution, profiles, and `depends_on` graph; unset secret env vars fall back to the `:-` defaults so validation is clean.)

- [ ] **Step 8: Validate the `full` profile too (energex + neo4j included).** Run:

```bash
docker compose --profile full config >/dev/null && echo "full profile OK"
```

Expected output:

```
full profile OK
```

- [ ] **Step 9: Commit.**

```bash
git add docker-compose.yml
git commit -m "Add minio, dagster-postgres, webserver, daemon, neo4j services with dev/full profiles"
```

---

### Task 3 — Dagster instance config + MinIO bucket policy under `deploy/`

**Files:**
- Create: `/Users/marty/repos/energex/deploy/dagster/dagster.yaml`
- Create: `/Users/marty/repos/energex/deploy/dagster/workspace.yaml`
- Create: `/Users/marty/repos/energex/deploy/minio/arctic-rw.json`

Steps:

- [ ] **Step 1: Write the Dagster instance config (Postgres run/event/schedule storage + retention + local compute logs).** Create `/Users/marty/repos/energex/deploy/dagster/dagster.yaml`:

```yaml
# Dagster instance config shared by webserver + daemon via DAGSTER_HOME.
# Postgres (NOT SQLite) backs run/event/schedule storage so webserver+daemon
# can run concurrently without file-lock failures.
storage:
  postgres:
    postgres_db:
      username:
        env: DAGSTER_PG_USERNAME
      password:
        env: DAGSTER_PG_PASSWORD
      hostname:
        env: DAGSTER_PG_HOST
      db_name:
        env: DAGSTER_PG_DB
      port: 5432

run_coordinator:
  module: dagster.core.run_coordinator
  class: QueuedRunCoordinator
  config:
    max_concurrent_runs: 2

# Tick retention so schedule/sensor history does not grow unbounded on the shared disk.
retention:
  schedule:
    purge_after_days: 90
  sensor:
    purge_after_days: 30

compute_logs:
  module: dagster.core.storage.local_compute_log_manager
  class: LocalComputeLogManager
  config:
    base_dir: /opt/dagster/home/compute_logs

telemetry:
  enabled: false
```

- [ ] **Step 2: Write the workspace pointing at the (future) orchestration definitions.** Create `/Users/marty/repos/energex/deploy/dagster/workspace.yaml`:

```yaml
# Loaded by webserver/daemon. energex.orchestration.definitions is created in S1 phase 1;
# this file is config-only and is not imported by `docker compose config`.
load_from:
  - python_module:
      module_name: energex.orchestration.definitions
      working_directory: /opt/dagster/app
```

- [ ] **Step 3: Write the scoped MinIO policy used by `minio-init`.** Create `/Users/marty/repos/energex/deploy/minio/arctic-rw.json`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:*"],
      "Resource": [
        "arn:aws:s3:::arctic",
        "arn:aws:s3:::arctic/*"
      ]
    }
  ]
}
```

- [ ] **Step 4: Confirm the policy file is valid JSON and the compose mounts resolve.** Run:

```bash
python -c "import json,pathlib; json.loads(pathlib.Path('deploy/minio/arctic-rw.json').read_text()); print('policy JSON OK')"
docker compose --profile dev config >/dev/null && echo "compose still OK"
```

Expected output:

```
policy JSON OK
compose still OK
```

- [ ] **Step 5: Commit.**

```bash
git add deploy/dagster/dagster.yaml deploy/dagster/workspace.yaml deploy/minio/arctic-rw.json
git commit -m "Add Dagster Postgres instance config, workspace, and scoped MinIO arctic policy"
```

---

### Task 4 — Preserve `settings.database` as a property alias

Convert the `database` field to a property aliasing a renamed `LegacyDuckDBConfig`, matching spec §5.1 / decision #8 so S1 phase 1 can add `ArcticDBConfig`/`Neo4jConfig`/`ConnectorConfig` siblings without breaking the two contract tests. Refactor rhythm: confirm the target tests are green before and after, then run the full suite.

**Files:**
- Modify: `/Users/marty/repos/energex/src/energex/config.py`
- Test: `/Users/marty/repos/energex/tests/test_api_contract.py`, `/Users/marty/repos/energex/tests/test_database_ergonomics.py` (existing, unchanged)

Steps:

- [ ] **Step 1: Establish the green baseline for the two contract tests.** Run:

```bash
uv run --all-extras pytest -q tests/test_api_contract.py tests/test_database_ergonomics.py
```

Expected: both files pass (the alias contract already holds via the current field). Record the pass count.

- [ ] **Step 2: Rename `DatabaseConfig` to `LegacyDuckDBConfig`.** In `src/energex/config.py`, change the class definition (lines 49–54 region):

```python
class LegacyDuckDBConfig(BaseSettings):
    """Legacy DuckDB path config (read path / existing tests). Reached via the
    `settings.database` property alias; preserved while core config grows
    ArcticDB/Neo4j/Connector sections in S1 phase 1."""

    db_path: Path = Field(default=Path("energy.db"), description="Path to DuckDB database")

    model_config = SettingsConfigDict(env_prefix="ENERGEX_", case_sensitive=False)

    @field_validator("db_path", mode="before")
    @classmethod
    def validate_db_path(cls, v: str | Path) -> Path:
        """Convert string to Path."""
        return Path(v) if isinstance(v, str) else v
```

- [ ] **Step 3: Replace the `database` field with a `legacy_db` field on `EnergexSettings`.** Change the sub-configuration field declaration:

```python
    legacy_db: LegacyDuckDBConfig = Field(default_factory=LegacyDuckDBConfig)
```

(replacing the old `database: DatabaseConfig = Field(default_factory=DatabaseConfig)` line).

- [ ] **Step 4: Add the `database` property alias.** Add this method to `EnergexSettings`, immediately after the `model_post_init` method:

```python
    @property
    def database(self) -> LegacyDuckDBConfig:
        """Back-compat alias preserving `settings.database.db_path`. Kept as a
        property (not a field) so future core config sections can be added
        alongside it without changing this read path."""
        return self.legacy_db
```

- [ ] **Step 5: Re-run the two contract tests (must stay green).** Run:

```bash
uv run --all-extras pytest -q tests/test_api_contract.py tests/test_database_ergonomics.py
```

Expected: same pass count as Step 1. `settings.database` now resolves via the property to `LegacyDuckDBConfig`, which has `db_path` and not `path` — `test_settings_database_uses_db_path` passes; `EnergyDatabase()` still reads `settings.database.db_path`.

- [ ] **Step 6: Run the full suite (no regressions from the rename).** Run:

```bash
uv run --all-extras pytest -q
```

Expected: `122 passed`.

- [ ] **Step 7: Commit.**

```bash
git add src/energex/config.py
git commit -m "Make settings.database a property alias over renamed LegacyDuckDBConfig"
```

---

### Task 5 — Retire the ad-hoc root `test_phase_*.py` scripts

**Files:**
- Delete: `/Users/marty/repos/energex/test_phase_1_3.py`
- Delete: `/Users/marty/repos/energex/test_phase_4.py`
- Test: full `tests/` suite (regression gate)

Steps:

- [ ] **Step 1: Confirm there are no unique asserts to migrate (coverage already in `tests/`).** Run:

```bash
grep -rln "add_sentiment_to_prices\|_rule_based_sentiment\|get_sentiment_summary\|_analyze_article" tests/
grep -rln "LLMProviderFactory\|list_providers" tests/
grep -rln "RateLimiter" tests/
grep -rln "NewsArticle" tests/
grep -rln "issubclass" tests/test_exceptions.py
```

Expected (every phase-script behavior is covered under `tests/`, so nothing to migrate):

```
tests/test_sentiment.py
tests/test_sentiment_hardening.py
tests/test_llm_factory.py
tests/test_rate_limiter.py
tests/test_news_article.py
tests/test_exceptions.py
```

Gate: if any grep returns no match for its behavior, STOP and port that specific assert into the matching `tests/test_*.py` before deleting; otherwise proceed.

- [ ] **Step 2: Delete the two root scripts.** Run:

```bash
git rm test_phase_1_3.py test_phase_4.py
```

- [ ] **Step 3: Verify the pytest suite is unaffected.** Run:

```bash
uv run --all-extras pytest -q
```

Expected: `122 passed` (the deleted scripts were never collected by pytest — `testpaths = ["tests"]` — so the count is unchanged and import-time `sys.path` hacks are gone).

- [ ] **Step 4: Commit.**

```bash
git commit -m "Remove ad-hoc root test_phase scripts (behavior covered under tests/)"
```

---

**Gate:** `uv sync --all-extras` resolves exit 0; `docker compose --profile dev config` and `docker compose --profile full config` both validate exit 0; `uv run --all-extras pytest -q` reports `122 passed` with the two root `test_phase_*.py` scripts deleted and `settings.database.db_path` still resolving via the property alias.

---

## Phase 0 — Discovery & Gating Experiments

These are **spike tasks**, not TDD: each runs a command (or short throwaway script), records the literal result into `docs/superpowers/notes/2026-06-16-phase0-findings.md`, and ends at a gate. No production code is written in this phase; the only committed artifacts are the findings file, the MinIO console screenshot, and the docker-compose MinIO blocks needed to run the smoke. Phase 0 runs **after** the PRE-S1 compose/extras work and **before** any `core/storage.py` code.

---

### Task 0.1 — Create the findings file skeleton

**Files:**
- Create: `docs/superpowers/notes/2026-06-16-phase0-findings.md`

Steps:

- [ ] **Step 1: Create the findings file with the three required sections and explicit UNRESOLVED markers.**

```bash
mkdir -p /Users/marty/repos/energex/docs/superpowers/notes
cat > /Users/marty/repos/energex/docs/superpowers/notes/2026-06-16-phase0-findings.md <<'EOF'
# Energex S1 — Phase 0 Findings (2026-06-16)

Source of truth: docs/superpowers/specs/2026-06-16-energex-unified-platform-design.md (§5.10 phase 0, §11).
Each section below is a gating experiment. A section is DONE only when every UNRESOLVED token is replaced
with a recorded literal result. Do not start Phase 1 until all three gates pass.

---

## 1. EIA v2 series freeze (gas storage + petroleum status)

### 1a. Natural gas — weekly underground storage, Lower 48
- Route slug: UNRESOLVED
- frequency value: UNRESOLVED
- facet field names: UNRESOLVED
- Lower-48 facet id + value: UNRESOLVED
- data column for value: UNRESOLVED
- exact metadata curl: UNRESOLVED
- exact data curl: UNRESOLVED

### 1b. Petroleum — weekly status (crude stocks)
- Route slug: UNRESOLVED
- frequency value: UNRESOLVED
- facet field names: UNRESOLVED
- crude-stocks facet ids + values: UNRESOLVED
- data column for value: UNRESOLVED
- exact metadata curl: UNRESOLVED
- exact data curl: UNRESOLVED

### Decision (locked)
- Frozen instrument_id -> route/frequency/facets mapping for symbology.py: UNRESOLVED

---

## 2. ArcticDB-on-MinIO connectivity smoke

- docker compose up command + result: UNRESOLVED
- spike script path: scripts/phase0_minio_smoke.py
- spike stdout (write version + readback rows): UNRESOLVED
- EXACT working ArcticDB URI grammar: UNRESOLVED
- MinIO console visual confirmation (screenshot path): UNRESOLVED
- Gate status: UNRESOLVED

---

## 3. Snapshot vs version-index addressing experiment

- spike script path: scripts/phase0_version_addressing.py
- read by int version (v0/v1/v2) results: UNRESOLVED
- read by datetime as_of results: UNRESOLVED
- read by snapshot name results: UNRESOLVED
- CONFIRMED: datetime-as_of resolves to version WRITE time (collapses backfills)? UNRESOLVED
- CONFIRMED: int-version is exact-match? UNRESOLVED
- DECISION (locked): version-index authority? UNRESOLVED
EOF
```

Expected: file exists with three UNRESOLVED-tagged sections.

```bash
ls -1 /Users/marty/repos/energex/docs/superpowers/notes/2026-06-16-phase0-findings.md
```

Expected output:

```
/Users/marty/repos/energex/docs/superpowers/notes/2026-06-16-phase0-findings.md
```

- [ ] **Step 2: Commit the skeleton.**

```bash
cd /Users/marty/repos/energex && git add docs/superpowers/notes/2026-06-16-phase0-findings.md && git commit -m "Add Phase 0 findings skeleton for S1 discovery experiments"
```

Expected: `1 file changed, ... insertions(+)`.

---

### Task 0.2 — Freeze EIA v2 series IDs, frequency, and facet field names

**Files:**
- Modify: `docs/superpowers/notes/2026-06-16-phase0-findings.md`

Steps:

- [ ] **Step 1: Confirm the API key is present.**

```bash
test -n "$EIA_API_KEY" && echo "EIA_API_KEY set (len=${#EIA_API_KEY})" || echo "MISSING EIA_API_KEY"
```

Expected output (key length will vary):

```
EIA_API_KEY set (len=40)
```

Gate: if `MISSING EIA_API_KEY`, stop and export it from the `.env` before continuing (`set -a; source /Users/marty/repos/energex/.env; set +a`).

- [ ] **Step 2: Pull natural-gas weekly underground-storage route metadata (frequency + facet ids).**

```bash
curl -s "https://api.eia.gov/v2/natural-gas/stor/wkly?api_key=${EIA_API_KEY}" \
  | python -c 'import sys,json; r=json.load(sys.stdin)["response"]; print("FREQUENCIES:", [f["id"] for f in r["frequency"]]); print("FACETS:", [f["id"] for f in r["facets"]]); print("DATA_COLS:", list(r["data"].keys()))'
```

Expected shape of output (record the literal values returned):

```
FREQUENCIES: ['weekly']
FACETS: ['duoarea', 'series', 'process', 'product']
DATA_COLS: ['value']
```

- [ ] **Step 3: Enumerate the natural-gas facet values to find the Lower-48 selector.**

```bash
for f in duoarea series process; do
  echo "=== facet: $f ===";
  curl -s "https://api.eia.gov/v2/natural-gas/stor/wkly/facet/${f}?api_key=${EIA_API_KEY}" \
    | python -c 'import sys,json; [print(x["id"],"|",x["name"]) for x in json.load(sys.stdin)["response"]["facets"]]';
done
```

Expected: a list of `id | name` rows; identify the Lower-48 storage selector (the row whose name reads "Lower 48 States" / "Weekly Working Gas in Underground Storage, Lower 48 States"). Record its facet field and id literally.

- [ ] **Step 4: Verify the chosen gas selector returns weekly values (sanity data pull, 2 rows).**

```bash
curl -s "https://api.eia.gov/v2/natural-gas/stor/wkly/data/?api_key=${EIA_API_KEY}&frequency=weekly&data[0]=value&facets[duoarea][]=NUS&facets[process][]=SAS&sort[0][column]=period&sort[0][direction]=desc&length=2" \
  | python -c 'import sys,json; r=json.load(sys.stdin)["response"]; print("TOTAL:", r["total"]); [print(d["period"], d.get("series"), d["value"], d.get("units")) for d in r["data"]]'
```

Expected: two most-recent weekly rows with non-null numeric `value` and `TOTAL` > 0. (If `duoarea=NUS`/`process=SAS` returns empty, substitute the exact ids found in Step 3 and re-run; record the working facet combination.)

- [ ] **Step 5: Pull petroleum weekly-stocks route metadata.**

```bash
curl -s "https://api.eia.gov/v2/petroleum/stoc/wstk?api_key=${EIA_API_KEY}" \
  | python -c 'import sys,json; r=json.load(sys.stdin)["response"]; print("FREQUENCIES:", [f["id"] for f in r["frequency"]]); print("FACETS:", [f["id"] for f in r["facets"]]); print("DATA_COLS:", list(r["data"].keys()))'
```

Expected shape (record literal values):

```
FREQUENCIES: ['weekly']
FACETS: ['duoarea', 'series', 'process', 'product']
DATA_COLS: ['value']
```

- [ ] **Step 6: Enumerate petroleum facet values and find the crude-stocks selector.**

```bash
for f in product process duoarea; do
  echo "=== facet: $f ===";
  curl -s "https://api.eia.gov/v2/petroleum/stoc/wstk/facet/${f}?api_key=${EIA_API_KEY}" \
    | python -c 'import sys,json; [print(x["id"],"|",x["name"]) for x in json.load(sys.stdin)["response"]["facets"]]';
done
```

Expected: `id | name` rows; identify product=crude oil (e.g. `EPC0`), process=ending stocks excluding SPR (e.g. `SAE`), duoarea=U.S. (e.g. `NUS`). Record the literal ids that name "Crude Oil" and "Ending Stocks Excluding SPR".

- [ ] **Step 7: Verify the chosen petroleum selector returns weekly values (2 rows).**

```bash
curl -s "https://api.eia.gov/v2/petroleum/stoc/wstk/data/?api_key=${EIA_API_KEY}&frequency=weekly&data[0]=value&facets[product][]=EPC0&facets[process][]=SAE&facets[duoarea][]=NUS&sort[0][column]=period&sort[0][direction]=desc&length=2" \
  | python -c 'import sys,json; r=json.load(sys.stdin)["response"]; print("TOTAL:", r["total"]); [print(d["period"], d.get("series"), d["value"], d.get("units")) for d in r["data"]]'
```

Expected: two most-recent weekly crude-stock rows with non-null numeric values and `TOTAL` > 0. (Substitute the exact ids from Step 6 if empty; record the working combination.)

- [ ] **Step 8: Provide the httpx equivalent of the two data pulls (the form connectors will use).**

```bash
uv run python - <<'PY'
import os, httpx
key = os.environ["EIA_API_KEY"]
def pull(route, params):
    p = {"api_key": key, "frequency": "weekly", "data[0]": "value", "length": 2,
         "sort[0][column]": "period", "sort[0][direction]": "desc", **params}
    r = httpx.get(f"https://api.eia.gov/v2/{route}/data/", params=p, timeout=30.0)
    r.raise_for_status()
    body = r.json()["response"]
    print(route, "->", r.url)
    print("  total:", body["total"], "first:", body["data"][:1])
pull("natural-gas/stor/wkly", {"facets[duoarea][]": "NUS", "facets[process][]": "SAS"})
pull("petroleum/stoc/wstk", {"facets[product][]": "EPC0", "facets[process][]": "SAE", "facets[duoarea][]": "NUS"})
PY
```

Expected: two lines each printing the fully-expanded request URL (httpx renders the `facets[...][]` brackets) and a non-zero `total` with a sample data row. Copy these expanded URLs verbatim into the findings file as the canonical request grammar.

- [ ] **Step 9: Record all frozen values into the findings file.** Replace every UNRESOLVED token in section 1 of `docs/superpowers/notes/2026-06-16-phase0-findings.md` with the literal route slugs (`natural-gas/stor/wkly`, `petroleum/stoc/wstk`), `frequency=weekly`, the facet field names (`duoarea`, `series`, `process`, `product`), the confirmed Lower-48 and crude-stocks facet ids from Steps 3/6, `data[0]=value`, and the exact curl + httpx commands from Steps 4/7/8. Fill the "Decision (locked)" block with the final mapping:

```
EIA.NG.STORAGE.LOWER48 -> route=natural-gas/stor/wkly, frequency=weekly, facets={duoarea:<id>, process:<id>}
EIA.PET.CRUDE.STOCKS   -> route=petroleum/stoc/wstk,  frequency=weekly, facets={product:<id>, process:<id>, duoarea:<id>}
```

- [ ] **Step 10: Commit the EIA freeze.**

```bash
cd /Users/marty/repos/energex && git add docs/superpowers/notes/2026-06-16-phase0-findings.md && git commit -m "Freeze EIA v2 gas-storage and petroleum-status routes/facets in Phase 0 findings"
```

Expected: `1 file changed`.

Gate: section 1 of the findings file has **zero** UNRESOLVED tokens; both data curls returned `total > 0` with numeric values.

---

### Task 0.3 — ArcticDB-on-MinIO connectivity smoke + Chrome visual confirmation

**Files:**
- Modify: `docker-compose.yml` (add `minio` + `minio-init` under the `dev` profile)
- Create: `scripts/phase0_minio_smoke.py`
- Create: `docs/superpowers/notes/phase0-minio-console.png` (screenshot)
- Modify: `docs/superpowers/notes/2026-06-16-phase0-findings.md`

Steps:

- [ ] **Step 1: Add the MinIO services (dev profile, separate named volume, idempotent bucket-create) to docker-compose.yml.** Insert these two services after the `energex` service block (before the top-level `volumes:` key). This does not touch the existing `energex` service.

```yaml
  minio:
    image: quay.io/minio/minio:RELEASE.2025-04-22T22-12-26Z
    container_name: energex-minio
    profiles: ["dev", "full"]
    init: true
    restart: unless-stopped
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
    ports:
      - "9000:9000"
      - "9001:9001"
    volumes:
      - minio-data:/data
    healthcheck:
      test: ["CMD", "mc", "ready", "local"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 10s
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "5"

  minio-init:
    image: quay.io/minio/mc:RELEASE.2025-04-16T18-13-26Z
    container_name: energex-minio-init
    profiles: ["dev", "full"]
    depends_on:
      minio:
        condition: service_healthy
    entrypoint: >
      /bin/sh -c "
      mc alias set local http://minio:9000 minioadmin minioadmin &&
      mc mb --ignore-existing local/arctic &&
      echo 'arctic bucket ready'
      "
    restart: "no"
```

Then add the new named volume to the existing top-level `volumes:` mapping:

```yaml
volumes:
  energex-data:
  minio-data:
```

- [ ] **Step 2: Bring up MinIO + bucket init.**

```bash
cd /Users/marty/repos/energex && docker compose --profile dev up -d minio minio-init
```

Expected: `energex-minio` becomes healthy and `energex-minio-init` exits 0. Verify:

```bash
cd /Users/marty/repos/energex && docker compose --profile dev ps minio && docker logs energex-minio-init
```

Expected: `minio` status `healthy`; init log ends with `arctic bucket ready`.

- [ ] **Step 3: Write the ArcticDB-on-MinIO smoke spike.**

```python
# scripts/phase0_minio_smoke.py
"""Phase-0 ArcticDB-on-MinIO connectivity smoke.

Confirms the EXACT s3 URI grammar ArcticDB accepts against local MinIO:
  s3://<endpoint>:<bucket>?access=..&secret=..&port=..&use_virtual_addressing=false
Writes a 2-row pandas frame, reads it back, asserts equality.
"""
import pandas as pd
from arcticdb import Arctic

URI = (
    "s3://localhost:arctic"
    "?access=minioadmin"
    "&secret=minioadmin"
    "&port=9000"
    "&use_virtual_addressing=false"
)


def main() -> None:
    print("URI:", URI)
    ac = Arctic(URI)
    lib = ac.get_or_create_library("phase0.smoke")
    frame = pd.DataFrame(
        {"instrument_id": ["SMOKE", "SMOKE"], "value": [1.0, 2.0]},
        index=pd.to_datetime(["2026-06-16T00:00:00", "2026-06-16T01:00:00"]),
    )
    frame.index.name = "valid_time"
    v = lib.write("smoke_symbol", frame)
    print("write version:", v.version)
    back = lib.read("smoke_symbol").data
    print("readback rows:", len(back))
    print(back.to_string())
    assert len(back) == 2, f"expected 2 rows, got {len(back)}"
    assert list(back["value"]) == [1.0, 2.0]
    print("SMOKE OK")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the smoke and record the working URI.**

```bash
cd /Users/marty/repos/energex && uv run python scripts/phase0_minio_smoke.py
```

Expected output (endpoint host may differ if MinIO is remote; record the literal that worked):

```
URI: s3://localhost:arctic?access=minioadmin&secret=minioadmin&port=9000&use_virtual_addressing=false
write version: 0
readback rows: 2
                     instrument_id  value
valid_time
2026-06-16 00:00:00          SMOKE    1.0
2026-06-16 01:00:00          SMOKE    2.0
SMOKE OK
```

Gate inside the step: terminates with `SMOKE OK`. If `s3://localhost:arctic?...port=9000` is rejected, try the alternate endpoint:port form `s3://localhost:9000:arctic?access=...&secret=...&use_virtual_addressing=false` and record whichever ArcticDB 6.18.1 accepts as the canonical grammar.

- [ ] **Step 5: Visually confirm the bucket and test object in the MinIO console with Chrome.** Load the browser tools, then navigate, log in, and screenshot.

```
ToolSearch query: "select:mcp__claude-in-chrome__tabs_context_mcp,mcp__claude-in-chrome__navigate,mcp__claude-in-chrome__computer,mcp__claude-in-chrome__read_page,mcp__claude-in-chrome__form_input"
```

Then, in order:
1. `navigate` to `http://localhost:9001`.
2. `form_input` the login form: user `minioadmin`, password `minioadmin`; submit.
3. `navigate` to `http://localhost:9001/browser/arctic` (Object Browser → `arctic` bucket).
4. Confirm the bucket lists ArcticDB-written objects under a `phase0.smoke` prefix (e.g. keys containing `smoke_symbol`).
5. `computer` screenshot, and save the captured image to `docs/superpowers/notes/phase0-minio-console.png`.

Expected: the `arctic` bucket is present and non-empty (objects written by the Step 4 smoke are visible).

- [ ] **Step 6: Record section 2 of the findings file.** Replace the UNRESOLVED tokens with: the `docker compose --profile dev up -d minio minio-init` command + its result, the smoke stdout from Step 4, the EXACT working URI grammar, the screenshot path `docs/superpowers/notes/phase0-minio-console.png`, and set `Gate status: GREEN`.

- [ ] **Step 7: Commit the smoke artifacts.**

```bash
cd /Users/marty/repos/energex && git add docker-compose.yml scripts/phase0_minio_smoke.py docs/superpowers/notes/phase0-minio-console.png docs/superpowers/notes/2026-06-16-phase0-findings.md && git commit -m "Add MinIO dev services and ArcticDB connectivity smoke; record Phase 0 URI grammar"
```

Expected: `4 files changed`.

Gate: smoke exits `SMOKE OK`; `arctic` bucket + test object visually confirmed in the MinIO console screenshot; the working URI grammar is recorded.

---

### Task 0.4 — Snapshot vs version-index addressing experiment (lock the decision)

**Files:**
- Create: `scripts/phase0_version_addressing.py`
- Modify: `docs/superpowers/notes/2026-06-16-phase0-findings.md`

Steps:

- [ ] **Step 1: Write the addressing experiment spike (offline LMDB-backed Arctic — no MinIO dependency).**

```python
# scripts/phase0_version_addressing.py
"""Phase-0 addressing experiment.

Writes 3 versions of ONE symbol (each version revises the value at the SAME valid_time),
snapshots each, then reads the symbol THREE ways:
  (a) by integer version (0,1,2),
  (b) by datetime as_of taken from BEFORE each write,
  (c) by snapshot name.

Goal: CONFIRM the spec claim that datetime-as_of resolves to version WRITE time
(so a later-written-but-earlier-dated backfill collapses to "now"), while int-version
is exact-match. Locks: per-symbol integer version index is the addressing authority.
"""
import shutil
import tempfile
import time
from datetime import datetime, timezone

import pandas as pd
from arcticdb import Arctic

WORKDIR = tempfile.mkdtemp(prefix="phase0_addr_")
URI = f"lmdb://{WORKDIR}"


def frame(value: float) -> pd.DataFrame:
    df = pd.DataFrame({"instrument_id": ["X"], "value": [value]},
                      index=pd.to_datetime(["2026-01-01T00:00:00"]))
    df.index.name = "valid_time"
    return df


def main() -> None:
    ac = Arctic(URI)
    lib = ac.get_or_create_library("phase0.addr")

    wall_times = []
    versions = []
    snapshots = []
    for i, val in enumerate([10.0, 20.0, 30.0]):
        wall_times.append(datetime.now(timezone.utc))   # captured BEFORE write i
        time.sleep(1.1)                                 # ensure distinct wall-clock per write
        v = lib.write("X", frame(val)).version
        snap = f"snap_v{v}"
        lib.snapshot(snap, versions={"X": v})
        versions.append(v); snapshots.append(snap)
        print(f"wrote value={val} -> version={v}, snapshot={snap}")

    print("\n--- (a) read by INTEGER version (expect exact-match 10/20/30) ---")
    int_results = []
    for v in versions:
        val = lib.read("X", as_of=int(v)).data["value"].iloc[0]
        int_results.append((v, val)); print(f"as_of=int({v}) -> {val}")

    print("\n--- (b) read by DATETIME as_of captured BEFORE each write ---")
    dt_results = []
    for i, wt in enumerate(wall_times):
        try:
            val = lib.read("X", as_of=wt).data["value"].iloc[0]
        except Exception as e:                          # before-first-write may raise
            val = f"ERR:{type(e).__name__}"
        dt_results.append((wt.isoformat(), val)); print(f"as_of=datetime({wt.isoformat()}) -> {val}")

    print("\n--- (c) read by SNAPSHOT name (expect exact-match 10/20/30) ---")
    snap_results = []
    for snap in snapshots:
        val = lib.read("X", as_of=snap).data["value"].iloc[0]
        snap_results.append((snap, val)); print(f"as_of='{snap}' -> {val}")

    # Assertions that encode the spec's claims:
    assert [r[1] for r in int_results] == [10.0, 20.0, 30.0], "int-version is NOT exact-match"
    assert [r[1] for r in snap_results] == [10.0, 20.0, 30.0], "snapshot name is NOT exact-match"
    # datetime-as_of must NOT reproduce the exact 10/20/30 sequence keyed on data dates:
    assert [r[1] for r in dt_results] != [10.0, 20.0, 30.0], \
        "datetime-as_of unexpectedly behaved like a data-knowledge index"
    print("\nCONFIRMED: int-version exact-match; snapshot exact-match; "
          "datetime-as_of tracks WRITE time (NOT data knowledge date).")
    shutil.rmtree(WORKDIR, ignore_errors=True)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the experiment.**

```bash
cd /Users/marty/repos/energex && uv run python scripts/phase0_version_addressing.py
```

Expected output (shape; datetime-as_of values will reflect write-time resolution, e.g. the wall-time before write 0 precedes all versions and errors, while later wall-times resolve to the most recent version at that instant):

```
wrote value=10.0 -> version=0, snapshot=snap_v0
wrote value=20.0 -> version=1, snapshot=snap_v1
wrote value=30.0 -> version=2, snapshot=snap_v2

--- (a) read by INTEGER version (expect exact-match 10/20/30) ---
as_of=int(0) -> 10.0
as_of=int(1) -> 20.0
as_of=int(2) -> 30.0

--- (b) read by DATETIME as_of captured BEFORE each write ---
as_of=datetime(...) -> ERR:...        # before first write
as_of=datetime(...) -> 10.0           # resolves to whatever version existed at that WALL time
as_of=datetime(...) -> 20.0

--- (c) read by SNAPSHOT name (expect exact-match 10/20/30) ---
as_of='snap_v0' -> 10.0
as_of='snap_v1' -> 20.0
as_of='snap_v2' -> 30.0

CONFIRMED: int-version exact-match; snapshot exact-match; datetime-as_of tracks WRITE time (NOT data knowledge date).
```

Gate inside the step: the script terminates without `AssertionError`. The datetime-as_of column must demonstrably key off wall-clock write time, not the (constant) data `valid_time`.

- [ ] **Step 3: Record section 3 and lock the decision.** Replace the UNRESOLVED tokens in section 3 of the findings file with the int/datetime/snapshot result tables from Step 2, set both CONFIRMED lines to `YES`, and write the locked decision:

```
DECISION (locked): The per-symbol INTEGER version index (sidecar {symbol}__vintages) is the
sole vintage-addressing authority. read_as_of resolves as_of -> floor entry -> lib.read(as_of=int(version)).
datetime-as_of is FORBIDDEN for vintage reads (resolves to version write time, collapsing backfills).
Named snapshots are UI-only convenience; correctness never depends on them.
```

- [ ] **Step 4: Commit the addressing decision.**

```bash
cd /Users/marty/repos/energex && git add scripts/phase0_version_addressing.py docs/superpowers/notes/2026-06-16-phase0-findings.md && git commit -m "Confirm int-version exact-match vs datetime-as_of write-time; lock version-index authority"
```

Expected: `2 files changed`.

- [ ] **Step 5: Verify the findings file has no remaining UNRESOLVED tokens.**

```bash
cd /Users/marty/repos/energex && ! grep -n "UNRESOLVED" docs/superpowers/notes/2026-06-16-phase0-findings.md && echo "ALL PHASE 0 ITEMS RESOLVED"
```

Expected output:

```
ALL PHASE 0 ITEMS RESOLVED
```

Gate: `grep` finds zero `UNRESOLVED` tokens; the version-index authority decision is committed.

---

**Gate:** `grep -c UNRESOLVED docs/superpowers/notes/2026-06-16-phase0-findings.md` returns `0`; `uv run python scripts/phase0_minio_smoke.py` prints `SMOKE OK` and the `arctic` bucket + test object are visible in the committed `phase0-minio-console.png`; `uv run python scripts/phase0_version_addressing.py` exits 0 (int-version exact-match, datetime-as_of = write time) and the version-index authority decision is committed — only then may Phase 1 (scaffold) begin.

---

## Phase 1 — Scaffold core + orchestration

This phase carves out the framework-agnostic `energex.core` package, moves the three storage-invariant utility modules into it behind thin re-export shims (so all 122 existing tests keep importing from the old paths), extends `exceptions`/`config` with the S1 contracts, and stands up an empty-but-loadable `energex.orchestration` Dagster `Definitions`. No business logic yet — the deliverable is a clean hexagonal skeleton that boots `uv run dagster dev` with zero errors and a green no-framework-imports boundary test.

Spec source: §5.1 (directory tree), §5.10 phase 1, §9 acceptance gates.

---

### Task 1 — Create `core/` package; move exceptions/logging_config/rate_limiter behind shims

**Files:**
- Create: `src/energex/core/__init__.py`
- Create (via `git mv`): `src/energex/core/exceptions.py`, `src/energex/core/logging_config.py`, `src/energex/core/rate_limiter.py`
- Modify: `src/energex/exceptions.py`, `src/energex/logging_config.py`, `src/energex/rate_limiter.py` (become thin re-export shims)
- Test: `tests/test_core_layout.py`

- [ ] **Step 1: Write the failing layout test.**

  Create `tests/test_core_layout.py`:
  ```python
  """Both the legacy import paths and the new energex.core paths must resolve to
  the SAME objects after the move, so the 122 pre-S1 tests keep importing the old
  paths while new code imports energex.core.*."""


  def test_exceptions_old_and_new_paths_are_identical():
      from energex.core.exceptions import EnergexError as New
      from energex.exceptions import EnergexError as Old

      assert Old is New


  def test_logging_config_old_and_new_paths_are_identical():
      from energex.core.logging_config import setup_logging as new
      from energex.logging_config import setup_logging as old

      assert old is new


  def test_rate_limiter_old_and_new_paths_are_identical():
      from energex.core.rate_limiter import RateLimiter as New
      from energex.rate_limiter import RateLimiter as Old

      assert Old is New
  ```

- [ ] **Step 2: Run the test and confirm the EXPECTED failure (no `energex.core` yet).**
  ```bash
  uv run pytest tests/test_core_layout.py -q
  ```
  Expected output (collection/import error):
  ```
  ModuleNotFoundError: No module named 'energex.core'
  ...
  3 errors in 0.XXs
  ```

- [ ] **Step 3: Create the empty `core` package.**

  Create `src/energex/core/__init__.py`:
  ```python
  """energex.core — framework-agnostic business contracts.

  CI-enforced invariant: this package must NEVER import dagster, fastapi, or
  langgraph (see tests/test_core_has_no_framework_imports.py).
  """
  ```

- [ ] **Step 4: Move the three modules into `core/` with git (preserves history).**
  ```bash
  cd /Users/marty/repos/energex && git mv src/energex/exceptions.py src/energex/core/exceptions.py && git mv src/energex/logging_config.py src/energex/core/logging_config.py && git mv src/energex/rate_limiter.py src/energex/core/rate_limiter.py
  ```
  Expected: the command exits 0 with no output.

- [ ] **Step 5: Write the `exceptions` shim at the old path.**

  Create `src/energex/exceptions.py`:
  ```python
  """Re-export shim — exceptions moved to energex.core.exceptions (S1).

  Kept so the 122 pre-S1 tests and existing modules keep importing energex.exceptions.
  """

  from energex.core.exceptions import (  # noqa: F401
      AnalysisError,
      ConfigurationError,
      DatabaseError,
      DataFetchError,
      EnergexError,
      LLMProviderError,
  )
  ```

- [ ] **Step 6: Write the `logging_config` shim at the old path.**

  Create `src/energex/logging_config.py`:
  ```python
  """Re-export shim — logging moved to energex.core.logging_config (S1)."""

  from energex.core.logging_config import setup_logging  # noqa: F401
  ```

- [ ] **Step 7: Write the `rate_limiter` shim at the old path.**

  Create `src/energex/rate_limiter.py`:
  ```python
  """Re-export shim — rate limiter moved to energex.core.rate_limiter (S1)."""

  from energex.core.rate_limiter import RateLimiter  # noqa: F401
  ```

- [ ] **Step 8: Run the layout test and confirm the EXPECTED pass.**
  ```bash
  uv run pytest tests/test_core_layout.py -q
  ```
  Expected output:
  ```
  3 passed in 0.XXs
  ```

- [ ] **Step 9: Run the FULL suite and confirm the move broke nothing (122 still green + 3 new = 125).**
  ```bash
  uv run pytest -q
  ```
  Expected tail:
  ```
  125 passed in X.XXs
  ```

- [ ] **Step 10: Commit.**
  ```bash
  cd /Users/marty/repos/energex && git add -A && git commit -m "Move exceptions/logging/rate_limiter into energex.core behind shims"
  ```

---

### Task 2 — Add S1 exception classes to `core/exceptions.py`

**Files:**
- Modify: `src/energex/core/exceptions.py`
- Test: `tests/test_core_exceptions.py`

- [ ] **Step 1: Write the failing test for the new exception classes.**

  Create `tests/test_core_exceptions.py`:
  ```python
  import pytest

  from energex.core.exceptions import (
      EnergexError,
      PartitionError,
      QualityGateError,
      StorageError,
      SymbologyError,
      VintageImmutableError,
  )


  @pytest.mark.parametrize(
      "exc",
      [QualityGateError, StorageError, SymbologyError, PartitionError, VintageImmutableError],
  )
  def test_new_exceptions_subclass_base(exc):
      assert issubclass(exc, EnergexError)


  def test_quality_gate_error_carries_schema_and_failures():
      err = QualityGateError(schema_name="OHLCV", failures=["row 3: Close < 0"])
      assert err.schema_name == "OHLCV"
      assert err.failures == ["row 3: Close < 0"]
      assert "OHLCV" in str(err)
  ```

- [ ] **Step 2: Run it and confirm the EXPECTED failure (import error).**
  ```bash
  uv run pytest tests/test_core_exceptions.py -q
  ```
  Expected:
  ```
  ImportError: cannot import name 'QualityGateError' from 'energex.core.exceptions'
  ...
  1 error in 0.XXs
  ```

- [ ] **Step 3: Append the new exception classes to `core/exceptions.py`.**

  Add to the END of `src/energex/core/exceptions.py`:
  ```python


  class QualityGateError(EnergexError):
      """Raised by core.quality.validate when a frame fails its pandera schema.

      Carries the schema name and the collected pandera failure_cases so the
      Dagster asset check and CI can surface every failure at once.
      """

      def __init__(self, *, schema_name: str, failures: object) -> None:
          self.schema_name = schema_name
          self.failures = failures
          super().__init__(
              f"Quality gate failed for schema {schema_name!r}: {len(failures)} failure(s)"
          )


  class StorageError(EnergexError):
      """Raised on ArcticDB storage / commit-protocol failures."""


  class SymbologyError(EnergexError):
      """Raised when an instrument_id cannot be resolved or its mode is inconsistent."""


  class PartitionError(EnergexError):
      """Raised when a Dagster partition key cannot be mapped to a valid_time range."""


  class VintageImmutableError(EnergexError):
      """Raised on an attempt to mutate an already-committed live (non-reconstructed) vintage."""
  ```

- [ ] **Step 4: Run the test and confirm the EXPECTED pass.**
  ```bash
  uv run pytest tests/test_core_exceptions.py -q
  ```
  Expected:
  ```
  6 passed in 0.XXs
  ```

- [ ] **Step 5: Commit.**
  ```bash
  cd /Users/marty/repos/energex && git add -A && git commit -m "Add S1 core exceptions (QualityGate/Storage/Symbology/Partition/VintageImmutable)"
  ```

---

### Task 3 — Boundary test: `core/` imports no orchestration framework

**Files:**
- Test: `tests/test_core_has_no_framework_imports.py`

- [ ] **Step 1: Write the boundary test (it must PASS on the clean core).**

  Create `tests/test_core_has_no_framework_imports.py`:
  ```python
  """CI-enforced hexagonal boundary: energex.core is framework-agnostic.

  Walks every .py file under src/energex/core and asserts none import dagster,
  fastapi, or langgraph. This is the load-bearing invariant from spec §4/§9."""

  import re
  from pathlib import Path

  import energex.core as core

  FORBIDDEN = re.compile(
      r"^\s*(?:import|from)\s+(dagster|fastapi|langgraph)\b",
      re.MULTILINE,
  )


  def test_core_has_no_framework_imports():
      core_dir = Path(core.__file__).parent
      offenders: list[str] = []
      for py in sorted(core_dir.rglob("*.py")):
          text = py.read_text(encoding="utf-8")
          if FORBIDDEN.search(text):
              offenders.append(str(py.relative_to(core_dir)))
      assert not offenders, f"framework imports found in energex.core: {offenders}"
  ```

- [ ] **Step 2: Run it and confirm the EXPECTED pass (clean core).**
  ```bash
  uv run pytest tests/test_core_has_no_framework_imports.py -q
  ```
  Expected:
  ```
  1 passed in 0.XXs
  ```

- [ ] **Step 3: Sanity-check that the regex actually bites (temporary negative probe, then revert).**
  ```bash
  cd /Users/marty/repos/energex && printf '\nimport dagster  # TEMP probe\n' >> src/energex/core/__init__.py && uv run pytest tests/test_core_has_no_framework_imports.py -q; git checkout -- src/energex/core/__init__.py
  ```
  Expected: the run FAILS with `framework imports found in energex.core: ['__init__.py']`, then `git checkout` restores the clean file (confirm with `git status` shows no change to `__init__.py`).

- [ ] **Step 4: Commit.**
  ```bash
  cd /Users/marty/repos/energex && git add -A && git commit -m "Add CI boundary test asserting energex.core imports no dagster/fastapi/langgraph"
  ```

---

### Task 4 — Move config into `core/`; add ArcticDB/Neo4j/Connector settings

**Files:**
- Create (via `git mv`): `src/energex/core/config.py`
- Modify: `src/energex/core/config.py` (new import path + new nested configs)
- Modify: `src/energex/config.py` (becomes re-export shim)
- Test: `tests/test_core_config_settings.py`

- [ ] **Step 1: Write the failing env-binding test for the new nested configs.**

  Create `tests/test_core_config_settings.py`:
  ```python
  from energex.core.config import (
      ArcticDBConfig,
      ConnectorConfig,
      EnergexSettings,
      Neo4jConfig,
      get_settings,
      reset_settings,
  )


  def test_new_config_classes_are_nested_on_settings():
      s = EnergexSettings()
      assert isinstance(s.arctic, ArcticDBConfig)
      assert isinstance(s.neo4j, Neo4jConfig)
      assert isinstance(s.connectors, ConnectorConfig)


  def test_legacy_database_alias_preserved():
      # test_api_contract / test_database_ergonomics rely on settings.database.db_path.
      s = EnergexSettings()
      assert s.database.db_path is not None


  def test_env_binding_for_arctic_neo4j_connectors(monkeypatch):
      monkeypatch.setenv("MINIO_ENDPOINT", "minio:9000")
      monkeypatch.setenv("ARCTIC_BUCKET", "arctic")
      monkeypatch.setenv("NEO4J_URI", "bolt://db:7687")
      monkeypatch.setenv("EIA_API_KEY", "secret-eia")
      monkeypatch.setenv("ERCOT_SUBSCRIPTION_KEY", "sub-key")
      monkeypatch.setenv("NOAA_TOKEN", "noaa-tok")
      reset_settings()
      s = get_settings(reload=True)
      assert s.arctic.minio_endpoint == "minio:9000"
      assert s.arctic.minio_bucket == "arctic"
      assert s.neo4j.uri == "bolt://db:7687"
      assert s.connectors.eia_api_key.get_secret_value() == "secret-eia"
      assert s.connectors.ercot_subscription_key.get_secret_value() == "sub-key"
      assert s.connectors.noaa_token.get_secret_value() == "noaa-tok"
      reset_settings()


  def test_config_old_and_new_paths_are_identical():
      from energex.config import get_settings as old
      from energex.core.config import get_settings as new

      assert old is new
  ```

- [ ] **Step 2: Run it and confirm the EXPECTED failure.**
  ```bash
  uv run pytest tests/test_core_config_settings.py -q
  ```
  Expected:
  ```
  ModuleNotFoundError: No module named 'energex.core.config'
  ...
  errors in 0.XXs
  ```

- [ ] **Step 3: Move config into `core/`.**
  ```bash
  cd /Users/marty/repos/energex && git mv src/energex/config.py src/energex/core/config.py
  ```

- [ ] **Step 4: Repoint the moved config's exceptions import to the core path.**

  In `src/energex/core/config.py`, replace:
  ```python
  from energex.exceptions import ConfigurationError
  ```
  with:
  ```python
  from energex.core.exceptions import ConfigurationError
  ```

- [ ] **Step 5: Add the three new nested config classes.**

  In `src/energex/core/config.py`, insert these classes immediately BEFORE `class EnergexSettings(BaseSettings):`:
  ```python
  class ArcticDBConfig(BaseSettings):
      """ArcticDB-on-MinIO storage config (env: MINIO_* / ARCTIC_*)."""

      minio_endpoint: str = Field(
          default="localhost:9000", validation_alias="MINIO_ENDPOINT"
      )
      minio_access_key: SecretStr | None = Field(
          default=None, validation_alias="MINIO_ACCESS_KEY"
      )
      minio_secret_key: SecretStr | None = Field(
          default=None, validation_alias="MINIO_SECRET_KEY"
      )
      minio_bucket: str = Field(default="arctic", validation_alias="ARCTIC_BUCKET")
      arctic_secure: bool = Field(default=False, validation_alias="ARCTIC_SECURE")

      model_config = SettingsConfigDict(case_sensitive=False, populate_by_name=True)


  class Neo4jConfig(BaseSettings):
      """Neo4j entity-graph config (env: NEO4J_*)."""

      uri: str = Field(default="bolt://localhost:7687", description="env: NEO4J_URI")
      user: str = Field(default="neo4j", description="env: NEO4J_USER")
      password: SecretStr | None = Field(default=None, description="env: NEO4J_PASSWORD")

      model_config = SettingsConfigDict(env_prefix="NEO4J_", case_sensitive=False)


  class ConnectorConfig(BaseSettings):
      """Source connector credentials (env: EIA_API_KEY, ERCOT_*, NOAA_TOKEN)."""

      eia_api_key: SecretStr | None = Field(default=None, validation_alias="EIA_API_KEY")
      ercot_username: str | None = Field(default=None, validation_alias="ERCOT_USERNAME")
      ercot_password: SecretStr | None = Field(
          default=None, validation_alias="ERCOT_PASSWORD"
      )
      ercot_subscription_key: SecretStr | None = Field(
          default=None, validation_alias="ERCOT_SUBSCRIPTION_KEY"
      )
      noaa_token: SecretStr | None = Field(default=None, validation_alias="NOAA_TOKEN")

      model_config = SettingsConfigDict(case_sensitive=False, populate_by_name=True)
  ```

- [ ] **Step 6: Nest the new configs onto `EnergexSettings`.**

  In `src/energex/core/config.py`, inside `class EnergexSettings`, locate:
  ```python
      analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)
  ```
  and add directly after it:
  ```python
      arctic: ArcticDBConfig = Field(default_factory=ArcticDBConfig)
      neo4j: Neo4jConfig = Field(default_factory=Neo4jConfig)
      connectors: ConnectorConfig = Field(default_factory=ConnectorConfig)
  ```

- [ ] **Step 7: Replace the old `config.py` with a re-export shim.**

  Create `src/energex/config.py`:
  ```python
  """Re-export shim — config moved to energex.core.config (S1).

  Kept so existing modules and the 122 pre-S1 tests keep importing energex.config.
  """

  from energex.core.config import (  # noqa: F401
      AnalysisConfig,
      ArcticDBConfig,
      ConnectorConfig,
      DataFetchConfig,
      DatabaseConfig,
      EnergexSettings,
      LLMConfig,
      LoggingConfig,
      Neo4jConfig,
      NewsConfig,
      get_settings,
      reset_settings,
  )
  ```

- [ ] **Step 8: Run the config test and confirm the EXPECTED pass.**
  ```bash
  uv run pytest tests/test_core_config_settings.py -q
  ```
  Expected:
  ```
  5 passed in 0.XXs
  ```

- [ ] **Step 9: Re-run the boundary test (core now has config.py) and the FULL suite.**
  ```bash
  uv run pytest tests/test_core_has_no_framework_imports.py -q && uv run pytest -q
  ```
  Expected: boundary test `1 passed`; full suite tail `134 passed in X.XXs` (122 pre-S1 + 12 new across tasks 1–4).

- [ ] **Step 10: Commit.**
  ```bash
  cd /Users/marty/repos/energex && git add -A && git commit -m "Move config into energex.core; add ArcticDB/Neo4j/Connector settings"
  ```

---

### Task 5 — Add the `orchestration` extra and install Dagster

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add the `orchestration` optional-dependency group.**

  In `pyproject.toml`, inside `[project.optional-dependencies]`, add after the `service = [...]` block:
  ```toml
  orchestration = [
      "dagster>=1.13.9,<1.14.0",
      "dagster-webserver>=1.13.9,<1.14.0",
      "dagster-postgres>=0.29.9,<0.30.0"
  ]
  ```

- [ ] **Step 2: Add `orchestration` to the `all` aggregate extra.**

  In `pyproject.toml`, change:
  ```toml
  all = [
      "energex[dev]",
      "energex[llm]",
      "energex[sentiment]",
      "energex[service]"
  ]
  ```
  to:
  ```toml
  all = [
      "energex[dev]",
      "energex[llm]",
      "energex[sentiment]",
      "energex[service]",
      "energex[orchestration]"
  ]
  ```

- [ ] **Step 3: Add a mypy override so the untyped Dagster import is tolerated.**

  In `pyproject.toml`, in the `[[tool.mypy.overrides]]` `module = [...]` list, add `"dagster.*",` after `"apscheduler.*",`:
  ```toml
  module = [
      "yfinance.*",
      "plotly.*",
      "duckdb.*",
      "feedparser.*",
      "bs4.*",
      "pytz",
      "requests.*",
      "apscheduler.*",
      "dagster.*",
  ]
  ```

- [ ] **Step 4: Sync the orchestration extra and verify Dagster imports at the pinned version.**
  ```bash
  cd /Users/marty/repos/energex && uv sync --extra dev --extra orchestration && uv run python -c "import dagster; print(dagster.__version__)"
  ```
  Expected last line:
  ```
  1.13.9
  ```

- [ ] **Step 5: Commit.**
  ```bash
  cd /Users/marty/repos/energex && git add -A && git commit -m "Add orchestration extra (dagster 1.13.9, webserver, postgres) + mypy override"
  ```

---

### Task 6 — Scaffold the `orchestration` package with an empty `Definitions`

**Files:**
- Create: `src/energex/orchestration/__init__.py`, `partitions.py`, `resources.py`, `assets.py`, `checks.py`, `schedules.py`, `sensors.py`, `reconcile.py`, `definitions.py`

- [ ] **Step 1: Create the package init.**

  Create `src/energex/orchestration/__init__.py`:
  ```python
  """energex.orchestration — the ONLY package that imports dagster (S1 write-side).

  Populated phase-by-phase (spec §5.6/§5.10). Phase 1 ships an empty, loadable
  Definitions so `uv run dagster dev` boots with no errors.
  """
  ```

- [ ] **Step 2: Create the partitions placeholder.**

  Create `src/energex/orchestration/partitions.py`:
  ```python
  """Partition definitions (EIA weekly / ERCOT daily / NOAA monthly).

  Populated in phases 5-7; empty in phase 1.
  """
  ```

- [ ] **Step 3: Create the resources placeholder.**

  Create `src/energex/orchestration/resources.py`:
  ```python
  """Dagster ConfigurableResources (ArcticDB / Http / ERCOT / Neo4j).

  Populated in phase 5; phase 1 exposes an empty resource map.
  """

  RESOURCES: dict[str, object] = {}
  ```

- [ ] **Step 4: Create the empty assets module.**

  Create `src/energex/orchestration/assets.py`:
  ```python
  """Dagster assets (fetch -> validate -> commit_vintage). Empty in phase 1."""

  from typing import Any

  ASSETS: list[Any] = []
  ```

- [ ] **Step 5: Create the empty checks module.**

  Create `src/energex/orchestration/checks.py`:
  ```python
  """Dagster @asset_check definitions (single-sourced core.quality gate). Empty in phase 1."""

  from typing import Any

  CHECKS: list[Any] = []
  ```

- [ ] **Step 6: Create the schedules placeholder.**

  Create `src/energex/orchestration/schedules.py`:
  ```python
  """Schedules (always set execution_timezone). Empty in phase 1."""

  from typing import Any

  SCHEDULES: list[Any] = []
  ```

- [ ] **Step 7: Create the sensors stub.**

  Create `src/energex/orchestration/sensors.py`:
  ```python
  """Sensors (missed-release catch-up). Stub in phase 1."""

  from typing import Any

  SENSORS: list[Any] = []
  ```

- [ ] **Step 8: Create the reconcile stub.**

  Create `src/energex/orchestration/reconcile.py`:
  ```python
  """Out-of-band GC / reconciliation asset (orphan-version cleanup, missed-vintage
  catch-up). Stub in phase 1; implemented in phase 5 (spec §5.6)."""

  from typing import Any

  RECONCILE_ASSETS: list[Any] = []
  ```

- [ ] **Step 9: Create the empty `Definitions`.**

  Create `src/energex/orchestration/definitions.py`:
  ```python
  """Top-level Dagster Definitions. Phase 1 wires everything empty but loadable."""

  import dagster as dg

  from energex.orchestration.assets import ASSETS
  from energex.orchestration.checks import CHECKS
  from energex.orchestration.reconcile import RECONCILE_ASSETS
  from energex.orchestration.resources import RESOURCES
  from energex.orchestration.schedules import SCHEDULES
  from energex.orchestration.sensors import SENSORS

  defs = dg.Definitions(
      assets=[*ASSETS, *RECONCILE_ASSETS],
      asset_checks=CHECKS,
      schedules=SCHEDULES,
      sensors=SENSORS,
      resources=RESOURCES,
  )
  ```

- [ ] **Step 10: Smoke-import the empty Definitions from Python.**
  ```bash
  cd /Users/marty/repos/energex && uv run python -c "from energex.orchestration.definitions import defs; import dagster as dg; assert isinstance(defs, dg.Definitions); print('defs OK')"
  ```
  Expected:
  ```
  defs OK
  ```

- [ ] **Step 11: Commit.**
  ```bash
  cd /Users/marty/repos/energex && git add -A && git commit -m "Scaffold energex.orchestration with an empty loadable Dagster Definitions"
  ```

---

### Task 7 — Definitions-load test + `dagster definitions validate` gate

**Files:**
- Test: `tests/test_definitions_load.py`

- [ ] **Step 1: Write the failing-then-passing definitions-load test.**

  Create `tests/test_definitions_load.py`:
  ```python
  """The empty orchestration.Definitions must build and validate (spec §9 gate)."""

  import subprocess

  import dagster as dg


  def test_definitions_builds():
      from energex.orchestration.definitions import defs

      assert isinstance(defs, dg.Definitions)
      # Empty in phase 1 — nothing to resolve, but the object must be well-formed.
      assert list(defs.get_all_asset_specs()) == []


  def test_dagster_definitions_validate_cli():
      result = subprocess.run(
          ["uv", "run", "dagster", "definitions", "validate",
           "-m", "energex.orchestration.definitions"],
          capture_output=True,
          text=True,
      )
      assert result.returncode == 0, result.stderr
      assert "Validation successful" in (result.stdout + result.stderr)
  ```

- [ ] **Step 2: Run the test and confirm it PASSES (Definitions already builds from Task 6).**
  ```bash
  uv run pytest tests/test_definitions_load.py -q
  ```
  Expected:
  ```
  2 passed in X.XXs
  ```

- [ ] **Step 3: Run the CLI validator directly to confirm the gate command.**
  ```bash
  cd /Users/marty/repos/energex && uv run dagster definitions validate -m energex.orchestration.definitions
  ```
  Expected (final line):
  ```
  Validation successful for code location energex.orchestration.definitions.
  ```

- [ ] **Step 4: Run the full Phase-1 verification trio.**
  ```bash
  uv run pytest tests/test_core_has_no_framework_imports.py tests/test_definitions_load.py -q && uv run pytest -q
  ```
  Expected: first command `3 passed`; full suite tail `136 passed in X.XXs` (122 pre-S1 + Task 1–4 + Task 7).

- [ ] **Step 5: Commit.**
  ```bash
  cd /Users/marty/repos/energex && git add -A && git commit -m "Add test_definitions_load: empty Definitions builds and validates via CLI"
  ```

---

### Task 8 — Chrome verification: Dagster UI loads the empty Definitions

**Files:** none (manual operator verification of the §9 gate).

- [ ] **Step 1: Launch `dagster dev` in the background and capture startup logs.**
  ```bash
  cd /Users/marty/repos/energex && DAGSTER_HOME=/tmp/energex-dagster-home uv run dagster dev -m energex.orchestration.definitions
  ```
  Run this with `run_in_background: true`. Expected log lines within ~15s (no tracebacks):
  ```
  Serving dagster-webserver on http://127.0.0.1:3000 ...
  Loaded code location energex.orchestration.definitions
  ```
  Gate check: grep the captured background output for `Serving dagster-webserver` AND confirm the absence of `Error` / `Traceback` before proceeding.

- [ ] **Step 2: Load the Chrome MCP tools.**

  Call `ToolSearch` with query:
  ```
  select:mcp__claude-in-chrome__tabs_context_mcp,mcp__claude-in-chrome__navigate,mcp__claude-in-chrome__computer,mcp__claude-in-chrome__read_page,mcp__claude-in-chrome__tabs_create_mcp
  ```

- [ ] **Step 3: Open the Dagster UI and confirm it renders.**

  Use `mcp__claude-in-chrome__navigate` to open `http://localhost:3000`, then `mcp__claude-in-chrome__read_page` to confirm the Dagster operator console renders (Overview/Assets/Deployment nav visible) with no error banner. Expected: the page loads; the Assets view shows an empty graph (no assets yet) — consistent with the empty phase-1 Definitions.

- [ ] **Step 4: Confirm the Deployment tab shows no code-location load errors and screenshot.**

  Use `mcp__claude-in-chrome__navigate` to open `http://localhost:3000/deployment/locations`, then `mcp__claude-in-chrome__computer` (action: `screenshot`) to capture the page. Expected: the `energex.orchestration.definitions` code location row shows status **Loaded** (green), with **no** "Failed"/red error status. Save the screenshot as the gate artifact.

- [ ] **Step 5: Stop the background `dagster dev` process.**

  Terminate the backgrounded `dagster dev` run (it was started detached in Step 1). Expected: process exits; port 3000 is freed.

---

Gate: `uv run dagster definitions validate -m energex.orchestration.definitions` exits 0 ("Validation successful"); `tests/test_core_has_no_framework_imports.py` and `tests/test_definitions_load.py` are green; the full suite passes (122 pre-S1 tests still green); and the Dagster UI at `http://localhost:3000` loads the empty Definitions with the code location in **Loaded** state and zero load errors on the Deployment tab (screenshot captured).

---

I have everything I need: confirmed `write().version`/`append().version` are ints, `append` rejects non-monotonic indices (sparse backfill needs read-concat-write), `lib.delete(symbol, versions=int)` removes a single orphan version, `read(symbol, as_of=int, date_range=...)` exact-matches by version, tz is stripped to naive on store, and `list_versions` keys expose `.version`/`.symbol`. CI's `test` job already runs `uv run --all-extras pytest`, so tests under `tests/` are gated once `arcticdb` lands in the `storage` extra. Here is the section.

## Phase 2 — Bitemporal Storage Core (CROWN JEWEL)

This phase builds `core/symbology.py` and `core/storage.py` — the bitemporal store of record — incrementally, one function per failing test, against an **offline LMDB-backed ArcticDB** (`lmdb://<tmp>`; MinIO is deployment-only). Verified facts that the code below depends on (probed against `arcticdb==6.18.1`): `write()/append().version` are plain `int`; `append` rejects an index whose start is `<` the existing end (so sparse backfill must read-concat-write, never `append`); `lib.delete(symbol, versions=<int>)` removes exactly one orphan version; `read(symbol, as_of=<int>, date_range=...)` is an exact-match by integer version; timezone is **stripped** on store (re-localize on read); `list_versions(symbol)` keys expose `.version`/`.symbol`.

**Assumptions carried from Phase 1 (must already be true before this phase):** `src/energex/core/__init__.py` exists; `src/energex/core/exceptions.py` exists and exports `StorageError` and `SymbologyError` (per the shared contract); the empty `Definitions` and `settings.database` alias are green. This phase adds `arcticdb`/`pandas` to the `storage` extra if Phase-1/PRE-S1 has not already.

### Task 0 — Branch, storage extra, offline ArcticDB fixtures

**Files:**
- Modify: `pyproject.toml`
- Modify: `tests/conftest.py`

Steps:

- [ ] **Step 1: Create the feature branch (never work on `main`).**
```bash
git -C /Users/marty/repos/energex checkout -b feat/s1-phase2-storage
```
Expected output: `Switched to a new branch 'feat/s1-phase2-storage'`.

- [ ] **Step 2: Ensure the `storage` extra carries arcticdb + pandas.** Open `pyproject.toml` and add this block under `[project.optional-dependencies]` (immediately after the `service = [...]` block). If a `storage = [...]` block already exists from PRE-S1, make it match exactly:
```toml
storage = [
    "arcticdb>=4.0",
    "pandas>=2.0"
]
```

- [ ] **Step 3: Sync and confirm arcticdb imports under uv.**
```bash
uv sync --extra storage --extra dev && uv run python -c "import arcticdb, pandas; print(arcticdb.__version__, pandas.__version__)"
```
Expected output (last line): `6.18.1 2.2.3`.

- [ ] **Step 4: Add offline LMDB ArcticDB fixtures to `tests/conftest.py`.** Append to the end of the file:
```python
@pytest.fixture
def arctic_uri(tmp_path) -> str:
    """A unique, offline LMDB-backed ArcticDB URI under pytest's tmp (no MinIO)."""
    return f"lmdb://{tmp_path / 'energex-test-arctic'}"


@pytest.fixture
def arctic_store(arctic_uri):
    """A fresh, isolated ArcticDB instance; LMDB files vacated with tmp_path."""
    import arcticdb as adb

    return adb.Arctic(arctic_uri)


@pytest.fixture
def arctic_lib(arctic_store):
    """A single throwaway library; storage functions take the Library object directly."""
    return arctic_store.create_library("phase2")
```

- [ ] **Step 5: Confirm the existing suite still collects (no behavior change yet).**
```bash
uv run pytest -q tests/conftest.py --collect-only >/dev/null && echo CONFTEST_OK
```
Expected output: `CONFTEST_OK`.

- [ ] **Step 6: Commit.**
```bash
git -C /Users/marty/repos/energex add pyproject.toml tests/conftest.py && git -C /Users/marty/repos/energex commit -m "Phase 2: storage extra + offline LMDB ArcticDB test fixtures"
```

### Task 1 — `core/symbology.py` + guardrail test (mode ⇄ library class)

**Files:**
- Create: `src/energex/core/symbology.py`
- Test: `tests/test_symbology.py`

Steps:

- [ ] **Step 1: Write the failing guardrail test.** Create `tests/test_symbology.py`:
```python
"""Symbology guardrail: every entry's revision_mode must match its library class."""

from __future__ import annotations

import pytest

from energex.core import symbology
from energex.core.exceptions import SymbologyError


def test_every_entry_mode_matches_library_class():
    for instrument_id, (library, _symbol, mode) in symbology._TABLE.items():
        assert mode == symbology.LIBRARY_MODE[library], (
            f"{instrument_id}: mode {mode!r} != library {library!r} class "
            f"{symbology.LIBRARY_MODE[library]!r}"
        )


def test_resolve_revision_mode_and_symbol_lookups():
    assert symbology.resolve("CME.CL.CLF26") == ("prices.futures", "CL_CLF26")
    assert symbology.revision_mode("CME.CL.CLF26") == "bitemporal_merge"
    assert symbology.mode_for_symbol("CL_FRONT") == "degenerate"
    assert symbology.library_for_symbol("hdd_texas") == "weather"
    assert symbology.contracts_for("crude") == ["CL_CLF26", "CL_CLG26"]


def test_unknown_identifiers_raise():
    with pytest.raises(SymbologyError):
        symbology.resolve("NOPE.X.Y")
    with pytest.raises(SymbologyError):
        symbology.mode_for_symbol("not_a_symbol")
    with pytest.raises(SymbologyError):
        symbology.contracts_for("unobtanium")
```

- [ ] **Step 2: Run it and observe the expected import failure.**
```bash
uv run pytest -q tests/test_symbology.py
```
Expected: collection error / failure — `ModuleNotFoundError: No module named 'energex.core.symbology'`.

- [ ] **Step 3: Implement `src/energex/core/symbology.py`.**
```python
"""Static symbology for S1: instrument_id <-> (library, symbol, revision_mode).

Numbers live in ArcticDB; this module only routes. The Neo4j graph (phase 9)
references these symbols but never owns them.
"""

from __future__ import annotations

from energex.core.exceptions import SymbologyError

# instrument_id -> (library, symbol, revision_mode)
_TABLE: dict[str, tuple[str, str, str]] = {
    "EIA.NG.STORAGE.LOWER48": ("fundamentals.eia", "ng_storage_lower48", "bitemporal_merge"),
    "EIA.PET.CRUDE.STOCKS": ("fundamentals.eia", "pet_crude_stocks", "bitemporal_merge"),
    "ERCOT.DALMP.HB_HOUSTON": ("prices.power", "dalmp_hb_houston", "bitemporal_merge"),
    "NOAA.HDD.TEXAS": ("weather", "hdd_texas", "bitemporal_replace"),
    "CME.CL.FRONT": ("prices.intraday", "CL_FRONT", "degenerate"),
    "CME.CL.CLF26": ("prices.futures", "CL_CLF26", "bitemporal_merge"),
    "CME.CL.CLG26": ("prices.futures", "CL_CLG26", "bitemporal_merge"),
}

# The single source of truth for which revision mode each library class implies.
LIBRARY_MODE: dict[str, str] = {
    "fundamentals.eia": "bitemporal_merge",
    "prices.power": "bitemporal_merge",
    "weather": "bitemporal_replace",
    "prices.intraday": "degenerate",
    "prices.futures": "bitemporal_merge",
}

# commodity -> ordered list of contract SYMBOL strings (used by read_curve).
_CONTRACTS: dict[str, list[str]] = {
    "crude": ["CL_CLF26", "CL_CLG26"],
}

# Reverse index: symbol -> (library, revision_mode).
_BY_SYMBOL: dict[str, tuple[str, str]] = {
    symbol: (library, mode) for library, symbol, mode in _TABLE.values()
}


def resolve(instrument_id: str) -> tuple[str, str]:
    try:
        library, symbol, _mode = _TABLE[instrument_id]
    except KeyError as exc:
        raise SymbologyError(f"unknown instrument_id {instrument_id!r}") from exc
    return (library, symbol)


def revision_mode(instrument_id: str) -> str:
    try:
        return _TABLE[instrument_id][2]
    except KeyError as exc:
        raise SymbologyError(f"unknown instrument_id {instrument_id!r}") from exc


def contracts_for(commodity: str) -> list[str]:
    try:
        return list(_CONTRACTS[commodity])
    except KeyError as exc:
        raise SymbologyError(f"unknown commodity {commodity!r}") from exc


def mode_for_symbol(symbol: str) -> str:
    try:
        return _BY_SYMBOL[symbol][1]
    except KeyError as exc:
        raise SymbologyError(f"unknown symbol {symbol!r}") from exc


def library_for_symbol(symbol: str) -> str:
    try:
        return _BY_SYMBOL[symbol][0]
    except KeyError as exc:
        raise SymbologyError(f"unknown symbol {symbol!r}") from exc
```

- [ ] **Step 4: Run the test and observe the expected pass.**
```bash
uv run pytest -q tests/test_symbology.py
```
Expected output: `3 passed`.

- [ ] **Step 5: Commit.**
```bash
git -C /Users/marty/repos/energex add src/energex/core/symbology.py tests/test_symbology.py && git -C /Users/marty/repos/energex commit -m "Phase 2: static symbology with mode<->library guardrail"
```

### Task 2 — `core/storage.py` skeleton: canonicalize + replace-commit + read_as_of + _to_polars [GATE: test_storage_roundtrip]

**Files:**
- Create: `src/energex/core/storage.py`
- Test: `tests/test_storage_roundtrip.py`

Steps:

- [ ] **Step 1: Write the failing round-trip test (tz-aware UTC + ContractMonth `pl.Date` in==out via `_to_polars`).** Create `tests/test_storage_roundtrip.py`:
```python
"""GATE: tz-aware-UTC + dtype (incl. ContractMonth) survive a commit/read/_to_polars round-trip."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pandas as pd
import polars as pl

from energex.core import storage


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "instrument_id": ["NOAA.HDD.TEXAS", "NOAA.HDD.TEXAS"],
            "valid_time": [
                datetime(2024, 1, 2, 0, 0, tzinfo=timezone.utc),
                datetime(2024, 2, 1, 0, 0, tzinfo=timezone.utc),
            ],
            "ContractMonth": [date(2024, 1, 1), date(2024, 2, 1)],
            "value": [410.0, 360.0],
        }
    )


def test_storage_roundtrip(arctic_lib):
    as_of = datetime(2024, 2, 5, 16, 0, tzinfo=timezone.utc)
    v = storage.commit_vintage(
        arctic_lib,
        "hdd_texas",
        _frame(),
        as_of=as_of,
        source="noaa-nclimdiv",
        source_url="https://example/noaa",
        fetched_at=as_of,
        mode="bitemporal_replace",
    )
    assert isinstance(v, int)

    vi = arctic_lib.read("hdd_texas", as_of=int(v))
    pf = storage._to_polars(vi)

    # tz preserved as UTC on both time axes.
    assert pf.schema["Datetime"] == pl.Datetime(time_unit="ns", time_zone="UTC")
    assert pf.schema["valid_time"] == pl.Datetime(time_unit="ns", time_zone="UTC")
    # ContractMonth came back as a true date, not datetime64.
    assert pf.schema["ContractMonth"] == pl.Date
    assert pf["ContractMonth"].to_list() == [date(2024, 1, 1), date(2024, 2, 1)]
    assert pf["value"].to_list() == [410.0, 360.0]

    # read_as_of(None) returns the freshly committed vintage as a pandas frame.
    df = storage.read_as_of(arctic_lib, "hdd_texas", as_of=None)
    assert list(df["value"]) == [410.0, 360.0]
    assert df["vintage_reconstructed"].tolist() == [False, False]
```

- [ ] **Step 2: Run it and observe the expected import failure.**
```bash
uv run pytest -q tests/test_storage_roundtrip.py
```
Expected: collection error — `ModuleNotFoundError: No module named 'energex.core.storage'`.

- [ ] **Step 3: Implement the storage skeleton.** Create `src/energex/core/storage.py` (replace-commit works; merge raises until Task 3; `write_bars`/`reconcile_orphans` arrive in later tasks). Note `read_as_of(as_of=None)` deliberately uses `_latest_version` (latest *data* version) here — Task 5 hardens it to committed-only:
```python
"""ArcticDB bitemporal storage layer + version-index commit protocol (S1 crown jewel).

Three revision modes (chosen via symbology):
  - degenerate        : never-revised bars; write_bars append-with-dedup, no vintage index.
  - bitemporal_replace: every release is a COMPLETE as-known series; full write.
  - bitemporal_merge  : every release revises a window inline; read-modify-write merge.

Vintage addressing is an append-only per-symbol sidecar index ({symbol}__vintages)
read by ArcticDB INTEGER version. The index append is the atomic COMMIT POINT; a crash
between data-write and index-append leaves an orphan data version cleaned by reconcile_orphans.
"""

from __future__ import annotations

import os
from collections import namedtuple
from datetime import datetime

import pandas as pd
import polars as pl

from energex.core import symbology
from energex.core.exceptions import StorageError

VINTAGE_COLS = ("as_of", "version", "fetched_at", "vintage_reconstructed")
VintageEntry = namedtuple("VintageEntry", VINTAGE_COLS)


# ---------------------------------------------------------------- time helpers
def _naive_utc(ts) -> pd.Timestamp:
    """Any datetime-like -> tz-naive UTC pd.Timestamp (ArcticDB strips tz on store)."""
    t = pd.Timestamp(ts)
    if t.tzinfo is not None:
        t = t.tz_convert("UTC").tz_localize(None)
    return t


def _naive(date_range):
    if date_range is None:
        return None
    lo, hi = date_range
    return (
        _naive_utc(lo) if lo is not None else None,
        _naive_utc(hi) if hi is not None else None,
    )


# ---------------------------------------------------------------- canonical frame
def _canonicalize(frame, as_of, source, source_url, fetched_at, reconstructed=False):
    """tz-aware-UTC -> tz-naive-UTC DatetimeIndex named 'Datetime', sorted+unique, + provenance."""
    if "valid_time" not in frame.columns:
        raise StorageError("frame is missing required column 'valid_time'")
    df = frame.copy()
    vt = pd.to_datetime(df["valid_time"], utc=True)
    df["valid_time"] = vt.dt.tz_convert("UTC").dt.tz_localize(None)
    if "ContractMonth" in df.columns:
        # pandas has no date dtype -> store as datetime64 (re-cast to pl.Date on read).
        df["ContractMonth"] = pd.to_datetime(df["ContractMonth"])
    df.index = pd.DatetimeIndex(df["valid_time"].to_numpy(), name="Datetime")
    df = df.sort_index()
    df = df[~df.index.duplicated(keep="last")]
    df["as_of"] = _naive_utc(as_of)
    df["source"] = source
    df["source_url"] = source_url
    df["fetched_at"] = _naive_utc(fetched_at)
    df["vintage_reconstructed"] = bool(reconstructed)
    return df


# ---------------------------------------------------------------- vintage index
def _vintage_symbol(symbol: str) -> str:
    return f"{symbol}__vintages"


def _read_vintage_index(lib, symbol):
    sym = _vintage_symbol(symbol)
    if not lib.has_symbol(sym):
        return []
    df = lib.read(sym).data
    out = []
    for r in df.itertuples(index=False):
        out.append(
            VintageEntry(
                _naive_utc(r.as_of),
                int(r.version),
                _naive_utc(r.fetched_at),
                bool(r.vintage_reconstructed),
            )
        )
    return out


def _append_vintage_index(lib, symbol, *, as_of, version, fetched_at, vintage_reconstructed):
    sym = _vintage_symbol(symbol)
    row = pd.DataFrame(
        [
            {
                "as_of": _naive_utc(as_of),
                "version": int(version),
                "fetched_at": _naive_utc(fetched_at),
                "vintage_reconstructed": bool(vintage_reconstructed),
            }
        ]
    )
    if lib.has_symbol(sym):
        out = pd.concat([lib.read(sym).data, row], ignore_index=True)
    else:
        out = row
    lib.write(sym, out)  # atomic per-symbol write = the COMMIT POINT


def _version_for(idx, a):
    for e in idx:
        if e.as_of == a:
            return e.version
    raise StorageError(f"no committed vintage with as_of {a}")


def _latest_version(lib, symbol) -> int:
    return max(k.version for k in lib.list_versions(symbol))


def _empty_like(lib, symbol, idx):
    if not idx:
        return pd.DataFrame()
    v = max(idx, key=lambda e: e.version).version
    return lib.read(symbol, as_of=int(v)).data.iloc[0:0]


# ---------------------------------------------------------------- commit / read
def commit_vintage(lib, symbol, frame, *, as_of, source, source_url, fetched_at,
                   mode, reconstructed=False, force=False) -> int:
    if mode not in ("bitemporal_merge", "bitemporal_replace"):
        raise StorageError(f"commit_vintage cannot handle mode {mode!r}")
    idx = _read_vintage_index(lib, symbol)
    a = _naive_utc(as_of)
    if not force and any(e.as_of == a for e in idx):
        return _version_for(idx, a)  # IDEMPOTENT NO-OP: never re-mutate a live vintage
    cframe = _canonicalize(frame, as_of, source, source_url, fetched_at, reconstructed)
    if mode == "bitemporal_merge":
        raise NotImplementedError("bitemporal_merge arrives in Task 3")
    v = lib.write(
        symbol,
        cframe,
        metadata={"as_of": str(a), "source": source, "vintage_reconstructed": bool(reconstructed)},
        validate_index=True,
    ).version
    _append_vintage_index(
        lib, symbol, as_of=a, version=v, fetched_at=fetched_at,
        vintage_reconstructed=reconstructed,
    )
    try:  # UI-only convenience snapshot; correctness never depends on it.
        lib.snapshot(f"{symbol}@{a:%Y-%m-%dT%H%M%SZ}", versions={symbol: int(v)})
    except Exception:
        pass
    return int(v)


def read_as_of(lib, symbol, *, as_of=None, date_range=None):
    if symbology.mode_for_symbol(symbol) == "degenerate":
        df = lib.read(symbol, date_range=_naive(date_range)).data
        if as_of is not None:  # filter on KNOWLEDGE time, never valid_time
            df = df[df["fetched_at"] <= _naive_utc(as_of)]
        return df
    idx = _read_vintage_index(lib, symbol)  # re-read every correctness-critical call
    if as_of is None:
        v = _latest_version(lib, symbol)  # TASK 5 hardens this to committed-only
    else:
        a = _naive_utc(as_of)
        earlier = [e for e in idx if e.as_of <= a]
        if not earlier:
            return _empty_like(lib, symbol, idx)  # as_of < earliest => EMPTY
        v = max(earlier, key=lambda e: e.as_of).version
    return lib.read(symbol, as_of=int(v), date_range=_naive(date_range)).data


# ---------------------------------------------------------------- polars seam
def _to_polars(versioned_item) -> pl.DataFrame:
    df = versioned_item.data.reset_index()  # DatetimeIndex 'Datetime' -> column
    if "Datetime" in df.columns:
        df["Datetime"] = df["Datetime"].dt.tz_localize("UTC")  # Arctic stripped tz
    if "valid_time" in df.columns:
        df["valid_time"] = df["valid_time"].dt.tz_localize("UTC")
    pf = pl.from_pandas(df)
    if "ContractMonth" in pf.columns:
        pf = pf.with_columns(pl.col("ContractMonth").cast(pl.Date))
    return pf
```

- [ ] **Step 4: Run the gate test and observe the expected pass.**
```bash
uv run pytest -q tests/test_storage_roundtrip.py
```
Expected output: `1 passed`.

- [ ] **Step 5: Commit.**
```bash
git -C /Users/marty/repos/energex add src/energex/core/storage.py tests/test_storage_roundtrip.py && git -C /Users/marty/repos/energex commit -m "Phase 2: storage round-trip (tz + ContractMonth via _to_polars)"
```

### Task 3 — bitemporal_merge (revise-by-valid_time) [GATE: test_pointintime_two_vintage]

**Files:**
- Modify: `src/energex/core/storage.py`
- Test: `tests/test_storage_pointintime.py`

Steps:

- [ ] **Step 1: Write the failing two-vintage point-in-time test.** Create `tests/test_storage_pointintime.py`:
```python
"""GATE: a later release revises an earlier period; each as_of reads its own truth."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from energex.core import storage

D1 = datetime(2024, 1, 1, tzinfo=timezone.utc)
D2 = datetime(2024, 1, 8, tzinfo=timezone.utc)
D3 = datetime(2024, 1, 15, tzinfo=timezone.utc)
A1 = datetime(2024, 1, 16, 15, 30, tzinfo=timezone.utc)
A2 = datetime(2024, 1, 23, 15, 30, tzinfo=timezone.utc)


def _frame(times, values):
    return pd.DataFrame(
        {"instrument_id": "CME.CL.CLF26", "valid_time": list(times), "Close": list(values)}
    )


def _close_at(df, when):
    naive = pd.Timestamp(when).tz_convert("UTC").tz_localize(None)
    return float(df.loc[df.index == naive, "Close"].iloc[0])


def test_pointintime_two_vintage(arctic_lib):
    storage.commit_vintage(
        arctic_lib, "CL_CLF26", _frame([D1, D2, D3], [10.0, 11.0, 12.0]),
        as_of=A1, source="yf", source_url="u", fetched_at=A1, mode="bitemporal_merge",
    )
    # A2 revises only the [D2, D3] lookback window.
    storage.commit_vintage(
        arctic_lib, "CL_CLF26", _frame([D2, D3], [21.0, 22.0]),
        as_of=A2, source="yf", source_url="u", fetched_at=A2, mode="bitemporal_merge",
    )

    pre = storage.read_as_of(arctic_lib, "CL_CLF26", as_of=A1)
    post = storage.read_as_of(arctic_lib, "CL_CLF26", as_of=A2)

    assert _close_at(pre, D2) == 11.0 and _close_at(pre, D3) == 12.0   # pre-revision
    assert _close_at(post, D2) == 21.0 and _close_at(post, D3) == 22.0  # revised
    assert _close_at(post, D1) == 10.0  # untouched earlier row preserved


def test_idempotent_recommit_is_a_noop(arctic_lib):
    v1 = storage.commit_vintage(
        arctic_lib, "CL_CLF26", _frame([D1, D2], [10.0, 11.0]),
        as_of=A1, source="yf", source_url="u", fetched_at=A1, mode="bitemporal_merge",
    )
    v2 = storage.commit_vintage(
        arctic_lib, "CL_CLF26", _frame([D1, D2], [99.0, 99.0]),
        as_of=A1, source="yf", source_url="u", fetched_at=A1, mode="bitemporal_merge",
    )
    assert v1 == v2  # same as_of => no new version, original values intact
    assert _close_at(storage.read_as_of(arctic_lib, "CL_CLF26", as_of=A1), D1) == 10.0
```

- [ ] **Step 2: Run it and observe the expected failure.**
```bash
uv run pytest -q tests/test_storage_pointintime.py
```
Expected: `NotImplementedError: bitemporal_merge arrives in Task 3` (2 failed).

- [ ] **Step 3: Implement the merge branch + helpers.** In `src/energex/core/storage.py`, replace the merge stub:
```python
    if mode == "bitemporal_merge":
        raise NotImplementedError("bitemporal_merge arrives in Task 3")
```
with:
```python
    if mode == "bitemporal_merge":
        prior = _read_full_series_before(lib, symbol, idx, a)
        cframe = _merge_revisions(prior, cframe)
```
Then add these two functions immediately above `def read_as_of(` (the as_of-floor fix lands in Task 4; the gap fix in Task 8 — both are intentionally "buggy" here so their gate tests fail first):
```python
def _read_full_series_before(lib, symbol, idx, a):
    """Full as-known series before this release (Task 4 makes this as_of-aware)."""
    if not idx:
        return None
    e = max(idx, key=lambda x: x.as_of)
    return lib.read(symbol, as_of=int(e.version)).data


def _merge_revisions(prior, frame):
    """Revisions overwrite by valid_time window (Task 8 makes this gap-safe)."""
    if prior is None or prior.empty:
        return frame
    lo, hi = frame.index.min(), frame.index.max()
    kept = prior[(prior.index < lo) | (prior.index > hi)]
    return pd.concat([kept, frame]).sort_index()
```

- [ ] **Step 4: Run and observe the expected pass.**
```bash
uv run pytest -q tests/test_storage_pointintime.py
```
Expected output: `2 passed`.

- [ ] **Step 5: Commit.**
```bash
git -C /Users/marty/repos/energex add src/energex/core/storage.py tests/test_storage_pointintime.py && git -C /Users/marty/repos/energex commit -m "Phase 2: bitemporal_merge two-vintage point-in-time + idempotent recommit"
```

### Task 4 — reverse-order backfill must not leak future [GATE: test_pointintime_reverse_backfill]

**Files:**
- Modify: `src/energex/core/storage.py`
- Test: `tests/test_pointintime_reverse_backfill.py`

Steps:

- [ ] **Step 1: Write the failing reverse-backfill test.** The later vintage carries an extra period `D4` the earlier one lacks; reading the earlier `as_of` must NOT show it. Create `tests/test_pointintime_reverse_backfill.py`:
```python
"""GATE: writing vintages in REVERSE as_of order must not leak later knowledge backward."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from energex.core import storage

D1 = datetime(2024, 1, 1, tzinfo=timezone.utc)
D2 = datetime(2024, 1, 8, tzinfo=timezone.utc)
D3 = datetime(2024, 1, 15, tzinfo=timezone.utc)
D4 = datetime(2024, 1, 22, tzinfo=timezone.utc)  # only known at the LATER as_of
A1 = datetime(2024, 1, 16, 15, 30, tzinfo=timezone.utc)  # earlier
A2 = datetime(2024, 1, 23, 15, 30, tzinfo=timezone.utc)  # later


def _frame(times, values):
    return pd.DataFrame(
        {"instrument_id": "CME.CL.CLF26", "valid_time": list(times), "Close": list(values)}
    )


def test_pointintime_reverse_backfill(arctic_lib):
    # Commit the LATER vintage first (carries the extra D4 row).
    storage.commit_vintage(
        arctic_lib, "CL_CLF26", _frame([D2, D3, D4], [21.0, 22.0, 40.0]),
        as_of=A2, source="yf", source_url="u", fetched_at=A2, mode="bitemporal_merge",
    )
    # Then backfill the EARLIER vintage (no D4).
    storage.commit_vintage(
        arctic_lib, "CL_CLF26", _frame([D1, D2, D3], [10.0, 11.0, 12.0]),
        as_of=A1, source="yf", source_url="u", fetched_at=A1, mode="bitemporal_merge",
    )

    early = storage.read_as_of(arctic_lib, "CL_CLF26", as_of=A1)
    early_naive = {pd.Timestamp(t).tz_convert("UTC").tz_localize(None) for t in (D1, D2, D3)}
    assert set(early.index) == early_naive  # NO D4 leak from the later vintage

    # as_of strictly before the earliest committed vintage => EMPTY.
    before = datetime(2023, 12, 31, tzinfo=timezone.utc)
    assert storage.read_as_of(arctic_lib, "CL_CLF26", as_of=before).empty
```

- [ ] **Step 2: Run it and observe the expected failure (future leak).**
```bash
uv run pytest -q tests/test_pointintime_reverse_backfill.py
```
Expected: `1 failed` — the `set(early.index)` assertion fails because the buggy `_read_full_series_before` merged the later vintage's `D4` into `as_of=A1`.

- [ ] **Step 3: Fix prior-series selection to be as_of-aware.** In `src/energex/core/storage.py`, replace `_read_full_series_before` with:
```python
def _read_full_series_before(lib, symbol, idx, a):
    """Full as-known series committed STRICTLY BEFORE this as_of (no future leak)."""
    earlier = [e for e in idx if e.as_of < a]
    if not earlier:
        return None
    e = max(earlier, key=lambda x: x.as_of)
    return lib.read(symbol, as_of=int(e.version)).data
```

- [ ] **Step 4: Run both point-in-time gates and observe the expected pass.**
```bash
uv run pytest -q tests/test_pointintime_reverse_backfill.py tests/test_storage_pointintime.py
```
Expected output: `3 passed`.

- [ ] **Step 5: Commit.**
```bash
git -C /Users/marty/repos/energex add src/energex/core/storage.py tests/test_pointintime_reverse_backfill.py && git -C /Users/marty/repos/energex commit -m "Phase 2: as_of-floored prior selection (reverse-backfill no future leak)"
```

### Task 5 — read_as_of(None) returns the latest COMMITTED vintage [GATE: test_latest_is_committed]

**Files:**
- Modify: `src/energex/core/storage.py`
- Test: `tests/test_latest_is_committed.py`

Steps:

- [ ] **Step 1: Write the failing test.** A raw data write with no index append (a simulated orphan) must never be returned by `read_as_of(as_of=None)`. Create `tests/test_latest_is_committed.py`:
```python
"""GATE: an orphan data write (no index entry) is never returned by read_as_of(as_of=None)."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from energex.core import storage

D1 = datetime(2024, 1, 1, tzinfo=timezone.utc)
A1 = datetime(2024, 1, 16, 15, 30, tzinfo=timezone.utc)


def test_latest_is_committed(arctic_lib):
    storage.commit_vintage(
        arctic_lib, "CL_CLF26",
        pd.DataFrame({"instrument_id": "CME.CL.CLF26", "valid_time": [D1], "Close": [10.0]}),
        as_of=A1, source="yf", source_url="u", fetched_at=A1, mode="bitemporal_merge",
    )
    # Simulate a crash AFTER the data write but BEFORE the index append: a higher,
    # uncommitted data version exists (NOT in {symbol}__vintages).
    orphan = arctic_lib.write(
        "CL_CLF26",
        pd.DataFrame({"Close": [999.0]},
                     index=pd.DatetimeIndex([pd.Timestamp("2024-01-01")], name="Datetime")),
        validate_index=True,
    ).version
    assert orphan > 0

    latest = storage.read_as_of(arctic_lib, "CL_CLF26", as_of=None)
    assert float(latest["Close"].iloc[0]) == 10.0  # committed, never the orphan 999.0
```

- [ ] **Step 2: Run it and observe the expected failure.**
```bash
uv run pytest -q tests/test_latest_is_committed.py
```
Expected: `1 failed` — `read_as_of(None)` returned `999.0` (the orphan latest *data* version).

- [ ] **Step 3: Harden read_as_of(None) to committed-only.** In `src/energex/core/storage.py`, add this helper directly below `_latest_version`:
```python
def _latest_committed_version(idx):
    """Latest COMMITTED vintage (by as_of); None if nothing is committed yet."""
    if not idx:
        return None
    return max(idx, key=lambda e: e.as_of).version
```
Then, inside `read_as_of`, replace:
```python
    if as_of is None:
        v = _latest_version(lib, symbol)  # TASK 5 hardens this to committed-only
```
with:
```python
    if as_of is None:
        v = _latest_committed_version(idx)  # never an orphan write version
        if v is None:
            return _empty_like(lib, symbol, idx)
```

- [ ] **Step 4: Run and observe the expected pass (and the round-trip still green).**
```bash
uv run pytest -q tests/test_latest_is_committed.py tests/test_storage_roundtrip.py
```
Expected output: `2 passed`.

- [ ] **Step 5: Commit.**
```bash
git -C /Users/marty/repos/energex add src/energex/core/storage.py tests/test_latest_is_committed.py && git -C /Users/marty/repos/energex commit -m "Phase 2: read_as_of(None) returns latest COMMITTED vintage, never an orphan"
```

### Task 6 — crash-safety + orphan GC (reconcile) [GATE: test_crash_safety]

**Files:**
- Modify: `src/energex/core/storage.py`
- Test: `tests/test_crash_safety.py`

Steps:

- [ ] **Step 1: Write the failing crash-safety test.** Create `tests/test_crash_safety.py`:
```python
"""GATE: a kill between data-write and index-append leaves a GC-able orphan;
read_as_of still returns the prior committed vintage (never an older one)."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from energex.core import storage

D1 = datetime(2024, 1, 1, tzinfo=timezone.utc)
D2 = datetime(2024, 1, 8, tzinfo=timezone.utc)
E1 = datetime(2024, 1, 16, 15, 30, tzinfo=timezone.utc)
E2 = datetime(2024, 1, 23, 15, 30, tzinfo=timezone.utc)


def _frame(times, values):
    return pd.DataFrame(
        {"instrument_id": "CME.CL.CLF26", "valid_time": list(times), "Close": list(values)}
    )


def _versions(lib, symbol):
    return {k.version for k in lib.list_versions(symbol) if k.symbol == symbol}


def test_crash_safety(arctic_lib):
    storage.commit_vintage(
        arctic_lib, "CL_CLF26", _frame([D1], [10.0]),
        as_of=E1, source="yf", source_url="u", fetched_at=E1, mode="bitemporal_merge",
    )
    storage.commit_vintage(
        arctic_lib, "CL_CLF26", _frame([D1, D2], [10.0, 11.0]),
        as_of=E2, source="yf", source_url="u", fetched_at=E2, mode="bitemporal_merge",
    )

    # CRASH: data version written, index append never happened.
    orphan = arctic_lib.write(
        "CL_CLF26",
        pd.DataFrame({"Close": [999.0]},
                     index=pd.DatetimeIndex([pd.Timestamp("2024-01-01")], name="Datetime")),
        validate_index=True,
    ).version

    committed = {e.version for e in storage._read_vintage_index(arctic_lib, "CL_CLF26")}
    assert orphan in _versions(arctic_lib, "CL_CLF26") and orphan not in committed

    # read_as_of returns the prior committed vintage (E2), not the orphan, not E1.
    latest = storage.read_as_of(arctic_lib, "CL_CLF26", as_of=None)
    assert float(latest.loc[latest.index == pd.Timestamp("2024-01-08"), "Close"].iloc[0]) == 11.0

    # GC removes the orphan; committed reads are unaffected.
    removed = storage.reconcile_orphans(arctic_lib, "CL_CLF26")
    assert removed == [orphan]
    assert orphan not in _versions(arctic_lib, "CL_CLF26")
    latest2 = storage.read_as_of(arctic_lib, "CL_CLF26", as_of=None)
    assert float(latest2.loc[latest2.index == pd.Timestamp("2024-01-08"), "Close"].iloc[0]) == 11.0
```

- [ ] **Step 2: Run it and observe the expected failure.**
```bash
uv run pytest -q tests/test_crash_safety.py
```
Expected: `AttributeError: module 'energex.core.storage' has no attribute 'reconcile_orphans'` (1 failed).

- [ ] **Step 3: Implement the GC helper.** In `src/energex/core/storage.py`, add at the end of the file:
```python
# ---------------------------------------------------------------- reconcile / GC
def reconcile_orphans(lib, symbol) -> list[int]:
    """Delete data versions with no committed index entry (crash residue). Returns removed."""
    committed = {e.version for e in _read_vintage_index(lib, symbol)}
    data_versions = {k.version for k in lib.list_versions(symbol) if k.symbol == symbol}
    orphans = sorted(data_versions - committed)
    for v in orphans:
        lib.delete(symbol, versions=int(v))  # committed versions carry snapshots; orphans do not
    return orphans
```

- [ ] **Step 4: Run and observe the expected pass.**
```bash
uv run pytest -q tests/test_crash_safety.py
```
Expected output: `1 passed`.

- [ ] **Step 5: Commit.**
```bash
git -C /Users/marty/repos/energex add src/energex/core/storage.py tests/test_crash_safety.py && git -C /Users/marty/repos/energex commit -m "Phase 2: crash-safety orphan GC via reconcile_orphans"
```

### Task 7 — write_bars: degenerate append-with-dedup (sparse-safe) [GATE: test_write_bars_sparse]

**Files:**
- Modify: `src/energex/core/storage.py`
- Test: `tests/test_write_bars_sparse.py`

Steps:

- [ ] **Step 1: Write the failing sparse-bars test.** ArcticDB `append` rejects a non-monotonic index (verified), so a `t2` re-ingested between existing `t1,t3` must fall back to read-concat-write. Create `tests/test_write_bars_sparse.py`:
```python
"""GATE: degenerate write_bars is append-with-dedup; re-ingesting an interior bar
must not delete the surrounding bars (no update(date_range))."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from energex.core import storage

T1 = datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc)
T2 = datetime(2024, 1, 2, 14, 31, tzinfo=timezone.utc)
T3 = datetime(2024, 1, 2, 14, 32, tzinfo=timezone.utc)
F = datetime(2024, 1, 2, 15, 0, tzinfo=timezone.utc)


def _bars(times, values):
    return pd.DataFrame(
        {"instrument_id": "CME.CL.FRONT", "valid_time": list(times), "Close": list(values)}
    )


def _idx(df):
    return {t.to_pydatetime().replace(tzinfo=timezone.utc) for t in df.index}


def test_write_bars_sparse(arctic_lib):
    storage.write_bars(arctic_lib, "CL_FRONT", _bars([T1, T3], [75.0, 75.2]), fetched_at=F)
    # Re-ingest ONLY the interior bar t2.
    storage.write_bars(arctic_lib, "CL_FRONT", _bars([T2], [75.1]), fetched_at=F)

    out = storage.read_as_of(arctic_lib, "CL_FRONT", as_of=None)
    assert _idx(out) == {T1, T2, T3}  # t1 and t3 survived the sparse interior insert
    assert float(out.loc[out.index == pd.Timestamp("2024-01-02 14:31:00"), "Close"].iloc[0]) == 75.1


def test_write_bars_reingest_is_idempotent(arctic_lib):
    v1 = storage.write_bars(arctic_lib, "CL_FRONT", _bars([T1, T2], [75.0, 75.1]), fetched_at=F)
    v2 = storage.write_bars(arctic_lib, "CL_FRONT", _bars([T1, T2], [99.0, 99.0]), fetched_at=F)
    assert v1 == v2  # all bars already present => no new version, originals untouched
    out = storage.read_as_of(arctic_lib, "CL_FRONT", as_of=None)
    assert float(out.loc[out.index == pd.Timestamp("2024-01-02 14:30:00"), "Close"].iloc[0]) == 75.0
```

- [ ] **Step 2: Run it and observe the expected failure.**
```bash
uv run pytest -q tests/test_write_bars_sparse.py
```
Expected: `AttributeError: module 'energex.core.storage' has no attribute 'write_bars'` (2 failed).

- [ ] **Step 3: Implement write_bars + a sparse guardrail.** In `src/energex/core/storage.py`, add directly above `def read_as_of(`:
```python
def write_bars(lib, symbol, frame, *, fetched_at) -> int:
    """DEGENERATE append-with-dedup on the UTC index. Fast-path append when strictly
    after the existing tail; otherwise read-concat-write (sparse interior inserts).
    NEVER lib.update(date_range) — it would delete omitted bars."""
    if symbology.mode_for_symbol(symbol) != "degenerate":
        raise StorageError(f"write_bars refuses non-degenerate symbol {symbol!r}")
    if "as_of" in frame.columns and frame["as_of"].nunique(dropna=False) > 1:
        raise StorageError("write_bars frame carries multiple as_of values")
    cframe = _canonicalize(frame, fetched_at, "", "", fetched_at, False)
    if not lib.has_symbol(symbol):
        return int(lib.write(symbol, cframe, validate_index=True).version)
    existing = lib.read(symbol).data
    new = cframe[~cframe.index.isin(existing.index)]
    if len(new) == 0:
        return _latest_version(lib, symbol)  # idempotent no-op
    if new.index.min() > existing.index.max():
        return int(lib.append(symbol, new, validate_index=True).version)
    combined = pd.concat([existing, new])
    combined = combined[~combined.index.duplicated(keep="last")].sort_index()
    return int(lib.write(symbol, combined, validate_index=True).version)
```

- [ ] **Step 4: Run and observe the expected pass.**
```bash
uv run pytest -q tests/test_write_bars_sparse.py
```
Expected output: `2 passed`.

- [ ] **Step 5: Commit.**
```bash
git -C /Users/marty/repos/energex add src/energex/core/storage.py tests/test_write_bars_sparse.py && git -C /Users/marty/repos/energex commit -m "Phase 2: degenerate write_bars (sparse-safe append-with-dedup)"
```

### Task 8 — merge gap-safety: revise by valid_time, never delete omitted rows [GATE: test_revision_merge_gap]

**Files:**
- Modify: `src/energex/core/storage.py`
- Test: `tests/test_revision_merge_gap.py`

Steps:

- [ ] **Step 1: Write the failing gap test.** A revision frame missing an interior `valid_time` must NOT drop that prior row. Create `tests/test_revision_merge_gap.py`:
```python
"""GATE: a revision frame with an interior gap must NOT delete the omitted prior row."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from energex.core import storage

D1 = datetime(2024, 1, 1, tzinfo=timezone.utc)
D2 = datetime(2024, 1, 8, tzinfo=timezone.utc)
D3 = datetime(2024, 1, 15, tzinfo=timezone.utc)
B1 = datetime(2024, 1, 16, 15, 30, tzinfo=timezone.utc)
B2 = datetime(2024, 1, 23, 15, 30, tzinfo=timezone.utc)


def _frame(times, values):
    return pd.DataFrame(
        {"instrument_id": "CME.CL.CLF26", "valid_time": list(times), "Close": list(values)}
    )


def test_revision_merge_gap(arctic_lib):
    storage.commit_vintage(
        arctic_lib, "CL_CLF26", _frame([D1, D2, D3], [10.0, 11.0, 12.0]),
        as_of=B1, source="yf", source_url="u", fetched_at=B1, mode="bitemporal_merge",
    )
    # B2 revises D1 and D3 but OMITS D2 (a gap inside the revised span).
    storage.commit_vintage(
        arctic_lib, "CL_CLF26", _frame([D1, D3], [100.0, 300.0]),
        as_of=B2, source="yf", source_url="u", fetched_at=B2, mode="bitemporal_merge",
    )

    post = storage.read_as_of(arctic_lib, "CL_CLF26", as_of=B2)
    at = lambda d: float(post.loc[post.index == pd.Timestamp(d).tz_convert("UTC").tz_localize(None), "Close"].iloc[0])  # noqa: E731
    assert at(D1) == 100.0   # revised
    assert at(D3) == 300.0   # revised
    assert at(D2) == 11.0    # OMITTED row preserved, NOT deleted
```

- [ ] **Step 2: Run it and observe the expected failure.**
```bash
uv run pytest -q tests/test_revision_merge_gap.py
```
Expected: `1 failed` — `at(D2)` raises `IndexError`/asserts wrong because the window-based `_merge_revisions` dropped the interior `D2`.

- [ ] **Step 3: Make the merge revise by exact valid_time (gap-safe).** In `src/energex/core/storage.py`, replace `_merge_revisions` with:
```python
def _merge_revisions(prior, frame):
    """Revisions overwrite by exact valid_time; prior rows absent from the frame survive."""
    if prior is None or prior.empty:
        return frame
    kept = prior[~prior.index.isin(frame.index)]
    return pd.concat([kept, frame]).sort_index()
```

- [ ] **Step 4: Run the gap test plus the other point-in-time gates (no regressions).**
```bash
uv run pytest -q tests/test_revision_merge_gap.py tests/test_storage_pointintime.py tests/test_pointintime_reverse_backfill.py
```
Expected output: `4 passed`.

- [ ] **Step 5: Commit.**
```bash
git -C /Users/marty/repos/energex add src/energex/core/storage.py tests/test_revision_merge_gap.py && git -C /Users/marty/repos/energex commit -m "Phase 2: gap-safe merge (revise by valid_time, never delete omitted rows)"
```

### Task 9 — read_curve assembler (completes the storage scope)

**Files:**
- Modify: `src/energex/core/storage.py`
- Test: `tests/test_storage_curve.py`

Steps:

- [ ] **Step 1: Write the failing curve test.** Create `tests/test_storage_curve.py`:
```python
"""read_curve assembles per-contract vintages for a commodity at one as_of."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pandas as pd

from energex.core import storage

OBS = datetime(2024, 1, 2, tzinfo=timezone.utc)
AS_OF = datetime(2024, 1, 3, tzinfo=timezone.utc)


def _contract(instrument_id, contract_month, close):
    return pd.DataFrame(
        {
            "instrument_id": [instrument_id],
            "valid_time": [OBS],
            "ContractMonth": [contract_month],
            "Close": [close],
        }
    )


def test_read_curve(arctic_store, arctic_uri, monkeypatch):
    monkeypatch.setenv("ENERGEX_ARCTIC_URI", arctic_uri)
    lib = arctic_store.create_library("prices.futures")
    storage.commit_vintage(
        lib, "CL_CLF26", _contract("CME.CL.CLF26", date(2026, 1, 1), 80.0),
        as_of=AS_OF, source="yf", source_url="u", fetched_at=AS_OF, mode="bitemporal_merge",
    )
    storage.commit_vintage(
        lib, "CL_CLG26", _contract("CME.CL.CLG26", date(2026, 2, 1), 79.5),
        as_of=AS_OF, source="yf", source_url="u", fetched_at=AS_OF, mode="bitemporal_merge",
    )

    curve = storage.read_curve("crude", AS_OF)
    assert sorted(curve["instrument_id"].tolist()) == ["CME.CL.CLF26", "CME.CL.CLG26"]
    assert sorted(curve["Close"].tolist()) == [79.5, 80.0]
```

- [ ] **Step 2: Run it and observe the expected failure.**
```bash
uv run pytest -q tests/test_storage_curve.py
```
Expected: `AttributeError: module 'energex.core.storage' has no attribute 'read_curve'` (1 failed).

- [ ] **Step 3: Implement the curve assembler.** In `src/energex/core/storage.py`, add at the end of the file:
```python
# ---------------------------------------------------------------- curve assembler
def _arctic():
    import arcticdb as adb

    return adb.Arctic(os.environ["ENERGEX_ARCTIC_URI"])


def read_curve(commodity, as_of) -> pd.DataFrame:
    ac = _arctic()
    frames = []
    for sym in symbology.contracts_for(commodity):
        lib = ac[symbology.library_for_symbol(sym)]
        frames.append(read_as_of(lib, sym, as_of=as_of))
    return _reassemble_curve(frames)


def _reassemble_curve(frames):
    frames = [f for f in frames if f is not None and not f.empty]
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames).sort_index()
```

- [ ] **Step 4: Run and observe the expected pass.**
```bash
uv run pytest -q tests/test_storage_curve.py
```
Expected output: `1 passed`.

- [ ] **Step 5: Commit.**
```bash
git -C /Users/marty/repos/energex add src/energex/core/storage.py tests/test_storage_curve.py && git -C /Users/marty/repos/energex commit -m "Phase 2: read_curve per-commodity vintage assembler"
```

### Task 10 — green the full suite + lock the gate into CI

**Files:**
- Modify: `.github/workflows/ci.yml`

Steps:

- [ ] **Step 1: Run the seven storage gate tests + the symbology guardrail together.**
```bash
uv run pytest -q tests/test_storage_roundtrip.py tests/test_storage_pointintime.py tests/test_pointintime_reverse_backfill.py tests/test_crash_safety.py tests/test_write_bars_sparse.py tests/test_revision_merge_gap.py tests/test_latest_is_committed.py tests/test_symbology.py
```
Expected output: `12 passed` (the 7 gate tests plus the extra idempotency/guardrail cases authored alongside them).

- [ ] **Step 2: Confirm no regression in the pre-existing 122 tests.**
```bash
uv run --all-extras pytest -q
```
Expected output: ends with a single summary line, all green, e.g. `135 passed` (122 prior + the 13 new tests), `0 failed`.

- [ ] **Step 3: Add an explicit bitemporal-gate CI job.** In `.github/workflows/ci.yml`, add this job under `jobs:` (after the existing `test:` job) so the crown-jewel suite is named and cannot be silently dropped from the matrix run:
```yaml
  storage-gate:
    name: Bitemporal storage gate
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true
      - name: Bitemporal CI gate suite (offline LMDB ArcticDB)
        run: >
          uv run --extra storage --extra dev pytest -q
          tests/test_storage_roundtrip.py
          tests/test_storage_pointintime.py
          tests/test_pointintime_reverse_backfill.py
          tests/test_crash_safety.py
          tests/test_write_bars_sparse.py
          tests/test_revision_merge_gap.py
          tests/test_latest_is_committed.py
          tests/test_symbology.py
```

- [ ] **Step 4: Lint/format the new modules so the `lint` CI job stays green.**
```bash
uv run --all-extras ruff check src/energex/core tests && uv run --all-extras ruff format src/energex/core tests
```
Expected output: `All checks passed!` then a formatting summary (e.g. `N files left unchanged`); re-stage if any file was reformatted.

- [ ] **Step 5: Commit.**
```bash
git -C /Users/marty/repos/energex add .github/workflows/ci.yml && git -C /Users/marty/repos/energex commit -m "Phase 2: add bitemporal storage-gate CI job"
```

Gate: `uv run --extra storage --extra dev pytest -q tests/test_storage_roundtrip.py tests/test_storage_pointintime.py tests/test_pointintime_reverse_backfill.py tests/test_crash_safety.py tests/test_write_bars_sparse.py tests/test_revision_merge_gap.py tests/test_latest_is_committed.py tests/test_symbology.py` is all green AND the new `storage-gate` job is present in `.github/workflows/ci.yml`, with the full `uv run --all-extras pytest` suite showing zero failures.

---

## Phase 3 — Quality Gate (`core/quality.py` + `core/schemas.py`)

Implements the fail-loud pre-write quality gate (spec §5.4). Depends on Phase 1 (scaffold gave us `src/energex/core/__init__.py` and `src/energex/core/exceptions.py` with the `EnergexError` base + error stubs) and Phase 2 (`core/storage.py`). This phase makes `core.quality.validate(frame, schema, *, as_of)` real, defines the six named pandera schemas, and proves both pass and deliberate-fail paths. The post-hoc `analysis/quality.py` (`DataQualityChecker`) is touched by nothing here — a dedicated test asserts the two coexist with no collision.

Design note (release-calendar freshness): pandera `DataFrameSchema` objects are static, but the freshness wide-check needs the per-call `as_of`. We thread it through a module-level `contextvars.ContextVar` that `validate()` sets/resets around `schema.validate()`. Freshness is **business-day-aware** (via `numpy.busday_count`), so a Monday `as_of` is not falsely flagged stale for a Friday `valid_time` — satisfying "not a fixed timedelta." The NOAA `-9999.` sentinel is coerced to NULL **before** validation via a per-schema preprocessor registry keyed on `schema.name`.

---

### Task 3.1 — Add the `quality` extra and the `QualityGateError` contract

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/energex/core/exceptions.py`
- Test: `tests/test_exceptions.py` (extend)

Steps:

- [ ] **Step 1: Add the failing test for `QualityGateError`'s constructor contract.**
  Append to `tests/test_exceptions.py`:
  ```python
  import pandas as pd

  from energex.core.exceptions import EnergexError, QualityGateError


  def test_quality_gate_error_carries_schema_name_and_failures():
      failures = pd.DataFrame(
          {"column": ["Open"], "check": ["greater_than_or_equal_to(0)"],
           "failure_case": [-1.0], "index": [0]}
      )
      err = QualityGateError(schema_name="OHLCV", failures=failures)
      assert isinstance(err, EnergexError)
      assert err.schema_name == "OHLCV"
      assert err.failures is failures
      assert "OHLCV" in str(err)
      assert "1" in str(err)  # one failure case reported
  ```

- [ ] **Step 2: Run the test and show the expected failure.**
  ```bash
  uv run pytest -q tests/test_exceptions.py::test_quality_gate_error_carries_schema_name_and_failures
  ```
  Expected output (Phase 1 left only a bare stub or no kwargs):
  ```
  E   TypeError: QualityGateError.__init__() got an unexpected keyword argument 'schema_name'
  1 failed
  ```

- [ ] **Step 3: Give `QualityGateError` its real constructor in `src/energex/core/exceptions.py`.**
  Replace the Phase-1 `QualityGateError` stub with the full class (keep the other added stubs `StorageError`, `SymbologyError`, `PartitionError`, `VintageImmutableError` exactly as they are):
  ```python
  class QualityGateError(EnergexError):
      """Raised by the pre-write quality gate when a pandera schema fails.

      Carries the failing schema's name and the pandera ``failure_cases``
      DataFrame so the asset/check layer can surface every violation at once.
      """

      def __init__(self, *, schema_name: str, failures) -> None:
          self.schema_name = schema_name
          self.failures = failures
          n = 0 if failures is None else len(failures)
          super().__init__(
              f"Quality gate '{schema_name}' failed with {n} failure case(s)"
          )
  ```

- [ ] **Step 4: Add the `quality` extra to `pyproject.toml`.**
  In `[project.optional-dependencies]`, add a new extra and include it in `all`:
  ```toml
  quality = [
      "pandera>=0.20.0",
      "numpy>=1.24.0"
  ]
  ```
  Then extend the `all` extra to include it:
  ```toml
  all = [
      "energex[dev]",
      "energex[llm]",
      "energex[sentiment]",
      "energex[service]",
      "energex[quality]"
  ]
  ```

- [ ] **Step 5: Sync the environment and confirm the import line resolves.**
  ```bash
  uv sync --extra quality --extra dev
  uv run python -c "import pandera.pandas as pa; print(pa.DataFrameSchema, pa.errors.SchemaErrors)"
  ```
  Expected output:
  ```
  <class 'pandera.api.pandas.container.DataFrameSchema'> <class 'pandera.errors.SchemaErrors'>
  ```

- [ ] **Step 6: Run the exception test green.**
  ```bash
  uv run pytest -q tests/test_exceptions.py::test_quality_gate_error_carries_schema_name_and_failures
  ```
  Expected output:
  ```
  1 passed
  ```

- [ ] **Step 7: Commit.**
  ```bash
  git add pyproject.toml uv.lock src/energex/core/exceptions.py tests/test_exceptions.py
  git commit -m "Add quality extra and QualityGateError constructor contract"
  ```

---

### Task 3.2 — Define the six named pandera schemas (`core/schemas.py`)

**Files:**
- Create: `src/energex/core/schemas.py`
- Test: `tests/test_pandera_schemas.py` (created here; populated with passing+failing cases in Task 3.4)

Steps:

- [ ] **Step 1: Add a thin import-smoke test that the six schemas exist and are named.**
  Create `tests/test_pandera_schemas.py`:
  ```python
  import pandera.pandas as pa

  from energex.core import schemas


  def test_all_six_schemas_present_and_named():
      expected = {
          "OHLCV": schemas.OHLCV,
          "DATED_CONTRACTS": schemas.DATED_CONTRACTS,
          "EIA_GAS_STORAGE": schemas.EIA_GAS_STORAGE,
          "EIA_PETROLEUM": schemas.EIA_PETROLEUM,
          "ERCOT_DALMP": schemas.ERCOT_DALMP,
          "NOAA_HDDCDD": schemas.NOAA_HDDCDD,
      }
      for name, schema in expected.items():
          assert isinstance(schema, pa.DataFrameSchema)
          assert schema.name == name
  ```

- [ ] **Step 2: Run it and show the expected failure.**
  ```bash
  uv run pytest -q tests/test_pandera_schemas.py::test_all_six_schemas_present_and_named
  ```
  Expected output:
  ```
  E   ModuleNotFoundError: No module named 'energex.core.schemas'
  1 error
  ```

- [ ] **Step 3: Create `src/energex/core/schemas.py` with the full schema set.**
  ```python
  """Pandera quality-gate schemas for the Energex bitemporal data platform.

  These are the PRE-WRITE gate schemas, distinct from analysis/quality.py's
  post-hoc DataQualityChecker. ``core.quality.validate`` runs these and raises
  ``QualityGateError`` on any failure. Each schema enforces column presence and
  dtype, non-null (instrument_id, valid_time), value sanity bands, a row-count
  floor, and two DataFrame-level wide checks: (instrument_id, valid_time)
  uniqueness and a release-calendar-aware freshness bound on max(valid_time).
  """
  from __future__ import annotations

  import contextvars
  from datetime import datetime

  import numpy as np
  import pandas as pd
  from pandera.pandas import Check, Column, DataFrameSchema

  # ``as_of`` is supplied per ``validate`` call; freshness wide-checks read it.
  AS_OF: contextvars.ContextVar[datetime] = contextvars.ContextVar("energex_quality_as_of")

  # NOAA nClimDiv fixed-width "missing" sentinel; coerced to NULL before checks.
  NOAA_SENTINEL = -9999.0

  # Common column dtypes.
  _UTC = "datetime64[ns, UTC]"


  def _business_days_between(start, end) -> int:
      """Count business days (Mon-Fri) from ``start`` up to ``end``.

      Release-calendar-aware: weekends do not count toward staleness, so a
      Monday as_of is not falsely flagged stale for a Friday valid_time. Future
      valid_time (start > end) is treated as zero lag (not stale).
      """
      if pd.isna(start) or pd.isna(end):
          return 0
      s = pd.Timestamp(start).tz_convert("UTC").tz_localize(None).normalize()
      e = pd.Timestamp(end).tz_convert("UTC").tz_localize(None).normalize()
      if e <= s:
          return 0
      return int(np.busday_count(s.date(), e.date()))


  def _freshness_check(max_business_days: int) -> Check:
      """Wide check: max(valid_time) within ``max_business_days`` of as_of."""

      def _check(df: pd.DataFrame) -> bool:
          if df.empty or "valid_time" not in df.columns:
              return False
          as_of = AS_OF.get()
          latest = df["valid_time"].max()
          return _business_days_between(latest, pd.Timestamp(as_of)) <= max_business_days

      return Check(
          _check,
          error=f"max(valid_time) staler than {max_business_days} business days from as_of",
      )


  def _unique_keys_check() -> Check:
      """Wide check: (instrument_id, valid_time) must be unique."""

      def _check(df: pd.DataFrame) -> bool:
          if {"instrument_id", "valid_time"} - set(df.columns):
              return False
          return not df.duplicated(subset=["instrument_id", "valid_time"]).any()

      return Check(_check, error="(instrument_id, valid_time) is not unique")


  def _row_floor_check(min_rows: int = 1) -> Check:
      """Wide check: empty (or below-floor) frames fail."""

      def _check(df: pd.DataFrame) -> bool:
          return len(df) >= min_rows

      return Check(_check, error=f"row-count below floor ({min_rows})")


  def _id_col() -> Column:
      return Column(str, nullable=False)


  def _valid_time_col() -> Column:
      return Column(_UTC, nullable=False, coerce=False)


  def _ohlcv_value_cols() -> dict:
      return {
          "Open": Column(float, Check.ge(0), nullable=False, coerce=True),
          "High": Column(float, Check.ge(0), nullable=False, coerce=True),
          "Low": Column(float, Check.ge(0), nullable=False, coerce=True),
          "Close": Column(float, Check.ge(0), nullable=False, coerce=True),
          "Volume": Column("int64", Check.ge(0), nullable=False, coerce=True),
      }


  OHLCV = DataFrameSchema(
      name="OHLCV",
      columns={"instrument_id": _id_col(), "valid_time": _valid_time_col(), **_ohlcv_value_cols()},
      checks=[_unique_keys_check(), _row_floor_check(), _freshness_check(2)],
      strict=False,
      coerce=True,
  )

  DATED_CONTRACTS = DataFrameSchema(
      name="DATED_CONTRACTS",
      columns={
          "instrument_id": _id_col(),
          "valid_time": _valid_time_col(),
          "ContractMonth": Column("datetime64[ns]", nullable=False, coerce=True),
          **_ohlcv_value_cols(),
      },
      checks=[_unique_keys_check(), _row_floor_check(), _freshness_check(5)],
      strict=False,
      coerce=True,
  )

  EIA_GAS_STORAGE = DataFrameSchema(
      name="EIA_GAS_STORAGE",
      columns={
          "instrument_id": _id_col(),
          "valid_time": _valid_time_col(),
          "value": Column(float, Check.ge(0), nullable=False, coerce=True),
      },
      checks=[_unique_keys_check(), _row_floor_check(), _freshness_check(6)],
      strict=False,
      coerce=True,
  )

  EIA_PETROLEUM = DataFrameSchema(
      name="EIA_PETROLEUM",
      columns={
          "instrument_id": _id_col(),
          "valid_time": _valid_time_col(),
          "value": Column(float, Check.ge(0), nullable=False, coerce=True),
      },
      checks=[_unique_keys_check(), _row_floor_check(), _freshness_check(6)],
      strict=False,
      coerce=True,
  )

  ERCOT_DALMP = DataFrameSchema(
      name="ERCOT_DALMP",
      columns={
          "instrument_id": _id_col(),
          "valid_time": _valid_time_col(),
          # Sane day-ahead LMP band ($/MWh): negative pricing happens; cap absurd values.
          "lmp": Column(float, Check.in_range(-250.0, 5000.0), nullable=False, coerce=True),
      },
      checks=[_unique_keys_check(), _row_floor_check(), _freshness_check(3)],
      strict=False,
      coerce=True,
  )


  def coerce_noaa_sentinel(frame: pd.DataFrame) -> pd.DataFrame:
      """Replace the -9999. fixed-width sentinel with NULL BEFORE range checks."""
      out = frame.copy()
      for col in ("hdd", "cdd"):
          if col in out.columns:
              out[col] = out[col].replace(NOAA_SENTINEL, np.nan)
      return out


  NOAA_HDDCDD = DataFrameSchema(
      name="NOAA_HDDCDD",
      columns={
          "instrument_id": _id_col(),
          "valid_time": _valid_time_col(),
          "hdd": Column(float, Check.in_range(0.0, 9999.0), nullable=True, coerce=True),
          "cdd": Column(float, Check.in_range(0.0, 9999.0), nullable=True, coerce=True),
      },
      checks=[_unique_keys_check(), _row_floor_check(), _freshness_check(45)],
      strict=False,
      coerce=True,
  )

  # Per-schema pre-validation transforms applied by core.quality.validate, keyed
  # on schema.name (e.g. NOAA sentinel -> NULL before the 0-9999 range check).
  PREPROCESSORS = {"NOAA_HDDCDD": coerce_noaa_sentinel}
  ```

- [ ] **Step 4: Run the smoke test green.**
  ```bash
  uv run pytest -q tests/test_pandera_schemas.py::test_all_six_schemas_present_and_named
  ```
  Expected output:
  ```
  1 passed
  ```

- [ ] **Step 5: Commit.**
  ```bash
  git add src/energex/core/schemas.py tests/test_pandera_schemas.py
  git commit -m "Add six named pandera gate schemas with wide checks"
  ```

---

### Task 3.3 — Implement `core/quality.validate`

**Files:**
- Create: `src/energex/core/quality.py`
- Test: `tests/test_pandera_schemas.py` (extend)

Steps:

- [ ] **Step 1: Add a failing test that `validate` returns a coerced frame and raises on failure.**
  Append to `tests/test_pandera_schemas.py`:
  ```python
  from datetime import datetime, timezone

  import pandas as pd
  import pytest

  from energex.core import quality
  from energex.core.exceptions import QualityGateError


  def _gas_frame(values, valid_times):
      return pd.DataFrame(
          {
              "instrument_id": ["EIA.NG.STORAGE.LOWER48"] * len(values),
              "valid_time": pd.to_datetime(valid_times, utc=True),
              "value": values,
          }
      )


  def test_validate_returns_coerced_frame_for_good_gas_storage():
      as_of = datetime(2026, 6, 11, 15, 30, tzinfo=timezone.utc)
      frame = _gas_frame([2100, 2150], ["2026-06-05", "2026-06-05"])
      # Make keys unique and value-coercible from int.
      frame.loc[1, "valid_time"] = pd.Timestamp("2026-05-29", tz="UTC")
      out = quality.validate(frame, schemas.EIA_GAS_STORAGE, as_of=as_of)
      assert out["value"].dtype == "float64"
      assert len(out) == 2


  def test_validate_raises_quality_gate_error_with_failures():
      as_of = datetime(2026, 6, 11, 15, 30, tzinfo=timezone.utc)
      frame = _gas_frame([-5.0], ["2026-06-05"])  # negative storage is impossible
      with pytest.raises(QualityGateError) as ei:
          quality.validate(frame, schemas.EIA_GAS_STORAGE, as_of=as_of)
      assert ei.value.schema_name == "EIA_GAS_STORAGE"
      assert (ei.value.failures["column"] == "value").any()
  ```

- [ ] **Step 2: Run and show the expected failure.**
  ```bash
  uv run pytest -q tests/test_pandera_schemas.py -k "validate_returns or validate_raises"
  ```
  Expected output:
  ```
  E   ModuleNotFoundError: No module named 'energex.core.quality'
  2 errors
  ```

- [ ] **Step 3: Create `src/energex/core/quality.py`.**
  ```python
  """Pre-write quality gate: run a pandera schema, fail loud on any violation.

  This is the GATE path. The post-hoc audit path (analysis/quality.py's
  DataQualityChecker) is unrelated and unchanged — no rename, no import shim.
  """
  from __future__ import annotations

  from datetime import datetime

  import pandas as pd
  import pandera.pandas as pa

  from energex.core import schemas
  from energex.core.exceptions import QualityGateError


  def validate(
      frame: pd.DataFrame, schema: pa.DataFrameSchema, *, as_of: datetime
  ) -> pd.DataFrame:
      """Validate ``frame`` against ``schema`` and return the coerced frame.

      ``as_of`` (the knowledge timestamp) is threaded to the freshness wide-check
      via a ContextVar. Schema-specific preprocessors (e.g. the NOAA -9999.
      sentinel -> NULL) run BEFORE validation. ``lazy=True`` collects every
      violation; any failure raises ``QualityGateError`` carrying failure_cases.
      """
      pre = schemas.PREPROCESSORS.get(schema.name)
      if pre is not None:
          frame = pre(frame)
      token = schemas.AS_OF.set(as_of)
      try:
          return schema.validate(frame, lazy=True)
      except pa.errors.SchemaErrors as exc:
          raise QualityGateError(
              schema_name=schema.name, failures=exc.failure_cases
          ) from exc
      finally:
          schemas.AS_OF.reset(token)
  ```

- [ ] **Step 4: Run both `validate` tests green.**
  ```bash
  uv run pytest -q tests/test_pandera_schemas.py -k "validate_returns or validate_raises"
  ```
  Expected output:
  ```
  2 passed
  ```

- [ ] **Step 5: Commit.**
  ```bash
  git add src/energex/core/quality.py tests/test_pandera_schemas.py
  git commit -m "Implement core.quality.validate gate over pandera schemas"
  ```

---

### Task 3.4 — Per-schema pass + deliberate-fail tests (all six series)

**Files:**
- Test: `tests/test_pandera_schemas.py` (extend with one passing + one failing test per remaining schema)

Steps:

- [ ] **Step 1: Add shared fixtures plus OHLCV pass/fail tests.**
  Append to `tests/test_pandera_schemas.py`:
  ```python
  AS_OF = datetime(2026, 6, 11, 15, 30, tzinfo=timezone.utc)


  def _ohlcv(rows, valid_times):
      return pd.DataFrame(
          {
              "instrument_id": ["CME.CL.FRONT"] * rows,
              "valid_time": pd.to_datetime(valid_times, utc=True),
              "Open": [70.0] * rows,
              "High": [71.0] * rows,
              "Low": [69.0] * rows,
              "Close": [70.5] * rows,
              "Volume": [1000] * rows,
          }
      )


  def test_ohlcv_pass_returns_coerced_frame():
      frame = _ohlcv(2, ["2026-06-11T14:00:00Z", "2026-06-11T14:01:00Z"])
      frame["Volume"] = frame["Volume"].astype("float64")  # coercion target int64
      out = quality.validate(frame, schemas.OHLCV, as_of=AS_OF)
      assert out["Volume"].dtype == "int64"
      assert len(out) == 2


  def test_ohlcv_fail_negative_price_blocked():
      frame = _ohlcv(1, ["2026-06-11T14:00:00Z"])
      frame.loc[0, "Low"] = -1.0
      with pytest.raises(QualityGateError) as ei:
          quality.validate(frame, schemas.OHLCV, as_of=AS_OF)
      assert (ei.value.failures["column"] == "Low").any()
  ```

- [ ] **Step 2: Add DATED_CONTRACTS pass/fail (ContractMonth dtype + uniqueness).**
  Append:
  ```python
  def _dated(rows):
      return pd.DataFrame(
          {
              "instrument_id": ["CME.CL.CLF26"] * rows,
              "valid_time": pd.to_datetime(
                  ["2026-06-11T00:00:00Z"] * rows, utc=True
              ),
              "ContractMonth": ["2026-01-01"] * rows,
              "Open": [70.0] * rows,
              "High": [71.0] * rows,
              "Low": [69.0] * rows,
              "Close": [70.5] * rows,
              "Volume": [10] * rows,
          }
      )


  def test_dated_contracts_pass_coerces_contract_month():
      frame = _dated(1)
      out = quality.validate(frame, schemas.DATED_CONTRACTS, as_of=AS_OF)
      assert out["ContractMonth"].dtype == "datetime64[ns]"


  def test_dated_contracts_fail_duplicate_keys_blocked():
      frame = _dated(2)  # identical (instrument_id, valid_time) rows
      with pytest.raises(QualityGateError) as ei:
          quality.validate(frame, schemas.DATED_CONTRACTS, as_of=AS_OF)
      checks = ei.value.failures["check"].astype(str)
      assert checks.str.contains("not unique").any()
  ```

- [ ] **Step 3: Add EIA_PETROLEUM pass/fail (value band + empty-frame floor).**
  Append:
  ```python
  def test_eia_petroleum_pass():
      frame = pd.DataFrame(
          {
              "instrument_id": ["EIA.PET.CRUDE.STOCKS"],
              "valid_time": pd.to_datetime(["2026-06-05"], utc=True),
              "value": [430_000.0],
          }
      )
      out = quality.validate(frame, schemas.EIA_PETROLEUM, as_of=AS_OF)
      assert len(out) == 1


  def test_eia_petroleum_fail_empty_frame_blocked():
      frame = pd.DataFrame(
          {
              "instrument_id": pd.Series([], dtype=str),
              "valid_time": pd.Series([], dtype="datetime64[ns, UTC]"),
              "value": pd.Series([], dtype=float),
          }
      )
      with pytest.raises(QualityGateError) as ei:
          quality.validate(frame, schemas.EIA_PETROLEUM, as_of=AS_OF)
      checks = ei.value.failures["check"].astype(str)
      assert checks.str.contains("row-count below floor").any()
  ```

- [ ] **Step 4: Add ERCOT_DALMP pass/fail (LMP band).**
  Append:
  ```python
  def test_ercot_dalmp_pass_allows_negative_pricing():
      frame = pd.DataFrame(
          {
              "instrument_id": ["ERCOT.DALMP.HB_HOUSTON", "ERCOT.DALMP.HB_HOUSTON"],
              "valid_time": pd.to_datetime(
                  ["2026-06-10T00:00:00Z", "2026-06-10T01:00:00Z"], utc=True
              ),
              "lmp": [-15.0, 42.5],  # negative LMP is real and must pass
          }
      )
      out = quality.validate(frame, schemas.ERCOT_DALMP, as_of=AS_OF)
      assert len(out) == 2


  def test_ercot_dalmp_fail_absurd_lmp_blocked():
      frame = pd.DataFrame(
          {
              "instrument_id": ["ERCOT.DALMP.HB_HOUSTON"],
              "valid_time": pd.to_datetime(["2026-06-10T00:00:00Z"], utc=True),
              "lmp": [999_999.0],  # outside the sane band
          }
      )
      with pytest.raises(QualityGateError) as ei:
          quality.validate(frame, schemas.ERCOT_DALMP, as_of=AS_OF)
      assert (ei.value.failures["column"] == "lmp").any()
  ```

- [ ] **Step 5: Add NOAA_HDDCDD pass (sentinel→NULL) + fail (out-of-range) + freshness fail.**
  Append:
  ```python
  def test_noaa_hddcdd_pass_coerces_sentinel_to_null():
      frame = pd.DataFrame(
          {
              "instrument_id": ["NOAA.HDD.TX", "NOAA.HDD.TX"],
              "valid_time": pd.to_datetime(
                  ["2026-05-01T00:00:00Z", "2026-04-01T00:00:00Z"], utc=True
              ),
              "hdd": [120.0, -9999.0],  # sentinel -> NULL before the 0-9999 check
              "cdd": [80.0, 60.0],
          }
      )
      as_of = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)
      out = quality.validate(frame, schemas.NOAA_HDDCDD, as_of=as_of)
      assert out["hdd"].isna().sum() == 1  # sentinel became NULL, did not fail range


  def test_noaa_hddcdd_fail_out_of_range_blocked():
      frame = pd.DataFrame(
          {
              "instrument_id": ["NOAA.HDD.TX"],
              "valid_time": pd.to_datetime(["2026-05-01T00:00:00Z"], utc=True),
              "hdd": [12000.0],  # > 9999 and not the sentinel
              "cdd": [80.0],
          }
      )
      as_of = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)
      with pytest.raises(QualityGateError) as ei:
          quality.validate(frame, schemas.NOAA_HDDCDD, as_of=as_of)
      assert (ei.value.failures["column"] == "hdd").any()


  def test_freshness_fail_stale_valid_time_blocked():
      # Gas storage whose newest valid_time is months before as_of => stale.
      frame = pd.DataFrame(
          {
              "instrument_id": ["EIA.NG.STORAGE.LOWER48"],
              "valid_time": pd.to_datetime(["2026-01-02"], utc=True),
              "value": [3000.0],
          }
      )
      with pytest.raises(QualityGateError) as ei:
          quality.validate(frame, schemas.EIA_GAS_STORAGE, as_of=AS_OF)
      checks = ei.value.failures["check"].astype(str)
      assert checks.str.contains("staler than").any()
  ```

- [ ] **Step 6: Run the full schema test module green.**
  ```bash
  uv run pytest -q tests/test_pandera_schemas.py
  ```
  Expected output:
  ```
  15 passed
  ```

- [ ] **Step 7: Commit.**
  ```bash
  git add tests/test_pandera_schemas.py
  git commit -m "Test all six gate schemas: pass frames coerce, bad frames blocked"
  ```

---

### Task 3.5 — Confirm no collision with `analysis/quality.py`

**Files:**
- Test: `tests/test_quality_collision.py`

Steps:

- [ ] **Step 1: Add the dual-import collision test.**
  Create `tests/test_quality_collision.py`:
  ```python
  """The pre-write GATE (core.quality) and post-hoc AUDIT (analysis.quality)
  are distinct modules with no name collision and no shim between them."""
  import energex.analysis.quality as audit
  import energex.core.quality as gate


  def test_gate_and_audit_are_distinct_modules():
      assert gate.__name__ == "energex.core.quality"
      assert audit.__name__ == "energex.analysis.quality"
      assert gate.__file__ != audit.__file__


  def test_gate_exposes_validate_not_dataqualitychecker():
      assert hasattr(gate, "validate")
      assert not hasattr(gate, "DataQualityChecker")


  def test_audit_exposes_dataqualitychecker_not_validate():
      assert hasattr(audit, "DataQualityChecker")
      assert not hasattr(audit, "validate")
  ```

- [ ] **Step 2: Run it green.**
  ```bash
  uv run pytest -q tests/test_quality_collision.py
  ```
  Expected output:
  ```
  3 passed
  ```

- [ ] **Step 3: Run the existing audit suite to prove it is untouched.**
  ```bash
  uv run pytest -q tests/test_quality.py
  ```
  Expected output (the pre-existing `DataQualityChecker` tests still pass):
  ```
  passed
  ```

- [ ] **Step 4: Commit.**
  ```bash
  git add tests/test_quality_collision.py
  git commit -m "Assert core gate and analysis audit quality modules do not collide"
  ```

---

### Task 3.6 — Wire the schema tests into CI

**Files:**
- Modify: `.github/workflows/ci.yml`

Steps:

- [ ] **Step 1: Read the CI workflow to find the test job and its install step.**
  ```bash
  uv run python - <<'PY'
  import pathlib, re
  text = pathlib.Path(".github/workflows/ci.yml").read_text()
  for i, line in enumerate(text.splitlines(), 1):
      if re.search(r"uv sync|pytest|extra", line):
          print(i, line)
  PY
  ```
  Gate: record the exact `uv sync ...` and `pytest` lines so the next edit matches them verbatim.

- [ ] **Step 2: Ensure the `quality` extra is installed in the CI test job.**
  In `.github/workflows/ci.yml`, update the dependency-install step in the unit-test job so the `quality` extra is present (match the existing form; if the job runs `uv sync --extra dev`, change it to include `--extra quality`):
  ```yaml
      - name: Install dependencies
        run: uv sync --extra dev --extra quality
  ```

- [ ] **Step 3: Confirm the gate tests are collected by the CI test command locally.**
  ```bash
  uv run pytest -q tests/test_pandera_schemas.py tests/test_quality_collision.py tests/test_exceptions.py
  ```
  Expected output:
  ```
  passed
  ```

- [ ] **Step 4: Run the full suite to confirm no regressions from this phase.**
  ```bash
  uv run pytest -q
  ```
  Expected: the prior 122 tests plus the new gate tests all pass (no failures, no errors).

- [ ] **Step 5: Commit.**
  ```bash
  git add .github/workflows/ci.yml
  git commit -m "Install quality extra in CI so pandera gate tests run"
  ```

---

**Gate:** `uv run pytest -q tests/test_pandera_schemas.py tests/test_quality_collision.py tests/test_exceptions.py` is fully green — every one of the six named schemas (`OHLCV`, `DATED_CONTRACTS`, `EIA_GAS_STORAGE`, `EIA_PETROLEUM`, `ERCOT_DALMP`, `NOAA_HDDCDD`) accepts a good frame (returning the coerced frame) and blocks a deliberately malformed frame with `QualityGateError` exposing the violation in `.failures`; `core.quality` and `analysis.quality` coexist with no collision; and `uv run pytest -q` shows no regressions, with the `quality` extra installed in CI so these tests run on every push.

---

## Phases 4–9 + Phase F — authored next (after Phase 0)

Sequenced in the spec (§5.10/§6); each gets its own detailed plan once Phase 0 freezes the EIA series IDs, confirms the MinIO URI grammar, and locks the vintage-addressing decision:

- **Phase 4–6:** EIA gas-storage connector → first Dagster asset + asset-check + `ArcticDBResource` → Thu-10:30-ET schedule + backfill (reconstructed baseline) + reconcile/GC. *Chrome check: materialized asset + passing check in the Dagster UI.*
- **Phase 7:** EIA petroleum, then ERCOT (OAuth2 + throttle + geo-probe, floor 2023-12-11), then NOAA (monthly nClimDiv).
- **Phase 8:** futures → ArcticDB migration (read-only baseline load; intraday `write_bars`; dated `bitemporal_merge`); cut the DuckDB write path; rewrite `/healthz` first.
- **Phase 9:** Neo4j entity-upsert path (non-blocking); restore-drill automation green = S1 exit gate.
- **Phase F:** cleanup & polish — prune superseded docs (surface a deletion list first), lint/format/type clean, full suite green, no scratch/dead files, zero Claude authorship.
