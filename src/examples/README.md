# Energy Market Analysis Examples

This directory contains example scripts demonstrating how to use the energex package for analyzing energy futures markets.

## Examples Overview

### 1. Data Quality Analysis (`01_data_quality_analysis.py`)
Demonstrates how to:
- Check for price gaps and anomalies
- Detect volume spikes
- Identify price reversals
- Generate data quality metrics
- Visualize anomalies

### 2. Volatility Analysis (`02_volatility_analysis.py`)
Shows how to:
- Calculate realized volatility
- Compute Parkinson volatility
- Estimate Garman-Klass volatility
- Compare different volatility measures
- Visualize volatility patterns

### 3. Futures Analysis (`03_futures_analysis.py`)
Illustrates:
- Term structure analysis
- Roll yield calculations
- Futures curve analysis
- Implied rate calculations
- Spread visualization

## Running the Examples

1. Make sure you have the database populated:
```bash
python -m energex.main
```

2. Run any example script:
```bash
python 01_data_quality_analysis.py
python 02_volatility_analysis.py
python 03_futures_analysis.py
```

## Output
Each script generates:
- Console output with key metrics and statistics
- Interactive HTML visualizations
- Summary reports of the analysis

## Customization
You can modify the parameters in each script to:
- Adjust analysis thresholds
- Change time windows
- Modify visualization settings
- Add new contracts or symbols

## Next Steps
After running these examples, you might want to:
1. Create custom analysis pipelines
2. Add more sophisticated trading signals
3. Implement real-time monitoring
4. Develop trading strategies