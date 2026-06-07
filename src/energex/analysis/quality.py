# src/energex/analysis/quality.py
from datetime import timedelta

import polars as pl


class DataQualityChecker:
    def __init__(self, df: pl.DataFrame):
        self.df = df

    def check_price_gaps(self, threshold_pct: float = 0.5) -> pl.DataFrame:
        """Detect significant price gaps between consecutive bars.

        Args:
            threshold_pct: percent move (e.g. 0.5 == 0.5%) flagged as a gap.
        """
        return (
            self.df.sort(["Symbol", "Datetime"])
            .with_columns(
                [
                    (pl.col("Close").pct_change() * 100).over("Symbol").alias("price_change_pct"),
                    pl.col("Datetime").diff().over("Symbol").alias("time_gap"),
                ]
            )
            .filter(
                (pl.col("price_change_pct").abs() > threshold_pct)
                | (pl.col("time_gap") > timedelta(minutes=5))
            )
        )

    def check_volume_anomalies(self, z_score_threshold: float = 3.0) -> pl.DataFrame:
        """Detect unusual volume spikes using a rolling per-symbol z-score."""
        return (
            self.df.sort(["Symbol", "Datetime"])
            .with_columns(
                [
                    pl.col("Volume")
                    .rolling_mean(window_size=20)
                    .over("Symbol")
                    .alias("avg_volume"),
                    pl.col("Volume").rolling_std(window_size=20).over("Symbol").alias("std_volume"),
                ]
            )
            .with_columns(
                ((pl.col("Volume") - pl.col("avg_volume")) / pl.col("std_volume")).alias(
                    "volume_z_score"
                )
            )
            .filter(pl.col("volume_z_score").abs() > z_score_threshold)
        )

    def check_price_reversals(self, threshold_pct: float = 1.0) -> pl.DataFrame:
        """Detect significant high-low range within a short rolling window, per symbol."""
        return (
            self.df.sort(["Symbol", "Datetime"])
            .with_columns(
                [
                    pl.col("High").rolling_max(window_size=5).over("Symbol").alias("max_5min"),
                    pl.col("Low").rolling_min(window_size=5).over("Symbol").alias("min_5min"),
                ]
            )
            .with_columns(
                ((pl.col("max_5min") - pl.col("min_5min")) / pl.col("min_5min") * 100).alias(
                    "price_range_pct"
                )
            )
            .filter(pl.col("price_range_pct") > threshold_pct)
        )

    def check_tick_quality(self) -> dict[str, object]:
        """Summarize overall data-quality metrics with scalar counts."""
        invalid_prices = self.df.filter(
            (pl.col("Close") <= 0)
            | (pl.col("High") <= 0)
            | (pl.col("Low") <= 0)
            | (pl.col("Open") <= 0)
        ).height

        invalid_ohlc = self.df.filter(
            (pl.col("High") < pl.col("Low"))
            | (pl.col("Open") > pl.col("High"))
            | (pl.col("Open") < pl.col("Low"))
            | (pl.col("Close") > pl.col("High"))
            | (pl.col("Close") < pl.col("Low"))
        ).height

        large_time_gaps = (
            self.df.sort(["Symbol", "Datetime"])
            .with_columns(pl.col("Datetime").diff().over("Symbol").alias("time_gap"))
            .filter(pl.col("time_gap") > timedelta(minutes=5))
            .height
        )

        return {
            "invalid_prices": invalid_prices,
            "invalid_ohlc": invalid_ohlc,
            "large_time_gaps": large_time_gaps,
            "total_records": self.df.height,
            "symbols": self.df["Symbol"].unique().to_list(),
            "date_range": [self.df["Datetime"].min(), self.df["Datetime"].max()],
        }
