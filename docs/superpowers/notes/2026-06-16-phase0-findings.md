# Energex S1 — Phase 0 Findings (2026-06-16)

Source of truth: docs/superpowers/specs/2026-06-16-energex-unified-platform-design.md (§5.3 storage contract, §11 verified APIs).
Each section below is a gating experiment. A section is DONE only when every UNRESOLVED token is replaced
with a recorded literal result. Do not start Phase 1 until all (non-deferred) gates pass.

Scope of THIS pass: the two **storage de-risking** spikes (sections 2 and 3). The EIA series freeze
(section 1) is **DEFERRED** pending `EIA_API_KEY` — see section 1.

---

## 1. EIA v2 series freeze (gas storage + petroleum status)

**STATUS: DEFERRED — pending EIA_API_KEY.**

The EIA v2 series-ID / facet freeze (plan Task 0.2) was NOT run this pass because no `EIA_API_KEY`
is available in the environment yet (`test -n "$EIA_API_KEY"` → MISSING). Nothing about the storage
gate depends on it, so it is cleanly separable.

### What still needs doing once the key lands (plan Task 0.2, Steps 1-10)
1. Export the key: `set -a; source /Users/marty/repos/energex/.env; set +a` and confirm
   `test -n "$EIA_API_KEY"`.
2. **Natural gas — weekly underground storage, Lower 48** (route `natural-gas/stor/wkly`):
   - Pull route metadata → record `FREQUENCIES`, `FACETS`, `DATA_COLS`.
   - Enumerate facets `duoarea`, `series`, `process` → record the Lower-48 selector
     (facet field + id; expected `duoarea=NUS`, `process=SAS`).
   - Sanity data pull (2 rows) → confirm `total > 0` and numeric `value`.
3. **Petroleum — weekly status / crude stocks** (route `petroleum/stoc/wstk`):
   - Pull route metadata → record `FREQUENCIES`, `FACETS`, `DATA_COLS`.
   - Enumerate facets `product`, `process`, `duoarea` → record the crude-stocks selectors
     (expected product=`EPC0` "Crude Oil", process=`SAE` "Ending Stocks Excluding SPR", duoarea=`NUS`).
   - Sanity data pull (2 rows) → confirm `total > 0` and numeric `value`.
4. Produce the **httpx**-rendered request URLs (the grammar connectors will use) for both pulls and
   copy them verbatim here.
5. Lock the mapping for `symbology.py`:
   ```
   EIA.NG.STORAGE.LOWER48 -> route=natural-gas/stor/wkly, frequency=weekly, facets={duoarea:<id>, process:<id>}
   EIA.PET.CRUDE.STOCKS   -> route=petroleum/stoc/wstk,  frequency=weekly, facets={product:<id>, process:<id>, duoarea:<id>}
   ```
6. Commit: `git commit -m "Freeze EIA v2 gas-storage and petroleum-status routes/facets in Phase 0 findings"`.

Gate (deferred): section 1 has zero UNRESOLVED tokens; both data curls return `total > 0` with numeric values.

---

## 2. ArcticDB-on-MinIO connectivity smoke — GREEN

- **docker compose up command + result:**
  `docker compose --profile dev up -d minio minio-init`
  → `energex-minio` reaches `Up (healthy)`; `energex-minio-init` exits `0`
  (logs: `Bucket created successfully 'local/arctic'`, `Created policy 'arctic-rw'`,
  service account `energex-arctic` created).

- **spike script path:** `scripts/phase0_minio_smoke.py`

- **spike stdout (write version + readback rows):**
  ```
  URI: s3://localhost:arctic?access=minioadmin&secret=minioadmin&port=9000&use_virtual_addressing=false
  write version: 0
  readback rows: 2
                      instrument_id  value
  valid_time
  2026-06-16 00:00:00         SMOKE    1.0
  2026-06-16 01:00:00         SMOKE    2.0
  SMOKE OK
  ```
  (A benign `W arcticdb | Failed to find segment for key 'C:smoke' : No response body.` precedes the
  output — it is the config-segment existence probe before the library is first created. Not an error.)

- **EXACT working ArcticDB URI grammar (ArcticDB 6.18.1, verbatim):**
  ```
  s3://localhost:arctic?access=minioadmin&secret=minioadmin&port=9000&use_virtual_addressing=false
  ```
  Grammar = `s3://<host>:<bucket>?access=<key>&secret=<secret>&port=<port>&use_virtual_addressing=false`.
  Notes for `ArcticDBResource`:
  - The token between `//` and `:` is the **host** (`localhost`); the token after `:` is the **bucket**
    (`arctic`). The port goes in the `port=` query param, NOT in the `host:port` position.
  - `use_virtual_addressing=false` (path-style addressing) is REQUIRED for MinIO; virtual-host style
    `<bucket>.<host>` does not resolve against a local MinIO.
  - No `https`/`region` params needed for plain-HTTP local MinIO. Secrets live in the URI here only
    because this is a throwaway spike; in `ArcticDBResource` they come from EnvVar fields (spec §5.3).
  - Root creds `minioadmin/minioadmin` were used per the spike brief; the scoped service account
    `energex-arctic`/`energex-arctic-secret` (created by `minio-init`) is the prod-intended key.

