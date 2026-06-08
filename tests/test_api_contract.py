"""Guards that the documented public API matches reality (R12).

These fail if the docs/examples drift back to the old fictional API.
"""

from datetime import datetime, timezone

import polars as pl

from energex.analysis.market_sentiment import MarketSentimentAnalyzer
from energex.config import get_settings
from energex.data_fetcher import EnergyDataFetcher


def test_fetcher_exposes_real_methods_not_fictional_ones():
    fetcher = EnergyDataFetcher()
    assert hasattr(fetcher, "get_commodity_data")
    assert hasattr(fetcher, "fetch_all_commodities")
    assert not hasattr(fetcher, "fetch_and_store")  # the old docs claimed this


def test_sentiment_summary_uses_documented_keys():
    prices = pl.DataFrame(
        {
            "Datetime": [datetime(2024, 1, 2, 12, tzinfo=timezone.utc)],
            "Symbol": ["CL=F"],
            "Open": [1.0],
            "High": [1.0],
            "Low": [1.0],
            "Close": [1.0],
            "Volume": [1],
        }
    )
    sentiment = pl.DataFrame(
        {
            "Datetime": [datetime(2024, 1, 2, 11, tzinfo=timezone.utc)],
            "Symbol": ["CL=F"],
            "news_title": ["t"],
            "news_url": ["u"],
            "sentiment_score": [0.5],
            "confidence": [0.8],
            "impact_sector": ["Oil"],
            "trade_signal": ["LONG"],
            "key_factors": ["[]"],
        }
    )
    summary = MarketSentimentAnalyzer(prices).get_sentiment_summary(sentiment)
    assert "avg_sentiment_by_symbol" in summary
    assert "avg_confidence" in summary
    assert "avg_sentiment" not in summary  # the key the old docs referenced
    assert "by_symbol" not in summary


def test_settings_database_uses_db_path():
    settings = get_settings()
    assert hasattr(settings.database, "db_path")
    assert not hasattr(settings.database, "path")
