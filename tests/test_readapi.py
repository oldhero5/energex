"""S2 read API: offline (LMDB) TestClient coverage of the frontend seam.

Seeds an LMDB-backed Arctic via ``energex.core.storage`` (no MinIO), points the app at
it through ``ENERGEX_ARCTIC_URI``, and exercises healthz / symbols / series (incl. the
as_of point-in-time behavior and the vintage_reconstructed passthrough) / curve.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from energex.core import storage
from energex.service.readapi import create_app

D1 = datetime(2024, 1, 1, tzinfo=timezone.utc)
D2 = datetime(2024, 1, 8, tzinfo=timezone.utc)
D3 = datetime(2024, 1, 15, tzinfo=timezone.utc)
A1 = datetime(2024, 1, 16, 15, 30, tzinfo=timezone.utc)
A2 = datetime(2024, 1, 23, 15, 30, tzinfo=timezone.utc)


def _frame(instrument_id, times, values, contract_month=None):
    data = {"instrument_id": instrument_id, "valid_time": list(times), "Close": list(values)}
    if contract_month is not None:
        data["ContractMonth"] = [contract_month] * len(times)
    return pd.DataFrame(data)


@pytest.fixture
def client(arctic_store, arctic_uri, monkeypatch):
    monkeypatch.setenv("ENERGEX_ARCTIC_URI", arctic_uri)
    lib = arctic_store.create_library("prices.futures")
    # A1: a RECONSTRUCTED baseline (the honesty boundary) covering D1..D3.
    storage.commit_vintage(
        lib,
        "CL_CLF26",
        _frame("CME.CL.CLF26", [D1, D2, D3], [10.0, 11.0, 12.0]),
        as_of=A1,
        source="yf",
        source_url="u",
        fetched_at=A1,
        mode="bitemporal_merge",
        reconstructed=True,
    )
    # A2: a TRUE forward vintage revising only the [D2, D3] window (D1 baseline survives).
    storage.commit_vintage(
        lib,
        "CL_CLF26",
        _frame("CME.CL.CLF26", [D2, D3], [21.0, 22.0]),
        as_of=A2,
        source="yf",
        source_url="u",
        fetched_at=A2,
        mode="bitemporal_merge",
        reconstructed=False,
    )
    # Second contract so read_curve("crude") assembles a multi-contract curve.
    storage.commit_vintage(
        lib,
        "CL_CLG26",
        _frame("CME.CL.CLG26", [D3], [19.5], contract_month=date(2026, 2, 1)),
        as_of=A2,
        source="yf",
        source_url="u",
        fetched_at=A2,
        mode="bitemporal_merge",
    )
    with TestClient(create_app()) as c:
        yield c


def test_healthz(client):
    body = client.get("/healthz").json()
    assert body["status"] == "ok"
    assert "prices.futures" in body["libraries"]
    assert body["latest_as_of"] is not None  # computed from the tiny vintage sidecars


def test_libraries(client):
    assert "prices.futures" in client.get("/libraries").json()


def test_symbols_excludes_vintage_sidecars(client):
    syms = client.get("/symbols", params={"library": "prices.futures"}).json()
    assert sorted(syms) == ["CL_CLF26", "CL_CLG26"]
    assert not any(s.endswith("__vintages") for s in syms)


def test_symbols_unknown_library_404(client):
    assert client.get("/symbols", params={"library": "nope"}).status_code == 404


def test_series_pointintime_and_reconstructed_flag(client):
    # as_of=A1 -> the reconstructed baseline: every row flagged reconstructed.
    pre = client.get(
        "/series",
        params={"library": "prices.futures", "symbol": "CL_CLF26", "as_of": A1.isoformat()},
    ).json()
    assert {row["Close"] for row in pre} == {10.0, 11.0, 12.0}
    assert all(row["vintage_reconstructed"] is True for row in pre)

    # default (latest committed vintage) -> revised rows are TRUE vintages (False),
    # while the untouched D1 baseline keeps its reconstructed=True provenance.
    latest = client.get(
        "/series", params={"library": "prices.futures", "symbol": "CL_CLF26"}
    ).json()
    assert {row["Close"]: row["vintage_reconstructed"] for row in latest} == {
        10.0: True,
        21.0: False,
        22.0: False,
    }


def test_series_date_range(client):
    rows = client.get(
        "/series",
        params={"library": "prices.futures", "symbol": "CL_CLF26", "start": D2.isoformat()},
    ).json()
    assert {row["Close"] for row in rows} == {21.0, 22.0}


def test_series_unknown_symbol_404(client):
    r = client.get("/series", params={"library": "prices.futures", "symbol": "NOPE"})
    assert r.status_code == 404


def test_series_bad_as_of_400(client):
    r = client.get(
        "/series",
        params={"library": "prices.futures", "symbol": "CL_CLF26", "as_of": "not-a-date"},
    )
    assert r.status_code == 400


def test_curve(client):
    rows = client.get("/curve", params={"commodity": "crude", "as_of": A2.isoformat()}).json()
    assert {row["instrument_id"] for row in rows} == {"CME.CL.CLF26", "CME.CL.CLG26"}


def test_curve_unknown_commodity_404(client):
    # An unknown commodity must be a clean 4xx, not a 500 from an uncaught SymbologyError.
    assert client.get("/curve", params={"commodity": "nope"}).status_code == 404


def test_series_row_cap_413(client, monkeypatch):
    monkeypatch.setenv("ENERGEX_SERIES_MAX_ROWS", "1")  # force the cap (fixture has 3 rows)
    full = client.get("/series", params={"library": "prices.futures", "symbol": "CL_CLF26"})
    assert full.status_code == 413
    # an intentionally bounded read (start/end) is exempt from the cap
    bounded = client.get(
        "/series",
        params={"library": "prices.futures", "symbol": "CL_CLF26", "start": D1.isoformat()},
    )
    assert bounded.status_code == 200


def test_api_key_required_when_configured(client, monkeypatch):
    monkeypatch.setenv("ENERGEX_READ_API_KEY", "s3cret")
    assert client.get("/libraries").status_code == 401  # missing key
    assert client.get("/libraries", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/libraries", headers={"X-API-Key": "s3cret"}).status_code == 200
    assert client.get("/healthz").status_code == 200  # healthz stays open for healthchecks
