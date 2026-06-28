"""ERCOT public-API connectors: settlement-point prices (RT + DAM) and system load.

ERCOT's public API authenticates via Azure AD B2C ROPC (username + password + a fixed
public client_id) to mint an ID token, then serves report endpoints gated by an APIM
subscription key. Report responses use an array-of-arrays ``data`` body with a separate
``fields`` schema and a ``_meta`` pagination envelope. All timestamps are Central
Prevailing Time (America/Chicago), hour-ending; we convert to tz-aware UTC.

RT and DAM settlement-point prices and system load can be restated, so their assets commit
``bitemporal_merge``. Credentials come from ``core.config`` (``ERCOT_USERNAME`` /
``ERCOT_PASSWORD`` / ``ERCOT_API_KEY_PRIMARY``); absent creds raise ``ConfigurationError``
(fail-fast -- the connector stays dormant). Only the canonical tradeable settlement points
(trading hubs + load zones) are ingested; resource nodes are dropped.
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

_SOURCE = "ercot"
_BASE_URL = "https://api.ercot.com/api/public-reports"
_TOKEN_URL = (
    "https://ercotb2c.b2clogin.com/ercotb2c.onmicrosoft.com/"
    "B2C_1_PUBAPI-ROPC-FLOW/oauth2/v2.0/token"
)
_CLIENT_ID = "fec253ea-0d06-4272-a5e6-b478baeecd70"
_SCOPE = f"openid {_CLIENT_ID} offline_access"
_PAGE_SIZE = 100_000
_CPT = "America/Chicago"
# Settlement-point types that select trading hubs + load zones server-side (RT SPP).
_SPP_TYPES = ("HU", "LZ")
# Canonical tradeable settlement points (hubs + load zones); resource nodes are dropped.
_SETTLEMENT_POINTS = frozenset(
    {
        "HB_HOUSTON", "HB_NORTH", "HB_PAN", "HB_SOUTH", "HB_WEST",
        "LZ_AEN", "LZ_CPS", "LZ_HOUSTON", "LZ_LCRA", "LZ_NORTH", "LZ_RAYBN", "LZ_SOUTH", "LZ_WEST",
    }
)


def _cpt_hour_ending_to_utc(
    days: pd.Series, minutes: pd.Series, dst_flag: pd.Series
) -> pd.Series:
    """(operating day, minutes-after-midnight hour-ending, DSTFlag) -> tz-aware UTC.

    ``days`` is date-like; ``minutes`` is minutes after local midnight of the interval-/
    hour-ending instant; ``dst_flag`` True marks the DST occurrence of the duplicated
    fall-back hour. Localize to Central Prevailing Time, then convert to UTC.
    """
    naive = pd.to_datetime(days) + pd.to_timedelta(minutes.astype(int), unit="m")
    ambiguous = dst_flag.astype(bool).to_numpy()
    local = naive.dt.tz_localize(_CPT, ambiguous=ambiguous, nonexistent="shift_forward")
    return local.dt.tz_convert("UTC")


def _hour_ending_to_minutes(hour_ending: pd.Series) -> pd.Series:
    """ERCOT hourEnding string ('01:00'..'24:00') -> minutes after midnight (60..1440)."""
    return hour_ending.astype(str).str.split(":").str[0].astype(int) * 60


def _empty_spp() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "instrument_id": pd.Series(dtype="object"),
            "valid_time": pd.Series(dtype="datetime64[ns, UTC]"),
            "settlement_point": pd.Series(dtype="object"),
            "price": pd.Series(dtype="float64"),
        }
    )


def _finalize_spp(prefix: str, raw: pd.DataFrame, valid_time: pd.Series) -> pd.DataFrame:
    cols = ["instrument_id", "valid_time", "settlement_point", "price"]
    sp = raw["settlementPoint"].astype(str)
    out = pd.DataFrame(
        {
            "instrument_id": prefix + sp,
            "valid_time": valid_time,
            "settlement_point": sp,
            "price": pd.to_numeric(raw["settlementPointPrice"], errors="coerce").astype("float64"),
        }
    )
    out = out[out["settlement_point"].isin(_SETTLEMENT_POINTS)]
    out = out.dropna(subset=["price"])
    out = out.drop_duplicates(subset=["instrument_id", "valid_time"], keep="last")
    return out.sort_values(["instrument_id", "valid_time"]).reset_index(drop=True)[cols]


class _ErcotConnector:
    """Shared ERCOT connector: B2C token mint -> paginated report pull -> FetchResult."""

    source = _SOURCE
    report_path: str  # lowercase EMIL path, set by subclass
    _filter_by_type = False  # SPP subclasses filter to hubs+load zones server-side

    def __init__(
        self,
        *,
        username: str | None = None,
        password: str | None = None,
        subscription_key: str | None = None,
        client: httpx.Client | None = None,
        timeout: float = 60.0,
        retries: int = 3,
        base_url: str = _BASE_URL,
        token_url: str = _TOKEN_URL,
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
                "ERCOT_API_KEY_PRIMARY) -- connector is dormant"
            )
        return user, pwd, key

    def _token(self, client: httpx.Client, user: str, pwd: str) -> str:
        @retry(
            stop=stop_after_attempt(self._retries),
            wait=wait_exponential(multiplier=1, max=10),
            reraise=True,
        )
        def _go() -> str:
            resp = client.post(
                self._token_url,
                data={
                    "grant_type": "password",
                    "username": user,
                    "password": pwd,
                    "client_id": _CLIENT_ID,
                    "scope": _SCOPE,
                    "response_type": "id_token",
                },
            )
            resp.raise_for_status()
            return resp.json()["id_token"]

        return _go()

    def _get_pages(
        self, client: httpx.Client, token: str, key: str, params: dict[str, Any]
    ) -> pd.DataFrame:
        url = f"{self._base_url}/{self.report_path}"
        headers = {"Authorization": f"Bearer {token}", "Ocp-Apim-Subscription-Key": key}
        fields: list[str] = []
        rows: list[list] = []
        page = 1
        while True:
            body = self._get(client, url, headers, {**params, "size": _PAGE_SIZE, "page": page})
            if not fields:
                fields = [f["name"] for f in body.get("fields", [])]
            rows.extend(body.get("data", []))
            total_pages = int(body.get("_meta", {}).get("totalPages", page))
            if page >= total_pages:
                break
            page += 1
        return pd.DataFrame(rows, columns=fields) if fields else pd.DataFrame()

    def _get(self, client, url, headers, params) -> dict:
        @retry(
            stop=stop_after_attempt(self._retries),
            wait=wait_exponential(multiplier=1, max=10),
            reraise=True,
        )
        def _go() -> dict:
            resp = client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            return resp.json()

        return _go()

    def fetch(self, window_start: date, window_end: date) -> FetchResult:
        user, pwd, key = self._creds()  # fail-fast before any network call
        fetched_at = datetime.now(timezone.utc)
        owns_client = self._client is None
        client = httpx.Client(timeout=self._timeout) if owns_client else self._client
        try:
            token = self._token(client, user, pwd)
            raw = self._collect(client, token, key, window_start, window_end)
        finally:
            if owns_client:
                client.close()
        frame = self._shape(raw)
        logger.info("ERCOT %s: %d rows", self.report_path, len(frame))
        return FetchResult(
            frame=frame,
            source=self.source,
            fetched_at=fetched_at,
            source_url=f"{self._base_url}/{self.report_path}",  # no secrets in the path
            complete_over_range=False,
        )

    def _collect(self, client, token, key, start: date, end: date) -> pd.DataFrame:
        base = self._date_params(start, end)
        if self._filter_by_type:
            frames = [
                self._get_pages(client, token, key, {**base, "settlementPointType": t})
                for t in _SPP_TYPES
            ]
            return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        return self._get_pages(client, token, key, base)

    def _date_params(self, start: date, end: date) -> dict[str, Any]:
        return {"deliveryDateFrom": start.isoformat(), "deliveryDateTo": end.isoformat()}

    def _shape(self, raw: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError


class ErcotRtSppConnector(_ErcotConnector):
    """RT (15-min SCED) settlement point prices for hubs + load zones -> ERCOT.SPP.<sp>."""

    report_path = "np6-905-cd/spp_node_zone_hub"
    _filter_by_type = True

    def _shape(self, raw: pd.DataFrame) -> pd.DataFrame:
        if raw.empty:
            return _empty_spp()
        minutes = (raw["deliveryHour"].astype(int) - 1) * 60 + raw["deliveryInterval"].astype(int) * 15
        valid_time = _cpt_hour_ending_to_utc(raw["deliveryDate"], minutes, raw["DSTFlag"])
        return _finalize_spp("ERCOT.SPP.", raw, valid_time)


# Backward-compat alias; removed in the orchestration task once assets import the new name.
ErcotSppConnector = ErcotRtSppConnector
