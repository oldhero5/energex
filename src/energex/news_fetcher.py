"""News fetching and aggregation for sentiment analysis."""

import hashlib
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta

from energex.exceptions import DataFetchError


@dataclass
class NewsArticle:
    """
    Standardized news article structure.

    Attributes:
        title: Article headline.
        source: News source identifier.
        published_at: Publication timestamp.
        url: Article URL.
        summary: Optional article summary/description.
        symbols: List of related energy symbols.
    """

    title: str
    source: str
    published_at: datetime
    url: str
    summary: str | None = None
    symbols: list[str] | None = None

    def __hash__(self) -> int:
        """Generate hash for deduplication based on URL."""
        # MD5 used for deduplication only, not security
        return int(hashlib.md5(self.url.encode(), usedforsecurity=False).hexdigest(), 16)  # nosec B324

    def __eq__(self, other: object) -> bool:
        """Check equality based on URL."""
        if not isinstance(other, NewsArticle):
            return False
        return self.url == other.url


class NewsSource(ABC):
    """Abstract base class for news sources."""

    def __init__(self) -> None:
        """Initialize the news source."""
        self.logger = logging.getLogger(__name__)

    @abstractmethod
    def fetch_articles(self, symbols: list[str], hours_back: int = 24) -> list[NewsArticle]:
        """
        Fetch news articles for given symbols.

        Args:
            symbols: List of ticker symbols to filter news for.
            hours_back: How many hours of historical news to fetch.

        Returns:
            List of NewsArticle objects.

        Raises:
            DataFetchError: If fetching fails.
        """
        pass


class RSSNewsSource(NewsSource):
    """RSS feed-based news source for energy markets."""

    # Energy-focused RSS feeds
    ENERGY_RSS_FEEDS = [
        "https://www.oilprice.com/rss/main",
        "https://www.naturalgasintel.com/feed/",
        "https://www.reuters.com/business/energy",
        "https://www.energyvoice.com/feed/",
    ]

    def fetch_articles(self, symbols: list[str], hours_back: int = 24) -> list[NewsArticle]:
        """Fetch articles from RSS feeds."""
        try:
            import feedparser
        except ImportError as e:
            raise DataFetchError(
                "feedparser not installed. Install with: pip install energex[sentiment]"
            ) from e

        articles: list[NewsArticle] = []
        cutoff_time = datetime.now() - timedelta(hours=hours_back)

        for feed_url in self.ENERGY_RSS_FEEDS:
            try:
                self.logger.debug(f"Fetching RSS feed: {feed_url}")
                feed = feedparser.parse(feed_url)

                for entry in feed.entries:
                    # Parse publication date
                    pub_date = None
                    if hasattr(entry, "published_parsed") and entry.published_parsed:
                        pub_date = datetime(*entry.published_parsed[:6])
                    elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
                        pub_date = datetime(*entry.updated_parsed[:6])
                    else:
                        # If no date, assume recent
                        pub_date = datetime.now()

                    # Filter by time window
                    if pub_date < cutoff_time:
                        continue

                    # Extract summary
                    summary = None
                    if hasattr(entry, "summary"):
                        summary = entry.summary
                    elif hasattr(entry, "description"):
                        summary = entry.description

                    # Determine relevant symbols based on keywords
                    relevant_symbols = self._match_symbols(
                        entry.title + " " + (summary or ""), symbols
                    )

                    if relevant_symbols:
                        article = NewsArticle(
                            title=entry.title,
                            source=feed_url.split("/")[2],  # Extract domain
                            published_at=pub_date,
                            url=entry.link,
                            summary=summary,
                            symbols=relevant_symbols,
                        )
                        articles.append(article)

            except Exception as e:
                self.logger.warning(f"Failed to fetch RSS feed {feed_url}: {e}")
                continue

        self.logger.info(f"Fetched {len(articles)} articles from RSS feeds")
        return articles

    def _match_symbols(self, text: str, symbols: list[str]) -> list[str]:
        """
        Match symbols to text based on keywords.

        Args:
            text: Article text (title + summary).
            symbols: List of symbols to match.

        Returns:
            List of matched symbols.
        """
        text_lower = text.lower()
        matched = []

        # Keyword mapping for energy symbols
        keyword_map = {
            "CL=F": ["crude oil", "wti", "oil price", "petroleum", "barrel"],
            "BZ=F": ["brent", "brent crude", "ice brent"],
            "NG=F": ["natural gas", "lng", "gas price", "henry hub"],
        }

        for symbol in symbols:
            keywords = keyword_map.get(symbol, [symbol.lower()])
            if any(keyword in text_lower for keyword in keywords):
                matched.append(symbol)

        # If no specific match, assign to all symbols (general energy news)
        if not matched:
            matched = symbols

        return matched


