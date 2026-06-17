"""Offline, deterministic unit test for the NOAA nClimDiv HDD/CDD connector.

The connector uses httpx, so respx intercepts every request — no live network is
touched. Small recorded-shape fixed-width samples (the real ``state-readme.txt`` layout:
code[1-3] division[4] element[5-6] year[7-10] + twelve F7.0 monthly values) are served
for the directory listing and the two ``-cst-`` files. The shaped FetchResult must
satisfy the SAME core.quality NOAA_HDDCDD gate the Dagster asset runs.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import httpx
import pandas as pd
import respx

from energex.core import quality, schemas
from energex.core.connectors import Connector
from energex.core.connectors.weather import NOAANClimDivConnector

BASE = "https://www.ncei.noaa.gov/pub/data/cirs/climdiv/"
HDD_FILE = "climdiv-hddcst-v1.0.0-20260604"
CDD_FILE = "climdiv-cddcst-v1.0.0-20260604"


def _val(v: float) -> str:
    """Render one F7.0 nClimDiv field, e.g. 606.0 -> '   606.', -9999.0 -> ' -9999.'."""
    return f"{int(round(v)):>6d}."


def _line(code: str, element: str, year: int, months: list[float]) -> str:
    assert len(months) == 12
    return f"{code}0{element}{year}" + "".join(_val(v) for v in months)


# CONUS (110) + Texas (041); element 25 = HDD, 26 = CDD. 2025 full; 2026 Jan-May present,
# Jun-Dec are the -9999. sentinel (not yet released by NCEI).
_S = -9999.0
_HDD_SAMPLE = "\n".join(
    [
        _line("110", "25", 2025, [600, 480, 360, 180, 70, 10, 2, 2, 12, 90, 300, 560]),
        _line("110", "25", 2026, [476, 191, 174, 117, 33, _S, _S, _S, _S, _S, _S, _S]),
        _line("041", "25", 2025, [606, 329, 118, 27, 4, 0, 0, 0, 0, 11, 110, 312]),
        _line("041", "25", 2026, [476, 191, 74, 17, 3, _S, _S, _S, _S, _S, _S, _S]),
    ]
)
_CDD_SAMPLE = "\n".join(
    [
        _line("110", "26", 2025, [4, 15, 29, 54, 123, 274, 388, 305, 198, 76, 23, 13]),
        _line("110", "26", 2026, [9, 12, 57, 62, 114, _S, _S, _S, _S, _S, _S, _S]),
        _line("041", "26", 2025, [20, 40, 90, 160, 290, 410, 470, 450, 360, 200, 70, 25]),
        _line("041", "26", 2026, [30, 55, 120, 185, 320, _S, _S, _S, _S, _S, _S, _S]),
    ]
)

_LISTING = (
    '<a href="climdiv-hddcst-v1.0.0-20260504">old hdd</a>\n'  # decoy older date
    f'<a href="{HDD_FILE}">hdd</a>\n'
    f'<a href="{CDD_FILE}">cdd</a>\n'
    '<a href="climdiv-tmpcst-v1.0.0-20260604">temp</a>\n'
)


def _mock_directory() -> None:
    respx.get(BASE).mock(return_value=httpx.Response(200, text=_LISTING))
    respx.get(BASE + HDD_FILE).mock(return_value=httpx.Response(200, text=_HDD_SAMPLE))
    respx.get(BASE + CDD_FILE).mock(return_value=httpx.Response(200, text=_CDD_SAMPLE))


@respx.mock
def test_fetch_shapes_degree_days_passing_the_gate():
    _mock_directory()

    conn = NOAANClimDivConnector()
    assert isinstance(conn, Connector)  # satisfies the contract Protocol

    result = conn.fetch(date(2026, 5, 1), date(2026, 6, 1))

    assert result.source == "noaa"
    assert result.complete_over_range is True  # whole-file = full as-known series
    assert result.fetched_at.tzinfo is not None  # tz-aware UTC knowledge time
    assert result.source_url == BASE + HDD_FILE  # newest date picked, not the decoy

    frame = result.frame
    assert list(frame.columns) == ["instrument_id", "valid_time", "hdd", "cdd"]
    assert set(frame["instrument_id"]) == {"NOAA.HDD.CONUS", "NOAA.HDD.TEXAS"}
    assert str(frame["valid_time"].dtype) == "datetime64[ns, UTC]"

    # 2 regions x (12 months 2025 + 5 months 2026) = 34 rows; sentinel months dropped.
    assert len(frame) == 34
    assert frame["valid_time"].max() == pd.Timestamp("2026-05-01", tz="UTC")

    # Spot-check a parsed value: CONUS Jan-2025 HDD and Texas May-2026 CDD.
    conus = frame[frame["instrument_id"] == "NOAA.HDD.CONUS"].set_index("valid_time")
    assert conus.loc["2025-01-01", "hdd"] == 600.0
    assert conus.loc["2025-06-01", "cdd"] == 274.0
    texas = frame[frame["instrument_id"] == "NOAA.HDD.TEXAS"].set_index("valid_time")
    assert texas.loc["2026-05-01", "cdd"] == 320.0

    # The frame must pass the exact NOAA_HDDCDD gate the asset runs (single-sourced).
    as_of = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)
    validated = quality.validate(frame, schemas.NOAA_HDDCDD, as_of=as_of)
    assert len(validated) == 34


@respx.mock
def test_sentinel_months_are_dropped_not_stored_as_minus_9999():
    _mock_directory()
    frame = NOAANClimDivConnector().fetch(date(2026, 5, 1), date(2026, 6, 1)).frame
    assert (frame["hdd"] == -9999.0).sum() == 0
    assert (frame["cdd"] == -9999.0).sum() == 0
    # June 2026 onward is sentinel in both files -> no such rows survive.
    assert frame["valid_time"].max() == pd.Timestamp("2026-05-01", tz="UTC")


@respx.mock
def test_fetch_retries_transient_failure():
    calls = {"n": 0}

    def _flaky(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("transient")
        return httpx.Response(200, text=_LISTING)

    respx.get(BASE).mock(side_effect=_flaky)
    respx.get(BASE + HDD_FILE).mock(return_value=httpx.Response(200, text=_HDD_SAMPLE))
    respx.get(BASE + CDD_FILE).mock(return_value=httpx.Response(200, text=_CDD_SAMPLE))

    frame = NOAANClimDivConnector(retries=3, timeout=5).fetch(
        date(2026, 5, 1), date(2026, 6, 1)
    ).frame
    assert calls["n"] == 2  # one retry then success
    assert len(frame) == 34
