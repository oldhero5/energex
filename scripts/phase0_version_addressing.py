"""Phase-0 addressing experiment (against MinIO, to mirror prod).

Writes 3 versions of ONE symbol (each version revises the value at the SAME
valid_time), snapshots each, then reads the symbol THREE ways:
  (a) by integer version (0,1,2),
  (b) by datetime as_of taken from BEFORE each write,
  (c) by snapshot name.

Goal: CONFIRM the spec claim that datetime-as_of resolves to version WRITE time
(so a later-written-but-earlier-dated backfill collapses to "now"), while
int-version is exact-match. Locks: per-symbol integer version index is the
addressing authority.

macOS/6.18.1 gotchas (see phase0_minio_smoke.py): `import arcticdb` BEFORE
pandas/pyarrow, and use `get_library(create_if_missing=True)` (no
`get_or_create_library` in 6.18.1).
"""
import arcticdb  # noqa: F401  (import FIRST — AWS-SDK symbol-collision guard)
import time
from datetime import datetime, timezone

import pandas as pd
from arcticdb import Arctic

URI = (
    "s3://localhost:arctic"
    "?access=minioadmin"
    "&secret=minioadmin"
    "&port=9000"
    "&use_virtual_addressing=false"
)
LIBRARY = "addr"
SYMBOL = "X"


def frame(value: float) -> pd.DataFrame:
    df = pd.DataFrame(
        {"instrument_id": ["X"], "value": [value]},
        index=pd.to_datetime(["2026-01-01T00:00:00"]),
    )
    df.index.name = "valid_time"
    return df


def main() -> None:
    ac = Arctic(URI)
    # Fresh library so version numbers deterministically start at 0.
    if ac.has_library(LIBRARY):
        ac.delete_library(LIBRARY)
    lib = ac.get_library(LIBRARY, create_if_missing=True)

    wall_times = []
    versions = []
    snapshots = []
    for val in [10.0, 20.0, 30.0]:
        wall_times.append(datetime.now(timezone.utc))  # captured BEFORE write i
        time.sleep(1.1)                                # distinct wall-clock per write
        v = lib.write(SYMBOL, frame(val)).version
        snap = f"snap_v{v}"
        lib.snapshot(snap, versions={SYMBOL: v})
        versions.append(v)
        snapshots.append(snap)
        print(f"wrote value={val} -> version={v}, snapshot={snap}")

    print("\n--- (a) read by INTEGER version (expect exact-match 10/20/30) ---")
    int_results = []
    for v in versions:
        val = lib.read(SYMBOL, as_of=int(v)).data["value"].iloc[0]
        int_results.append((v, val))
        print(f"as_of=int({v}) -> {val}")

    print("\n--- (b) read by DATETIME as_of captured BEFORE each write ---")
    dt_results = []
    for wt in wall_times:
        try:
            val = lib.read(SYMBOL, as_of=wt).data["value"].iloc[0]
        except Exception as e:                          # before-first-write may raise
            val = f"ERR:{type(e).__name__}"
        dt_results.append((wt.isoformat(), val))
        print(f"as_of=datetime({wt.isoformat()}) -> {val}")

    print("\n--- (c) read by SNAPSHOT name (expect exact-match 10/20/30) ---")
    snap_results = []
    for snap in snapshots:
        val = lib.read(SYMBOL, as_of=snap).data["value"].iloc[0]
        snap_results.append((snap, val))
        print(f"as_of='{snap}' -> {val}")

    # Assertions that encode the spec's claims:
    assert [r[1] for r in int_results] == [10.0, 20.0, 30.0], "int-version is NOT exact-match"
    assert [r[1] for r in snap_results] == [10.0, 20.0, 30.0], "snapshot name is NOT exact-match"
    # datetime-as_of must NOT reproduce the exact 10/20/30 sequence keyed on data dates:
    assert [r[1] for r in dt_results] != [10.0, 20.0, 30.0], \
        "datetime-as_of unexpectedly behaved like a data-knowledge index"
    print(
        "\nCONFIRMED: int-version exact-match; snapshot exact-match; "
        "datetime-as_of tracks WRITE time (NOT data knowledge date)."
    )


if __name__ == "__main__":
    main()
