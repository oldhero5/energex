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
from energex.core.exceptions import ConfigurationError

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
    minutes = pd.Series([60, 60])  # hour ending 01:00
    dst = pd.Series([False, False])
    out = _cpt_hour_ending_to_utc(days, minutes, dst)
    # CDT (summer) = UTC-5 -> 06:00Z; CST (winter) = UTC-6 -> 07:00Z.
    assert out.iloc[0] == pd.Timestamp("2026-06-25T06:00:00Z")
    assert out.iloc[1] == pd.Timestamp("2026-01-15T07:00:00Z")


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