- **MinIO bucket population confirmed via `mc ls` (one-off mc container on `energex_default` network):**
  ```
  === buckets ===
  [..] 0B arctic/
  === arctic recursive ===
  264B   _arctic_cfg/cref/*sUt*smoke
  169B   smoke<libid>/sl/*sSt*__add__*0*...*smoke_symbol*_v2_
  312B   smoke<libid>/tdata/*sTt*smoke_symbol*0*...           <- the row data
  1.1KiB smoke<libid>/tindex/*sTt*smoke_symbol*0*...
  603B   smoke<libid>/ver/*sTt*smoke_symbol*0*...             <- version key
  643B   smoke<libid>/vref/*sUt*smoke_symbol                  <- version ref
  === object count ===
  6
  ```
  The `arctic` bucket holds the 6 ArcticDB objects written by the smoke (config ref, symbol-list,
  tdata, tindex, ver, vref). Visual MinIO-console confirmation (screenshot) is handled by the
  orchestrator, not this pass.

- **Two ArcticDB 6.18.1 gotchas discovered (both encoded in the spike scripts; carry into Phase 1):**
  1. **AWS-SDK symbol collision (macOS).** `import arcticdb` MUST precede `import pandas`/`pyarrow`.
     Both `libarrow.dylib` and `arcticdb_ext.*.so` vendor the AWS C SDK; if pyarrow's copy loads
     first, the dynamic linker binds AWS symbols to an uninitialized allocator and the S3 client
     constructor aborts the process:
     `Fatal error condition occurred in .../aws-c-common/.../allocator.c:202: allocator != ((void*)0)`.
     Importing arcticdb first makes its (initialized) AWS symbols win and the crash disappears.
     → `core/storage.py` must import arcticdb before any pandas/pyarrow import.
  2. **No `get_or_create_library` in 6.18.1.** The plan's `Arctic(uri).get_or_create_library(...)`
     does not exist. Use `Arctic(uri).get_library(name, create_if_missing=True)`
     (or `create_library` / `has_library`). The available `Arctic` methods are:
     `create_library`, `delete_library`, `get_library`, `has_library`, `list_libraries`,
     `modify_library_option`.

- **Gate status: GREEN** (smoke exits `SMOKE OK`; `arctic` bucket populated; URI grammar recorded).

---

## 3. Snapshot vs version-index addressing experiment — CONFIRMED

- **spike script path:** `scripts/phase0_version_addressing.py`
  (run against the SAME MinIO ArcticDB — library `addr`, symbol `X` — to mirror prod, not LMDB).
  Each of 3 versions revises `value` at the SAME constant data `valid_time` = `2026-01-01T00:00:00`.

- **read by INT version (v0/v1/v2):** EXACT match.
  ```
  as_of=int(0) -> 10.0
  as_of=int(1) -> 20.0
  as_of=int(2) -> 30.0
  ```

- **read by DATETIME as_of (wall-clock captured BEFORE each write):** tracks WRITE time.
  ```
  as_of=datetime(...01:08:02.607...) -> ERR:NoSuchVersionException   # before first write
  as_of=datetime(...01:08:03.817...) -> 10.0                         # only v0 existed yet
  as_of=datetime(...01:08:04.973...) -> 20.0                         # v0,v1 existed yet
  ```
  Result vector `[ERR, 10.0, 20.0]` ≠ `[10.0, 20.0, 30.0]`. Because the data `valid_time` is identical
  across all three versions, the only thing that could vary the answer is the **wall-clock write
  time** — empirically proving datetime-as_of = "version latest at that wall-clock instant", NOT a
  business/data knowledge date.

- **read by SNAPSHOT name:** EXACT match.
  ```
  as_of='snap_v0' -> 10.0
  as_of='snap_v1' -> 20.0
  as_of='snap_v2' -> 30.0
  ```

- **CONFIRMED: datetime-as_of resolves to version WRITE time (collapses backfills)? YES.**
  A later-written-but-earlier-dated backfill would resolve to "now", so datetime-as_of cannot address
  a business as_of.
- **CONFIRMED: int-version is exact-match? YES.** (snapshot-name is also exact-match.)
- Script exits `0` with no `AssertionError`.

### DECISION (locked)
The per-symbol **INTEGER version index** (sidecar `{symbol}__vintages`) is the **sole**
vintage-addressing authority. `read_as_of` resolves: as_of → floor entry in the version index →
`lib.read(symbol, as_of=int(version))`. **datetime-as_of is FORBIDDEN for vintage reads** (resolves to
version write time, collapsing backfills). Named snapshots are UI-only convenience for the Dagster UI;
**correctness never depends on them.** The version-index append is the atomic commit point.

---

## Phase 0 gate summary

- Section 1 (EIA freeze): **DEFERRED** (no API key) — does not block storage de-risking.
- Section 2 (ArcticDB-on-MinIO smoke): **GREEN**.
- Section 3 (version-addressing): **CONFIRMED**, decision locked (integer version-index authority).
- **Non-EIA Phase 0 gate: PASS.** MinIO left running (`minio` + `minio-init`) with the `arctic` bucket
  populated for the orchestrator's console screenshot.
