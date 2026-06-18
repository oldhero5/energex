"""Offline, deterministic unit tests for the EIA v2 weekly fundamentals connectors.

The connectors use httpx, so respx intercepts every request — no live network is
touched. Small recorded-shape EIA v2 JSON payloads (the real
``{"response": {"total": N, "data": [{"period", "value", ...}]}}`` envelope, sorted
period-desc) are served for the gas-storage and petroleum-status ``/data/`` routes.
The shaped FetchResults must satisfy the SAME core.quality EIA_GAS_STORAGE /
EIA_PETROLEUM gates the Dagster assets run, and each pull must widen its window back
by the >=5-week revision lookback so it re-carries EIA's inline revisions.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pandas as pd
import pytest
import respx

from energex.core import quality, schemas
from energex.core.connectors import Connector
from energex.core.connectors.eia import (
    EiaGasStorageConnector,
    EiaPetroleumStatusConnector,
)

GAS_URL = "https://api.eia.gov/v2/natural-gas/stor/wkly/data/"
PET_URL = "https://api.eia.gov/v2/petroleum/stoc/wstk/data/"


def _row(period: str, value, series: str, units: str) -> dict:
    return {"period": period, "value": value, "series": series, "units": units}


# Lower-48 working gas (BCF), period-desc. One null + one string value prove coercion
# and null-dropping; the rest are the real refill curve recorded 2026-06.
_GAS_DATA = {
    "response": {
        "total": 858,
        "data": [
            _row("2026-06-05", 2686, "NW2_EPG0_SWO_R48_BCF", "BCF"),
            _row("2026-05-29", "2578", "NW2_EPG0_SWO_R48_BCF", "BCF"),  # string -> coerced
            _row("2026-05-22", 2483, "NW2_EPG0_SWO_R48_BCF", "BCF"),
            _row("2026-05-15", 2391, "NW2_EPG0_SWO_R48_BCF", "BCF"),
            _row("2026-05-08", None, "NW2_EPG0_SWO_R48_BCF", "BCF"),  # null -> dropped
            _row("2026-05-01", 2205, "NW2_EPG0_SWO_R48_BCF", "BCF"),
        ],
    }
}

# U.S. crude oil ending stocks excluding SPR (thousand barrels), period-desc.
_PET_DATA = {
    "response": {
        "total": 2281,
        "data": [
            _row("2026-06-12", 418222, "WCESTUS1", "MBBL"),
            _row("2026-06-05", 421558, "WCESTUS1", "MBBL"),
            _row("2026-05-29", 430915, "WCESTUS1", "MBBL"),
            _row("2026-05-22", 436012, "WCESTUS1", "MBBL"),
            _row("2026-05-15", 441880, "WCESTUS1", "MBBL"),
            _row("2026-05-08", 447233, "WCESTUS1", "MBBL"),
        ],
    }
}


@respx.mock
def test_gas_storage_shapes_to_passing_gate():
    route = respx.get(GAS_URL).mock(return_value=httpx.Response(200, json=_GAS_DATA))

    conn = EiaGasStorageConnector(api_key="TESTKEY")
    assert isinstance(conn, Connector)  # satisfies the contract Protocol

    window_end = date(2026, 6, 12)
    result = conn.fetch(date(2026, 6, 5), window_end)

    assert result.source == "eia"
    assert result.complete_over_range is False  # a revision window, not the full series
    assert result.fetched_at.tzinfo is not None  # tz-aware UTC knowledge time
    assert "api_key=REDACTED" in result.source_url and "TESTKEY" not in result.source_url

    frame = result.frame
    assert list(frame.columns) == ["instrument_id", "valid_time", "value"]
    assert set(frame["instrument_id"]) == {"EIA.NG.STORAGE.LOWER48"}
    assert str(frame["valid_time"].dtype) == "datetime64[ns, UTC]"

    # 6 rows recorded, the null week dropped -> 5; values numeric (string coerced).
    assert len(frame) == 5
    by_week = frame.set_index("valid_time")["value"]
    assert by_week.loc["2026-06-05"] == 2686.0
    assert by_week.loc["2026-05-29"] == 2578.0  # came in as a string
    assert pd.Timestamp("2026-05-08", tz="UTC") not in by_week.index  # null dropped

    # The request carried the real key + the >=5-week revision lookback widening.
    params = route.calls.last.request.url.params
    assert params["api_key"] == "TESTKEY"
    assert params["frequency"] == "weekly"
    assert params["facets[duoarea][]"] == "R48"
    assert params["facets[process][]"] == "SWO"
    assert params["facets[product][]"] == "EPG0"
    start = date.fromisoformat(params["start"])
    assert start <= window_end - timedelta(weeks=5)

    # Passes the exact EIA_GAS_STORAGE gate the asset runs (single-sourced).
    as_of = datetime(2026, 6, 11, 14, 30, tzinfo=timezone.utc)
    validated = quality.validate(frame, schemas.EIA_GAS_STORAGE, as_of=as_of)
    assert len(validated) == 5


@respx.mock
def test_petroleum_status_shapes_to_passing_gate():
    route = respx.get(PET_URL).mock(return_value=httpx.Response(200, json=_PET_DATA))

    conn = EiaPetroleumStatusConnector(api_key="TESTKEY")
    assert isinstance(conn, Connector)

    result = conn.fetch(date(2026, 6, 12), date(2026, 6, 12))
    frame = result.frame

    assert result.source == "eia"
    assert result.complete_over_range is False
    assert set(frame["instrument_id"]) == {"EIA.PET.CRUDE.STOCKS"}
    assert len(frame) == 6
    assert frame.set_index("valid_time")["value"].loc["2026-06-12"] == 418222.0

    params = route.calls.last.request.url.params
    assert params["facets[product][]"] == "EPC0"
    assert params["facets[process][]"] == "SAX"
    assert params["facets[duoarea][]"] == "NUS"

    as_of = datetime(2026, 6, 17, 14, 30, tzinfo=timezone.utc)
    validated = quality.validate(frame, schemas.EIA_PETROLEUM, as_of=as_of)
    assert len(validated) == 6


@respx.mock
def test_api_key_read_from_config_when_not_overridden(monkeypatch):
    """With no explicit api_key, the connector reads it via core.config.get_settings."""
    fake = SimpleNamespace(
        connectors=SimpleNamespace(
            eia_api_key=SimpleNamespace(get_secret_value=lambda: "FROMCONFIG")
        )
    )
    monkeypatch.setattr("energex.core.connectors.eia.get_settings", lambda: fake)
    route = respx.get(GAS_URL).mock(return_value=httpx.Response(200, json=_GAS_DATA))

    EiaGasStorageConnector().fetch(date(2026, 6, 5), date(2026, 6, 12))
    assert route.calls.last.request.url.params["api_key"] == "FROMCONFIG"


@respx.mock
def test_missing_api_key_raises():
    from energex.core.exceptions import ConfigurationError

    fake = SimpleNamespace(connectors=SimpleNamespace(eia_api_key=None))
    with respx.mock:
        respx.get(GAS_URL).mock(return_value=httpx.Response(200, json=_GAS_DATA))
        import energex.core.connectors.eia as eia_mod

        orig = eia_mod.get_settings
        eia_mod.get_settings = lambda: fake
        try:
            with pytest.raises(ConfigurationError):
                EiaGasStorageConnector().fetch(date(2026, 6, 5), date(2026, 6, 12))
        finally:
            eia_mod.get_settings = orig


@respx.mock
def test_fetch_retries_transient_failure():
    calls = {"n": 0}

    def _flaky(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("transient")
        return httpx.Response(200, json=_GAS_DATA)

    respx.get(GAS_URL).mock(side_effect=_flaky)
    frame = (
        EiaGasStorageConnector(api_key="TESTKEY", retries=3, timeout=5)
        .fetch(date(2026, 6, 5), date(2026, 6, 12))
        .frame
    )
    assert calls["n"] == 2  # one retry then success
    assert len(frame) == 5


@respx.mock
def test_empty_response_yields_empty_typed_frame():
    respx.get(GAS_URL).mock(
        return_value=httpx.Response(200, json={"response": {"total": 0, "data": []}})
    )
    frame = (
        EiaGasStorageConnector(api_key="TESTKEY").fetch(date(2026, 6, 5), date(2026, 6, 12)).frame
    )
    assert frame.empty
    assert list(frame.columns) == ["instrument_id", "valid_time", "value"]
    assert str(frame["valid_time"].dtype) == "datetime64[ns, UTC]"
