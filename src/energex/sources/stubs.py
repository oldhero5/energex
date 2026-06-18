"""Documented stubs for licensed/production data sources (Databento, ICE/Refinitiv, EIA/FRED).

These define the adapter boundary and fail clearly with setup guidance. Wiring the live
calls requires vendor accounts / API keys and is intentionally deferred.
"""

import polars as pl

from energex.sources.base import DataSource


class _NotConfiguredSource(DataSource):
    redistributable = True
    setup: str = "not configured"

    def fetch(self, commodity: str) -> pl.DataFrame:
        raise NotImplementedError(self.setup)

    def fetch_all(self) -> pl.DataFrame:
        raise NotImplementedError(self.setup)

    def fetch_dated(self) -> pl.DataFrame:
        raise NotImplementedError(self.setup)


class DatabentoDataSource(_NotConfiguredSource):
    """Primary intraday source for CME CL/NG (per-contract symbology + expiry + OI)."""

    name = "databento"
    setup = (
        "Databento GLBX.MDP3 adapter not implemented. It provides per-contract CME "
        "intraday (CL/NG) with expiry and open interest. Needs DATABENTO_API_KEY."
    )


class ICEBrentDataSource(_NotConfiguredSource):
    """Brent (BZ) is an ICE product, not on CME Globex — needs an ICE-licensed vendor."""

    name = "ice-brent"
    setup = (
        "ICE Brent adapter not implemented. Brent is an ICE product; use an "
        "ICE-licensed vendor (Refinitiv / ICE Data Services / Barchart)."
    )


class EIASpotDataSource(_NotConfiguredSource):
    """Free EIA/FRED spot benchmarks (WTI Cushing, Henry Hub) for the basis/carry leg."""

    name = "eia-spot"
    setup = (
        "EIA/FRED spot adapter not implemented. It supplies the cash/spot leg "
        "(WTI Cushing, Henry Hub) for real basis/implied-carry. Needs a free EIA_API_KEY."
    )
