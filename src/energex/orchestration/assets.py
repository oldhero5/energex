"""Dagster assets (fetch -> quality gate -> ArcticDB).

The intraday futures asset is the S1 proof-of-pipeline vertical slice: yfinance 1m
front-month bars -> core.quality.validate(OHLCV) -> storage.write_bars per symbol
into the degenerate ``prices.intraday`` library. as_of = knowledge time = fetched_at.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import dagster as dg

from energex.core import quality, schemas, storage, symbology
from energex.core.connectors.eia import (
    EiaGasStorageConnector,
    EiaPetroleumStatusConnector,
)
from energex.core.connectors.eia930 import Eia930FuelConnector, Eia930RegionConnector
from energex.core.connectors.fred import FredConnector
from energex.core.connectors.weather import NOAANClimDivConnector
from energex.core.connectors.yfinance import YFinanceIntradayConnector
from energex.orchestration.partitions import (
    EIA930_DAILY,
    EIA_GAS_WEEKLY,
    EIA_PETROLEUM_WEEKLY,
    FRED_DAILY,
    NOAA_MONTHLY,
)
from energex.orchestration.resources import ArcticDBResource

INTRADAY_LIBRARY = "prices.intraday"
_LOOKBACK_DAYS = 2  # well within yfinance's ~7-day 1m cap

SPOT_LIBRARY = "prices.spot"
# Pull this many calendar days back per partition so the append-with-dedup write re-carries
# FRED's few-business-day publication lag (idempotent across overlapping daily partitions).
_FRED_LOOKBACK_DAYS = 10

NOAA_LIBRARY = "weather"
# Whole-file replace source: a partition older than this lag is a backfill of today's
# already-revised file (reconstructed baseline), not a true forward vintage (spec §5.6).
_NOAA_LIVE_GRACE = timedelta(days=70)

EIA_LIBRARY = "fundamentals.eia"
# Inline-revision source: a partition whose release week closed more than this long ago
# is a backfill of already-released (revised) data — a reconstructed baseline, not a true
# live capture (spec §5.6 honesty boundary).
_EIA_LIVE_GRACE = timedelta(days=10)

# EIA-930 degenerate (latest-wins) hourly grid monitor; one library per series.
_EIA930_LOOKBACK_DAYS = 2


@dg.asset(
    name="intraday_futures_bars",
    group_name="prices_legacy",
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


@dg.asset(
    name="fred_spot_prices",
    group_name="prices",
    compute_kind="arcticdb",
    partitions_def=FRED_DAILY,
    description=(
        "Daily WTI/Brent/Henry Hub benchmark spot prices (FRED) -> prices.spot "
        "(degenerate, append-with-dedup; short publication-lag lookback)."
    ),
)
def fred_spot_prices(
    context: dg.AssetExecutionContext, arctic: ArcticDBResource
) -> dg.MaterializeResult:
    window = context.partition_time_window
    end = window.start.date()  # the partition day (valid_time index)
    start = end - timedelta(days=_FRED_LOOKBACK_DAYS)
    result = FredConnector().fetch(start, end)

    # SINGLE-SOURCED gate: the same core.quality.validate the asset_check re-runs.
    # as_of = fetched_at = knowledge time (degenerate live capture).
    frame = quality.validate(result.frame, schemas.FRED_SPOT, as_of=result.fetched_at)

    lib = arctic.get_library(SPOT_LIBRARY)
    versions: dict[str, int] = {}
    rows_by_symbol: dict[str, int] = {}
    for instrument_id, group in frame.groupby("instrument_id", sort=True):
        library, symbol = symbology.resolve(str(instrument_id))
        if library != SPOT_LIBRARY:
            raise ValueError(f"{instrument_id} routes to {library!r}, not {SPOT_LIBRARY!r}")
        versions[symbol] = storage.write_bars(lib, symbol, group, fetched_at=result.fetched_at)
        rows_by_symbol[symbol] = int(len(group))

    context.log.info("wrote %d FRED spot rows across %s", len(frame), sorted(rows_by_symbol))
    return dg.MaterializeResult(
        metadata={
            "source": result.source,
            "source_url": dg.MetadataValue.url(result.source_url),
            "fetched_at": result.fetched_at.isoformat(),
            "library": SPOT_LIBRARY,
            "symbols": dg.MetadataValue.json(sorted(versions)),
            "versions": dg.MetadataValue.json(versions),
            "rows_total": int(len(frame)),
            "rows_by_symbol": dg.MetadataValue.json(rows_by_symbol),
        }
    )


def _noaa_knowledge_time(context: dg.AssetExecutionContext) -> tuple[datetime, bool]:
    """(as_of, reconstructed) for a NOAA partition. as_of = knowledge time = run time;
    reconstructed=True when the partition's month closed long enough ago that we are
    backfilling today's already-revised file rather than capturing a fresh release."""
    fetched_at = datetime.now(timezone.utc)
    window_end = context.partition_time_window.end  # tz-aware UTC next-month start
    reconstructed = (fetched_at - window_end) > _NOAA_LIVE_GRACE
    return fetched_at, reconstructed


