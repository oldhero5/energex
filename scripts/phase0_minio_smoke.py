"""Phase-0 ArcticDB-on-MinIO connectivity smoke.

Confirms the EXACT s3 URI grammar ArcticDB 6.18.1 accepts against local MinIO:
  s3://<endpoint>:<bucket>?access=..&secret=..&port=..&use_virtual_addressing=false
Writes a 2-row pandas frame, reads it back, asserts equality.

Two macOS/6.18.1 gotchas discovered in Phase 0 and encoded here:
  1. `import arcticdb` MUST precede `import pandas` (pyarrow). Both libarrow and
     arcticdb_ext vendor the AWS C SDK; if pyarrow's copy loads first the dynamic
     linker binds AWS symbols to an uninitialized allocator and the S3 client
     constructor aborts (aws-c-common allocator.c:202: allocator != NULL).
  2. There is NO `get_or_create_library` in 6.18.1. Use
     `get_library(name, create_if_missing=True)`.
"""
import arcticdb  # noqa: F401  (import FIRST — see module docstring gotcha #1)
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
    lib = ac.get_library("smoke", create_if_missing=True)
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
