# src/energex/analysis/quality.py
import polars as pl
from datetime import datetime, timedelta
import numpy as np

class DataQualityChecker:
    def __init__(self, df: pl.DataFrame):
        self.df = df
        
    def check_price_gaps(self, threshold_pct: float = 0.5) -> pl.DataFrame:
        """
        Detect significant price gaps between consecutive timestamps.
        Args:
            threshold_pct: Percentage change threshold to flag as gap
        """
        return (self.df
            .sort(['Symbol', 'Datetime'])
            .group_by('Symbol')
            .agg([
                pl.col('Close').pct_change().alias('price_change_pct'),
                pl.col('Datetime').diff().alias('time_gap')
            ])
            .filter(
                (pl.col('price_change_pct').abs() > threshold_pct) |
                (pl.col('time_gap') > timedelta(minutes=5))
            )
        )
    
    def check_volume_anomalies(self, z_score_threshold: float = 3.0) -> pl.DataFrame:
        """
        Detect unusual volume spikes using z-score.
        """
        return (self.df
            .group_by('Symbol')
            .mutate([
                pl.col('Volume')
                  .rolling_mean(window_size=20)
                  .alias('avg_volume'),
                pl.col('Volume')
                  .rolling_std(window_size=20)
                  .alias('std_volume')
            ])
            .with_columns([
                ((pl.col('Volume') - pl.col('avg_volume')) / 
                 pl.col('std_volume')).alias('volume_z_score')
            ])
            .filter(pl.col('volume_z_score').abs() > z_score_threshold)
        )
    
    def check_price_reversals(self, threshold_pct: float = 1.0) -> pl.DataFrame:
        """
        Detect significant price reversals within short timeframes.
        """
        return (self.df
            .sort(['Symbol', 'Datetime'])
            .group_by('Symbol')
            .mutate([
                pl.col('High').rolling_max(window_size=5).alias('max_5min'),
                pl.col('Low').rolling_min(window_size=5).alias('min_5min'),
                ((pl.col('max_5min') - pl.col('min_5min')) / 
                 pl.col('min_5min') * 100).alias('price_range_pct')
            ])
            .filter(pl.col('price_range_pct') > threshold_pct)
        )
    
    def check_tick_quality(self) -> dict:
        """
        Analyze overall data quality metrics.
        """
        metrics = {}
        
        # Check for zero or negative prices
        invalid_prices = (self.df
            .filter(
                (pl.col('Close') <= 0) |
                (pl.col('High') <= 0) |
                (pl.col('Low') <= 0) |
                (pl.col('Open') <= 0)
            )
            .count()
        )
        
        # Check OHLC consistency
        invalid_ohlc = (self.df
            .filter(
                (pl.col('High') < pl.col('Low')) |
                (pl.col('Open') > pl.col('High')) |
                (pl.col('Open') < pl.col('Low')) |
                (pl.col('Close') > pl.col('High')) |
                (pl.col('Close') < pl.col('Low'))
            )
            .count()
        )
        
        # Check timestamp consistency
        time_gaps = (self.df
            .sort(['Symbol', 'Datetime'])
            .group_by('Symbol')
            .agg([
                pl.col('Datetime').diff().alias('time_gap')
            ])
            .filter(pl.col('time_gap') > timedelta(minutes=5))
            .count()
        )
        
        metrics.update({
            'invalid_prices': invalid_prices,
            'invalid_ohlc': invalid_ohlc,
            'large_time_gaps': time_gaps,
            'total_records': len(self.df),
            'symbols': self.df['Symbol'].unique().to_list(),
            'date_range': [
                self.df['Datetime'].min(),
                self.df['Datetime'].max()
            ]
        })
        
        return metrics