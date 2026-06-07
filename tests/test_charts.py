"""Tests that the Plotly charts build without raising (R3) + futures gating (R4)."""

import plotly.graph_objects as go
import pytest

from energex.visualization.charts import MarketVisualizer


def test_plot_price_quality_returns_figure(sample_ohlcv):
    fig = MarketVisualizer(sample_ohlcv).plot_price_quality("CL=F")
    assert isinstance(fig, go.Figure)


def test_plot_volatility_analysis_returns_figure(sample_ohlcv):
    # Previously raised NameError (numpy used but never imported).
    fig = MarketVisualizer(sample_ohlcv).plot_volatility_analysis("CL=F")
    assert isinstance(fig, go.Figure)


def test_plot_futures_curve_gated_until_data_model(sample_ohlcv):
    # Relies on an 'expiry' column that the schema does not have (R8).
    with pytest.raises(NotImplementedError):
        MarketVisualizer(sample_ohlcv).plot_futures_curve(["CL=F", "NG=F"])
