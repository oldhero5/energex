# Energex Examples - Complete Guide

This directory contains comprehensive examples demonstrating all features of energex v0.3.0, including the new market sentiment analysis capabilities.

## Quick Start

### Prerequisites

1. **Install energex with all features:**
   ```bash
   pip install energex[all]
   # OR for development:
   uv pip install -e ".[all]"
   ```

2. **Configure API keys (optional for sentiment analysis):**
   ```bash
   cp .env.example .env
   # Edit .env and add your API keys
   ```

### Setup Data (Required First Step)

**Before running any examples, populate the database:**

#### Option 1: Real-time Intraday Data (Markets Open)

```bash
python src/examples/00_setup_data.py
```

This script will:
- Initialize the DuckDB database
- Fetch recent 1-minute intraday market data for CL=F, BZ=F, NG=F
- Verify data integrity
- Take 2-3 minutes to complete

**Requirements:** Markets must be open (Sunday 6pm - Friday 5pm ET, excluding holidays)

#### Option 2: Historical Daily Data (Markets Closed) ⭐ Use This on Holidays

```bash
python src/examples/00_setup_data_historical.py
```

**Use this version when:**
- Markets are closed (weekends, Christmas, New Year's, etc.)
- Testing examples outside trading hours
- You need sample data immediately

This script will:
- Fetch the last 30 days of daily OHLCV data
- Works anytime, regardless of market status
- Perfect for testing and learning

**Note:** Examples will work with daily data, but analysis results will differ from real-time intraday usage

Expected output:
```
======================================================================
ENERGEX - Data Setup for Examples
======================================================================

[1/3] Initializing database...
✅ Database: ./data/energex.db

[2/3] Initializing data fetcher...
✅ Data fetcher ready

[3/3] Fetching market data...
This will take 2-3 minutes. Fetching:
  - CL=F (WTI Crude Oil)
  - BZ=F (Brent Crude)
  - NG=F (Natural Gas)

✅ Data fetch complete!
```

## Examples Overview

### 00_setup_data.py - Data Setup Script ⚙️

**Purpose:** Initial database population

**Run First:**
```bash
python src/examples/00_setup_data.py
```

**What it does:**
- Creates/initializes DuckDB database
- Fetches latest 1-minute intraday data
- Populates database for all examples
- Verifies data integrity

---

### 01_data_quality_analysis.py - Data Quality Checks ✅

**Purpose:** Detect anomalies and validate data quality

**Run:**
```bash
python src/examples/01_data_quality_analysis.py
```

**Demonstrates:**
- Price gap detection (threshold-based)
- Volume anomaly detection (z-score method)
- Price reversal identification
- Overall quality metrics calculation
- Interactive visualization generation

**Output:**
- Console: Quality metrics summary
- File: `quality_volume_anomalies.html`

**Key Concepts:**
- Data quality is critical for trading algorithms
- Anomalies can indicate market events or data issues
- Z-score method identifies statistical outliers

---

### 02_volatility_analysis.py - Volatility Metrics 📊

**Purpose:** Calculate and compare volatility measures

**Run:**
```bash
python src/examples/02_volatility_analysis.py
```

**Demonstrates:**
- **Realized Volatility** - Close-to-close returns
- **Parkinson Volatility** - High-low range estimator
- **Garman-Klass Volatility** - OHLC-based estimator
- Volatility ratio analysis
- Intraday range patterns

**Output:**
- Console: Volatility statistics per symbol
- Files: `volatility_CLF.html`, `volatility_BZF.html`, `volatility_NGF.html`

**Key Concepts:**
- Multiple volatility estimators capture different aspects
- Parkinson & Garman-Klass use more price information
- Volatility ratios indicate efficiency of estimators

---

### 03_futures_analysis.py - Futures Curve Analysis 📈

**Purpose:** Analyze futures term structure

**Run:**
```bash
python src/examples/03_futures_analysis.py
```

**Demonstrates:**
- Term structure analysis
- Roll yield calculations
- Basis risk measurement
- Implied interest rates
- Futures curve visualization

**Output:**
- Console: Futures analysis summary
- Notes on data requirements

**Key Concepts:**
- Contango vs Backwardation
- Roll yield impacts returns
- Term structure reflects supply/demand expectations

**Note:** Full analysis requires multiple contract months. This example demonstrates the API with available data.

---

### 04_sentiment_analysis.py - Market Sentiment ✨ NEW in v0.3.0

**Purpose:** AI-powered news sentiment analysis

**Prerequisites:**
- Configure at least one LLM provider in `.env`:
  ```bash
  DEFAULT_LLM_PROVIDER=openai
  OPENAI_API_KEY=sk-your-key-here
  ```
- OR use rule-based fallback (no API key required)

**Run:**
```bash
python src/examples/04_sentiment_analysis.py
```

**Demonstrates:**
- News fetching from RSS feeds and NewsAPI
- LLM-powered sentiment analysis
- Rule-based fallback (works without API keys)
- Time-aligned sentiment joining to price data
- Weighted sentiment aggregation
- Interactive sentiment overlay visualizations

**Output:**
- Console: Sentiment summary with distribution
- Files: `sentiment_CLF.html`, `sentiment_NGF.html`, `sentiment_BZF.html`

**Features:**
- **Multi-LLM Support:** OpenAI (GPT-4), Anthropic (Claude), Ollama (local)
- **Graceful Degradation:** Falls back to rule-based if LLM unavailable
- **Caching:** Prevents redundant API calls
- **Multiple Aggregation:** Mean, weighted by confidence, latest

**Key Concepts:**
- News sentiment can signal market direction
- LLMs provide nuanced analysis vs keyword matching
- Time-alignment critical for backtesting
- Confidence weighting improves signal quality

---

## Running All Examples

Execute examples in order:

```bash
# 1. Setup data (required first)
python src/examples/00_setup_data.py

# 2. Data quality analysis
python src/examples/01_data_quality_analysis.py

# 3. Volatility analysis
python src/examples/02_volatility_analysis.py

# 4. Futures analysis
python src/examples/03_futures_analysis.py

# 5. Sentiment analysis (requires API key or uses fallback)
python src/examples/04_sentiment_analysis.py
```

## Generated Files

After running all examples, you'll have:

**HTML Visualizations:**
- `quality_volume_anomalies.html` - Volume anomaly scatter plot
- `volatility_CLF.html` - WTI crude volatility dashboard
- `volatility_BZF.html` - Brent crude volatility dashboard
- `volatility_NGF.html` - Natural gas volatility dashboard
- `sentiment_CLF.html` - WTI sentiment overlay
- `sentiment_BZF.html` - Brent sentiment overlay  
- `sentiment_NGF.html` - Natural gas sentiment overlay

**Database:**
- `./data/energex.db` - DuckDB with price data

Open HTML files in your browser for interactive charts!

## Customization

### Modify Time Windows

```python
# Example: Analyze last 30 days instead of 7
query = """
SELECT * FROM intraday_prices
WHERE Datetime >= CURRENT_TIMESTAMP - INTERVAL '30' DAY
ORDER BY Symbol, Datetime
"""
```

### Add More Symbols

```python
# In 00_setup_data.py
db.insert_intraday_data(fetcher.fetch_all_commodities())
```

### Adjust Thresholds

```python
# More sensitive gap detection
gaps = checker.check_price_gaps(threshold_pct=0.1)

# Stricter volume anomalies
anomalies = checker.check_volume_anomalies(z_score_threshold=4.0)
```

### Change LLM Provider

```python
# Use Claude instead of GPT-4
analyzer = MarketSentimentAnalyzer(df, provider='anthropic')

# Use local Ollama
analyzer = MarketSentimentAnalyzer(df, provider='ollama')
```

## Troubleshooting

### "No data fetched" or "Markets are closed"

**Problem:** Running `00_setup_data.py` on Christmas, weekends, or market holidays

**Solution:** Use the historical data script instead:
```bash
python src/examples/00_setup_data_historical.py
```

This fetches daily historical data that works anytime, regardless of market status.

### "No data found in database"

**Solution:** Run `00_setup_data.py` (or `00_setup_data_historical.py`) first

### "Sentiment analysis not available"

**Solution:** Install sentiment dependencies:
```bash
pip install energex[sentiment]
```

### "LLM provider not available"

**Expected behavior** - Analyzer falls back to rule-based sentiment

**To use LLM:**
1. Add API key to `.env`
2. Verify provider name (openai, anthropic, ollama)
3. Check API key validity

### "No news articles found"

**Normal behavior** - RSS feeds may have no recent energy news

**Solutions:**
- Increase `hours_back` parameter (try 72 or 168)
- Add NewsAPI key to `.env` for more sources
- Fallback sentiment still works

### Network/Timeout Errors

**During data fetch:**
- Check internet connection
- Try again in a few minutes (Yahoo Finance rate limits)
- Reduce number of symbols

**During sentiment analysis:**
- LLM API timeouts are normal, retries happen automatically
- Falls back to rule-based if persistent failures

## Performance Notes

### Execution Times (Approximate)

- `00_setup_data.py`: 2-3 minutes (network-dependent)
- `01_data_quality_analysis.py`: 5-10 seconds
- `02_volatility_analysis.py`: 10-20 seconds
- `03_futures_analysis.py`: 5-10 seconds
- `04_sentiment_analysis.py`: 30-90 seconds (LLM API calls)

### Database Size

- ~50MB for 7 days of 1-minute data (3 symbols)
- Scales linearly with time window and symbols

### Memory Usage

- Data quality: <100MB RAM
- Volatility: <200MB RAM
- Sentiment: <500MB RAM (depends on article count)

## Next Steps

After running examples:

1. **Explore the code** - Examples are well-commented
2. **Modify parameters** - Experiment with thresholds
3. **Add custom analysis** - Build on existing analyzers
4. **Create trading signals** - Combine multiple indicators
5. **Backtest strategies** - Use sentiment + volatility
6. **Deploy to production** - See `docs/TESTING.md`

## Advanced Usage

### Custom Pipeline

```python
from energex import (
    EnergyDatabase,
    VolatilityAnalyzer,
    MarketSentimentAnalyzer
)

# Load data
db = EnergyDatabase()
df = pl.from_arrow(db.conn.execute("SELECT * FROM intraday_prices").arrow())

# Combined analysis
vol_analyzer = VolatilityAnalyzer(df)
vol_results = vol_analyzer.calculate_volatility_metrics()

sent_analyzer = MarketSentimentAnalyzer(df)
sentiment_df = sent_analyzer.analyze_news_sentiment(hours_back=48)

# Join volatility + sentiment
enriched = sent_analyzer.add_sentiment_to_prices(sentiment_df)
# Now you have: price, OHLCV, volatility metrics, sentiment scores
```

### Scheduled Updates

```python
# cron job or scheduler
import schedule

def update_data_and_analyze():
    fetcher = EnergyDataFetcher(db)
    db.insert_intraday_data(fetcher.fetch_all_commodities())
    # Run your analysis...

schedule.every(1).hour.do(update_data_and_analyze)
```

## Support

- **Documentation:** See main `README.md` and `docs/TESTING.md`
- **Issues:** https://github.com/yourusername/energex/issues
- **API Reference:** Check docstrings in source code

## License

MIT License - See LICENSE file for details

---

**Last Updated:** 2025-12-25
**Energex Version:** 0.3.0
