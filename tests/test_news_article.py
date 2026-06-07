"""Tests for NewsArticle URL-based equality / hashing / deduplication."""

from datetime import datetime

from energex.news_fetcher import NewsArticle


def _article(url: str, title: str = "headline") -> NewsArticle:
    return NewsArticle(title=title, source="src", published_at=datetime(2024, 1, 1), url=url)


def test_same_url_articles_are_equal_regardless_of_title():
    assert _article("https://x/1", "A") == _article("https://x/1", "B")


def test_same_url_articles_hash_equal():
    assert hash(_article("https://x/1", "A")) == hash(_article("https://x/1", "B"))


def test_different_url_articles_not_equal():
    assert _article("https://x/1") != _article("https://x/2")


def test_set_deduplicates_by_url():
    arts = [
        _article("https://x/1", "A"),
        _article("https://x/1", "B"),
        _article("https://x/2"),
    ]
    assert len(set(arts)) == 2
