# src/energex/analysis/volatility.py

import numpy as np
import polars as pl

# Naive intraday annualization factor (1-min bars assumed 24h session).
# NOTE: methodology correctness (5-min sampling, session-gap masking, calendar-based
# annualization, Yang-Zhang) is addressed separately in ASSESSMENT R7; this module
# only restores correct *execution* on the Polars 1.20 API (group_by has no .mutate;
# use with_columns(expr.over('Symbol')) instead).
_ANNUALIZE = float(np.sqrt(252 * 1440))


class VolatilityAnalyzer:
    def __init__(self, df: pl.DataFrame):
        self.df = df

    def calculate_realized_volatility(
        self, window_minutes: int = 30, df: pl.DataFrame | None = None
    ) -> pl.DataFrame:
        """Rolling realized volatility from log returns, computed per symbol."""
        frame = self.df if df is None else df
        return frame.sort(["Symbol", "Datetime"]).with_columns(
            (pl.col("Close").log().diff().rolling_std(window_size=window_minutes) * _ANNUALIZE)
            .over("Symbol")
            .alias("realized_vol")
        )

    def calculate_parkinson_volatility(
        self, window_minutes: int = 30, df: pl.DataFrame | None = None
    ) -> pl.DataFrame:
        """Parkinson high-low range volatility, computed per symbol."""
        frame = self.df if df is None else df
        return frame.sort(["Symbol", "Datetime"]).with_columns(
            (
                (pl.col("High") / pl.col("Low"))
                .log()
                .pow(2)
                .rolling_mean(window_size=window_minutes)
                .mul(1 / (4 * np.log(2)))
                .sqrt()
                .mul(_ANNUALIZE)
            )
            .over("Symbol")
            .alias("parkinson_vol")
        )

    def calculate_garman_klass_volatility(
        self, window_minutes: int = 30, df: pl.DataFrame | None = None
    ) -> pl.DataFrame:
        """Garman-Klass OHLC volatility, computed per symbol."""
        frame = self.df if df is None else df
        return frame.sort(["Symbol", "Datetime"]).with_columns(
            (
                (
                    0.5 * (pl.col("High") / pl.col("Low")).log().pow(2)
                    - (2 * np.log(2) - 1) * (pl.col("Close") / pl.col("Open")).log().pow(2)
                )
                .rolling_mean(window_size=window_minutes)
                .sqrt()
                .mul(_ANNUALIZE)
            )
            .over("Symbol")
            .alias("garman_klass_vol")
        )

    def calculate_volatility_metrics(self) -> pl.DataFrame:
        """Compose all volatility measures plus ratios and intraday range."""
        df = self.calculate_realized_volatility()
        df = self.calculate_parkinson_volatility(df=df)
        df = self.calculate_garman_klass_volatility(df=df)
        return df.with_columns(
            [
                (pl.col("parkinson_vol") / pl.col("realized_vol")).alias("vol_ratio_pk_rv"),
                (pl.col("garman_klass_vol") / pl.col("realized_vol")).alias("vol_ratio_gk_rv"),
                ((pl.col("High") - pl.col("Low")) / pl.col("Open") * 100).alias(
                    "intraday_range_pct"
                ),
            ]
        )
