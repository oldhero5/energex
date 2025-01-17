import polars as pl
import yfinance as yf
import duckdb

prices = yf.download("NVDA", start='2023-01-01', end='2024-01-01')

df = (
    pl.from_pandas(
        prices.reset_index()
    )
    .with_columns(
        [pl.lit("NVDA").alias("symbol")]
    )
)

print(df)

con= duckdb.connect('stocks.db')
con.execute("""
             CREATE TABLE IF NOT EXISTS stocks AS SELECT * FROM df
             """)
