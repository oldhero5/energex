"""Offline respx tests for the ERCOT connectors (B2C token mint + report shaping)."""

from __future__ import annotations

from datetime import date

import httpx
import pandas as pd
import pytest
import respx

from energex.core import quality, schemas
from energex.core.connectors.base import FetchResult
from energex.core.connectors.ercot import (
    ErcotRtSppConnector,
    _cpt_hour_ending_to_utc,
)
from energex.core.exceptions import ConfigurationError, DataFetchError

TOKEN_URL = (
    "https://ercotb2c.b2clogin.com/ercotb2c.onmicrosoft.com/"
    "B2C_1_PUBAPI-ROPC-FLOW/oauth2/v2.0/token"
)
BASE = "https://api.ercot.com/api/public-reports"
RT_URL = f"{BASE}/np6-905-cd/spp_node_zone_hub"

_TOKEN = {"id_token": "idtok", "access_token": "acctok", "token_type": "Bearer", "expires_in": 3600}
_TODAY = date.today().isoformat()
_RT_FIELDS = [
    "deliveryDate",
    "deliveryHour",
    "deliveryInterval",
    "settlementPoint",
    "settlementPointType",
    "settlementPointPrice",
    "DSTFlag",
]


def _envelope(fields, rows, *, total_pages=1, current_page=1):
    return {
        "data": rows,
        "fields": [{"name": n, "dataType": "VARCHAR"} for n in fields],
        "_meta": {
            "totalRecords": len(rows),
            "pageSize": 100000,
            "totalPages": total_pages,
            "currentPage": current_page,
        },
    }


def _kwargs():
    return {
        "username": "u",
        "password": "p",
        "subscription_key": "subkey-123",
        "token_url": TOKEN_URL,
        "base_url": BASE,
    }


@respx.mock
def test_rt_spp_mints_id_token_and_shapes():
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json=_TOKEN))
    hu = _envelope(
        _RT_FIELDS,
        [
            [_TODAY, 1, 1, "HB_HOUSTON", "HU", 30.31, False],
            [_TODAY, 1, 2, "HB_HOUSTON", "HU", 31.00, False],
        ],
    )
    lz = _envelope(_RT_FIELDS, [[_TODAY, 1, 1, "LZ_NORTH", "LZ", 29.50, False]])
    respx.get(RT_URL).mock(side_effect=[httpx.Response(200, json=hu), httpx.Response(200, json=lz)])

    result = ErcotRtSppConnector(**_kwargs()).fetch(date.today(), date.today())

    assert isinstance(result, FetchResult)
    assert set(result.frame["instrument_id"]) == {"ERCOT.SPP.HB_HOUSTON", "ERCOT.SPP.LZ_NORTH"}
    assert result.complete_over_range is False
    # Uses the ID token (not the access token) as the Bearer.
    assert respx.calls.last.request.headers["Authorization"] == "Bearer idtok"
    assert respx.calls.last.request.headers["Ocp-Apim-Subscription-Key"] == "subkey-123"
    # Provenance leaks no secret.
    assert "idtok" not in result.source_url and "subkey-123" not in result.source_url
    quality.validate(result.frame, schemas.ERCOT_SPP, as_of=result.fetched_at)


@respx.mock
def test_rt_spp_paginates_all_pages():
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json=_TOKEN))
    hu1 = _envelope(
        _RT_FIELDS, [[_TODAY, 1, 1, "HB_HOUSTON", "HU", 30.0, False]], total_pages=2, current_page=1
    )
    hu2 = _envelope(
        _RT_FIELDS, [[_TODAY, 2, 1, "HB_NORTH", "HU", 31.0, False]], total_pages=2, current_page=2
    )
    lz1 = _envelope(_RT_FIELDS, [[_TODAY, 1, 1, "LZ_WEST", "LZ", 28.0, False]])
    respx.get(RT_URL).mock(
        side_effect=[
            httpx.Response(200, json=hu1),
            httpx.Response(200, json=hu2),
            httpx.Response(200, json=lz1),
        ]
    )
    result = ErcotRtSppConnector(**_kwargs()).fetch(date.today(), date.today())
    assert set(result.frame["settlement_point"]) == {"HB_HOUSTON", "HB_NORTH", "LZ_WEST"}
    assert respx.calls.call_count == 4  # token + HU(2 pages) + LZ(1 page)


