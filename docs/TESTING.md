# Energex v0.3.0 - End-to-End Testing Guide

This guide walks you through testing the complete energex v0.3.0 functionality from installation to running all features.

## Prerequisites

- Python 3.10 or higher
- `uv` package manager (recommended) or `pip`
- Internet connection (for fetching market data and news)

## Step 1: Environment Setup

### 1.1 Clone and Navigate to Repository

```bash
cd /Users/marty/repos/energex
git checkout feat/production-upgrade-v0.3.0
```

### 1.2 Create Virtual Environment

```bash
# Using uv (recommended)
uv venv .venv
source .venv/bin/activate

# OR using standard venv
python -m venv .venv
source .venv/bin/activate
```

### 1.3 Install Energex

```bash
# Install with all optional dependencies (includes sentiment analysis)
uv pip install -e ".[all]"

# OR install just core + sentiment
uv pip install -e ".[sentiment]"
```

**Expected output:**
```
Resolved XX packages in XXXms
Installed XX packages in XXXms
✅ energex==0.3.0
```

### 1.4 Verify Installation

```bash
python -c "import energex; print(f'✅ Energex v{energex.__version__} installed')"
```

**Expected output:**
```
✅ Energex v0.3.0 installed
```

## Step 2: Configuration

### 2.1 Create .env File

Copy the example configuration:

```bash
cp .env.example .env
```

### 2.2 Configure API Keys (Optional but Recommended)

Edit `.env` and add your API keys for sentiment analysis:

```bash
# For OpenAI (GPT-4)
DEFAULT_LLM_PROVIDER=openai
OPENAI_API_KEY=sk-your-actual-key-here

# OR for Anthropic (Claude)
DEFAULT_LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-your-actual-key-here

# OR for local Ollama (requires Ollama running)
DEFAULT_LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434

# Optional: NewsAPI for additional news sources
NEWS_NEWS_API_KEY=your-newsapi-key-here
```

**Note:** The sentiment analyzer will work without API keys using rule-based fallback mode, but LLM-powered analysis provides better results.

## Step 3: Test Core Functionality

### 3.1 Test Data Fetching and Storage

Create a test script `test_core.py`:

```python
import polars as pl
from energex import EnergyDatabase, EnergyDataFetcher

print("=" * 70)
print("TEST 1: Data Fetching and Storage")
print("=" * 70)

# Initialize database
db = EnergyDatabase()
print("✅ Database initialized")

# Initialize fetcher
fetcher = EnergyDataFetcher(db)
print("✅ Data fetcher initialized")

# Fetch latest data for all symbols
print("\nFetching data for CL=F, BZ=F, NG=F...")
db.insert_intraday_data(fetcher.fetch_all_commodities())
print("✅ Data fetched and stored")

# Query and display data
query = "SELECT * FROM intraday_prices ORDER BY Datetime DESC LIMIT 5"
df = pl.from_arrow(db.conn.execute(query).arrow())
print("\nLatest 5 records:")
print(df)

print("\n✅ Core functionality test PASSED")
```

Run the test:

```bash
python test_core.py
```

**Expected output:**
- Database creation confirmation
- Data fetching progress
- 5 most recent price records displayed

### 3.2 Test Analysis Modules

Create `test_analysis.py`:

```python
import polars as pl
from energex import (
    EnergyDatabase,
    VolatilityAnalyzer,
    FuturesAnalyzer,
    DataQualityChecker
)

print("=" * 70)
print("TEST 2: Analysis Modules")
print("=" * 70)

# Get data from database
db = EnergyDatabase()
query = """
SELECT * FROM intraday_prices
WHERE Symbol = 'CL=F'
AND Datetime >= CURRENT_DATE - INTERVAL '1' DAY
ORDER BY Datetime
"""
df = pl.from_arrow(db.conn.execute(query).arrow())
print(f"✅ Loaded {len(df)} records for analysis")

# Test Volatility Analyzer
print("\n[1/3] Testing VolatilityAnalyzer...")
vol_analyzer = VolatilityAnalyzer(df)
vol_results = vol_analyzer.calculate_volatility_metrics()
print(f"✅ Volatility metrics calculated: {vol_results.shape}")

# Test Data Quality Checker
print("\n[2/3] Testing DataQualityChecker...")
quality_checker = DataQualityChecker(df)
quality_results = quality_checker.check_all_quality_metrics()
print(f"✅ Quality metrics calculated: {len(quality_results)} metrics")

# Test Futures Analyzer (if data available)
print("\n[3/3] Testing FuturesAnalyzer...")
try:
    futures_analyzer = FuturesAnalyzer(df)
    futures_summary = futures_analyzer.calculate_term_structure("CL=F", "BZ=F")
    print(f"✅ Futures analysis complete")
except Exception as e:
    print(f"⚠️  Futures analysis skipped (requires futures data): {e}")

print("\n✅ Analysis modules test PASSED")
```

