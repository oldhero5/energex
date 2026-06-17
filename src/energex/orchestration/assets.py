"""Dagster assets (fetch -> quality gate -> ArcticDB).

The intraday futures asset is the S1 proof-of-pipeline vertical slice: yfinance 1m
front-month bars -> core.quality.validate(OHLCV) -> storage.write_bars per symbol
into the degenerate ``prices.intraday`` library. as_of = knowledge time = fetched_at.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import dagster as dg

from energex.core import quality, schemas, storage, symbology
from energex.core.connectors.yfinance import YFinanceIntradayConnector
from energex.orchestration.resources import ArcticDBResource

INTRADAY_LIBRARY = "prices.intraday"
_LOOKBACK_DAYS = 2  # well within yfinance's ~7-day 1m cap


@dg.asset(
    name="intraday_futures_bars",
    group_name="prices",
    compute_kind="arcticdb",
    description=(
        "Front-month CL/BZ/NG 1-minute OHLCV bars (yfinance) -> prices.intraday "
        "(degenerate, append-with-dedup)."
    ),
)
def intraday_futures_bars(
    context: dg.AssetExecutionContext, arctic: ArcticDBResource
) -> dg.MaterializeResult:
    fetched_at = datetime.now(timezone.utc)
    today = fetched_at.date()
    result = YFinanceIntradayConnector().fetch(
        today - timedelta(days=_LOOKBACK_DAYS), today + timedelta(days=1)
    )

    # SINGLE-SOURCED gate: the same core.quality.validate the asset_check re-runs.
    # as_of = fetched_at = knowledge time (live capture).
    frame = quality.validate(result.frame, schemas.OHLCV, as_of=result.fetched_at)

    lib = arctic.get_library(INTRADAY_LIBRARY)
    versions: dict[str, int] = {}
    rows_by_symbol: dict[str, int] = {}
    for instrument_id, group in frame.groupby("instrument_id", sort=True):
        library, symbol = symbology.resolve(str(instrument_id))
        if library != INTRADAY_LIBRARY:
            raise ValueError(f"{instrument_id} routes to {library!r}, not {INTRADAY_LIBRARY!r}")
        versions[symbol] = storage.write_bars(lib, symbol, group, fetched_at=result.fetched_at)
        rows_by_symbol[symbol] = int(len(group))

    context.log.info("wrote %d bars across %s", len(frame), sorted(rows_by_symbol))
    return dg.MaterializeResult(
        metadata={
            "source": result.source,
            "source_url": dg.MetadataValue.url(result.source_url),
            "fetched_at": result.fetched_at.isoformat(),
            "library": INTRADAY_LIBRARY,
            "symbols": dg.MetadataValue.json(sorted(versions)),
            "versions": dg.MetadataValue.json(versions),
            "rows_total": int(len(frame)),
            "rows_by_symbol": dg.MetadataValue.json(rows_by_symbol),
        }
    )


ASSETS: list[Any] = [intraday_futures_bars]