@respx.mock
def test_rt_spp_drops_non_hub_loadzone_points():
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json=_TOKEN))
    page = _envelope(
        _RT_FIELDS,
        [
            [_TODAY, 1, 1, "HB_SOUTH", "HU", 30.0, False],
            [_TODAY, 1, 1, "XYZ_RESOURCE_RN", "RN", 45.0, False],
        ],
    )
    respx.get(RT_URL).mock(return_value=httpx.Response(200, json=page))
    result = ErcotRtSppConnector(**_kwargs()).fetch(date.today(), date.today())
    assert set(result.frame["settlement_point"]) == {"HB_SOUTH"}


def test_cpt_hour_ending_to_utc_summer_and_winter():
    days = pd.Series(["2026-06-25", "2026-01-15"])
    end_minutes = pd.Series([60, 60])  # hour ending 01:00
    dst = pd.Series([False, False])
    out = _cpt_hour_ending_to_utc(days, end_minutes, dst, 60)
    # CDT (summer) = UTC-5 -> 06:00Z; CST (winter) = UTC-6 -> 07:00Z.
    assert out.iloc[0] == pd.Timestamp("2026-06-25T06:00:00Z")
    assert out.iloc[1] == pd.Timestamp("2026-01-15T07:00:00Z")


def test_cpt_hour_ending_to_utc_fall_back_keeps_both_repeats_distinct():
    # 2026-11-01 fall-back: the 01:00-02:00 (hour-ending 02:00) hour repeats. ERCOT marks the
    # daylight repeat DSTFlag=True (CDT, ends 07:00Z) and the standard repeat False (CST, 08:00Z).
    days = pd.Series(["2026-11-01", "2026-11-01"])
    end_minutes = pd.Series([120, 120])  # hour ending 02:00
    dst = pd.Series([True, False])
    out = _cpt_hour_ending_to_utc(days, end_minutes, dst, 60)
    assert out.iloc[0] == pd.Timestamp("2026-11-01T07:00:00Z")  # CDT repeat
    assert out.iloc[1] == pd.Timestamp("2026-11-01T08:00:00Z")  # CST repeat
    assert out.iloc[0] != out.iloc[1]  # the two settlement hours must not collapse


def test_cpt_hour_ending_to_utc_spring_forward():
    # 2026-03-08 spring-forward: 02:00-03:00 CST is skipped (ERCOT omits hour-ending 03:00).
    # Hour-ending 02:00 (still CST, ends at the 02:00 instant that jumps to 03:00 CDT) and the
    # following CDT hours must convert without collapsing onto one instant.
    days = pd.Series(["2026-03-08", "2026-03-08"])
    end_minutes = pd.Series([120, 240])  # HE 02:00 (CST) and HE 04:00 (CDT)
    dst = pd.Series([False, False])
    out = _cpt_hour_ending_to_utc(days, end_minutes, dst, 60)
    # HE 02:00: begins 01:00 CST = 07:00Z, +1h = 08:00Z; HE 04:00: begins 03:00 CDT = 08:00Z,
    # +1h = 09:00Z. Distinct.
    assert out.iloc[0] == pd.Timestamp("2026-03-08T08:00:00Z")
    assert out.iloc[1] == pd.Timestamp("2026-03-08T09:00:00Z")


@respx.mock
def test_dam_spp_fall_back_day_preserves_both_repeated_hours():
    from energex.core.connectors.ercot import ErcotDamSppConnector

    respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json=_TOKEN))
    page = _envelope(
        _DAM_FIELDS,
        [
            ["2026-11-01", "02:00", "HB_HOUSTON", 20.0, True],  # CDT repeat
            ["2026-11-01", "02:00", "HB_HOUSTON", 21.0, False],  # CST repeat
        ],
    )
    respx.get(DAM_URL).mock(return_value=httpx.Response(200, json=page))
    result = ErcotDamSppConnector(**_kwargs()).fetch(date(2026, 11, 1), date(2026, 11, 1))
    # Both physically distinct settlement hours survive (the dedup must not collapse them).
    assert len(result.frame) == 2
    assert result.frame["valid_time"].nunique() == 2
    assert set(result.frame["price"]) == {20.0, 21.0}


@respx.mock
def test_token_mint_does_not_retry_on_4xx():
    # A 401 (bad creds) must fail fast, not hammer the Azure AD B2C auth endpoint with retries.
    route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(401, json={"error": "invalid_grant"})
    )
    with pytest.raises(httpx.HTTPStatusError):
        ErcotRtSppConnector(**_kwargs()).fetch(date.today(), date.today())
    assert route.call_count == 1  # exactly one attempt, no retries on 4xx


