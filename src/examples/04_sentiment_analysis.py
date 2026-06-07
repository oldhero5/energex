# examples/04_sentiment_analysis.py
"""
Market Sentiment Analysis Example

This example demonstrates how to use the MarketSentimentAnalyzer to:
1. Fetch and analyze energy market news sentiment
2. Join sentiment data to price data
3. Visualize price movements with sentiment overlays
4. Generate sentiment summary reports

Requirements:
    pip install energex[sentiment]

    Configure .env with at least one LLM provider:
    - OPENAI_API_KEY=sk-...
    - ANTHROPIC_API_KEY=sk-ant-...
    - OLLAMA_BASE_URL=http://localhost:11434

Optional: NewsAPI key for additional news sources
    - NEWS_NEWS_API_KEY=...
"""


import plotly.graph_objects as go
import polars as pl
from plotly.subplots import make_subplots

from energex import EnergyDatabase, MarketSentimentAnalyzer, check_sentiment_available


def analyze_sentiment():
    """Example of using the MarketSentimentAnalyzer."""

    # Check if sentiment analysis is available
    if not check_sentiment_available():
        print("❌ Sentiment analysis not available.")
        print("Install with: pip install energex[sentiment]")
        return

    print("=" * 70)
    print("ENERGEX - Market Sentiment Analysis Example")
    print("=" * 70)

    # Connect to database
    db = EnergyDatabase()

    # Get recent price data (last 7 days)
    query = """
    SELECT *
    FROM intraday_prices
    WHERE Datetime >= CURRENT_DATE - INTERVAL '7' DAY
    ORDER BY Symbol, Datetime
    """
    price_df = pl.from_arrow(db.conn.execute(query).arrow())

    print(f"\n[1/5] Loaded {len(price_df)} price records from database")
    print(f"       Symbols: {price_df['Symbol'].unique().to_list()}")
    print(f"       Date range: {price_df['Datetime'].min()} to {price_df['Datetime'].max()}")

    # Initialize sentiment analyzer
    analyzer = MarketSentimentAnalyzer(price_df)

    print("\n[2/5] Initialized MarketSentimentAnalyzer")
    print(f"       LLM Provider: {analyzer.llm.__class__.__name__ if analyzer.llm else 'None (fallback mode)'}")
    print(f"       News Sources: {len(analyzer.news_fetcher.sources)}")

    # Fetch and analyze news sentiment (last 48 hours)
    print("\n[3/5] Fetching and analyzing news sentiment...")
    try:
        sentiment_df = analyzer.analyze_news_sentiment(
            symbols=None,  # Auto-detect from price data
            hours_back=48
        )

        if len(sentiment_df) == 0:
            print("       ⚠️  No news articles found in the last 48 hours")
            print("       This is normal if RSS feeds have no recent energy news.")
            print("       Try increasing hours_back or check your NewsAPI key if configured.")
            return

        print(f"       ✅ Analyzed {len(sentiment_df)} article-symbol pairs")

    except Exception as e:
        print(f"       ❌ Failed to fetch news: {e}")
        print("       Check your internet connection and API keys in .env")
        return

    # Display sentiment summary
    print("\n[4/5] Generating sentiment summary...")
    summary = analyzer.get_sentiment_summary(sentiment_df)

    print("\n       SENTIMENT SUMMARY")
    print("       -" * 35)
    print(f"       Total Articles: {summary['total_articles']}")
    print(f"       Average Sentiment: {summary['avg_sentiment']:.3f}")
    print(f"       Average Confidence: {summary['avg_confidence']:.2%}")
    print("\n       Distribution:")
    print(f"         • Bullish:  {summary['sentiment_distribution']['bullish']:3d} articles")
    print(f"         • Neutral:  {summary['sentiment_distribution']['neutral']:3d} articles")
    print(f"         • Bearish:  {summary['sentiment_distribution']['bearish']:3d} articles")
    print("\n       By Symbol:")
    for symbol, avg_sent in summary['by_symbol'].items():
        sentiment_label = "🟢 BULLISH" if avg_sent > 0.2 else "🔴 BEARISH" if avg_sent < -0.2 else "⚪ NEUTRAL"
        print(f"         {symbol}: {avg_sent:+.3f} {sentiment_label}")

    # Join sentiment to prices
    print("\n[5/5] Joining sentiment to price data...")
    enriched_df = analyzer.add_sentiment_to_prices(
        sentiment_df,
        aggregation='weighted',  # Weight by confidence
        time_window_minutes=60
    )

    print(f"       ✅ Enriched {len(enriched_df)} price records with sentiment")
    print("       Columns added: avg_sentiment, avg_confidence, news_count")

    # Create visualizations for each symbol
    for symbol in enriched_df['Symbol'].unique().to_list():
        create_sentiment_visualization(enriched_df, sentiment_df, symbol)

    # Print sample enriched data
    print("\n" + "=" * 70)
    print("SAMPLE ENRICHED DATA (last 5 rows with sentiment)")
    print("=" * 70)

    sample = (
        enriched_df
        .filter(pl.col('news_count') > 0)
        .select(['Datetime', 'Symbol', 'Close', 'avg_sentiment', 'avg_confidence', 'news_count'])
        .tail(5)
    )
    print(sample)

    print("\n✅ Analysis complete!")
    print("Check the generated HTML files for interactive visualizations.")


