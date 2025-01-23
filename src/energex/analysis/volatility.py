# src/energex/analysis/volatility.py
import polars as pl
import numpy as np
from datetime import datetime, timedelta

class VolatilityAnalyzer:
    def __init__(self, df: pl.DataFrame):
        self.df = df
        
    def calculate_realized_volatility(self, window_minutes: int = 30) -> pl.DataFrame:
        """
        Calculate realized volatility using log returns.
        """
        return (self.df
            .sort(['Symbol', 'Datetime'])
            .group_by('Symbol')
            .mutate([
                pl.col('Close')
                  .log()
                  .diff()
                  .rolling_std(window_size=window_minutes)
                  .mul(np.sqrt(252 * 1440))  # Annualize (252 days * 1440 minutes)
                  .alias('realized_vol')
            ])
        )
    
    def calculate_parkinson_volatility(self, window_minutes: int = 30) -> pl.DataFrame:
        """
        Calculate Parkinson volatility using high-low range.
        """
        return (self.df
            .sort(['Symbol', 'Datetime'])
            .group_by('Symbol')
            .mutate([
                (pl.col('High') / pl.col('Low'))
                  .log()
                  .pow(2)
                  .rolling_mean(window_size=window_minutes)
                  .mul(1 / (4 * np.log(2)))
                  .sqrt()
                  .mul(np.sqrt(252 * 1440))
                  .alias('parkinson_vol')
            ])
        )
    
    def calculate_garman_klass_volatility(self, window_minutes: int = 30) -> pl.DataFrame:
        """
        Calculate Garman-Klass volatility using OHLC prices.
        """
        return (self.df
            .sort(['Symbol', 'Datetime'])
            .group_by('Symbol')
            .mutate([
                (0.5 * (pl.col('High') / pl.col('Low')).log().pow(2) -
                 (2 * np.log(2) - 1) * (pl.col('Close') / pl.col('Open')).log().pow(2))
                .rolling_mean(window_size=window_minutes)
                .sqrt()
                .mul(np.sqrt(252 * 1440))
                .alias('garman_klass_vol')
            ])
        )
    
    def calculate_volatility_metrics(self) -> pl.DataFrame:
        """
        Calculate comprehensive volatility metrics.
        """
        df = self.df.clone()
        
        # Add all volatility measures
        df = (df
            .pipe(self.calculate_realized_volatility)
            .pipe(self.calculate_parkinson_volatility)
            .pipe(self.calculate_garman_klass_volatility)
        )
        
        # Add volatility ratios and spreads
        df = df.with_columns([
            (pl.col('parkinson_vol') / pl.col('realized_vol'))
              .alias('vol_ratio_pk_rv'),
            (pl.col('garman_klass_vol') / pl.col('realized_vol'))
              .alias('vol_ratio_gk_rv'),
            (pl.col('High') - pl.col('Low'))
              .div(pl.col('Open'))
              .mul(100)
              .alias('intraday_range_pct')
        ])
        
        return df