@dg.asset(
    name="noaa_degree_days",
    group_name="weather",
    compute_kind="arcticdb",
    partitions_def=NOAA_MONTHLY,
    description=(
        "Monthly NOAA nClimDiv HDD+CDD by region (contiguous-US national + nine NCEI "
        "climate regions + Texas) -> weather (bitemporal_replace, whole-file vintage)."
    ),
)
def noaa_degree_days(
    context: dg.AssetExecutionContext, arctic: ArcticDBResource
) -> dg.MaterializeResult:
    as_of, reconstructed = _noaa_knowledge_time(context)
    window = context.partition_time_window
    result = NOAANClimDivConnector().fetch(window.start.date(), window.end.date())

    # SINGLE-SOURCED gate: the same core.quality.validate the asset_check re-runs.
    frame = quality.validate(result.frame, schemas.NOAA_HDDCDD, as_of=as_of)

    lib = arctic.get_library(NOAA_LIBRARY)
    versions: dict[str, int] = {}
    rows_by_symbol: dict[str, int] = {}
    for instrument_id, group in frame.groupby("instrument_id", sort=True):
        library, symbol = symbology.resolve(str(instrument_id))
        if library != NOAA_LIBRARY:
            raise ValueError(f"{instrument_id} routes to {library!r}, not {NOAA_LIBRARY!r}")
        versions[symbol] = storage.commit_vintage(
            lib,
            symbol,
            group,
            as_of=as_of,
            source=result.source,
            source_url=result.source_url,
            fetched_at=result.fetched_at,
            mode=symbology.revision_mode(str(instrument_id)),
            reconstructed=reconstructed,
        )
        rows_by_symbol[symbol] = int(len(group))

    context.log.info("committed %d region-months across %s", len(frame), sorted(versions))
    return dg.MaterializeResult(
        metadata={
            "source": result.source,
            "source_url": dg.MetadataValue.url(result.source_url),
            "fetched_at": result.fetched_at.isoformat(),
            "as_of": as_of.isoformat(),
            "vintage_reconstructed": bool(reconstructed),
            "library": NOAA_LIBRARY,
            "symbols": dg.MetadataValue.json(sorted(versions)),
            "versions": dg.MetadataValue.json(versions),
            "rows_total": int(len(frame)),
            "rows_by_symbol": dg.MetadataValue.json(rows_by_symbol),
        }
    )


def _eia_knowledge_time(context: dg.AssetExecutionContext) -> tuple[datetime, bool]:
    """(as_of, reconstructed) for an EIA partition. as_of = knowledge time = run time;
    reconstructed=True when the partition's release week closed long enough ago that we
    are backfilling EIA's already-revised values rather than capturing a live release."""
    fetched_at = datetime.now(timezone.utc)
    window_end = context.partition_time_window.end  # tz-aware UTC next-week start
    reconstructed = (fetched_at - window_end) > _EIA_LIVE_GRACE
    return fetched_at, reconstructed


def _commit_eia(
    context: dg.AssetExecutionContext,
    arctic: ArcticDBResource,
    connector: Any,
    schema: Any,
) -> dg.MaterializeResult:
    """Shared EIA body: fetch (revision-lookback window) -> gate -> bitemporal_merge."""
    as_of, reconstructed = _eia_knowledge_time(context)
    window = context.partition_time_window
    result = connector.fetch(window.start.date(), window.end.date())

    # SINGLE-SOURCED gate: the same core.quality.validate the asset_check re-runs.
    frame = quality.validate(result.frame, schema, as_of=as_of)

    lib = arctic.get_library(EIA_LIBRARY)
    versions: dict[str, int] = {}
    rows_by_symbol: dict[str, int] = {}
    for instrument_id, group in frame.groupby("instrument_id", sort=True):
        library, symbol = symbology.resolve(str(instrument_id))
        if library != EIA_LIBRARY:
            raise ValueError(f"{instrument_id} routes to {library!r}, not {EIA_LIBRARY!r}")
        versions[symbol] = storage.commit_vintage(
            lib,
            symbol,
            group,
            as_of=as_of,
            source=result.source,
            source_url=result.source_url,
            fetched_at=result.fetched_at,
            mode=symbology.revision_mode(str(instrument_id)),
            reconstructed=reconstructed,
        )
        rows_by_symbol[symbol] = int(len(group))

    context.log.info("committed %d EIA weekly rows across %s", len(frame), sorted(versions))
    return dg.MaterializeResult(
        metadata={
            "source": result.source,
            "source_url": dg.MetadataValue.url(result.source_url),
            "fetched_at": result.fetched_at.isoformat(),
            "as_of": as_of.isoformat(),
            "vintage_reconstructed": bool(reconstructed),
            "library": EIA_LIBRARY,
            "symbols": dg.MetadataValue.json(sorted(versions)),
            "versions": dg.MetadataValue.json(versions),
            "rows_total": int(len(frame)),
            "rows_by_symbol": dg.MetadataValue.json(rows_by_symbol),
        }
    )


