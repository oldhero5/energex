"""
Energex - Energy Derivatives Trading Data & Analysis
====================================================

A Python library for collecting, analyzing, and visualizing energy derivatives
trading data (Crude Oil, Brent, Natural Gas).

Features:
- Real-time data fetching from Yahoo Finance
- DuckDB-based storage with efficient querying
- Quality analysis, volatility metrics, futures analysis
- Market sentiment analysis using LLMs (OpenAI, Anthropic, Ollama)
- Interactive Plotly visualizations

Installation:
    Core functionality:
        pip install energex

    With sentiment analysis:
        pip install energex[sentiment]

    All optional features:
        pip install energex[all]

Quick Start:
    >>> from energex.database import EnergyDatabase
    >>> from energex.data_fetcher import EnergyDataFetcher
    >>> from energex.analysis import VolatilityAnalyzer
    >>>
    >>> # Fetch and store data
    >>> db = EnergyDatabase()
    >>> fetcher = EnergyDataFetcher(db)
    >>> fetcher.fetch_and_store(['CL=F', 'NG=F'])
    >>>
    >>> # Analyze volatility
    >>> import polars as pl
    >>> df = pl.from_arrow(db.conn.execute("SELECT * FROM intraday_prices").arrow())
    >>> analyzer = VolatilityAnalyzer(df)
    >>> results = analyzer.calculate_volatility_metrics()

Configuration:
    Create a .env file based on .env.example to configure:
    - LLM API keys (OpenAI, Anthropic, Ollama)
    - News API keys
    - Database settings
    - Logging preferences

For more examples, see: src/examples/
"""

__version__ = "0.3.0"
__author__ = "Marty H"
__license__ = "MIT"

# Core modules
# Analysis modules
from energex.analysis import (
    DataQualityChecker,
    FuturesAnalyzer,
    VolatilityAnalyzer,
    check_sentiment_available,
)
from energex.config import get_settings
from energex.data_fetcher import EnergyDataFetcher
from energex.database import EnergyDatabase

# Visualization
from energex.visualization import MarketVisualizer

# Conditionally import sentiment analyzer
try:
    from energex.analysis import MarketSentimentAnalyzer
except ImportError:
    # Optional dependencies not installed
    pass

# Configuration utilities
from energex.exceptions import (
    AnalysisError,
    ConfigurationError,
    DatabaseError,
    DataFetchError,
    EnergexError,
    LLMProviderError,
)

__all__ = [
    # Version
    "__version__",
    # Core
    "EnergyDatabase",
    "EnergyDataFetcher",
    "get_settings",
    # Analysis
    "DataQualityChecker",
    "VolatilityAnalyzer",
    "FuturesAnalyzer",
    "MarketSentimentAnalyzer",
    "check_sentiment_available",
    # Visualization
    "MarketVisualizer",
    # Exceptions
    "EnergexError",
    "ConfigurationError",
    "DataFetchError",
    "DatabaseError",
    "AnalysisError",
    "LLMProviderError",
]
