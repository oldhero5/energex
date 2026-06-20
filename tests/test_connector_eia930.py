"""Offline respx tests for the EIA-930 hourly grid-monitor connectors."""

from __future__ import annotations

from datetime import date

import httpx
import pytest
import respx

from energex.core import quality, schemas
from energex.core.connectors.base import FetchResult
from energex.core.connectors.eia930 import Eia930FuelConnector, Eia930RegionConnector

REGION_URL = "https://api.eia.gov/v2/electricity/rto/region-data/data/"
FUEL_URL = "https://api.eia.gov/v2/electricity/rto/fuel-type-data/data/"

_REGION_PAGE = {
    "response": {
        "total": 3,
        "data": [
            {"period": "2026-06-18T10", "respondent": "ERCO", "type": "D", "value": "56000"},
            {"period": "2026-06-18T10", "respondent": "ERCO", "type": "DF", "value": "55000"},
            {"period": "2026-06-18T10", "respondent": "CISO", "type": "TI", "value": "-1200"},
        ],
    }
}
_FUEL_PAGE = {
    "response": {
        "total": 2,
        "data": [
            {"period": "2026-06-18T10", "respondent": "ERCO", "fueltype": "NG", "value": "30000"},
            {"period": "2026-06-18T10", "respondent": "ERCO", "fueltype": "WND", "value": "12000"},
        ],
    }
}
_EMPTY = {"response": {"total": 0, "data": []}}


@respx.mock
def test_region_connector_shapes_all_types():
    # First call returns the page; second (offset) returns empty to end pagination.
    respx.get(REGION_URL).mock(
        side_effect=[httpx.Response(200, json=_REGION_PAGE), httpx.Response(200, json=_EMPTY)]
    )
    result = Eia930RegionConnector(api_key="k").fetch(date(2026, 6, 18), date(2026, 6, 19))
    assert isinstance(result, FetchResult)
    ids = set(result.frame["instrument_id"])
    assert ids == {"EIA930.D.ERCO", "EIA930.DF.ERCO", "EIA930.TI.CISO"}
    assert result.complete_over_range is False
    assert "REDACTED" in result.source_url  # key never leaked
    assert "k" not in result.source_url


@respx.mock
def test_region_frame_passes_gate():
    respx.get(REGION_URL).mock(
        side_effect=[httpx.Response(200, json=_REGION_PAGE), httpx.Response(200, json=_EMPTY)]
    )
    result = Eia930RegionConnector(api_key="k").fetch(date(2026, 6, 18), date(2026, 6, 19))
    quality.validate(result.frame, schemas.POWER_REGION, as_of=result.fetched_at)


@respx.mock
def test_fuel_connector_carries_fuel_type():
    respx.get(FUEL_URL).mock(
        side_effect=[httpx.Response(200, json=_FUEL_PAGE), httpx.Response(200, json=_EMPTY)]
    )
    result = Eia930FuelConnector(api_key="k").fetch(date(2026, 6, 18), date(2026, 6, 19))
    assert set(result.frame["instrument_id"]) == {"EIA930.GEN_FUEL.ERCO"}
    assert set(result.frame["fuel_type"]) == {"NG", "WND"}
    quality.validate(result.frame, schemas.POWER_GEN_BY_FUEL, as_of=result.fetched_at)


def test_region_requires_api_key(monkeypatch):
    from energex.core.exceptions import ConfigurationError

    monkeypatch.delenv("EIA_API_KEY", raising=False)
    with pytest.raises(ConfigurationError):
        Eia930RegionConnector().fetch(date(2026, 6, 18), date(2026, 6, 19))