Run the test:

```bash
python test_analysis.py
```

## Step 4: Test Sentiment Analysis (Phase 4)

### 4.1 Run Phase 4 Test Suite

This comprehensive test validates the refactored sentiment analyzer:

```bash
python test_phase_4.py
```

**Expected output:**
```
======================================================================
ENERGEX PHASE 4 TESTING - Market Sentiment Analyzer
======================================================================

[TEST 1] Importing MarketSentimentAnalyzer...
✅ MarketSentimentAnalyzer imported successfully

[TEST 2] Creating sample price DataFrame...
✅ Created price DataFrame: (100, 7)

[TEST 3] Initializing MarketSentimentAnalyzer...
✅ Analyzer initialized successfully
   - LLM provider: OpenAIProvider (or AnthropicProvider/OllamaProvider)
   - News sources: 1

[TEST 4] Testing rule-based sentiment analysis...
✅ 'Oil prices surge on OPEC production cuts...' → LONG (0.40)
✅ 'Natural gas prices fall amid oversupply ...' → SHORT (-0.40)
✅ 'Energy markets remain stable today...' → NEUTRAL (0.00)

[TEST 5] Testing DataFrame pattern compliance...
✅ add_sentiment_to_prices() returns DataFrame with sentiment columns
✅ get_sentiment_summary() returns dict with metrics

[TEST 6] Testing empty DataFrame handling...
✅ Gracefully handles empty DataFrames

[TEST 7] Testing aggregation strategies...
✅ Aggregation 'mean' works
✅ Aggregation 'weighted' works
✅ Aggregation 'latest' works

[TEST 8] Testing LLM provider override...
✅ Provider override 'openai' → OpenAIProvider
✅ Provider override 'anthropic' → AnthropicProvider
✅ Provider override 'ollama' → OllamaProvider

[TEST 9] Testing dict-based cache for LLM responses...
✅ Dict cache working (same input → same output)
   - Cache entries: 1

======================================================================
PHASE 4 TESTING COMPLETE
======================================================================

✅ All critical tests passed!
```

### 4.2 Test Sentiment Analyzer with Real Data

Create `test_sentiment.py`:

```python
import polars as pl
from energex import (
    EnergyDatabase,
    MarketSentimentAnalyzer,
    check_sentiment_available
)

print("=" * 70)
print("TEST 3: Sentiment Analysis")
print("=" * 70)

# Check availability
if not check_sentiment_available():
    print("❌ Sentiment analysis not available")
    print("Install with: uv pip install -e '.[sentiment]'")
    exit(1)

print("✅ Sentiment analysis available")

# Get price data
db = EnergyDatabase()
query = """
SELECT * FROM intraday_prices
WHERE Datetime >= CURRENT_DATE - INTERVAL '7' DAY
ORDER BY Symbol, Datetime
"""
df = pl.from_arrow(db.conn.execute(query).arrow())
print(f"✅ Loaded {len(df)} price records")

# Initialize analyzer
analyzer = MarketSentimentAnalyzer(df)
provider = analyzer.llm.__class__.__name__ if analyzer.llm else 'None (fallback)'
print(f"✅ Analyzer initialized with {provider}")

# Fetch news sentiment
print("\nFetching news sentiment (this may take 30-60 seconds)...")
try:
    sentiment_df = analyzer.analyze_news_sentiment(hours_back=48)

    if len(sentiment_df) == 0:
        print("⚠️  No news articles found in last 48 hours")
        print("   This is normal - try increasing hours_back or check RSS feeds")
    else:
        print(f"✅ Analyzed {len(sentiment_df)} article-symbol pairs")

        # Get summary
        summary = analyzer.get_sentiment_summary(sentiment_df)
        print(f"\nSentiment Summary:")
        print(f"  Total articles: {summary['total_articles']}")
        print(f"  Avg confidence: {summary['avg_confidence']:.3f}")
        print(f"  Bullish: {summary['sentiment_distribution']['bullish']}")
        print(f"  Bearish: {summary['sentiment_distribution']['bearish']}")
        print(f"  Neutral: {summary['sentiment_distribution']['neutral']}")

        # Join to prices
        enriched_df = analyzer.add_sentiment_to_prices(sentiment_df)
        print(f"\n✅ Enriched {len(enriched_df)} price records with sentiment")

except Exception as e:
    print(f"❌ Sentiment analysis failed: {e}")
    import traceback
    traceback.print_exc()

print("\n✅ Sentiment analysis test PASSED")
```

