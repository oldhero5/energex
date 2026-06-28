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
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from energex.core.config import get_settings
from energex.core.connectors.base import FetchResult
from energex.core.exceptions import ConfigurationError, DataFetchError

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
        "HB_HOUSTON",
        "HB_NORTH",
        "HB_PAN",
        "HB_SOUTH",
        "HB_WEST",
        "LZ_AEN",
        "LZ_CPS",
        "LZ_HOUSTON",
        "LZ_LCRA",
        "LZ_NORTH",
        "LZ_RAYBN",
        "LZ_SOUTH",
        "LZ_WEST",
    }
)


def _is_retryable(exc: BaseException) -> bool:
    """Retry only transient failures: transport/timeout errors and 5xx responses. Never retry
    4xx (bad creds, bad request) — retrying those just hammers ERCOT's auth/API and risks
    lockout without ever succeeding."""
    if isinstance(exc, httpx.TransportError):  # includes TimeoutException, ConnectError, etc.
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return False


def _cpt_hour_ending_to_utc(
    days: pd.Series, end_minutes: pd.Series, dst_flag: pd.Series, duration_minutes: int
) -> pd.Series:
    """(operating day, minutes-after-midnight of the interval END, DSTFlag, interval length)
    -> tz-aware UTC instant of the interval end.

    ERCOT times are Central Prevailing Time, hour-ending. On the fall-back day the 01:00-02:00
    hour repeats; ERCOT marks the daylight (CDT) repeat with DSTFlag=Y and the standard (CST)
    repeat with DSTFlag=N (verified against a real fall-back-day payload). Only the 01:00-01:59
    *beginning* wall instants are ambiguous to pandas, so we localize the interval BEGINNING
    (``end_minutes - duration``) with ``ambiguous=DSTFlag`` (pandas ``ambiguous=True`` selects the
    earlier/DST occurrence, matching DSTFlag=Y), then add the duration in absolute time.
    Localizing the END instant instead would leave 02:00 unambiguous and silently collapse the
    two repeated hours onto a single UTC timestamp.
    """
    end_minutes = pd.to_numeric(end_minutes, errors="coerce")
    begin = pd.to_datetime(days) + pd.to_timedelta(end_minutes - duration_minutes, unit="m")
    ambiguous = dst_flag.astype(bool).to_numpy()
    local_begin = begin.dt.tz_localize(_CPT, ambiguous=ambiguous, nonexistent="shift_forward")
    return (local_begin + pd.Timedelta(minutes=duration_minutes)).dt.tz_convert("UTC")


def _hour_ending_to_minutes(hour_ending: pd.Series) -> pd.Series:
    """ERCOT hourEnding string ('01:00'..'24:00') -> minutes after midnight (60..1440).

    Coerces unparseable values to NaN (which become NaT valid_time and are rejected loudly by
    the non-null quality gate) rather than raising on a single malformed row.
    """
    hours = pd.to_numeric(hour_ending.astype(str).str.split(":").str[0], errors="coerce")
    return hours * 60


def _empty_spp() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "instrument_id": pd.Series(dtype="object"),
            "valid_time": pd.Series(dtype="datetime64[ns, UTC]"),
            "settlement_point": pd.Series(dtype="object"),
            "price": pd.Series(dtype="float64"),
        }
    )


def _empty_load() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "instrument_id": pd.Series(dtype="object"),
            "valid_time": pd.Series(dtype="datetime64[ns, UTC]"),
            "value": pd.Series(dtype="float64"),
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
    drift = {p for p in sp.unique() if p.startswith(("HB_", "LZ_"))} - set(_SETTLEMENT_POINTS)
    if drift:
        logger.warning(
            "ERCOT: hub/load-zone settlement points seen but not in the curated allowlist "
            "(possible drift — review _SETTLEMENT_POINTS): %s",
            sorted(drift),
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
            retry=retry_if_exception(_is_retryable),
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
            batch = body.get("data", [])
            page_fields = body.get("fields")
            if page_fields:
                fields = [f["name"] for f in page_fields]
            elif batch and not fields:
                # data rows with no column schema would silently vanish in the DataFrame build.
                raise DataFetchError(
                    f"ERCOT {self.report_path}: response carried data rows but no 'fields' schema"
                )
            rows.extend(batch)
            total_pages = body.get("_meta", {}).get("totalPages")
            if total_pages is not None:
                if page >= int(total_pages):
                    break
            elif len(batch) < _PAGE_SIZE:
                # No pagination metadata: a short page means the end; a full page means keep going
                # (stopping here would silently truncate; looping forever is avoided by the floor).
                break
            page += 1
        return pd.DataFrame(rows, columns=fields) if fields else pd.DataFrame()

    def _get(self, client, url, headers, params) -> dict:
        @retry(
            stop=stop_after_attempt(self._retries),
            wait=wait_exponential(multiplier=1, max=10),
            retry=retry_if_exception(_is_retryable),
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
        # follow_redirects=False so a 30x cannot silently move the credentialed request
        # (bearer token + subscription key) to an off-host location.
        client = (
            httpx.Client(timeout=self._timeout, follow_redirects=False)
            if owns_client
            else self._client
        )
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
        hour = pd.to_numeric(raw["deliveryHour"], errors="coerce")
        interval = pd.to_numeric(raw["deliveryInterval"], errors="coerce")
        end_minutes = (
            hour - 1
        ) * 60 + interval * 15  # 15-min interval-ending, minutes past midnight
        valid_time = _cpt_hour_ending_to_utc(raw["deliveryDate"], end_minutes, raw["DSTFlag"], 15)
        return _finalize_spp("ERCOT.SPP.", raw, valid_time)


class ErcotDamSppConnector(_ErcotConnector):
    """DAM hourly settlement point prices for hubs + load zones -> ERCOT.DASPP.<sp>."""

    report_path = "np4-190-cd/dam_stlmnt_pnt_prices"

    def _shape(self, raw: pd.DataFrame) -> pd.DataFrame:
        if raw.empty:
            return _empty_spp()
        end_minutes = _hour_ending_to_minutes(raw["hourEnding"])
        valid_time = _cpt_hour_ending_to_utc(raw["deliveryDate"], end_minutes, raw["DSTFlag"], 60)
        return _finalize_spp("ERCOT.DASPP.", raw, valid_time)


class ErcotLoadConnector(_ErcotConnector):
    """ERCOT-wide actual system load (the `total` weather-zone column) -> ERCOT.LOAD.ERCOT."""

    report_path = "np6-345-cd/act_sys_load_by_wzn"

    def _date_params(self, start: date, end: date) -> dict[str, Any]:
        return {"operatingDayFrom": start.isoformat(), "operatingDayTo": end.isoformat()}

    def _shape(self, raw: pd.DataFrame) -> pd.DataFrame:
        cols = ["instrument_id", "valid_time", "value"]
        if raw.empty:
            return _empty_load()
        end_minutes = _hour_ending_to_minutes(raw["hourEnding"])
        out = pd.DataFrame(
            {
                "instrument_id": "ERCOT.LOAD.ERCOT",
                "valid_time": _cpt_hour_ending_to_utc(
                    raw["operatingDay"], end_minutes, raw["DSTFlag"], 60
                ),
                "value": pd.to_numeric(raw["total"], errors="coerce").astype("float64"),
            }
        )
        out = out.dropna(subset=["value"])
        out = out.drop_duplicates(subset=["instrument_id", "valid_time"], keep="last")
        return out.sort_values("valid_time").reset_index(drop=True)[cols]
