# src/energex/analysis/futures.py
import polars as pl
import numpy as np
from datetime import datetime, timedelta

class FuturesAnalyzer:
    def __init__(self, df: pl.DataFrame):
        self.df = df
        
    def calculate_term_structure(self, front_month: str, back_month: str) -> pl.DataFrame:
        """
        Calculate futures term structure and spreads.
        """
        # Assuming df contains data for multiple contract months
        front = self.df.filter(pl.col('Symbol') == front_month)
        back = self.df.filter(pl.col('Symbol') == back_month)
        
        # Join and calculate spreads
        spreads = (front
            .join(
                back,
                on='Datetime',
                suffix='_back'
            )
            .with_columns([
                (pl.col('Close') - pl.col('Close_back')).alias('spread'),
                ((pl.col('Close') - pl.col('Close_back')) / 
                 pl.col('Close_back') * 100).alias('spread_pct'),
                (pl.col('Volume') + pl.col('Volume_back')).alias('total_volume')
            ])
        )
        
        return spreads
    
    def calculate_basis_risk(self, spot_symbol: str, futures_symbol: str) -> pl.DataFrame:
        """
        Calculate basis risk between spot and futures prices.
        """
        spot = self.df.filter(pl.col('Symbol') == spot_symbol)
        futures = self.df.filter(pl.col('Symbol') == futures_symbol)
        
        basis = (spot
            .join(
                futures,
                on='Datetime',
                suffix='_futures'
            )
            .with_columns([
                (pl.col('Close') - pl.col('Close_futures')).alias('basis'),
                ((pl.col('Close') - pl.col('Close_futures')) / 
                 pl.col('Close_futures') * 100).alias('basis_pct')
            ])
        )
        
        return basis
    
    def analyze_roll_yield(self, front_month: str, back_month: str,
                          window_minutes: int = 30) -> pl.DataFrame:
        """
        Analyze roll yield between futures contracts.
        """
        spreads = self.calculate_term_structure(front_month, back_month)
        
        roll_metrics = (spreads
            .with_columns([
                # Annualized roll yield
                ((-pl.col('spread_pct') / 100) * 
                 (365 / (pl.col('expiry_back') - pl.col('expiry')).days) * 100
                ).alias('roll_yield_annual'),
                
                # Roll momentum
                pl.col('spread')
                  .diff()
                  .rolling_mean(window_size=window_minutes)
                  .alias('roll_momentum'),
                  
                # Roll volatility
                pl.col('spread')
                  .rolling_std(window_size=window_minutes)
                  .alias('roll_volatility')
            ])
        )
        
        return roll_metrics
    
    def analyze_futures_curve(self, symbols: list[str]) -> pl.DataFrame:
        """
        Analyze the entire futures curve.
        """
        # Get latest prices for all contract months
        latest = (self.df
            .filter(pl.col('Symbol').is_in(symbols))
            .group_by('Symbol')
            .tail(1)
        )
        
        # Calculate curve metrics
        curve = (latest
            .sort('expiry')
            .with_columns([
                pl.col('Close').diff().alias('curve_spread'),
                pl.col('Close').pct_change().alias('curve_return'),
                pl.col('Volume').alias('curve_volume')
            ])
        )
        
        return curve
    
    def calculate_implied_rates(self, spot_symbol: str, futures_symbol: str,
                              risk_free_rate: float) -> pl.DataFrame:
        """
        Calculate implied interest rates from futures-spot relationship.
        """
        basis = self.calculate_basis_risk(spot_symbol, futures_symbol)
        
        implied = (basis
            .with_columns([
                # Implied rate calculation
                (pl.log(pl.col('Close_futures') / pl.col('Close')) * 
                 (365 / (pl.col('expiry') - pl.col('Datetime')).days) * 100
                ).alias('implied_rate'),
                
                # Rate spread
                (pl.col('implied_rate') - risk_free_rate).alias('rate_spread')
            ])
        )
        
        return implied