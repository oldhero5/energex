"""ERCOT public-API connectors: settlement point prices, system load, fuel mix.

ERCOT's public API authenticates via OAuth2 ROPC (username + password + subscription
key) to mint a short-lived bearer token, then serves report endpoints. SPPs can be
restated, so the SPP asset commits ``bitemporal_merge``. Credentials come from
``core.config`` (``ERCOT_USERNAME`` / ``ERCOT_PASSWORD`` / ``ERCOT_SUBSCRIPTION_KEY``);
absent creds raise ``ConfigurationError`` (fail-fast -- the schedule stays dormant).

NOTE: the exact report paths and JSON field names are confirmed against ERCOT's API
Explorer when credentials are provisioned; each report isolates that mapping in its own
``_shape`` so only those methods change.
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

_SOURCE = "ercot"
_DEFAULT_BASE = "https://api.ercot.com/api/public-reports"
_DEFAULT_TOKEN_URL = "https://ercotb2c.b2clogin.com/token"  # confirm exact ROPC URL with creds


class _ErcotConnector:
    source = _SOURCE
    report_path: str  # set by subclass

    def __init__(
        self,
        *,
        username: str | None = None,
        password: str | None = None,
        subscription_key: str | None = None,
        client: httpx.Client | None = None,
        timeout: float = 60.0,
        retries: int = 3,
        base_url: str = _DEFAULT_BASE,
        token_url: str = _DEFAULT_TOKEN_URL,
    ) -> None:
        self._username = username
        self._password = password
        self._subscription_key = subscription_key
        self._client = client
        self._timeout = timeout
        self._retries = max(1, retries)
        self._base_url = base_url.rstrip("/")
        self._token_url = token_url

    def _creds(self) -> tuple[str, str, str]:
        cfg = get_settings().connectors
        user = self._username or cfg.ercot_username
        pwd = self._password or (
            cfg.ercot_password.get_secret_value() if cfg.ercot_password else None
        )
        key = self._subscription_key or (
            cfg.ercot_subscription_key.get_secret_value() if cfg.ercot_subscription_key else None
        )
        if not (user and pwd and key):
            raise ConfigurationError(
                "ERCOT credentials absent (need ERCOT_USERNAME, ERCOT_PASSWORD, "
                "ERCOT_SUBSCRIPTION_KEY) -- connector is dormant"
            )
        return user, pwd, key

    def _token(self, client: httpx.Client, user: str, pwd: str) -> str:
        resp = client.post(
            self._token_url,
            data={
                "grant_type": "password",
                "username": user,
                "password": pwd,
                "response_type": "token",
                "scope": "openid",
            },
        )
        resp.raise_for_status()
        return resp.json()["access_token"]

    def fetch(self, window_start: date, window_end: date) -> FetchResult:
        user, pwd, key = self._creds()  # fail-fast before any network call
        fetched_at = datetime.now(timezone.utc)
        owns_client = self._client is None
        client = httpx.Client(timeout=self._timeout) if owns_client else self._client
        try:
            token = self._token(client, user, pwd)
            rows = self._get_report(client, token, key, window_start, window_end)
        finally:
            if owns_client:
                client.close()
        frame = self._shape(rows)
        url = f"{self._base_url}/{self.report_path}"
        logger.info("ERCOT %s: %d rows", self.report_path, len(frame))
        return FetchResult(
            frame=frame,
            source=self.source,
            fetched_at=fetched_at,
            source_url=url,  # no secrets in the path
            complete_over_range=False,
        )

    def _get_report(
        self, client: httpx.Client, token: str, key: str, start: date, end: date
    ) -> list[dict]:
        url = f"{self._base_url}/{self.report_path}"
        headers = {"Authorization": f"Bearer {token}", "Ocp-Apim-Subscription-Key": key}
        params = {"deliveryDateFrom": start.isoformat(), "deliveryDateTo": end.isoformat()}

        @retry(
            stop=stop_after_attempt(self._retries),
            wait=wait_exponential(multiplier=1, max=10),
            reraise=True,
        )
        def _go() -> list[dict]:
            resp = client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            return resp.json().get("data", [])

        return _go()

    def _shape(self, rows: list[dict]) -> pd.DataFrame:
        raise NotImplementedError


class ErcotSppConnector(_ErcotConnector):
    """RT + DA settlement point prices -> ERCOT.SPP.<settlement point>."""

    report_path = "spp"

    def _shape(self, rows: list[dict]) -> pd.DataFrame:
        cols = ["instrument_id", "valid_time", "settlement_point", "price"]
        if not rows:
            return pd.DataFrame(
                {
                    "instrument_id": pd.Series(dtype="object"),
                    "valid_time": pd.Series(dtype="datetime64[ns, UTC]"),
                    "settlement_point": pd.Series(dtype="object"),
                    "price": pd.Series(dtype="float64"),
                }
            )
        df = pd.DataFrame(rows)
        out = pd.DataFrame(
            {
                "instrument_id": "ERCOT.SPP." + df["settlementPoint"].astype(str),
                "valid_time": pd.to_datetime(df["deliveryHour"], utc=True),
                "settlement_point": df["settlementPoint"].astype(str),
                "price": pd.to_numeric(df["price"], errors="coerce").astype("float64"),
            }
        )
        out = out.dropna(subset=["price"])
        out = out.drop_duplicates(subset=["instrument_id", "valid_time"], keep="last")
        out = out.sort_values(["instrument_id", "valid_time"]).reset_index(drop=True)
        return out[cols]
