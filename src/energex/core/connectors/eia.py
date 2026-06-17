"""EIA v2 weekly fundamentals connectors: gas storage + petroleum status -> FetchResult.

EIA's open-data v2 API (https://api.eia.gov/v2) serves weekly energy fundamentals. Two
routes are frozen here (phase-0 findings §1; codes pulled live from the EIA facet
endpoints, never invented):

  - ``natural-gas/stor/wkly`` — Lower-48 working gas in underground storage.
    facets ``duoarea=R48``, ``process=SWO``, ``product=EPG0`` -> series
    ``NW2_EPG0_SWO_R48_BCF`` (Billion Cubic Feet) -> instrument ``EIA.NG.STORAGE.LOWER48``.
  - ``petroleum/stoc/wstk`` — U.S. crude oil ending stocks EXCLUDING SPR.
    facets ``product=EPC0``, ``process=SAX``, ``duoarea=NUS`` -> series ``WCESTUS1``
    (thousand barrels) -> instrument ``EIA.PET.CRUDE.STOCKS``.

EIA has NO vintage/as_of parameter and revises prior weeks INLINE, so every fetch widens
its window back by ``REVISION_LOOKBACK`` (>=5 weeks) to re-carry EIA's revisions; the asset
commits ``bitemporal_merge`` (read-modify-write by ``valid_time``). ``valid_time`` is the
week's ``period`` at 00:00 UTC; ``value`` is the numeric reading. ``complete_over_range``
is False — a revision window is not the full as-known series. The ``api_key`` comes from
``core.config`` (never hardcoded). Network calls go through tenacity retry over httpx.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx
import pandas as pd
from tenacity import retry, stop_after_attempt, wait_exponential

from energex.core.config import get_settings
from energex.core.connectors.base import FetchResult
from energex.core.exceptions import ConfigurationError

logger = logging.getLogger(__name__)

_SOURCE = "eia"
_BASE_URL = "https://api.eia.gov/v2"
# EIA revises prior weeks inline; widen every pull this far back so it re-carries the
# inline revisions (spec §5.4: EIA >= 5 weeks). Six weeks gives a one-week safety margin.
REVISION_LOOKBACK = timedelta(weeks=6)
# EIA caps page length at 5000; one weekly series over the lookback is a handful of rows.
_PAGE_LENGTH = 5000

_FRAME_COLS = ["instrument_id", "valid_time", "value"]


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "instrument_id": pd.Series(dtype="object"),
            "valid_time": pd.Series(dtype="datetime64[ns, UTC]"),
            "value": pd.Series(dtype="float64"),
        }
    )


class _EiaWeeklyConnector:
    """Shared EIA v2 weekly single-series connector (one instrument per route/facets)."""

    source = _SOURCE

    # Set by subclasses.
    route: str
    instrument_id: str
    facets: dict[str, str]

    def __init__(
        self,
        *,
        api_key: str | None = None,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
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

    def fetch(self, window_start: date, window_end: date) -> FetchResult:
        fetched_at = datetime.now(timezone.utc)
        # Widen back >=5 weeks so the pull re-carries EIA's inline revisions.
        start = window_start - REVISION_LOOKBACK
        params: dict[str, Any] = {
            "api_key": self._key(),
            "frequency": "weekly",
            "data[0]": "value",
            "start": start.isoformat(),
            "end": window_end.isoformat(),
            "sort[0][column]": "period",
            "sort[0][direction]": "desc",
            "length": _PAGE_LENGTH,
        }
        for field, value in self.facets.items():
            params[f"facets[{field}][]"] = value

        url = f"{self._base_url}/{self.route}/data/"
        owns_client = self._client is None
        client = httpx.Client(timeout=self._timeout) if owns_client else self._client
        try:
            payload = self._get(client, url, params)
        finally:
            if owns_client:
                client.close()

        rows = payload.get("response", {}).get("data", [])
        frame = self._shape(rows)
        logger.info("EIA %s: %d weekly rows for %s", self.route, len(frame), self.instrument_id)
        # Provenance URL with the key redacted (never leak the secret into metadata).
        source_url = str(httpx.Request("GET", url, params={**params, "api_key": "REDACTED"}).url)
        return FetchResult(
            frame=frame,
            source=self.source,
            fetched_at=fetched_at,
            source_url=source_url,
            complete_over_range=False,  # a revision window, not the full as-known series
        )

    def _shape(self, rows: list[dict]) -> pd.DataFrame:
        """EIA data rows -> canonical (instrument_id, tz-aware-UTC valid_time, value)."""
        if not rows:
            return _empty_frame()
        df = pd.DataFrame(rows)
        out = pd.DataFrame(
            {
                "instrument_id": self.instrument_id,
                "valid_time": pd.to_datetime(df["period"], utc=True),
                "value": pd.to_numeric(df["value"], errors="coerce").astype("float64"),
            }
        )
        out = out.dropna(subset=["value"])  # EIA emits null for not-yet-released weeks
        out = out.drop_duplicates(subset=["valid_time"], keep="first")
        out = out.sort_values("valid_time").reset_index(drop=True)
        return out[_FRAME_COLS]

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


class EiaGasStorageConnector(_EiaWeeklyConnector):
    """Lower-48 weekly working gas in underground storage (BCF) -> EIA.NG.STORAGE.LOWER48."""

    route = "natural-gas/stor/wkly"
    instrument_id = "EIA.NG.STORAGE.LOWER48"
    facets = {"duoarea": "R48", "process": "SWO", "product": "EPG0"}


class EiaPetroleumStatusConnector(_EiaWeeklyConnector):
    """U.S. weekly crude oil ending stocks excluding SPR (thousand bbl) -> EIA.PET.CRUDE.STOCKS."""

    route = "petroleum/stoc/wstk"
    instrument_id = "EIA.PET.CRUDE.STOCKS"
    facets = {"product": "EPC0", "process": "SAX", "duoarea": "NUS"}
