"""Tests for sentiment hardening: structured schema, TTL cache, rate limit, temp=0 (R13)."""

import types
from datetime import datetime, timezone

import polars as pl

from energex.analysis.market_sentiment import MarketSentimentAnalyzer, SentimentResult
from energex.config import get_settings


def _prices() -> pl.DataFrame:
    return pl.DataFrame(
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


def test_sentiment_result_clamps_out_of_range():
    r = SentimentResult(sentiment_score=5.0, confidence=2.0)
    assert r.sentiment_score == 1.0
    assert r.confidence == 1.0
    r2 = SentimentResult(sentiment_score=-9.0, confidence=-1.0)
    assert r2.sentiment_score == -1.0
    assert r2.confidence == 0.0


def test_sentiment_result_normalizes_trade_signal():
    assert SentimentResult(trade_signal="long").trade_signal == "LONG"
    assert SentimentResult(trade_signal="garbage").trade_signal == "NEUTRAL"


def test_rate_limiter_configured_from_settings():
    analyzer = MarketSentimentAnalyzer(_prices())
    assert analyzer._rate_limiter.max_calls == get_settings().llm.requests_per_minute


def test_ttl_cache_expires_and_recomputes():
    analyzer = MarketSentimentAnalyzer(_prices())
    analyzer.llm = None  # force deterministic rule-based path
    clock = {"t": 0.0}
    analyzer._clock = lambda: clock["t"]
    analyzer._cache_ttl = 100

    first = analyzer._analyze_article("Oil prices climb", "summary")
    assert len(analyzer._sentiment_cache) == 1

    clock["t"] = 50.0  # within TTL -> served from cache
    assert analyzer._analyze_article("Oil prices climb", "summary") == first

    clock["t"] = 250.0  # past TTL -> entry refreshed (still one key)
    analyzer._analyze_article("Oil prices climb", "summary")
    assert len(analyzer._sentiment_cache) == 1


def test_openai_provider_uses_temperature_zero(monkeypatch):
    from energex.llm_providers import OpenAIProvider

    captured: dict = {}

    class _Completions:
        @staticmethod
        def create(**kwargs):
            captured.update(kwargs)
            msg = types.SimpleNamespace(content='{"sentiment_score": 0.1, "confidence": 0.5}')
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)])

    fake_client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=_Completions()))
    provider = OpenAIProvider(api_key="k")
    monkeypatch.setattr(provider, "_get_client", lambda: fake_client)
    provider.generate_completion("sys", "user")
    assert captured["temperature"] == 0
