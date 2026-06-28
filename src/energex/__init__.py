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
    >>> fetcher = EnergyDataFetcher()
    >>> data = fetcher.fetch_all_commodities()  # or get_commodity_data('crude')
    >>> with EnergyDatabase() as db:
    ...     db.insert_intraday_data(data)
    >>>
    >>> # Analyze volatility (read-only)
    >>> stored = EnergyDatabase(read_only=True).query("SELECT * FROM intraday_prices")
    >>> results = VolatilityAnalyzer(stored).calculate_volatility_metrics()

Configuration:
    Create a .env file based on .env.example to configure:
    - LLM API keys (OpenAI, Anthropic, Ollama)
    - News API keys
    - Database settings
    - Logging preferences

For more examples, see: src/examples/
"""

# Load the repo-root .env for local runs so every config — including nested sub-configs that
# read os.environ only (e.g. ConnectorConfig) — resolves credentials uniformly through
# os.environ, with real environment variables always taking precedence (load_dotenv never
# overrides an existing var). The path is resolved relative to THIS package, never via a
# CWD/parent-directory search (so a REPL/debugger cannot bind an unintended parent .env). The
# load is skipped when ENERGEX_SKIP_DOTENV=1 (the test suite sets this to preserve its
# no-credentials invariant); the deployment injects env via docker-compose and ships no .env.
import os
from pathlib import Path

if os.environ.get("ENERGEX_SKIP_DOTENV") != "1":
    from dotenv import load_dotenv

    _dotenv_path = Path(__file__).resolve().parents[2] / ".env"
    if _dotenv_path.is_file():
        load_dotenv(_dotenv_path)

# Pin ArcticDB's vendored AWS C SDK ahead of pyarrow's (phase-0 load-order hazard):
# whichever of libarrow / arcticdb_ext loads first wins the AWS symbols, and if
# pyarrow wins, ArcticDB's S3 client constructor aborts the process on macOS. The
# heavy imports below pull pyarrow, so arcticdb must load first. Best-effort: arcticdb
# is the optional `storage` extra, so a core-only install skips this silently.
try:
    import arcticdb as _arcticdb  # noqa: F401
except ImportError:
    pass

__version__ = "0.4.0"
__author__ = "Marty H"
__license__ = "PolyForm-Noncommercial-1.0.0"

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
