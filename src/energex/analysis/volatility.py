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

    # ------------------------------------------------------------------
    # Methodologically-correct estimators (ASSESSMENT R7)
    # ------------------------------------------------------------------
    def realized_volatility_daily(self) -> pl.DataFrame:
        """Canonical daily realized volatility per symbol.

        Realized variance is the SUM of squared intraday log returns (not a
        mean-subtracted rolling std), with the overnight (cross-day) return masked so
        a session gap is never treated as an intraday return. Daily volatility
        (sqrt of the daily realized variance) is annualized by sqrt(252).
        """
        df = self.df.sort(["Symbol", "Datetime"]).with_columns(
            [
                pl.col("Close").log().diff().over("Symbol").alias("log_ret"),
                pl.col("Datetime").dt.date().alias("date"),
            ]
        )
        # Mask the first bar of each day (its diff spans the overnight gap).
        df = df.with_columns(
            pl.when(pl.col("date") != pl.col("date").shift(1).over("Symbol"))
            .then(None)
            .otherwise(pl.col("log_ret"))
            .alias("log_ret")
        )
        return (
            df.group_by(["Symbol", "date"])
            .agg(pl.col("log_ret").pow(2).sum().alias("realized_variance"))
            .with_columns(
                (pl.col("realized_variance").sqrt() * np.sqrt(252)).alias("realized_vol_annual")
            )
            .sort(["Symbol", "date"])
        )

    def to_daily_ohlc(self) -> pl.DataFrame:
        """Resample intraday bars to daily OHLC per symbol."""
        return (
            self.df.sort(["Symbol", "Datetime"])
            .group_by_dynamic("Datetime", every="1d", group_by="Symbol")
            .agg(
                [
                    pl.col("Open").first().alias("Open"),
                    pl.col("High").max().alias("High"),
                    pl.col("Low").min().alias("Low"),
                    pl.col("Close").last().alias("Close"),
                    pl.col("Volume").sum().alias("Volume"),
                ]
            )
            .sort(["Symbol", "Datetime"])
        )

    def yang_zhang_volatility(self) -> pl.DataFrame:
        """Annualized Yang-Zhang volatility per symbol (drift- and gap-independent).

        Computed on DAILY OHLC bars (range estimators are daily tools). Combines
        overnight, open-to-close, and Rogers-Satchell variances; requires >= 2 days.
        """
        daily = self.to_daily_ohlc().with_columns(
            pl.col("Close").shift(1).over("Symbol").alias("prev_close")
        )
        daily = daily.with_columns(
            [
                (pl.col("Open") / pl.col("prev_close")).log().alias("o"),
                (pl.col("Close") / pl.col("Open")).log().alias("c"),
                (
                    (pl.col("High") / pl.col("Close")).log()
                    * (pl.col("High") / pl.col("Open")).log()
                    + (pl.col("Low") / pl.col("Close")).log()
                    * (pl.col("Low") / pl.col("Open")).log()
                ).alias("rs"),
            ]
        )
        agg = daily.group_by("Symbol").agg(
            [
                pl.col("o").var().alias("v_o"),
                pl.col("c").var().alias("v_c"),
                pl.col("rs").mean().alias("v_rs"),
                pl.len().alias("n"),
            ]
        )
        k = 0.34 / (1.34 + (pl.col("n") + 1) / (pl.col("n") - 1))
        return agg.with_columns(
            (
                (pl.col("v_o") + k * pl.col("v_c") + (1 - k) * pl.col("v_rs")).sqrt() * np.sqrt(252)
            ).alias("yang_zhang_vol_annual")
        ).select(["Symbol", "n", "yang_zhang_vol_annual"])
