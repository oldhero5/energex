"""Tests for news symbol matching — no blanket fan-out across all symbols (R6)."""

from energex.news_fetcher import RSSNewsSource

SYMBOLS = ["CL=F", "BZ=F", "NG=F"]


def test_match_symbols_returns_empty_for_generic_text():
    # Previously returned ALL symbols (triple-counting generic news).
    assert RSSNewsSource()._match_symbols("the economy grew last quarter", SYMBOLS) == []


def test_match_symbols_matches_specific_keyword():
    assert RSSNewsSource()._match_symbols("brent crude rallies on supply fears", SYMBOLS) == [
        "BZ=F"
    ]


def test_match_symbols_can_match_multiple():
    matched = RSSNewsSource()._match_symbols("oil price and natural gas both climb", SYMBOLS)
    assert set(matched) == {"CL=F", "NG=F"}
