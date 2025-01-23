# src/energex/visualization/charts.py
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import polars as pl
from datetime import datetime, timedelta

class MarketVisualizer:
    def __init__(self, df: pl.DataFrame):
        self.df = df
    
    def plot_price_quality(self, symbol: str) -> go.Figure:
        """
        Create price quality visualization with anomaly detection.
        """
        df = self.df.filter(pl.col('Symbol') == symbol)
        
        fig = make_subplots(rows=3, cols=1,
                           shared_xaxes=True,
                           vertical_spacing=0.05,
                           subplot_titles=('Price', 'Volume', 'Quality Metrics'),
                           row_heights=[0.5, 0.25, 0.25])
        
        # Price chart with gaps highlighted
        fig.add_trace(
            go.Scatter(x=df['Datetime'], y=df['Close'],
                      name='Price', line=dict(color='blue')),
            row=1, col=1
        )
        
        # Add OHLC candlesticks
        fig.add_trace(
            go.Candlestick(x=df['Datetime'],
                          open=df['Open'],
                          high=df['High'],
                          low=df['Low'],
                          close=df['Close'],
                          name='OHLC'),
            row=1, col=1
        )
        
        # Volume with anomalies
        fig.add_trace(
            go.Bar(x=df['Datetime'], y=df['Volume'],
                  name='Volume'),
            row=2, col=1
        )
        
        # Price reversals and gaps
        price_changes = df.with_columns([
            pl.col('Close').pct_change().alias('price_change')
        ])
        
        fig.add_trace(
            go.Scatter(x=price_changes['Datetime'], 
                      y=price_changes['price_change'],
                      name='Price Changes',
                      mode='lines+markers',
                      marker=dict(
                          color=price_changes['price_change'].abs(),
                          colorscale='RdYlBu',
                          showscale=True
                      )),
            row=3, col=1
        )
        
        fig.update_layout(
            title=f'{symbol} Price Quality Analysis',
            height=800,
            showlegend=True
        )
        
        return fig

    def plot_volatility_analysis(self, symbol: str) -> go.Figure:
        """
        Create volatility analysis visualization.
        """
        df = self.df.filter(pl.col('Symbol') == symbol)
        
        fig = make_subplots(rows=2, cols=2,
                           subplot_titles=('Realized Volatility',
                                         'Volatility Metrics',
                                         'Intraday Range',
                                         'Volume Profile'))
        
        # Realized volatility
        vol_metrics = df.with_columns([
            pl.col('Close')
              .pct_change()
              .rolling_std(window_size=30)
              .mul(np.sqrt(252 * 1440))
              .alias('realized_vol')
        ])
        
        fig.add_trace(
            go.Scatter(x=vol_metrics['Datetime'],
                      y=vol_metrics['realized_vol'],
                      name='Realized Vol'),
            row=1, col=1
        )
        
        # Volatility metrics (High-Low range)
        fig.add_trace(
            go.Scatter(x=df['Datetime'],
                      y=((df['High'] - df['Low']) / df['Open'] * 100),
                      name='H-L Range %'),
            row=1, col=2
        )
        
        # Intraday range analysis
        fig.add_trace(
            go.Box(y=((df['High'] - df['Low']) / df['Open'] * 100),
                  name='Range Distribution'),
            row=2, col=1
        )
        
        # Volume profile
        fig.add_trace(
            go.Histogram(y=df['Close'],
                        weights=df['Volume'],
                        nbinsy=50,
                        name='Volume Profile',
                        orientation='h'),
            row=2, col=2
        )
        
        fig.update_layout(
            title=f'{symbol} Volatility Analysis',
            height=800,
            showlegend=True
        )
        
        return fig
    
    def plot_term_structure(self, front_symbol: str, back_symbol: str) -> go.Figure:
        """
        Create term structure and spread visualization.
        """
        front = self.df.filter(pl.col('Symbol') == front_symbol)
        back = self.df.filter(pl.col('Symbol') == back_symbol)
        
        fig = make_subplots(rows=2, cols=1,
                           shared_xaxes=True,
                           subplot_titles=('Contract Prices', 'Spread'),
                           row_heights=[0.6, 0.4])
        
        # Contract prices
        fig.add_trace(
            go.Scatter(x=front['Datetime'],
                      y=front['Close'],
                      name=f'{front_symbol}'),
            row=1, col=1
        )
        
        fig.add_trace(
            go.Scatter(x=back['Datetime'],
                      y=back['Close'],
                      name=f'{back_symbol}'),
            row=1, col=1
        )
        
        # Calculate and plot spread
        spreads = front.join(
            back,
            on='Datetime',
            suffix='_back'
        ).with_columns([
            (pl.col('Close') - pl.col('Close_back')).alias('spread')
        ])
        
        fig.add_trace(
            go.Scatter(x=spreads['Datetime'],
                      y=spreads['spread'],
                      name='Spread',
                      fill='tozeroy'),
            row=2, col=1
        )
        
        fig.update_layout(
            title=f'Term Structure Analysis: {front_symbol} vs {back_symbol}',
            height=800,
            showlegend=True
        )
        
        return fig
    
    def plot_futures_curve(self, symbols: list[str]) -> go.Figure:
        """
        Create futures curve visualization.
        """
        # Get latest prices for all contracts
        latest = (self.df
            .filter(pl.col('Symbol').is_in(symbols))
            .group_by('Symbol')
            .tail(1)
        )
        
        fig = go.Figure()
        
        # Plot current curve
        fig.add_trace(
            go.Scatter(x=latest['expiry'],
                      y=latest['Close'],
                      mode='lines+markers',
                      name='Futures Curve')
        )
        
        # Add volume bubbles
        fig.add_trace(
            go.Scatter(x=latest['expiry'],
                      y=latest['Close'],
                      mode='markers',
                      marker=dict(
                          size=latest['Volume'],
                          sizeref=2.*max(latest['Volume'])/(40.**2),
                          sizemin=4
                      ),
                      name='Volume')
        )
        
        fig.update_layout(
            title='Futures Curve Analysis',
            xaxis_title='Expiry',
            yaxis_title='Price',
            height=600,
            showlegend=True
        )
        
        return fig