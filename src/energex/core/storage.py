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

# arcticdb MUST be imported before pandas/pyarrow (phase0 findings: AWS-SDK symbol
# collision aborts the process on macOS otherwise).
import arcticdb  # noqa: F401
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


def _latest_committed_version(idx):
    """Latest COMMITTED vintage (by as_of); None if nothing is committed yet."""
    if not idx:
        return None
    return max(idx, key=lambda e: e.as_of).version


def _empty_like(lib, symbol, idx):
    if not idx:
        return pd.DataFrame()
    v = max(idx, key=lambda e: e.version).version
    return lib.read(symbol, as_of=int(v)).data.iloc[0:0]


# Per-commit provenance columns; identical underlying data under a new as_of is NOT new
# knowledge, so these are excluded when deciding whether a commit changes the payload.
_PROVENANCE_COLS = ("as_of", "source", "source_url", "fetched_at", "vintage_reconstructed")


def _same_payload(new, prior) -> bool:
    """True iff two canonical frames carry identical data (index + non-provenance columns)."""
    if prior is None:
        return False
    a = new.drop(columns=[c for c in _PROVENANCE_COLS if c in new.columns])
    b = prior.drop(columns=[c for c in _PROVENANCE_COLS if c in prior.columns])
    if list(a.columns) != list(b.columns) or len(a) != len(b):
        return False
    return a.equals(b)


# ---------------------------------------------------------------- commit / read
def commit_vintage(
    lib,
    symbol,
    frame,
    *,
    as_of,
    source,
    source_url,
    fetched_at,
    mode,
    reconstructed=False,
    force=False,
) -> int:
    if mode not in ("bitemporal_merge", "bitemporal_replace"):
        raise StorageError(f"commit_vintage cannot handle mode {mode!r}")
    idx = _read_vintage_index(lib, symbol)
    a = _naive_utc(as_of)
    if not force and any(e.as_of == a for e in idx):
        return _version_for(idx, a)  # IDEMPOTENT NO-OP: never re-mutate a live vintage
    cframe = _canonicalize(frame, as_of, source, source_url, fetched_at, reconstructed)
    if mode == "bitemporal_merge":
        prior = _read_full_series_before(lib, symbol, idx, a)
        cframe = _merge_revisions(prior, cframe)
    # Content idempotency: if this commit's payload matches the latest committed vintage, a
    # re-record under a new as_of adds no knowledge — skip it. Without this, an unchanged hourly
    # re-pull (the ERCOT case) creates a fresh full-history vintage every run (unbounded growth).
    if not force:
        latest_v = _latest_committed_version(idx)
        if latest_v is not None and _same_payload(
            cframe, lib.read(symbol, as_of=int(latest_v)).data
        ):
            return int(latest_v)
    v = lib.write(
        symbol,
        cframe,
        metadata={"as_of": str(a), "source": source, "vintage_reconstructed": bool(reconstructed)},
        validate_index=True,
    ).version
    _append_vintage_index(
        lib,
        symbol,
        as_of=a,
        version=v,
        fetched_at=fetched_at,
        vintage_reconstructed=reconstructed,
    )
    try:  # UI-only convenience snapshot; correctness never depends on it.
        # Microsecond resolution so two commits within the same second cannot collide on name.
        lib.snapshot(f"{symbol}@{a:%Y-%m-%dT%H%M%S_%fZ}", versions={symbol: int(v)})
    except Exception:
        pass
    return int(v)


def _read_full_series_before(lib, symbol, idx, a):
    """Full as-known series committed STRICTLY BEFORE this as_of (no future leak)."""
    earlier = [e for e in idx if e.as_of < a]
    if not earlier:
        return None
    e = max(earlier, key=lambda x: x.as_of)
    return lib.read(symbol, as_of=int(e.version)).data


def _merge_revisions(prior, frame):
    """Revisions overwrite by exact valid_time; prior rows absent from the frame survive."""
    if prior is None or prior.empty:
        return frame
    kept = prior[~prior.index.isin(frame.index)]
    return pd.concat([kept, frame]).sort_index()


def write_bars(lib, symbol, frame, *, fetched_at, mode=None) -> int:
    """DEGENERATE append-with-dedup on the UTC index. Fast-path append when strictly
    after the existing tail; otherwise read-concat-write (sparse interior inserts).
    NEVER lib.update(date_range) — it would delete omitted bars.

    ``mode`` is the symbol's revision mode; pass it explicitly for high-cardinality
    libraries (e.g. power.*) whose bare symbols are not in the static reverse index.
    When None it is derived from the symbol (the enumerated static path)."""
    if (mode or symbology.mode_for_symbol(symbol)) != "degenerate":
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


def read_as_of(lib, symbol, *, as_of=None, date_range=None, mode=None):
    if (mode or symbology.mode_for_symbol(symbol)) == "degenerate":
        df = lib.read(symbol, date_range=_naive(date_range)).data
        if as_of is not None:  # filter on KNOWLEDGE time, never valid_time
            df = df[df["fetched_at"] <= _naive_utc(as_of)]
        return df
    idx = _read_vintage_index(lib, symbol)  # re-read every correctness-critical call
    if as_of is None:
        v = _latest_committed_version(idx)  # never an orphan write version
        if v is None:
            return _empty_like(lib, symbol, idx)
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
    if "Datetime" in df.columns and df["Datetime"].dt.tz is None:
        df["Datetime"] = df["Datetime"].dt.tz_localize("UTC")  # Arctic stripped tz
    if "valid_time" in df.columns and df["valid_time"].dt.tz is None:
        df["valid_time"] = df["valid_time"].dt.tz_localize("UTC")
    pf = pl.from_pandas(df)
    if "ContractMonth" in pf.columns:
        pf = pf.with_columns(pl.col("ContractMonth").cast(pl.Date))
    return pf


# ---------------------------------------------------------------- reconcile / GC
def reconcile_orphans(lib, symbol) -> list[int]:
    """Delete data versions with no committed index entry (crash residue). Returns removed."""
    committed = {e.version for e in _read_vintage_index(lib, symbol)}
    data_versions = {k.version for k in lib.list_versions(symbol) if k.symbol == symbol}
    orphans = sorted(data_versions - committed)
    for v in orphans:
        lib.delete(symbol, versions=int(v))  # committed versions carry snapshots; orphans do not
    return orphans


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
