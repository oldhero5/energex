"""Analysis modules for energy derivatives trading."""

from energex.analysis.dated_futures import DatedFuturesAnalyzer
from energex.analysis.futures import FuturesAnalyzer
from energex.analysis.quality import DataQualityChecker
from energex.analysis.volatility import VolatilityAnalyzer

# Conditional import for MarketSentimentAnalyzer (requires optional dependencies)
try:
    from energex.analysis.market_sentiment import MarketSentimentAnalyzer

    _SENTIMENT_AVAILABLE = True
except ImportError:
    _SENTIMENT_AVAILABLE = False
    MarketSentimentAnalyzer = None  # type: ignore


def check_sentiment_available() -> bool:
    """
    Check if sentiment analysis is available.

    Returns:
        True if MarketSentimentAnalyzer can be imported, False otherwise.

    Note:
        Sentiment analysis requires optional dependencies.
        Install with: pip install energex[sentiment]
    """
    return _SENTIMENT_AVAILABLE


__all__ = [
    "DataQualityChecker",
    "VolatilityAnalyzer",
    "FuturesAnalyzer",
    "DatedFuturesAnalyzer",
    "MarketSentimentAnalyzer",
    "check_sentiment_available",
]
