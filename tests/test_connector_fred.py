"""Offline, deterministic unit tests for the FRED daily spot-price connector.

The connector uses httpx, so respx intercepts every request — no live network is
touched. Small recorded-shape FRED v1 JSON payloads (the real
``{"observations": [{"date", "value", ...}]}`` envelope, sorted date-asc) are served per
``series_id``. The shaped FetchResult must satisfy the SAME core.quality FRED_SPOT gate
the Dagster asset runs, and the FRED ``"."`` missing-value sentinel must be dropped.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace

import httpx
import pandas as pd
import pytest
import respx

from energex.core import quality, schemas
from energex.core.connectors import Connector
from energex.core.connectors.fred import FredConnector

OBS_URL = "https://api.stlouisfed.org/fred/series/observations"


def _obs(date_: str, value: str) -> dict:
    return {
        "realtime_start": "2026-06-18",
        "realtime_end": "2026-06-18",
        "date": date_,
        "value": value,
    }


# Recorded-shape FRED observations (date-asc). Each series carries one "." missing marker
# (a market holiday/gap) to prove it is dropped, plus the real 2026-06 benchmark levels.
_SERIES_OBS = {
    "DCOILWTICO": [
        _obs("2026-06-10", "93.68"),
        _obs("2026-06-11", "91.58"),
        _obs("2026-06-12", "88.62"),
        _obs("2026-06-13", "."),  # weekend/holiday -> dropped
        _obs("2026-06-15", "84.65"),
    ],
    "DCOILBRENTEU": [
        _obs("2026-06-10", "95.73"),
        _obs("2026-06-11", "92.84"),
        _obs("2026-06-12", "88.64"),
        _obs("2026-06-13", "."),
        _obs("2026-06-15", "84.36"),
    ],
    "DHHNGSP": [
        _obs("2026-06-10", "3.27"),
        _obs("2026-06-11", "3.16"),
        _obs("2026-06-12", "3.06"),
        _obs("2026-06-13", "."),
        _obs("2026-06-15", "3.06"),
    ],
}


def _by_series(request: httpx.Request) -> httpx.Response:
    series_id = request.url.params["series_id"]
    return httpx.Response(200, json={"observations": _SERIES_OBS[series_id]})


@respx.mock
def test_fetch_shapes_spot_prices_passing_the_gate():
    route = respx.get(OBS_URL).mock(side_effect=_by_series)

    conn = FredConnector(api_key="TESTKEY")
    assert isinstance(conn, Connector)  # satisfies the contract Protocol

    result = conn.fetch(date(2026, 6, 8), date(2026, 6, 17))

    assert result.source == "fred"
    assert result.complete_over_range is False  # continuous degenerate stream
    assert result.fetched_at.tzinfo is not None  # tz-aware UTC knowledge time

    frame = result.frame
    assert list(frame.columns) == ["instrument_id", "valid_time", "value"]
    assert set(frame["instrument_id"]) == {
        "FRED.WTI.SPOT",
        "FRED.BRENT.SPOT",
        "FRED.HENRYHUB.SPOT",
    }
    assert str(frame["valid_time"].dtype) == "datetime64[ns, UTC]"

    # 3 series x (5 recorded - 1 "." dropped) = 12 rows.
    assert len(frame) == 12
    assert (frame["value"] == ".").sum() == 0  # the string sentinel never survives
    assert pd.Timestamp("2026-06-13", tz="UTC") not in set(frame["valid_time"])  # "." dropped

    wti = frame[frame["instrument_id"] == "FRED.WTI.SPOT"].set_index("valid_time")["value"]
    assert wti.loc["2026-06-15"] == 84.65
    brent = frame[frame["instrument_id"] == "FRED.BRENT.SPOT"].set_index("valid_time")["value"]
    assert brent.loc["2026-06-15"] == 84.36
    hh = frame[frame["instrument_id"] == "FRED.HENRYHUB.SPOT"].set_index("valid_time")["value"]
    assert hh.loc["2026-06-15"] == 3.06

    # One request per series carried the real key + the requested observation window.
    assert route.call_count == 3
    last = route.calls.last.request.url.params
    assert last["api_key"] == "TESTKEY"
    assert last["file_type"] == "json"
    assert last["observation_start"] == "2026-06-08"
    assert last["observation_end"] == "2026-06-17"

    # Passes the exact FRED_SPOT gate the asset runs (single-sourced).
    as_of = datetime(2026, 6, 17, 14, 30, tzinfo=timezone.utc)
    validated = quality.validate(frame, schemas.FRED_SPOT, as_of=as_of)
    assert len(validated) == 12


@respx.mock
def test_api_key_read_from_config_when_not_overridden(monkeypatch):
    """With no explicit api_key, the connector reads it via core.config.get_settings."""
    fake = SimpleNamespace(
        connectors=SimpleNamespace(
            fred_api_key=SimpleNamespace(get_secret_value=lambda: "FROMCONFIG")
        )
    )
    monkeypatch.setattr("energex.core.connectors.fred.get_settings", lambda: fake)
    route = respx.get(OBS_URL).mock(side_effect=_by_series)

    FredConnector().fetch(date(2026, 6, 8), date(2026, 6, 17))
    assert route.calls.last.request.url.params["api_key"] == "FROMCONFIG"


@respx.mock
def test_missing_api_key_raises():
    from energex.core.exceptions import ConfigurationError

    fake = SimpleNamespace(connectors=SimpleNamespace(fred_api_key=None))
    import energex.core.connectors.fred as fred_mod

    orig = fred_mod.get_settings
    fred_mod.get_settings = lambda: fake
    try:
        with pytest.raises(ConfigurationError):
            FredConnector().fetch(date(2026, 6, 8), date(2026, 6, 17))
    finally:
        fred_mod.get_settings = orig


@respx.mock
def test_fetch_retries_transient_failure():
    calls = {"n": 0}

    def _flaky(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("transient")
        return _by_series(request)

    respx.get(OBS_URL).mock(side_effect=_flaky)
    frame = (
        FredConnector(api_key="TESTKEY", retries=3, timeout=5)
        .fetch(date(2026, 6, 8), date(2026, 6, 17))
        .frame
    )
    assert calls["n"] == 4  # one transient failure retried, then 3 series succeed
    assert len(frame) == 12


@respx.mock
def test_empty_response_yields_empty_typed_frame():
    respx.get(OBS_URL).mock(return_value=httpx.Response(200, json={"observations": []}))
    frame = FredConnector(api_key="TESTKEY").fetch(date(2026, 6, 8), date(2026, 6, 17)).frame
    assert frame.empty
    assert list(frame.columns) == ["instrument_id", "valid_time", "value"]
    assert str(frame["valid_time"].dtype) == "datetime64[ns, UTC]"