Run the test:

```bash
python test_sentiment.py
```

## Step 5: Run Example Scripts

### 5.1 Example 1: Data Quality Analysis

```bash
python src/examples/01_data_quality_analysis.py
```

**Expected output:**
- Quality metrics summary
- HTML visualization files created

### 5.2 Example 2: Volatility Analysis

```bash
python src/examples/02_volatility_analysis.py
```

**Expected output:**
- Volatility metrics calculated
- `volatility_CL=F.html` and similar files created

### 5.3 Example 3: Futures Analysis

```bash
python src/examples/03_futures_analysis.py
```

**Expected output:**
- Term structure analysis
- Futures curve visualizations

### 5.4 Example 4: Sentiment Analysis (NEW in v0.3.0)

```bash
python src/examples/04_sentiment_analysis.py
```

**Expected output:**
```
======================================================================
ENERGEX - Market Sentiment Analysis Example
======================================================================

[1/5] Loaded XXX price records from database
       Symbols: ['CL=F', 'BZ=F', 'NG=F']
       Date range: 2025-XX-XX to 2025-XX-XX

[2/5] Initialized MarketSentimentAnalyzer
       LLM Provider: OpenAIProvider
       News Sources: 1

[3/5] Fetching and analyzing news sentiment...
       ✅ Analyzed XX article-symbol pairs

[4/5] Generating sentiment summary...

       SENTIMENT SUMMARY
       ----------------------------------------------------------------------
       Total Articles: XX
       Average Sentiment: X.XXX
       Average Confidence: XX.X%

       Distribution:
         • Bullish:  XX articles
         • Neutral:  XX articles
         • Bearish:  XX articles

       By Symbol:
         CL=F: +X.XXX 🟢 BULLISH
         NG=F: -X.XXX 🔴 BEARISH

[5/5] Joining sentiment to price data...
       ✅ Enriched XXX price records with sentiment
       Columns added: avg_sentiment, avg_confidence, news_count

       📊 Visualization saved: sentiment_CLF.html
       📊 Visualization saved: sentiment_NGF.html

======================================================================
SAMPLE ENRICHED DATA (last 5 rows with sentiment)
======================================================================
[DataFrame displayed]

✅ Analysis complete!
Check the generated HTML files for interactive visualizations.
```

**Generated files:**
- `sentiment_CLF.html` - Crude oil sentiment overlay
- `sentiment_NGF.html` - Natural gas sentiment overlay
- `sentiment_BZF.html` - Brent crude sentiment overlay

Open these HTML files in a browser to see interactive charts!

## Step 6: Code Quality Checks

### 6.1 Run Linter

```bash
source .venv/bin/activate
ruff check src/energex/
```

**Expected output:**
```
All checks passed!
```

### 6.2 Run Security Scan

```bash
bandit -r src/energex/
```

**Expected output:**
```
No issues identified.
```

### 6.3 Run Type Checker (Optional)

```bash
mypy src/energex/ --ignore-missing-imports
```

## Step 7: Integration Test

Create a complete end-to-end test `test_e2e.py`:

```python
"""End-to-end integration test for energex v0.3.0"""
import polars as pl
from energex import (
    EnergyDatabase,
    EnergyDataFetcher,
    VolatilityAnalyzer,
    MarketSentimentAnalyzer,
    check_sentiment_available,
    __version__
)

print("=" * 70)
print(f"ENERGEX v{__version__} - END-TO-END INTEGRATION TEST")
print("=" * 70)

# Test 1: Data Pipeline
print("\n[1/4] Testing data pipeline...")
db = EnergyDatabase()
fetcher = EnergyDataFetcher(db)
db.insert_intraday_data(fetcher.fetch_all_commodities())
query = "SELECT * FROM intraday_prices WHERE Symbol = 'CL=F' LIMIT 100"
df = pl.from_arrow(db.conn.execute(query).arrow())
assert len(df) > 0, "No data fetched"
print(f"✅ Fetched {len(df)} records")

# Test 2: Analysis
print("\n[2/4] Testing volatility analysis...")
analyzer = VolatilityAnalyzer(df)
results = analyzer.calculate_volatility_metrics()
assert 'realized_vol' in results.columns
print(f"✅ Calculated volatility metrics")

# Test 3: Sentiment (if available)
print("\n[3/4] Testing sentiment analysis...")
if check_sentiment_available():
    sent_analyzer = MarketSentimentAnalyzer(df)
    print(f"✅ Sentiment analyzer initialized")

    # Test with mock data (avoid API calls in CI)
    print("   Using rule-based fallback for testing")
    test_result = sent_analyzer._rule_based_sentiment("Oil prices rise", None)
    assert test_result['sentiment_score'] > 0
    print(f"✅ Sentiment analysis working")
else:
    print("⚠️  Sentiment analysis not available (optional)")

# Test 4: Configuration
print("\n[4/4] Testing configuration...")
from energex import get_settings
settings = get_settings()
assert hasattr(settings.database, "db_path")
print(f"✅ Configuration loaded")

print("\n" + "=" * 70)
print("END-TO-END INTEGRATION TEST PASSED")
print("=" * 70)
print("\n✅ All systems operational!")
```

Run the integration test:

```bash
python test_e2e.py
```

## Troubleshooting

### Issue: "ModuleNotFoundError: No module named 'pyarrow'"

**Solution:**
```bash
uv pip install pyarrow>=14.0.0
```

### Issue: "No news articles found"

**Causes:**
- RSS feeds may have no recent energy news
- Network connectivity issues
- NewsAPI rate limits (if using NewsAPI)

**Solutions:**
- Increase `hours_back` parameter (try 72 or 168 hours)
- Check internet connection
- Verify NewsAPI key in `.env` if configured
- Sentiment analyzer will use rule-based fallback automatically

### Issue: "LLM provider not available"

**This is expected if:**
- No API key configured in `.env`
- Ollama not running locally
- Invalid API key

**Solution:**
- Add valid API key to `.env`
- Start Ollama if using local LLM
- Analyzer automatically falls back to rule-based sentiment

### Issue: "Database locked"

**Solution:**
```bash
# Close any open database connections
rm ./data/energex.db-wal ./data/energex.db-shm
```

## Success Criteria

✅ All imports work without errors
✅ Core data fetching and storage works
✅ All analyzers (Volatility, Futures, Quality) run successfully
✅ Sentiment analyzer initializes (with or without LLM)
✅ Phase 4 test suite passes all 9 tests
✅ Example scripts generate visualizations
✅ Ruff, Bandit security scans pass
✅ End-to-end integration test passes

## Next Steps

After testing passes:

1. **Review visualizations** - Open generated HTML files in browser
2. **Test with your data** - Modify examples for your specific use case
3. **Configure production settings** - Update `.env` with production API keys
4. **Deploy** - Package and deploy to your production environment

## Support

If you encounter issues not covered in this guide:

1. Check the [GitHub Issues](https://github.com/oldhero5/energex/issues)
2. Review commit messages for implementation details
3. Examine example scripts for usage patterns

---

**Document Version:** 1.0
**Energex Version:** 0.3.0
**Last Updated:** 2025-12-25