def create_sentiment_visualization(enriched_df: pl.DataFrame, sentiment_df: pl.DataFrame, symbol: str):
    """Create interactive visualization with price and sentiment overlay."""

    symbol_price = enriched_df.filter(pl.col('Symbol') == symbol).sort('Datetime')
    symbol_sentiment = sentiment_df.filter(pl.col('Symbol') == symbol).sort('Datetime')

    # Create subplots: Price + Sentiment / Sentiment Score / News Count
    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        subplot_titles=(
            f'{symbol} - Price with Sentiment Overlay',
            'Sentiment Score (Bullish/Bearish)',
            'News Article Count'
        ),
        specs=[
            [{"secondary_y": True}],
            [{"secondary_y": False}],
            [{"secondary_y": False}]
        ]
    )

    # Row 1: Price candlestick
    fig.add_trace(
        go.Candlestick(
            x=symbol_price['Datetime'],
            open=symbol_price['Open'],
            high=symbol_price['High'],
            low=symbol_price['Low'],
            close=symbol_price['Close'],
            name='Price',
            increasing_line_color='green',
            decreasing_line_color='red'
        ),
        row=1, col=1,
        secondary_y=False
    )

    # Row 1: Sentiment overlay (secondary y-axis)
    sentiment_with_data = symbol_price.filter(pl.col('news_count') > 0)
    if len(sentiment_with_data) > 0:
        colors = [
            'green' if s > 0.2 else 'red' if s < -0.2 else 'gray'
            for s in sentiment_with_data['avg_sentiment'].to_list()
        ]

        fig.add_trace(
            go.Scatter(
                x=sentiment_with_data['Datetime'],
                y=sentiment_with_data['avg_sentiment'],
                mode='markers+lines',
                name='Avg Sentiment',
                marker=dict(
                    size=10,
                    color=colors,
                    line=dict(width=1, color='white')
                ),
                line=dict(width=2, dash='dot')
            ),
            row=1, col=1,
            secondary_y=True
        )

    # Row 2: Individual article sentiments
    if len(symbol_sentiment) > 0:
        colors_articles = [
            'green' if s > 0.2 else 'red' if s < -0.2 else 'gray'
            for s in symbol_sentiment['sentiment_score'].to_list()
        ]

        fig.add_trace(
            go.Scatter(
                x=symbol_sentiment['Datetime'],
                y=symbol_sentiment['sentiment_score'],
                mode='markers',
                name='Individual Articles',
                marker=dict(
                    size=8,
                    color=colors_articles,
                    opacity=0.7
                ),
                text=symbol_sentiment['news_title'],
                hovertemplate='<b>%{text}</b><br>Sentiment: %{y:.3f}<extra></extra>'
            ),
            row=2, col=1
        )

        # Add zero line
        fig.add_hline(y=0, line_dash="dash", line_color="gray", row=2, col=1)

    # Row 3: News count
    if len(sentiment_with_data) > 0:
        fig.add_trace(
            go.Bar(
                x=sentiment_with_data['Datetime'],
                y=sentiment_with_data['news_count'],
                name='News Count',
                marker_color='steelblue'
            ),
            row=3, col=1
        )

    # Update layout
    fig.update_layout(
        height=1000,
        title=f'Sentiment Analysis - {symbol}',
        showlegend=True,
        hovermode='x unified',
        xaxis3_title='Date',
    )

    # Update y-axes labels
    fig.update_yaxes(title_text="Price ($)", row=1, col=1, secondary_y=False)
    fig.update_yaxes(title_text="Sentiment", row=1, col=1, secondary_y=True)
    fig.update_yaxes(title_text="Sentiment Score", row=2, col=1)
    fig.update_yaxes(title_text="Article Count", row=3, col=1)

    # Save
    filename = f"sentiment_{symbol.replace('=', '')}.html"
    fig.write_html(filename)
    print(f"\n       📊 Visualization saved: {filename}")


if __name__ == "__main__":
    analyze_sentiment()
