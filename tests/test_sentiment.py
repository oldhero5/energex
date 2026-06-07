"""Tests for sentiment correctness: look-ahead, timezones, fan-out, fallback (R6)."""

from datetime import datetime, timezone

import polars as pl
import pytest

from energex.analysis.market_sentiment import MarketSentimentAnalyzer
from energex.news_fetcher import NewsArticle


def _prices(symbols, times):
    rows = []
    for sym in symbols:
        for t in times:
            rows.append(
                {
                    "Datetime": t,
                    "Symbol": sym,
                    "Open": 1.0,
                    "High": 1.0,
                    "Low": 1.0,
                    "Close": 1.0,
                    "Volume": 1,
                }
            )
    return pl.DataFrame(rows)


def _sentiment_row(dt, symbol="CL=F", score=0.8):
    return pl.DataFrame(
        {
            "Datetime": [dt],
            "Symbol": [symbol],
            "news_title": ["headline"],
            "news_url": ["https://x/1"],
            "sentiment_score": [score],
            "confidence": [0.9],
            "impact_sector": ["Oil"],
            "trade_signal": ["LONG"],
            "key_factors": ["[]"],
        }
    )


def test_future_news_does_not_leak_onto_earlier_bar():
    t1015 = datetime(2024, 1, 2, 10, 15, tzinfo=timezone.utc)
    t1100 = datetime(2024, 1, 2, 11, 0, tzinfo=timezone.utc)
    prices = _prices(["CL=F"], [t1015, t1100])
    analyzer = MarketSentimentAnalyzer(prices)

    # News published 10:45 (inside the 10:00-11:00 window).
    sentiment = _sentiment_row(datetime(2024, 1, 2, 10, 45, tzinfo=timezone.utc))
    out = analyzer.add_sentiment_to_prices(sentiment, time_window="1h").sort("Datetime")

    at_1015 = out.filter(pl.col("Datetime") == t1015)["avg_sentiment"][0]
    at_1100 = out.filter(pl.col("Datetime") == t1100)["avg_sentiment"][0]
    assert at_1015 == 0.0  # earlier bar must not see the later news
    assert at_1100 == pytest.approx(0.8)


def test_join_handles_naive_price_and_aware_sentiment():
    # Price bars naive, news tz-aware — previously crashed with a SchemaError.
    prices = _prices(["CL=F"], [datetime(2024, 1, 2, 12, 0)])  # naive
    analyzer = MarketSentimentAnalyzer(prices)
    sentiment = _sentiment_row(datetime(2024, 1, 2, 9, 0, tzinfo=timezone.utc))
    out = analyzer.add_sentiment_to_prices(sentiment)
    assert "avg_sentiment" in out.columns
    assert out.height == 1


def test_specific_oil_headline_maps_to_single_symbol(monkeypatch):
    prices = _prices(["CL=F", "BZ=F", "NG=F"], [datetime(2024, 1, 2, 12, 0, tzinfo=timezone.utc)])
    analyzer = MarketSentimentAnalyzer(prices)
    analyzer.llm = None  # force rule-based path

    articles = [
        NewsArticle(
            title="Oil prices surge on OPEC production cuts",
            source="src",
            published_at=datetime(2024, 1, 2, 11, 0, tzinfo=timezone.utc),
            url="https://x/1",
            summary=None,
            symbols=None,  # general feed item -> assigned by impact sector
        )
    ]
    monkeypatch.setattr(analyzer.news_fetcher, "fetch_all", lambda *a, **k: articles)

    sdf = analyzer.analyze_news_sentiment(symbols=["CL=F", "BZ=F", "NG=F"])
    # 'Oil' sector maps to CL=F only — not triple-counted across all three.
    assert set(sdf["Symbol"].unique()) == {"CL=F"}


def test_non_json_llm_response_falls_back_to_rule_based():
    prices = _prices(["CL=F"], [datetime(2024, 1, 2, 12, 0, tzinfo=timezone.utc)])
    analyzer = MarketSentimentAnalyzer(prices)

    class BadLLM:
        def is_available(self):
            return True

        def generate_completion(self, system, user):
            return "this is not json"

    analyzer.llm = BadLLM()  # type: ignore[assignment]
    result = analyzer._analyze_article("Oil rises sharply", "summary")
    assert result["key_factors"] == ["Rule-based analysis"]


def test_malformed_numeric_field_does_not_abort():
    prices = _prices(["CL=F"], [datetime(2024, 1, 2, 12, 0, tzinfo=timezone.utc)])
    analyzer = MarketSentimentAnalyzer(prices)

    class TypeErrorLLM:
        def is_available(self):
            return True

        def generate_completion(self, system, user):
            # sentiment_score is an object -> min()/max() raise TypeError
            return '{"sentiment_score": {"bad": 1}, "confidence": 0.5}'

    analyzer.llm = TypeErrorLLM()  # type: ignore[assignment]
    result = analyzer._analyze_article("Gas falls", "summary")
    assert result["key_factors"] == ["Rule-based analysis"]
