# Energex

Energy derivatives data collection and analysis system with advanced analytics for futures trading.

## Features

### Data Collection
- Real-time intraday data fetching (1-minute intervals)
- Support for major energy futures contracts (CL=F, BZ=F, NG=F)
- Efficient storage using DuckDB
- Robust error handling and validation

### Analysis Tools
- **Data Quality**:
  - Price gap detection
  - Volume anomaly detection
  - OHLC consistency checks

- **Volatility Analysis**:
  - Realized volatility
  - Parkinson volatility estimator
  - Garman-Klass volatility
  - Intraday range analysis

- **Futures Analysis**:
  - Term structure analysis
  - Roll yield calculations
  - Basis risk measurement
  - Implied interest rates

- **Market Sentiment Analysis** ✨ *New in v0.3.0*:
  - AI-powered news sentiment analysis
  - Multi-LLM provider support (OpenAI, Anthropic, Ollama)
  - Automatic news aggregation from RSS feeds and NewsAPI
  - Time-aligned sentiment enrichment of price data
  - Graceful degradation with rule-based fallback

### Visualization
- Interactive Plotly charts
- Price and volume analysis
- Sentiment overlay visualizations
- Term structure curves
- Volatility metrics dashboards

## Installation

### Core Functionality
```bash
pip install energex
```

### With Sentiment Analysis
```bash
pip install energex[sentiment]
```

### All Optional Features
```bash
pip install energex[all]
```

## Quick Start

### Basic Usage

```python
import polars as pl
from energex import EnergyDatabase, EnergyDataFetcher, VolatilityAnalyzer

# Initialize database and fetcher
db = EnergyDatabase()
fetcher = EnergyDataFetcher()

# Fetch and store data
data = fetcher.fetch_all_commodities()
db.insert_intraday_data(data)

# Query and analyze
query = "SELECT * FROM intraday_prices WHERE Symbol = 'CL=F'"
df = pl.from_arrow(db.conn.execute(query).arrow())

analyzer = VolatilityAnalyzer(df)
results = analyzer.calculate_volatility_metrics()
print(results)
```

### Sentiment Analysis

```python
from energex import MarketSentimentAnalyzer, check_sentiment_available

# Check if sentiment analysis is available
if check_sentiment_available():
    # Initialize analyzer with price data
    analyzer = MarketSentimentAnalyzer(df)

    # Fetch and analyze news sentiment
    sentiment_df = analyzer.analyze_news_sentiment(hours_back=48)

    # Join sentiment to price data
    enriched_df = analyzer.add_sentiment_to_prices(
        sentiment_df,
        aggregation='weighted'
    )

    # Get summary
    summary = analyzer.get_sentiment_summary(sentiment_df)
    for symbol, avg in summary["avg_sentiment_by_symbol"].items():
        print(f"  {symbol}: {avg:.3f}")
```

## Configuration

Energex uses environment variables for configuration. Create a `.env` file in your project root:

```bash
# LLM Provider (for sentiment analysis)
DEFAULT_LLM_PROVIDER=openai  # or anthropic, ollama
DEFAULT_LLM_MODEL=gpt-4

# API Keys
OPENAI_API_KEY=sk-your-key-here
ANTHROPIC_API_KEY=sk-ant-your-key-here

# Local LLM (Ollama)
OLLAMA_BASE_URL=http://localhost:11434

# News Sources (optional)
NEWS_NEWS_API_KEY=your-newsapi-key

# Database
DATABASE_PATH=./data/energex.db

# Logging
LOG_LEVEL=INFO
```

See [.env.example](.env.example) for all available configuration options.

## Examples

Complete examples are available in the `src/examples/` directory:

- `01_data_quality_analysis.py` - Data quality checks and validation
- `02_volatility_analysis.py` - Volatility metrics and visualization
- `03_futures_analysis.py` - Futures term structure analysis
- `04_sentiment_analysis.py` - Market sentiment analysis with LLMs

Run an example:
```bash
python src/examples/04_sentiment_analysis.py
```

## Contributing

Contributions are welcome! Please read our [Contributing Guidelines](CONTRIBUTING.md) for details.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.