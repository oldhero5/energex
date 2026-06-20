"""Offline respx tests for the ERCOT connectors (token mint + report shaping)."""

from __future__ import annotations

from datetime import date

import httpx
import pytest
import respx

from energex.core import quality, schemas
from energex.core.connectors.ercot import ErcotSppConnector
from energex.core.exceptions import ConfigurationError

TOKEN_URL = "https://ercotb2c.b2clogin.com/token"  # set to the real ROPC URL in impl
SPP_URL = "https://api.ercot.com/api/public-reports/spp"  # set to the real report path

_TOKEN = {"access_token": "tok123", "token_type": "Bearer", "expires_in": 3600}
_SPP_PAGE = {
    "data": [
        {"deliveryHour": "2026-06-18T10:00:00", "settlementPoint": "HB_HOUSTON", "price": "42.5"},
        {"deliveryHour": "2026-06-18T11:00:00", "settlementPoint": "HB_HOUSTON", "price": "38.9"},
    ]
}


@respx.mock
def test_spp_connector_mints_token_and_shapes():
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json=_TOKEN))
    respx.get(SPP_URL).mock(return_value=httpx.Response(200, json=_SPP_PAGE))
    conn = ErcotSppConnector(
        username="u",
        password="p",
        subscription_key="s",
        token_url=TOKEN_URL,
        base_url="https://api.ercot.com/api/public-reports",
    )
    result = conn.fetch(date(2026, 6, 18), date(2026, 6, 19))
    assert set(result.frame["instrument_id"]) == {"ERCOT.SPP.HB_HOUSTON"}
    assert result.complete_over_range is False
    quality.validate(result.frame, schemas.ERCOT_SPP, as_of=result.fetched_at)


def test_spp_connector_fails_fast_without_creds(monkeypatch):
    monkeypatch.delenv("ERCOT_USERNAME", raising=False)
    monkeypatch.delenv("ERCOT_PASSWORD", raising=False)
    with pytest.raises(ConfigurationError, match="ERCOT"):
        ErcotSppConnector().fetch(date(2026, 6, 18), date(2026, 6, 19))