@respx.mock
def test_get_pages_raises_when_data_has_no_fields_schema():
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json=_TOKEN))
    bad = {  # data rows but no 'fields' column schema -> would silently vanish
        "data": [[_TODAY, 1, 1, "HB_HOUSTON", "HU", 30.0, False]],
        "_meta": {"totalPages": 1, "currentPage": 1},
    }
    respx.get(RT_URL).mock(return_value=httpx.Response(200, json=bad))
    with pytest.raises(DataFetchError, match="fields"):
        ErcotRtSppConnector(**_kwargs()).fetch(date.today(), date.today())


@respx.mock
def test_get_pages_handles_missing_meta_without_truncation():
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json=_TOKEN))
    # No _meta envelope at all: a short page must be returned as-is (not dropped, not looped).
    page = {
        "data": [[_TODAY, 1, 1, "HB_HOUSTON", "HU", 30.0, False]],
        "fields": [{"name": n} for n in _RT_FIELDS],
    }
    respx.get(RT_URL).mock(return_value=httpx.Response(200, json=page))
    result = ErcotRtSppConnector(**_kwargs()).fetch(date.today(), date.today())
    assert set(result.frame["settlement_point"]) == {"HB_HOUSTON"}


def test_rt_spp_fails_fast_without_creds(monkeypatch):
    for var in (
        "ERCOT_USERNAME",
        "ERCOT_PASSWORD",
        "ERCOT_API_KEY_PRIMARY",
        "ERCOT_SUBSCRIPTION_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(ConfigurationError, match="ERCOT"):
        ErcotRtSppConnector().fetch(date.today(), date.today())


DAM_URL = f"{BASE}/np4-190-cd/dam_stlmnt_pnt_prices"
_DAM_FIELDS = ["deliveryDate", "hourEnding", "settlementPoint", "settlementPointPrice", "DSTFlag"]


@respx.mock
def test_dam_spp_shapes_and_filters():
    from energex.core.connectors.ercot import ErcotDamSppConnector

    respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json=_TOKEN))
    page = _envelope(
        _DAM_FIELDS,
        [
            [_TODAY, "01:00", "HB_HOUSTON", 27.47, False],
            [_TODAY, "02:00", "HB_HOUSTON", 26.00, False],
            [_TODAY, "01:00", "XYZ_RESOURCE_RN", 30.00, False],  # dropped (not hub/LZ)
        ],
    )
    respx.get(DAM_URL).mock(return_value=httpx.Response(200, json=page))
    result = ErcotDamSppConnector(**_kwargs()).fetch(date.today(), date.today())
    assert set(result.frame["instrument_id"]) == {"ERCOT.DASPP.HB_HOUSTON"}
    assert len(result.frame) == 2
    assert respx.calls.call_count == 2  # token + single (no per-type) page
    quality.validate(result.frame, schemas.ERCOT_SPP, as_of=result.fetched_at)


LOAD_URL = f"{BASE}/np6-345-cd/act_sys_load_by_wzn"
_LOAD_FIELDS = [
    "operatingDay",
    "hourEnding",
    "coast",
    "east",
    "farWest",
    "north",
    "northC",
    "southern",
    "southC",
    "west",
    "total",
    "DSTFlag",
]


@respx.mock
def test_load_shapes_total_only():
    from energex.core.connectors.ercot import ErcotLoadConnector

    respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json=_TOKEN))
    page = _envelope(
        _LOAD_FIELDS,
        [
            [
                _TODAY,
                "01:00",
                15796.82,
                2014.35,
                7595.58,
                1879.89,
                17819.16,
                5016.6,
                9775.83,
                1900.13,
                61798.36,
                False,
            ],
            [
                _TODAY,
                "02:00",
                15159.63,
                1918.33,
                7656.68,
                1763.04,
                16733.24,
                4778.72,
                9164.31,
                1828.51,
                59002.46,
                False,
            ],
        ],
    )
    route = respx.get(LOAD_URL).mock(return_value=httpx.Response(200, json=page))
    result = ErcotLoadConnector(**_kwargs()).fetch(date.today(), date.today())
    assert set(result.frame["instrument_id"]) == {"ERCOT.LOAD.ERCOT"}
    assert result.frame["value"].tolist() == [61798.36, 59002.46]
    # Uses operatingDay* date params (not deliveryDate*).
    assert "operatingDayFrom" in route.calls.last.request.url.params
    quality.validate(result.frame, schemas.ERCOT_LOAD, as_of=result.fetched_at)
