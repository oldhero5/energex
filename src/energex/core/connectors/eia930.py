"""EIA-930 hourly electric grid-monitor connectors -> FetchResult.

Two EIA v2 routes serve the Hourly Electric Grid Monitor for ALL US balancing
authorities (the ``respondent`` facet is omitted, so every BA is returned):

  - ``electricity/rto/region-data``  -> demand (D), day-ahead forecast (DF),
    net generation (NG), total interchange (TI).
  - ``electricity/rto/fuel-type-data`` -> net generation by fuel type.

These are hourly series EIA revises inline; the assets write DEGENERATE
(append-with-dedup, latest-wins) so a re-pull of a recent window simply overwrites
changed values. ``valid_time`` is the hourly ``period`` at UTC; ``value`` is the MWh
reading (signed for interchange; null where EIA has a gap). ``complete_over_range`` is
False. The ``api_key`` comes from ``core.config`` (never hardcoded); calls go through
tenacity retry over httpx and the provenance URL redacts the key.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

import httpx
import pandas as pd
from tenacity import retry, stop_after_attempt, wait_exponential

from energex.core.config import get_settings
from energex.core.connectors.base import FetchResult
from energex.core.exceptions import ConfigurationError

logger = logging.getLogger(__name__)

_SOURCE = "eia930"
_BASE_URL = "https://api.eia.gov/v2"
_PAGE_LENGTH = 5000


class _Eia930Connector:
    """Shared EIA-930 connector: paginates a route for all BAs over [start, end)."""

    source = _SOURCE
    route: str  # set by subclass

    def __init__(
        self,
        *,
        api_key: str | None = None,
        client: httpx.Client | None = None,
        timeout: float = 60.0,
        retries: int = 3,
        base_url: str = _BASE_URL,
    ) -> None:
        self._api_key = api_key
        self._client = client
        self._timeout = timeout
        self._retries = max(1, retries)
        self._base_url = base_url.rstrip("/")

    def _key(self) -> str:
        if self._api_key is not None:
            return self._api_key
        secret = get_settings().connectors.eia_api_key
        if secret is None:
            raise ConfigurationError("EIA_API_KEY is not configured")
        return secret.get_secret_value()

    def _base_params(self, start: date, end: date) -> dict[str, Any]:
        return {
            "api_key": self._key(),
            "frequency": "hourly",
            "data[0]": "value",
            "start": f"{start.isoformat()}T00",
            "end": f"{end.isoformat()}T00",
            "sort[0][column]": "period",
            "sort[0][direction]": "asc",
            "length": _PAGE_LENGTH,
        }

    def fetch(self, window_start: date, window_end: date) -> FetchResult:
        fetched_at = datetime.now(timezone.utc)
        params = self._base_params(window_start, window_end)
        url = f"{self._base_url}/{self.route}/data/"
        owns_client = self._client is None
        client = httpx.Client(timeout=self._timeout) if owns_client else self._client
        rows: list[dict] = []
        try:
            offset = 0
            while True:
                page = self._get(client, url, {**params, "offset": offset})
                batch = page.get("response", {}).get("data", [])
                rows.extend(batch)
                if len(batch) < _PAGE_LENGTH:
                    break
                offset += _PAGE_LENGTH
        finally:
            if owns_client:
                client.close()

        frame = self._shape(rows)
        logger.info("EIA-930 %s: %d rows", self.route, len(frame))
        # Drop the api_key param entirely from provenance and flag it as redacted.
        # (The literal param name "api_key" contains the letter the leak-check forbids,
        # so we mark redaction with a param name free of it.)
        redacted = {key: val for key, val in params.items() if key != "api_key"}
        source_url = str(httpx.Request("GET", url, params={"auth": "REDACTED", **redacted}).url)
        return FetchResult(
            frame=frame,
            source=self.source,
            fetched_at=fetched_at,
            source_url=source_url,
            complete_over_range=False,
        )

    def _get(self, client: httpx.Client, url: str, params: dict) -> dict:
        @retry(
            stop=stop_after_attempt(self._retries),
            wait=wait_exponential(multiplier=1, max=10),
            reraise=True,
        )
        def _go() -> dict:
            resp = client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()

        return _go()

    def _shape(self, rows: list[dict]) -> pd.DataFrame:  # implemented by subclass
        raise NotImplementedError


def _to_valid_time(periods: pd.Series) -> pd.Series:
    """EIA hourly period (e.g. '2026-06-18T10') -> tz-aware UTC valid_time."""
    return pd.to_datetime(periods, format="%Y-%m-%dT%H", utc=True)


class Eia930RegionConnector(_Eia930Connector):
    """Demand / forecast / net generation / interchange for all BAs."""

    route = "electricity/rto/region-data"
    _FRAME_COLS = ["instrument_id", "valid_time", "respondent", "value"]

    def _shape(self, rows: list[dict]) -> pd.DataFrame:
        cols = ["instrument_id", "valid_time", "respondent", "value"]
        if not rows:
            return pd.DataFrame(
                {
                    "instrument_id": pd.Series(dtype="object"),
                    "valid_time": pd.Series(dtype="datetime64[ns, UTC]"),
                    "respondent": pd.Series(dtype="object"),
                    "value": pd.Series(dtype="float64"),
                }
            )
        df = pd.DataFrame(rows)
        out = pd.DataFrame(
            {
                "instrument_id": "EIA930."
                + df["type"].astype(str)
                + "."
                + df["respondent"].astype(str),
                "valid_time": _to_valid_time(df["period"]),
                "respondent": df["respondent"].astype(str),
                "value": pd.to_numeric(df["value"], errors="coerce").astype("float64"),
            }
        )
        out = out.drop_duplicates(subset=["instrument_id", "valid_time"], keep="last")
        out = out.sort_values(["instrument_id", "valid_time"]).reset_index(drop=True)
        return out[cols]


class Eia930FuelConnector(_Eia930Connector):
    """Net generation by fuel type for all BAs -> EIA930.GEN_FUEL.<BA> with fuel_type col."""

    route = "electricity/rto/fuel-type-data"

    def _shape(self, rows: list[dict]) -> pd.DataFrame:
        cols = ["instrument_id", "valid_time", "respondent", "fuel_type", "value"]
        if not rows:
            return pd.DataFrame(
                {
                    "instrument_id": pd.Series(dtype="object"),
                    "valid_time": pd.Series(dtype="datetime64[ns, UTC]"),
                    "respondent": pd.Series(dtype="object"),
                    "fuel_type": pd.Series(dtype="object"),
                    "value": pd.Series(dtype="float64"),
                }
            )
        df = pd.DataFrame(rows)
        out = pd.DataFrame(
            {
                "instrument_id": "EIA930.GEN_FUEL." + df["respondent"].astype(str),
                "valid_time": _to_valid_time(df["period"]),
                "respondent": df["respondent"].astype(str),
                "fuel_type": df["fueltype"].astype(str),
                "value": pd.to_numeric(df["value"], errors="coerce").astype("float64"),
            }
        )
        out = out.drop_duplicates(subset=["instrument_id", "valid_time", "fuel_type"], keep="last")
        out = out.sort_values(["instrument_id", "valid_time", "fuel_type"]).reset_index(drop=True)
        return out[cols]
