# Energy Options Research Database

A data pipeline for downloading, processing, and analyzing energy price options data using Polars and DuckDB. This project creates a queryable database of historical energy options data for research purposes.

## Features

- Automated downloads of energy options data from multiple exchanges
- Fast data processing using Polars DataFrames
- Persistent storage in DuckDB with SQL querying capabilities
- Data quality checks and validation
- Configurable download schedules and data sources

## Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/energy-options-db.git
cd energy-options-db
```

2. Install uv if you haven't already:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

3. Create a virtual environment and install dependencies using uv:
```bash
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
uv pip install -r requirements.txt
```

Note: The project uses [uv](https://github.com/astral/uv) for dependency management due to its superior performance and reproducible builds.

## Project Structure

```
energy-options-db/
├── src/
│   ├── downloaders/       # Data download modules for different exchanges
│   ├── processors/        # Data cleaning and transformation
│   ├── database/          # DuckDB interface and schema management
│   └── utils/            # Helper functions and utilities
├── config/
│   ├── sources.yaml      # Data source configurations
│   └── schema.sql        # Database schema definitions
├── requirements.txt      # Project dependencies managed by uv
├── requirements-dev.txt  # Development dependencies
├── tests/                # Unit and integration tests
├── notebooks/           # Analysis notebooks
└── data/
    ├── raw/             # Downloaded raw data
    ├── processed/       # Cleaned and transformed data
    └── database/        # DuckDB database files
```

## Configuration

1. Copy the example configuration:
```bash
cp config/sources.example.yaml config/sources.yaml
```

2. Edit `config/sources.yaml` to set up your data sources and API keys:
```yaml
sources:
  exchange_name:
    api_key: your_api_key
    base_url: https://api.exchange.com
    instruments:
      - crude_oil_options
      - natural_gas_options
```

## Usage

1. Initialize the database:
```bash
python src/database/init_db.py
```

2. Download and process data:
```bash
python src/main.py --download-data
```

3. Query the database using DuckDB:
```python
import duckdb

# Connect to the database
con = duckdb.connect('data/database/energy_options.db')

# Example query
result = con.execute("""
    SELECT 
        date,
        instrument,
        strike,
        AVG(implied_volatility) as avg_iv
    FROM options
    WHERE date >= '2024-01-01'
    GROUP BY date, instrument, strike
    ORDER BY date
""").fetchdf()
```

## Data Model

The database schema includes the following main tables:

- `options`: Core options data
  - date: DATE
  - instrument: VARCHAR
  - strike: DECIMAL
  - expiry: DATE
  - call_put: VARCHAR
  - price: DECIMAL
  - implied_volatility: DECIMAL
  - volume: INTEGER
  - open_interest: INTEGER

- `underlying`: Underlying asset prices
  - date: DATE
  - instrument: VARCHAR
  - price: DECIMAL
  - volume: INTEGER

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

- Data provided by [Exchange Names]
- Built with [Polars](https://pola.rs/) and [DuckDB](https://duckdb.org/)