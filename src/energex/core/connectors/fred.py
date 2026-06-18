"""FRED daily benchmark spot-price connector: WTI / Brent / Henry Hub -> FetchResult.

The St. Louis Fed FRED API (https://api.stlouisfed.org/fred) serves daily benchmark
energy spot prices with a few-business-day publication lag. Three series are pulled
(codes verified live, never invented):

  - ``DCOILWTICO``   WTI crude, Cushing OK ($/bbl)    -> instrument ``FRED.WTI.SPOT``
  - ``DCOILBRENTEU`` Brent crude, Europe ($/bbl)      -> instrument ``FRED.BRENT.SPOT``
  - ``DHHNGSP``      Henry Hub natural gas ($/MMBtu)  -> instrument ``FRED.HENRYHUB.SPOT``

These are final daily spot values (FRED does not vintage them on this endpoint), so the
stream is DEGENERATE: the asset writes append-with-dedup via ``storage.write_bars`` with
as_of = fetched_at = knowledge time. ``valid_time`` is the observation ``date`` at 00:00
UTC; ``value`` is the numeric reading. FRED emits missing observations (holidays/gaps) as
the string ``"."`` — those are dropped before the frame is produced. ``complete_over_range``
is False (a continuous degenerate stream is never the full as-known series). The ``api_key``
comes from ``core.config`` (never hardcoded). Network calls go through tenacity retry over
httpx.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

import httpx
import pandas as pd
from tenacity import retry, stop_after_attempt, wait_exponential

from energex.core.config import get_settings
from energex.core.connectors.base import FetchResult
from energex.core.exceptions import ConfigurationError

logger = logging.getLogger(__name__)

_SOURCE = "fred"
_BASE_URL = "https://api.stlouisfed.org/fred"

# FRED series_id -> instrument_id (codes frozen from a live FRED pull, never invented).
_SERIES: dict[str, str] = {
    "DCOILWTICO": "FRED.WTI.SPOT",
    "DCOILBRENTEU": "FRED.BRENT.SPOT",
    "DHHNGSP": "FRED.HENRYHUB.SPOT",
}

#: instrument_ids this connector produces (consumed by the asset + asset_check).
INSTRUMENT_IDS: list[str] = list(_SERIES.values())

# FRED renders a missing observation (holiday/gap) as this string sentinel.
_MISSING = "."

_FRAME_COLS = ["instrument_id", "valid_time", "value"]


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "instrument_id": pd.Series(dtype="object"),
            "valid_time": pd.Series(dtype="datetime64[ns, UTC]"),
            "value": pd.Series(dtype="float64"),
        }
    )


class FredConnector:
    """Daily WTI/Brent/Henry Hub benchmark spot prices (degenerate stream)."""

    source = _SOURCE

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
        self._endpoint = f"{base_url.rstrip('/')}/series/observations"

    def _key(self) -> str:
        if self._api_key is not None:
            return self._api_key
        secret = get_settings().connectors.fred_api_key
        if secret is None:
            raise ConfigurationError("FRED_API_KEY is not configured")
        return secret.get_secret_value()

    def fetch(self, window_start: date, window_end: date) -> FetchResult:
        fetched_at = datetime.now(timezone.utc)
        key = self._key()
        owns_client = self._client is None
        client = httpx.Client(timeout=self._timeout) if owns_client else self._client
        try:
            frames = [
                self._shape(
                    self._get(
                        client,
                        {
                            "series_id": series_id,
                            "api_key": key,
                            "file_type": "json",
                            "observation_start": window_start.isoformat(),
                            "observation_end": window_end.isoformat(),
                            "sort_order": "asc",
                        },
                    ).get("observations", []),
                    instrument_id,
                )
                for series_id, instrument_id in _SERIES.items()
            ]
        finally:
            if owns_client:
                client.close()

        frame = pd.concat(frames, ignore_index=True) if frames else _empty_frame()
        logger.info("FRED: %d daily spot rows across %s", len(frame), sorted(_SERIES.values()))
        return FetchResult(
            frame=frame[_FRAME_COLS],
            source=self.source,
            fetched_at=fetched_at,
            source_url=self._endpoint,
            complete_over_range=False,  # continuous degenerate stream, not a full series
        )

    def _shape(self, observations: list[dict], instrument_id: str) -> pd.DataFrame:
        """FRED observations -> canonical (instrument_id, tz-aware-UTC valid_time, value)."""
        if not observations:
            return _empty_frame()
        df = pd.DataFrame(observations)
        df = df[df["value"] != _MISSING]  # drop FRED "." holiday/gap markers
        if df.empty:
            return _empty_frame()
        out = pd.DataFrame(
            {
                "instrument_id": instrument_id,
                "valid_time": pd.to_datetime(df["date"], utc=True),
                "value": pd.to_numeric(df["value"], errors="coerce").astype("float64"),
            }
        )
        out = out.dropna(subset=["value"])
        out = out.drop_duplicates(subset=["valid_time"], keep="first")
        out = out.sort_values("valid_time").reset_index(drop=True)
        return out[_FRAME_COLS]

    def _get(self, client: httpx.Client, params: dict) -> dict:
        @retry(
            stop=stop_after_attempt(self._retries),
            wait=wait_exponential(multiplier=1, max=10),
            reraise=True,
        )
        def _go() -> dict:
            resp = client.get(self._endpoint, params=params)
            resp.raise_for_status()
            return resp.json()

        return _go()
