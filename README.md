# Energex: Energy Market Analysis Tools

A Python package for downloading, analyzing, and visualizing energy market data using Polars and DuckDB.

## Features

- Automated data collection from major energy markets
- Fast data processing using Polars DataFrames
- Persistent storage in DuckDB with SQL querying capabilities
- Technical analysis tools including:
  - Moving averages (20, 50, 200 days)
  - RSI (Relative Strength Index)
  - Trading signals (Golden Cross, Death Cross)
- Interactive visualizations using Plotly

## Installation

```bash
# Install using uv (recommended)
curl -LsSf https://astral.sh/uv/install.sh | sh
uv pip install energex

# Or using pip
pip install energex
```

## Quick Start

```python
from energex import TechnicalAnalyzer

# Initialize analyzer
analyzer = TechnicalAnalyzer()

# Analyze crude oil futures
df, signals, fig = analyzer.analyze("CL=F")

# Save analysis chart
fig.write_html("crude_oil_analysis.html")

# Print recent trading signals
print("Recent Trading Signals:")
print(signals)
```

## Project Structure

```
energex/
├── src/
│   ├── energex/
│   │   ├── __init__.py
│   │   ├── database.py       # DuckDB interface
│   │   ├── data_fetcher.py   # Data collection
│   │   └── analysis.py       # Technical analysis
│   └── examples/
│       ├── 01_basic_queries.py
│       ├── 02_technical_analysis.py
│       └── 03_spread_analysis.py
├── tests/                    # Unit and integration tests
├── pyproject.toml           # Project configuration
└── README.md
```

## Basic Usage

### 1. Query Historical Data

```python
from energex import EnergyQueryTool

# Initialize query tool
tool = EnergyQueryTool()

# Get latest prices
prices = tool.get_latest_prices()

# Get daily returns for crude oil
returns = tool.get_daily_returns("CL=F")

# Analyze trading volume
volume = tool.get_volume_analysis("NG=F")
```

### 2. Technical Analysis

```python
from energex import TechnicalAnalyzer

analyzer = TechnicalAnalyzer()

# Full analysis with visualization
df, signals, fig = analyzer.analyze("CL=F")

# Access individual components
df = analyzer.get_data("CL=F")
df = analyzer.add_moving_averages(df)
df = analyzer.add_rsi(df)
```

### 3. Spread Analysis

```python
from energex import SpreadAnalyzer

analyzer = SpreadAnalyzer()

# Analyze WTI-Brent spread
spread_data = analyzer.get_spread_data("CL=F", "BZ=F")
stats = analyzer.calculate_spread_stats(spread_data)
```

## Configuration

The package uses DuckDB for storage and can be configured through environment variables:

```bash
ENERGEX_DB_PATH=/path/to/database.db
ENERGEX_DATA_DIR=/path/to/data
```

## Development

1. Clone the repository:
```bash
git clone https://github.com/oldhero5/energex.git
cd energex
```

2. Set up the development environment:
```bash
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
uv pip install -e ".[dev]"
```

3. Run tests:
```bash
pytest tests/
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

- Data provided by Yahoo Finance
- Built with:
  - [Polars](https://pola.rs/)
  - [DuckDB](https://duckdb.org/)
  - [Plotly](https://plotly.com/)