@dg.asset(
    name="eia_gas_storage",
    group_name="fundamentals_legacy",
    compute_kind="arcticdb",
    partitions_def=EIA_GAS_WEEKLY,
    description=(
        "Weekly Lower-48 working gas in underground storage (EIA v2) -> fundamentals.eia "
        "(bitemporal_merge; >=5-week revision-lookback window)."
    ),
)
def eia_gas_storage(
    context: dg.AssetExecutionContext, arctic: ArcticDBResource
) -> dg.MaterializeResult:
    return _commit_eia(context, arctic, EiaGasStorageConnector(), schemas.EIA_GAS_STORAGE)


@dg.asset(
    name="eia_petroleum_status",
    group_name="fundamentals_legacy",
    compute_kind="arcticdb",
    partitions_def=EIA_PETROLEUM_WEEKLY,
    description=(
        "Weekly U.S. crude oil ending stocks excluding SPR (EIA v2) -> fundamentals.eia "
        "(bitemporal_merge; >=5-week revision-lookback window)."
    ),
)
def eia_petroleum_status(
    context: dg.AssetExecutionContext, arctic: ArcticDBResource
) -> dg.MaterializeResult:
    return _commit_eia(context, arctic, EiaPetroleumStatusConnector(), schemas.EIA_PETROLEUM)


def _write_power_degenerate(
    context: dg.AssetExecutionContext,
    arctic: ArcticDBResource,
    result,
    schema,
    group_keys,
) -> dg.MaterializeResult:
    """Gate -> per-symbol degenerate write_bars for an EIA-930 frame (all BAs)."""
    frame = quality.validate(result.frame, schema, as_of=result.fetched_at)
    versions: dict[str, int] = {}
    rows_by_symbol: dict[str, int] = {}
    libs: dict[str, Any] = {}
    for instrument_id, group in frame.groupby("instrument_id", sort=True):
        library, symbol = symbology.resolve(str(instrument_id))
        lib = libs.get(library) or libs.setdefault(library, arctic.get_library(library))
        versions[f"{library}:{symbol}"] = storage.write_bars(
            lib, symbol, group, fetched_at=result.fetched_at
        )
        rows_by_symbol[f"{library}:{symbol}"] = int(len(group))
    context.log.info("EIA-930 wrote %d rows across %d symbols", len(frame), len(versions))
    return dg.MaterializeResult(
        metadata={
            "source": result.source,
            "source_url": dg.MetadataValue.url(result.source_url),
            "fetched_at": result.fetched_at.isoformat(),
            "rows_total": int(len(frame)),
            "symbols": dg.MetadataValue.json(sorted(versions)),
            "versions": dg.MetadataValue.json(versions),
        }
    )


@dg.asset(
    name="eia930_region",
    group_name="power",
    compute_kind="arcticdb",
    partitions_def=EIA930_DAILY,
    description=(
        "EIA-930 hourly demand/forecast/net-generation/interchange for all balancing "
        "authorities -> power.{demand,demand_forecast,generation,interchange} (degenerate)."
    ),
)
def eia930_region(
    context: dg.AssetExecutionContext, arctic: ArcticDBResource
) -> dg.MaterializeResult:
    window = context.partition_time_window
    end = window.end.date()
    start = window.start.date() - timedelta(days=_EIA930_LOOKBACK_DAYS)
    result = Eia930RegionConnector().fetch(start, end)
    return _write_power_degenerate(context, arctic, result, schemas.POWER_REGION, None)


@dg.asset(
    name="eia930_generation_by_fuel",
    group_name="power",
    compute_kind="arcticdb",
    partitions_def=EIA930_DAILY,
    description=(
        "EIA-930 hourly net generation by fuel type for all balancing authorities -> "
        "power.generation_by_fuel (degenerate)."
    ),
)
def eia930_generation_by_fuel(
    context: dg.AssetExecutionContext, arctic: ArcticDBResource
) -> dg.MaterializeResult:
    window = context.partition_time_window
    end = window.end.date()
    start = window.start.date() - timedelta(days=_EIA930_LOOKBACK_DAYS)
    result = Eia930FuelConnector().fetch(start, end)
    return _write_power_degenerate(context, arctic, result, schemas.POWER_GEN_BY_FUEL, None)


ASSETS: list[Any] = [
    intraday_futures_bars,
    fred_spot_prices,
    noaa_degree_days,
    eia_gas_storage,
    eia_petroleum_status,
    eia930_region,
    eia930_generation_by_fuel,
]
