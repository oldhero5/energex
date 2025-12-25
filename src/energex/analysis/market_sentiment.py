"""Market sentiment analysis using LLMs for energy derivatives trading."""

import json
import logging
from typing import Literal

import polars as pl

from energex.config import get_settings
from energex.exceptions import AnalysisError, LLMProviderError
from energex.llm_providers import BaseLLMProvider, LLMProviderFactory
from energex.news_fetcher import NewsAPISource, NewsFetcher, RSSNewsSource


class MarketSentimentAnalyzer:
    """
    Analyze market sentiment from energy news using LLMs.

    This analyzer follows the energex pattern: accepts a Polars DataFrame,
    fetches and analyzes news, and returns DataFrames or summary dicts.

    Example:
        >>> from energex.database import EnergyDatabase
        >>> db = EnergyDatabase()
        >>> price_data = pl.from_arrow(db.conn.execute("SELECT * FROM intraday_prices").arrow())
        >>> analyzer = MarketSentimentAnalyzer(price_data)
        >>> sentiment = analyzer.analyze_news_sentiment(hours_back=24)
        >>> enriched = analyzer.add_sentiment_to_prices(sentiment)
    """

    def __init__(self, df: pl.DataFrame, provider: str | None = None):
        """
        Initialize the sentiment analyzer.

        Args:
            df: Polars DataFrame with price data (must have Symbol, Datetime columns).
            provider: Optional LLM provider override (openai, anthropic, ollama).
                     If None, uses config default.

        Raises:
            AnalysisError: If DataFrame is missing required columns.
        """
        self.df = df
        self.logger = logging.getLogger(__name__)
        self.settings = get_settings()

        # Validate required columns
        required_cols = {"Symbol", "Datetime"}
        if not required_cols.issubset(set(df.columns)):
            raise AnalysisError(
                f"DataFrame must contain {required_cols} columns. Found: {df.columns}"
            )

        # Initialize LLM provider
        try:
            provider_name = provider or self.settings.llm.provider
            self.llm: BaseLLMProvider = LLMProviderFactory.create(
                provider=provider_name,
                model=self.settings.llm.model,
                api_key=self.settings.llm.api_key,
                base_url=self.settings.llm.base_url,
            )

            if not self.llm.is_available():
                self.logger.warning(
                    f"LLM provider {provider_name} not available. "
                    "Sentiment analysis will use fallback mode."
                )
        except Exception as e:
            self.logger.warning(f"Failed to initialize LLM provider: {e}")
            self.llm = None  # type: ignore

        # Initialize news fetcher
        news_sources = [RSSNewsSource()]
        if self.settings.news.news_api_key:
            news_sources.append(NewsAPISource(api_key=self.settings.news.news_api_key))

        self.news_fetcher = NewsFetcher(news_sources)

        # Simple dict-based cache for LLM responses (avoids lru_cache memory leak on methods)
        self._sentiment_cache: dict[str, dict[str, any]] = {}  # type: ignore

        # System prompt for LLM
        self.system_prompt = """You are a senior energy derivatives trader analyzing market news.
For each headline, provide a JSON response with:
{
    "sentiment_score": float between -1.0 (very bearish) and 1.0 (very bullish),
    "confidence": float between 0.0 (uncertain) and 1.0 (very confident),
    "impact_sector": string ("Oil", "Natural Gas", "Brent", "General"),
    "trade_signal": string ("LONG", "SHORT", "NEUTRAL"),
    "key_factors": list of strings (2-3 key factors driving the sentiment)
}

Only output valid JSON, nothing else."""

    def analyze_news_sentiment(
        self, symbols: list[str] | None = None, hours_back: int = 24
    ) -> pl.DataFrame:
        """
        Fetch and analyze recent news sentiment.

        Args:
            symbols: List of ticker symbols to filter news for. If None, uses all
                    symbols from the analyzer's DataFrame.
            hours_back: How many hours of historical news to fetch. Defaults to 24.

        Returns:
            DataFrame with columns: Datetime, Symbol, news_title, news_url,
            sentiment_score, confidence, impact_sector, trade_signal, key_factors.

        Example:
            >>> sentiment_df = analyzer.analyze_news_sentiment(["CL=F", "NG=F"], hours_back=48)
            >>> print(sentiment_df.head())
        """
        # Get unique symbols from DataFrame if not provided
        if symbols is None:
            symbols = self.df["Symbol"].unique().to_list()

        self.logger.info(f"Fetching news for symbols: {symbols}, hours_back={hours_back}")

        # Fetch news articles
        try:
            articles = self.news_fetcher.fetch_all(symbols, hours_back)
            self.logger.info(f"Fetched {len(articles)} articles")
        except Exception as e:
            self.logger.error(f"News fetching failed: {e}")
            # Return empty DataFrame with correct schema
            return pl.DataFrame(
                schema={
                    "Datetime": pl.Datetime,
                    "Symbol": pl.Utf8,
                    "news_title": pl.Utf8,
                    "news_url": pl.Utf8,
                    "sentiment_score": pl.Float64,
                    "confidence": pl.Float64,
                    "impact_sector": pl.Utf8,
                    "trade_signal": pl.Utf8,
                    "key_factors": pl.Utf8,
                }
            )

        # Analyze each article
        results = []
        for article in articles:
            analysis = self._analyze_article(article.title, article.summary)

            # Map impact sector to symbol
            article_symbols = article.symbols or self._map_sector_to_symbols(
                analysis["impact_sector"], symbols
            )

            for symbol in article_symbols:
                results.append(
                    {
                        "Datetime": article.published_at,
                        "Symbol": symbol,
                        "news_title": article.title,
                        "news_url": article.url,
                        "sentiment_score": analysis["sentiment_score"],
                        "confidence": analysis["confidence"],
                        "impact_sector": analysis["impact_sector"],
                        "trade_signal": analysis["trade_signal"],
                        "key_factors": json.dumps(analysis["key_factors"]),
                    }
                )

        if not results:
            self.logger.warning("No sentiment data generated")
            return pl.DataFrame(
                schema={
                    "Datetime": pl.Datetime,
                    "Symbol": pl.Utf8,
                    "news_title": pl.Utf8,
                    "news_url": pl.Utf8,
                    "sentiment_score": pl.Float64,
                    "confidence": pl.Float64,
                    "impact_sector": pl.Utf8,
                    "trade_signal": pl.Utf8,
                    "key_factors": pl.Utf8,
                }
            )

        sentiment_df = pl.DataFrame(results)
        self.logger.info(f"Generated sentiment for {len(sentiment_df)} article-symbol pairs")
        return sentiment_df

    def _analyze_article(self, title: str, summary: str | None) -> dict[str, any]:  # type: ignore
        """
        Analyze a single article with LLM (with caching).

        Uses instance-level dict cache to avoid memory leaks from lru_cache on methods.

        Args:
            title: Article headline.
            summary: Article summary/description.

        Returns:
            Dictionary with sentiment analysis results.
        """
        # Check cache first
        cache_key = f"{title}::{summary}"
        if cache_key in self._sentiment_cache:
            return self._sentiment_cache[cache_key]
        # Use LLM if available
        if self.llm and self.llm.is_available():
            try:
                user_prompt = f"Headline: {title}\nSummary: {summary or 'N/A'}"
                response = self.llm.generate_completion(self.system_prompt, user_prompt)

                # Parse JSON response
                analysis = json.loads(response)

                # Validate and normalize
                result = {
                    "sentiment_score": float(
                        max(-1.0, min(1.0, analysis.get("sentiment_score", 0.0)))
                    ),
                    "confidence": float(max(0.0, min(1.0, analysis.get("confidence", 0.5)))),
                    "impact_sector": str(analysis.get("impact_sector", "General")),
                    "trade_signal": str(analysis.get("trade_signal", "NEUTRAL")).upper(),
                    "key_factors": list(analysis.get("key_factors", [])),
                }

                # Cache the result
                self._sentiment_cache[cache_key] = result
                return result

            except (json.JSONDecodeError, LLMProviderError) as e:
                self.logger.warning(f"LLM analysis failed for '{title}': {e}")
                # Fall through to rule-based fallback

        # Fallback: simple rule-based sentiment
        result = self._rule_based_sentiment(title, summary)
        self._sentiment_cache[cache_key] = result
        return result

    def _rule_based_sentiment(self, title: str, summary: str | None) -> dict[str, any]:  # type: ignore
        """
        Simple rule-based sentiment analysis fallback.

        Args:
            title: Article headline.
            summary: Article summary.

        Returns:
            Dictionary with basic sentiment analysis.
        """
        text = (title + " " + (summary or "")).lower()

        # Bullish keywords
        bullish_words = [
            "surge",
            "rally",
            "boom",
            "rise",
            "increase",
            "gain",
            "production cut",
            "shortage",
            "demand",
        ]
        # Bearish keywords
        bearish_words = [
            "fall",
            "drop",
            "crash",
            "decline",
            "decrease",
            "glut",
            "oversupply",
            "weak",
        ]

        bullish_count = sum(1 for word in bullish_words if word in text)
        bearish_count = sum(1 for word in bearish_words if word in text)

        if bullish_count > bearish_count:
            sentiment = min(0.6, 0.2 * bullish_count)
            signal = "LONG"
        elif bearish_count > bullish_count:
            sentiment = max(-0.6, -0.2 * bearish_count)
            signal = "SHORT"
        else:
            sentiment = 0.0
            signal = "NEUTRAL"

        # Determine sector
        sector = "General"
        if any(word in text for word in ["oil", "crude", "wti", "petroleum"]):
            sector = "Oil"
        elif any(word in text for word in ["gas", "lng", "natural gas"]):
            sector = "Natural Gas"
        elif "brent" in text:
            sector = "Brent"

        return {
            "sentiment_score": sentiment,
            "confidence": 0.4,  # Lower confidence for rule-based
            "impact_sector": sector,
            "trade_signal": signal,
            "key_factors": ["Rule-based analysis"],
        }

    def add_sentiment_to_prices(
        self,
        sentiment_df: pl.DataFrame,
        aggregation: Literal["mean", "weighted", "latest"] = "mean",
        time_window: str = "1h",
    ) -> pl.DataFrame:
        """
        Join sentiment scores to price data.

        Args:
            sentiment_df: DataFrame from analyze_news_sentiment().
            aggregation: How to aggregate multiple sentiments per time window:
                - 'mean': Simple average of sentiment scores
                - 'weighted': Confidence-weighted average
                - 'latest': Most recent sentiment only
            time_window: Time window for aggregation (e.g., '1h', '30m', '1d').

        Returns:
            Original DataFrame with added sentiment columns:
            avg_sentiment, avg_confidence, news_count.

        Example:
            >>> enriched = analyzer.add_sentiment_to_prices(sentiment_df, aggregation='weighted')
        """
        if sentiment_df.is_empty():
            # Return original df with null sentiment columns
            return self.df.with_columns(
                [
                    pl.lit(None).cast(pl.Float64).alias("avg_sentiment"),
                    pl.lit(None).cast(pl.Float64).alias("avg_confidence"),
                    pl.lit(0).cast(pl.Int64).alias("news_count"),
                ]
            )

        # Aggregate sentiment by Symbol and time window
        if aggregation == "mean":
            agg_sentiment = (
                sentiment_df.with_columns(
                    [pl.col("Datetime").dt.truncate(time_window).alias("time_window")]
                )
                .group_by(["Symbol", "time_window"])
                .agg(
                    [
                        pl.col("sentiment_score").mean().alias("avg_sentiment"),
                        pl.col("confidence").mean().alias("avg_confidence"),
                        pl.col("news_title").count().alias("news_count"),
                    ]
                )
                .rename({"time_window": "Datetime"})
            )
        elif aggregation == "weighted":
            # Weighted average: (sentiment * confidence).sum() / confidence.sum()
            agg_sentiment = (
                sentiment_df.with_columns(
                    [pl.col("Datetime").dt.truncate(time_window).alias("time_window")]
                )
                .group_by(["Symbol", "time_window"])
                .agg(
                    [
                        (pl.col("sentiment_score") * pl.col("confidence"))
                        .sum()
                        .truediv(pl.col("confidence").sum())
                        .alias("avg_sentiment"),
                        pl.col("confidence").mean().alias("avg_confidence"),
                        pl.col("news_title").count().alias("news_count"),
                    ]
                )
                .rename({"time_window": "Datetime"})
            )
        else:  # latest
            agg_sentiment = (
                sentiment_df.sort("Datetime", descending=True)
                .with_columns(
                    [pl.col("Datetime").dt.truncate(time_window).alias("time_window")]
                )
                .group_by(["Symbol", "time_window"])
                .agg(
                    [
                        pl.col("sentiment_score").first().alias("avg_sentiment"),
                        pl.col("confidence").first().alias("avg_confidence"),
                        pl.col("news_title").count().alias("news_count"),
                    ]
                )
                .rename({"time_window": "Datetime"})
            )

        # Join with price data using asof join (backward fill)
        result = (
            self.df.sort(["Symbol", "Datetime"])
            .join_asof(
                agg_sentiment.sort(["Symbol", "Datetime"]),
                on="Datetime",
                by="Symbol",
                strategy="backward",
            )
            .with_columns(
                [
                    pl.col("avg_sentiment").fill_null(0.0),
                    pl.col("avg_confidence").fill_null(0.0),
                    pl.col("news_count").fill_null(0),
                ]
            )
        )

        self.logger.info(f"Added sentiment to {len(result)} price rows")
        return result

    def get_sentiment_summary(self, sentiment_df: pl.DataFrame) -> dict[str, any]:  # type: ignore
        """
        Get summary statistics of sentiment analysis.

        Args:
            sentiment_df: DataFrame from analyze_news_sentiment().

        Returns:
            Dictionary with overall sentiment metrics:
            - total_articles: Number of articles analyzed
            - avg_sentiment_by_symbol: Average sentiment per symbol
            - sentiment_distribution: Count of bullish/neutral/bearish
            - avg_confidence: Overall confidence
            - date_range: [min_date, max_date]
            - top_bullish: Top 3 bullish headlines
            - top_bearish: Top 3 bearish headlines

        Example:
            >>> summary = analyzer.get_sentiment_summary(sentiment_df)
            >>> print(f"Bullish articles: {summary['sentiment_distribution']['bullish']}")
        """
        if sentiment_df.is_empty():
            return {
                "total_articles": 0,
                "avg_sentiment_by_symbol": {},
                "sentiment_distribution": {"bullish": 0, "neutral": 0, "bearish": 0},
                "avg_confidence": 0.0,
                "date_range": [None, None],
                "top_bullish": [],
                "top_bearish": [],
            }

        # Average sentiment by symbol
        avg_by_symbol = (
            sentiment_df.group_by("Symbol")
            .agg(pl.col("sentiment_score").mean())
            .to_dicts()
        )
        avg_sentiment_map = {
            row["Symbol"]: float(row["sentiment_score"]) for row in avg_by_symbol
        }

        # Sentiment distribution
        bullish = len(sentiment_df.filter(pl.col("sentiment_score") > 0.3))
        neutral = len(
            sentiment_df.filter(
                (pl.col("sentiment_score") >= -0.3) & (pl.col("sentiment_score") <= 0.3)
            )
        )
        bearish = len(sentiment_df.filter(pl.col("sentiment_score") < -0.3))

        # Top headlines
        top_bullish = (
            sentiment_df.sort("sentiment_score", descending=True)
            .select(["news_title", "sentiment_score", "Symbol"])
            .head(3)
            .to_dicts()
        )

        top_bearish = (
            sentiment_df.sort("sentiment_score")
            .select(["news_title", "sentiment_score", "Symbol"])
            .head(3)
            .to_dicts()
        )

        return {
            "total_articles": len(sentiment_df.unique(subset=["news_url"])),
            "avg_sentiment_by_symbol": avg_sentiment_map,
            "sentiment_distribution": {
                "bullish": bullish,
                "neutral": neutral,
                "bearish": bearish,
            },
            "avg_confidence": float(sentiment_df["confidence"].mean()),
            "date_range": [
                sentiment_df["Datetime"].min(),
                sentiment_df["Datetime"].max(),
            ],
            "top_bullish": top_bullish,
            "top_bearish": top_bearish,
        }

    def _map_sector_to_symbols(self, sector: str, available_symbols: list[str]) -> list[str]:
        """
        Map LLM sector output to ticker symbols.

        Args:
            sector: Sector name from LLM analysis.
            available_symbols: List of symbols to choose from.

        Returns:
            List of matching symbols.
        """
        sector_map = {
            "Oil": ["CL=F"],
            "Brent": ["BZ=F"],
            "Natural Gas": ["NG=F"],
            "General": available_symbols,  # Applies to all
        }

        matched = sector_map.get(sector, [])
        # Only return symbols that are in available_symbols
        return [s for s in matched if s in available_symbols]
