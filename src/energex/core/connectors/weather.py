"""NOAA nClimDiv monthly HDD/CDD connector: fixed-width degree-day files -> FetchResult.

NCEI publishes monthly heating- and cooling-degree-day values (period of record 1895 to
present) as fixed-width download files at
``https://www.ncei.noaa.gov/pub/data/cirs/climdiv/`` (no API key). This connector reads
the STATEWIDE-REGIONAL-NATIONAL files (``climdiv-hddcst-*`` for HDD, ``climdiv-cddcst-*``
for CDD), whose record layout is documented in ``state-readme.txt``::

    cols  1-3   state / region code (001-110 states, regions, national; see REGIONS)
    col   4     division number (0 = area-averaged)
    cols  5-6   element code (25 = Heating Degree Days, 26 = Cooling Degree Days)
    cols  7-10  year
    cols 11-94  twelve F7.0 monthly values (right-justified; ``-9999.`` = missing)

The current dated filename changes every month, so ``fetch`` reads the live directory
listing and selects the newest ``-cst-`` file by its ``YYYYMMDD`` suffix (never a
hardcoded version). Each whole file is the full as-known degree-day series, so
``complete_over_range=True`` and the asset commits it under ``bitemporal_replace``.

One combined weather instrument is emitted per region — ``NOAA.HDD.<region>`` carrying
both the ``hdd`` and ``cdd`` columns for each region-month, matching
``schemas.NOAA_HDDCDD`` (which requires both columns). The ``-9999.`` sentinel is coerced
to NULL. Network calls go through tenacity retry over an httpx client.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone

import httpx
import numpy as np
import pandas as pd
from tenacity import retry, stop_after_attempt, wait_exponential

from energex.core.connectors.base import FetchResult

logger = logging.getLogger(__name__)

_SOURCE = "noaa"
_BASE_URL = "https://www.ncei.noaa.gov/pub/data/cirs/climdiv/"

# nClimDiv state/region/national codes -> instrument_id region token (state-readme.txt).
# The contiguous-US national aggregate (110), the nine standard NCEI U.S. climate regions
# (101-109), and Texas (041, the ERCOT footprint) — a documented, energy-relevant set.
REGIONS: dict[str, str] = {
    "110": "CONUS",  # National (contiguous 48 States)
    "101": "NORTHEAST",
    "102": "ENCENTRAL",  # East North Central
    "103": "CENTRAL",
    "104": "SOUTHEAST",
    "105": "WNCENTRAL",  # West North Central
    "106": "SOUTH",
    "107": "SOUTHWEST",
    "108": "NORTHWEST",
    "109": "WEST",
    "041": "TEXAS",
}

#: instrument_ids this connector produces (consumed by the asset + asset_check).
INSTRUMENT_IDS: list[str] = [f"NOAA.HDD.{token}" for token in REGIONS.values()]

# Fixed-width layout (0-indexed slices) and the per-file element codes / sentinel.
_HEADER_WIDTH = 10  # code(3) + division(1) + element(2) + year(4)
_VALUE_WIDTH = 7
_MONTHS = 12
_SENTINEL = -9999.0
_HDD_ELEMENT = "25"
_CDD_ELEMENT = "26"

_FRAME_COLS = ["instrument_id", "valid_time", "hdd", "cdd"]


def _instrument_id(code: str) -> str:
    return f"NOAA.HDD.{REGIONS[code]}"


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "instrument_id": pd.Series(dtype="object"),
            "valid_time": pd.Series(dtype="datetime64[ns, UTC]"),
            "hdd": pd.Series(dtype="float64"),
            "cdd": pd.Series(dtype="float64"),
        }
    )


def _select_latest(listing: str, kind: str) -> str:
    """Newest ``climdiv-<kind>-vX.Y.Z-YYYYMMDD`` filename in the directory listing."""
    matches = list(re.finditer(rf"climdiv-{kind}-v\d+\.\d+\.\d+-(\d{{8}})", listing))
    if not matches:
        raise ValueError(f"no climdiv-{kind} file found in NOAA directory listing")
    return max(matches, key=lambda m: m.group(1)).group(0)


def _parse_file(text: str, element: str, value_col: str) -> pd.DataFrame:
    """Fixed-width nClimDiv state file -> long (instrument_id, valid_time, <value_col>).

    Keeps only the configured REGIONS and the file's element code; melts the 12 monthly
    fields to one row per region-month; coerces the ``-9999.`` sentinel to NaN.
    """
    records: list[tuple[str, int, int, float]] = []
    for line in text.splitlines():
        if len(line) < _HEADER_WIDTH:
            continue
        code = line[0:3]
        if code not in REGIONS or line[4:6] != element:
            continue
        year = int(line[6:10])
        instrument_id = _instrument_id(code)
        for m in range(_MONTHS):
            lo = _HEADER_WIDTH + m * _VALUE_WIDTH
            field = line[lo : lo + _VALUE_WIDTH].strip()
            if not field:
                continue
            records.append((instrument_id, year, m + 1, float(field)))

    if not records:
        return pd.DataFrame({"instrument_id": [], "valid_time": [], value_col: []})

    df = pd.DataFrame(records, columns=["instrument_id", "_year", "_month", value_col])
    df["valid_time"] = pd.to_datetime(
        pd.DataFrame({"year": df["_year"], "month": df["_month"], "day": 1})
    ).dt.tz_localize("UTC")
    df[value_col] = df[value_col].replace(_SENTINEL, np.nan)
    return df[["instrument_id", "valid_time", value_col]]


def _combine(hdd: pd.DataFrame, cdd: pd.DataFrame) -> pd.DataFrame:
    """Join HDD + CDD on (instrument_id, valid_time); drop fully-missing months."""
    if hdd.empty and cdd.empty:
        return _empty_frame()
    merged = pd.merge(hdd, cdd, on=["instrument_id", "valid_time"], how="outer")
    merged = merged.dropna(subset=["hdd", "cdd"], how="all")
    merged = merged.sort_values(["instrument_id", "valid_time"]).reset_index(drop=True)
    return merged[_FRAME_COLS]


class NOAANClimDivConnector:
    """Connector for monthly nClimDiv HDD+CDD degree days (bitemporal_replace)."""

    source = _SOURCE

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
        retries: int = 3,
        base_url: str = _BASE_URL,
    ) -> None:
        self._client = client
        self._timeout = timeout
        self._retries = max(1, retries)
        self._base_url = base_url

    def fetch(self, window_start: date, window_end: date) -> FetchResult:
        # nClimDiv is whole-file (the full as-known series); window is informational only.
        del window_start, window_end
        fetched_at = datetime.now(timezone.utc)
        owns_client = self._client is None
        client = httpx.Client(timeout=self._timeout) if owns_client else self._client
        try:
            listing = self._get(client, self._base_url)
            hdd_name = _select_latest(listing, "hddcst")
            cdd_name = _select_latest(listing, "cddcst")
            hdd_text = self._get(client, self._base_url + hdd_name)
            cdd_text = self._get(client, self._base_url + cdd_name)
        finally:
            if owns_client:
                client.close()

        frame = _combine(
            _parse_file(hdd_text, _HDD_ELEMENT, "hdd"),
            _parse_file(cdd_text, _CDD_ELEMENT, "cdd"),
        )
        logger.info("NOAA nClimDiv: %d region-months from %s", len(frame), hdd_name)
        return FetchResult(
            frame=frame,
            source=self.source,
            fetched_at=fetched_at,
            source_url=self._base_url + hdd_name,
            complete_over_range=True,
        )

    def _get(self, client: httpx.Client, url: str) -> str:
        @retry(
            stop=stop_after_attempt(self._retries),
            wait=wait_exponential(multiplier=1, max=10),
            reraise=True,
        )
        def _go() -> str:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.text

        return _go()
