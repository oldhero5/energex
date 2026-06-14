# src/energex/analysis/dated_futures.py
"""Term-structure analytics over the dated futures contract strip.

Unlike :class:`energex.analysis.futures.FuturesAnalyzer` (which only has continuous
front-month proxies), this operates on real dated contracts (``daily_contracts`` rows)
so the forward curve, slope, roll yield, and curve shape are genuine cross-sectional
quantities at a single point in time (ASSESSMENT R8).
"""

from datetime import date

import polars as pl


class DatedFuturesAnalyzer:
    """Forward-curve / term-structure analytics over dated contracts.

    Args:
        df: Polars frame of ``daily_contracts`` rows (columns include Commodity,
            ContractMonth, Datetime, Close).
    """

    def __init__(self, df: pl.DataFrame):
        self.df = df

    def curve_as_of(self, commodity: str, asof: date) -> pl.DataFrame:
        """The dated forward curve for ``commodity`` observed on ``asof``.

        One row per ContractMonth (sorted ascending) with the settlement Close and
        ``days_to_maturity`` = (ContractMonth - asof).days. Returns the rows whose
        ``Datetime`` falls on ``asof``.
        """
        curve = (
            self.df.filter(
                (pl.col("Commodity") == commodity) & (pl.col("Datetime").dt.date() == asof)
            )
            .select(["ContractMonth", "Close"])
            .unique(subset=["ContractMonth"])
            .sort("ContractMonth")
            .with_columns(
                (pl.col("ContractMonth") - pl.lit(asof)).dt.total_days().alias("days_to_maturity")
            )
        )
        return curve

    def term_structure_slope(self, commodity: str, asof: date) -> float:
        """Annualized front-to-back slope: (back/front - 1) * 365 / (back_dtm - front_dtm).

        Returns ``nan`` when the curve has fewer than two points or the maturity span /
        front price is degenerate.
        """
        curve = self.curve_as_of(commodity, asof)
        if curve.height < 2:
            return float("nan")
        front = curve.row(0, named=True)
        back = curve.row(-1, named=True)
        span = back["days_to_maturity"] - front["days_to_maturity"]
        if span == 0 or front["Close"] == 0:
            return float("nan")
        return float((back["Close"] / front["Close"] - 1.0) * 365.0 / span)

    def roll_yield(self, commodity: str, asof: date) -> pl.DataFrame:
        """Annualized roll yield between each adjacent contract pair.

        For neighbours (near, far): (near/far - 1) * 365 / (far_dtm - near_dtm). Positive
        in backwardation (near > far). Returns one row per adjacent pair.
        """
        curve = self.curve_as_of(commodity, asof)
        if curve.height < 2:
            return pl.DataFrame(
                schema={
                    "ContractMonth": pl.Date,
                    "ContractMonth_far": pl.Date,
                    "roll_yield": pl.Float64,
                }
            )
        return (
            curve.with_columns(
                pl.col("ContractMonth").shift(-1).alias("ContractMonth_far"),
                pl.col("Close").shift(-1).alias("Close_far"),
                pl.col("days_to_maturity").shift(-1).alias("dtm_far"),
            )
            .drop_nulls("Close_far")
            .with_columns((pl.col("dtm_far") - pl.col("days_to_maturity")).alias("_span"))
            .with_columns(
                pl.when(pl.col("_span") > 0)
                .then((pl.col("Close") / pl.col("Close_far") - 1.0) * 365.0 / pl.col("_span"))
                .otherwise(None)  # degenerate same-/inverted-maturity pair: no roll yield
                .alias("roll_yield")
            )
            .select(["ContractMonth", "ContractMonth_far", "roll_yield"])
        )

    def shape(self, commodity: str, asof: date) -> str:
        """Curve shape from the sign of the slope.

        Returns "backwardation" (downward-sloping), "contango" (upward-sloping), or
        "flat" (zero / undefined slope).
        """
        slope = self.term_structure_slope(commodity, asof)
        if slope != slope or slope == 0.0:  # nan or exactly flat
            return "flat"
        return "contango" if slope > 0 else "backwardation"
