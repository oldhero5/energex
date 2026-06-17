# Energex S1 — Phase 0 Findings (2026-06-16)

Source of truth: docs/superpowers/specs/2026-06-16-energex-unified-platform-design.md (§5.3 storage contract, §11 verified APIs).
Each section below is a gating experiment. A section is DONE only when every UNRESOLVED token is replaced
with a recorded literal result. Do not start Phase 1 until all (non-deferred) gates pass.

Scope of THIS pass: the two **storage de-risking** spikes (sections 2 and 3). The EIA series freeze
(section 1) is **DEFERRED** pending `EIA_API_KEY` — see section 1.

---

## 1. EIA v2 series freeze (gas storage + petroleum status) — FROZEN (2026-06-17)

**STATUS: DONE.** `EIA_API_KEY` (len=40) loaded via `get_settings().connectors.eia_api_key`
(pydantic-settings + `.env`); key never hardcoded. All values below pulled LIVE from the EIA v2
metadata/facet/data endpoints — no invented codes.

### (a) Natural gas — weekly underground storage, Lower 48 (route `natural-gas/stor/wkly`)
- **Route metadata:** `FREQUENCIES=['weekly']`, `FACETS=['duoarea','product','process','series']`,
  `DATA_COLS=['value']`.
- **Facet enumeration (live):**
  - `duoarea`: `R31 R32 R33 R34 R35 R48` (all `name="NA"`; region codes, R48 = Lower 48).
  - `process`: `SWO` "Underground Storage - Working Gas", `SNO` "Non-Salt ... Working Gas",
    `SSO` "Salt ... Working Gas".
  - `product`: `EPG0` "Natural Gas" (only value).
  - `series`: the Lower-48 series is **`NW2_EPG0_SWO_R48_BCF`** "Weekly Lower 48 States Natural Gas
    Working Underground Storage (Billion Cubic Feet)". (The other 7 are single-region series.)
- **Lower-48 selector (FROZEN):** `duoarea=R48`, `process=SWO`, `product=EPG0` → series
  `NW2_EPG0_SWO_R48_BCF`, units `BCF`.
- **Sanity data pull (`total=858`):** `2026-06-05=2686`, `2026-05-29=2578`, `2026-05-22=2483` BCF …
  (numeric, monotone refill — the canonical headline US working-gas figure).
- ⚠️ **Deviation from plan's guess:** plan/section expected `duoarea=NUS, process=SAS`. Those codes do
  **not exist** on this route (NUS/SAS are *petroleum* facet ids). The real Lower-48 selector is
  `duoarea=R48, process=SWO`. The brief's "~322" hint was an unfiltered/single-region row, **not**
  the Lower-48 total (which is ~2686 BCF in June 2026).

### (b) Petroleum — weekly stocks / crude oil, excl. SPR (route `petroleum/stoc/wstk`)
- **Route metadata:** `FREQUENCIES=['weekly']`, `FACETS=['duoarea','product','process','series']`,
  `DATA_COLS=['value']`.
- **Facet enumeration (live):**
  - `duoarea`: 11 values incl. `NUS` "U.S.".
  - `product`: 33 values incl. `EPC0` "Crude Oil".
  - `process` (all 7): `SAE` "Ending Stocks", `SAS` "Ending Stocks SPR",
    `SAX` "Ending Stocks Excluding SPR", `SAXL` "Ending Stocks Excluding SPR and Lease",
    `SAXP`, `SKB`, `SKA`.
- **Series disambiguation (live):**
  - `EPC0 + SAE + NUS` → `WCRSTUS1` "U.S. Ending Stocks of Crude Oil" (total **incl SPR**) =
    `2026-06-12=758473` MBBL.
  - `EPC0 + SAX + NUS` → `WCESTUS1` "U.S. Ending Stocks **excluding SPR** of Crude Oil" =
    `2026-06-12=418222` MBBL.
- **Crude-stocks selector (FROZEN):** `product=EPC0`, `process=SAX`, `duoarea=NUS` → series
  `WCESTUS1`, units `MBBL` (thousand barrels). `total=2281`.
- ⚠️ **Deviation from plan's guess:** plan expected `process=SAE` *labelled* "Ending Stocks Excluding
  SPR". That label is wrong: live `SAE`="Ending Stocks" = **total incl SPR** (`WCRSTUS1`, 758M bbl).
  The excl-SPR headline number traders watch is **`SAX`** = `WCESTUS1` (418M bbl). We freeze `SAX` to
  honor the documented *intent* ("Excluding SPR").

### (c) Canonical httpx request grammar (key redacted; `data/` endpoint, sort period desc)
```
https://api.eia.gov/v2/natural-gas/stor/wkly/data/?api_key=<KEY>&frequency=weekly&data%5B0%5D=value&sort%5B0%5D%5Bcolumn%5D=period&sort%5B0%5D%5Bdirection%5D=desc&length=2&facets%5Bduoarea%5D%5B%5D=R48&facets%5Bprocess%5D%5B%5D=SWO&facets%5Bproduct%5D%5B%5D=EPG0
https://api.eia.gov/v2/petroleum/stoc/wstk/data/?api_key=<KEY>&frequency=weekly&data%5B0%5D=value&sort%5B0%5D%5Bcolumn%5D=period&sort%5B0%5D%5Bdirection%5D=desc&length=2&facets%5Bproduct%5D%5B%5D=EPC0&facets%5Bprocess%5D%5B%5D=SAX&facets%5Bduoarea%5D%5B%5D=NUS
```
(`facets[...][]`, `data[0]`, `sort[0][column/direction]` are URL-encoded by httpx; decode to the
literal bracket grammar EIA expects.)

### (d) Revision behavior (bitemporal_merge driver)
EIA v2 has **no vintage/as_of query parameter**: weekly releases overwrite (revise) the value at a
prior `period` **inline**. Re-pulling a span returns *today's* values for every week in it. Therefore
the connector fetch window MUST include a **≥5-week revision lookback** so each pull re-carries EIA's
inline revisions, and the asset commits `mode="bitemporal_merge"` (read-modify-write by `valid_time`).
True forward vintages exist only from first live capture; pulls of past weeks are reconstructed
baselines (`vintage_reconstructed=True`).

### DECISION (locked) — symbology mapping
```
EIA.NG.STORAGE.LOWER48 -> route=natural-gas/stor/wkly, frequency=weekly,
                          facets={duoarea:R48, process:SWO, product:EPG0}  series NW2_EPG0_SWO_R48_BCF  (BCF)
EIA.PET.CRUDE.STOCKS   -> route=petroleum/stoc/wstk,  frequency=weekly,
                          facets={product:EPC0, process:SAX, duoarea:NUS}  series WCESTUS1            (MBBL)
```

Gate: section 1 has zero UNRESOLVED tokens; both data pulls return `total > 0` with numeric `value`. **PASS.**

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

- Section 1 (EIA freeze): **DONE** (2026-06-17, key landed) — routes/facets/series frozen, two
  deviations from the plan's guessed codes recorded (gas `R48/SWO` not `NUS/SAS`; crude `SAX` not `SAE`).
- Section 2 (ArcticDB-on-MinIO smoke): **GREEN**.
- Section 3 (version-addressing): **CONFIRMED**, decision locked (integer version-index authority).
- **Non-EIA Phase 0 gate: PASS.** MinIO left running (`minio` + `minio-init`) with the `arctic` bucket
  populated for the orchestrator's console screenshot.