class NewsAPISource(NewsSource):
    """NewsAPI.org integration for news fetching."""

    def __init__(self, api_key: str | None = None):
        """
        Initialize NewsAPI source.

        Args:
            api_key: NewsAPI.org API key.
        """
        super().__init__()
        self.api_key = api_key
        self.base_url = "https://newsapi.org/v2/everything"

    def fetch_articles(self, symbols: list[str], hours_back: int = 24) -> list[NewsArticle]:
        """Fetch articles from NewsAPI."""
        if not self.api_key:
            self.logger.warning("NewsAPI key not configured, skipping NewsAPI source")
            return []

        try:
            import requests
        except ImportError as e:
            raise DataFetchError("requests not installed. Install with: pip install energex") from e

        articles: list[NewsArticle] = []

        # Energy-related search queries
        queries = ["oil price", "natural gas", "energy market", "crude oil", "brent"]

        from_date = (datetime.now() - timedelta(hours=hours_back)).strftime("%Y-%m-%dT%H:%M:%S")

        for query in queries:
            try:
                params = {
                    "q": query,
                    "from": from_date,
                    "sortBy": "publishedAt",
                    "language": "en",
                    "apiKey": self.api_key,
                }

                response = requests.get(self.base_url, params=params, timeout=10)
                response.raise_for_status()
                data = response.json()

                for item in data.get("articles", []):
                    pub_date = datetime.fromisoformat(item["publishedAt"].replace("Z", "+00:00"))

                    article = NewsArticle(
                        title=item["title"],
                        source=item["source"]["name"],
                        published_at=pub_date,
                        url=item["url"],
                        summary=item.get("description"),
                        symbols=symbols,  # Assign all symbols for now
                    )
                    articles.append(article)

            except Exception as e:
                self.logger.warning(f"Failed to fetch NewsAPI query '{query}': {e}")
                continue

        self.logger.info(f"Fetched {len(articles)} articles from NewsAPI")
        return articles


class NewsFetcher:
    """
    Aggregate news from multiple sources with deduplication.

    Example:
        >>> sources = [RSSNewsSource(), NewsAPISource(api_key="...")]
        >>> fetcher = NewsFetcher(sources)
        >>> articles = fetcher.fetch_all(["CL=F", "NG=F"], hours_back=24)
    """

    def __init__(self, sources: list[NewsSource]):
        """
        Initialize the news fetcher.

        Args:
            sources: List of NewsSource instances to aggregate from.
        """
        self.sources = sources
        self.logger = logging.getLogger(__name__)

    def fetch_all(self, symbols: list[str], hours_back: int = 24) -> list[NewsArticle]:
        """
        Fetch articles from all sources and deduplicate.

        Args:
            symbols: List of ticker symbols to filter news for.
            hours_back: How many hours of historical news to fetch.

        Returns:
            Deduplicated list of NewsArticle objects, sorted by publish date (newest first).

        Example:
            >>> fetcher = NewsFetcher([RSSNewsSource()])
            >>> articles = fetcher.fetch_all(["CL=F"], hours_back=48)
            >>> print(f"Found {len(articles)} unique articles")
        """
        all_articles: list[NewsArticle] = []

        for source in self.sources:
            try:
                source_articles = source.fetch_articles(symbols, hours_back)
                all_articles.extend(source_articles)
                self.logger.info(
                    f"Source {source.__class__.__name__} returned {len(source_articles)} articles"
                )
            except Exception as e:
                self.logger.error(f"Source {source.__class__.__name__} failed: {e}", exc_info=True)
                continue

        # Deduplicate using set (relies on NewsArticle.__hash__)
        unique_articles = list(set(all_articles))

        # Sort by publication date (newest first)
        unique_articles.sort(key=lambda x: x.published_at, reverse=True)

        self.logger.info(
            f"Total: {len(all_articles)} articles, {len(unique_articles)} unique after deduplication"
        )

        return unique_articles
