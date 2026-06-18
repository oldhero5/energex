# src/energex/analysis/futures.py

import polars as pl

# These analytics require a real contract-month/expiry data model (and a spot leg /
# risk-free curve) that the current single-table, continuous-front-month schema does
# not provide. They are gated until that model lands so they fail
# clearly instead of crashing on a missing 'expiry' column or invalid Polars APIs.
_NEEDS_CONTRACT_MODEL = (
    "{name} requires a contract-month/expiry data model (dated contracts, and for "
    "carry/implied-rate a spot leg + risk-free curve); this FuturesAnalyzer only has "
    "continuous front-month proxies (CL=F/BZ=F/NG=F). For real dated-contract term "
    "structure, slope, and roll yield use energex.analysis.dated_futures."
    "DatedFuturesAnalyzer over the daily_contracts table."
)


class FuturesAnalyzer:
    def __init__(self, df: pl.DataFrame):
        self.df = df

    def calculate_term_structure(self, front_month: str, back_month: str) -> pl.DataFrame:
        """Spread between two symbols aligned on Datetime.

        NOTE: with only continuous front-month proxies stored, this is an
        inter-instrument spread, not a true single-curve term structure (which needs
        multiple dated contract months at the same instant).
        """
        front = self.df.filter(pl.col("Symbol") == front_month)
        back = self.df.filter(pl.col("Symbol") == back_month)

        return front.join(back, on="Datetime", suffix="_back").with_columns(
            [
                (pl.col("Close") - pl.col("Close_back")).alias("spread"),
                ((pl.col("Close") - pl.col("Close_back")) / pl.col("Close_back") * 100).alias(
                    "spread_pct"
                ),
                (pl.col("Volume") + pl.col("Volume_back")).alias("total_volume"),
            ]
        )

    def calculate_basis_risk(self, spot_symbol: str, futures_symbol: str) -> pl.DataFrame:
        """Difference between two symbols aligned on Datetime.

        NOTE: a true basis needs a real cash/spot series (e.g. EIA/FRED) which is not
        ingested yet; passing two futures proxies gives an inter-instrument spread,
        not spot-vs-futures basis.
        """
        spot = self.df.filter(pl.col("Symbol") == spot_symbol)
        futures = self.df.filter(pl.col("Symbol") == futures_symbol)

        return spot.join(futures, on="Datetime", suffix="_futures").with_columns(
            [
                (pl.col("Close") - pl.col("Close_futures")).alias("basis"),
                ((pl.col("Close") - pl.col("Close_futures")) / pl.col("Close_futures") * 100).alias(
                    "basis_pct"
                ),
            ]
        )

    def analyze_roll_yield(
        self, front_month: str, back_month: str, window_minutes: int = 30
    ) -> pl.DataFrame:
        """Annualized roll yield — gated. Use DatedFuturesAnalyzer.roll_yield instead."""
        raise NotImplementedError(_NEEDS_CONTRACT_MODEL.format(name="analyze_roll_yield"))

    def analyze_futures_curve(self, symbols: list[str]) -> pl.DataFrame:
        """Cross-sectional curve by expiry — gated. Use DatedFuturesAnalyzer.curve_as_of."""
        raise NotImplementedError(_NEEDS_CONTRACT_MODEL.format(name="analyze_futures_curve"))

    def calculate_implied_rates(
        self, spot_symbol: str, futures_symbol: str, risk_free_rate: float
    ) -> pl.DataFrame:
        """Implied net carry from F/S — gated (needs spot leg + expiries)."""
        raise NotImplementedError(_NEEDS_CONTRACT_MODEL.format(name="calculate_implied_rates"))
