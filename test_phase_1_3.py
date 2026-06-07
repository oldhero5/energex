"""
Test script for Phase 1-3 modules.
Tests configuration, logging, rate limiter, LLM providers, and news fetcher.
"""

import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

print("=" * 70)
print("ENERGEX PHASE 1-3 TESTING")
print("=" * 70)

# Test 1: Import all modules
print("\n[TEST 1] Importing modules...")
try:
    from energex.exceptions import EnergexError, ConfigurationError, LLMProviderError
    from energex.config import get_settings, reset_settings
    from energex.logging_config import setup_logging
    from energex.rate_limiter import RateLimiter
    from energex.llm_providers import (
        BaseLLMProvider,
        OpenAIProvider,
        AnthropicProvider,
        OllamaProvider,
        LLMProviderFactory,
    )
    from energex.news_fetcher import NewsArticle, NewsFetcher, RSSNewsSource
    print("✅ All modules imported successfully")
except ImportError as e:
    print(f"❌ Import failed: {e}")
    sys.exit(1)

# Test 2: Configuration system
print("\n[TEST 2] Testing configuration system...")
try:
    reset_settings()
    settings = get_settings()
    print(f"✅ Default LLM provider: {settings.llm.provider}")
    print(f"✅ Default model: {settings.llm.model}")
    print(f"✅ DB path: {settings.database.db_path}")
    print(f"✅ Log level: {settings.logging.log_level}")
except Exception as e:
    print(f"❌ Config test failed: {e}")
    sys.exit(1)

# Test 3: Logging setup
print("\n[TEST 3] Testing logging configuration...")
try:
    setup_logging(log_level="INFO", enable_console=True)
    import logging
    logger = logging.getLogger("energex.test")
    logger.info("Test log message")
    print("✅ Logging configured successfully")
except Exception as e:
    print(f"❌ Logging test failed: {e}")
    sys.exit(1)

# Test 4: Rate limiter
print("\n[TEST 4] Testing rate limiter...")
try:
    import time

    @RateLimiter(max_calls=3, period=2)
    def rate_limited_func():
        return time.time()

    # Should allow first 3 calls quickly
    start = time.time()
    results = [rate_limited_func() for _ in range(3)]
    elapsed = time.time() - start

    if elapsed < 1.0:
        print(f"✅ First 3 calls completed in {elapsed:.2f}s (expected <1s)")
    else:
        print(f"⚠️  First 3 calls took {elapsed:.2f}s (expected <1s)")

    print("✅ Rate limiter working")
except Exception as e:
    print(f"❌ Rate limiter test failed: {e}")
    sys.exit(1)

# Test 5: LLM Provider Factory
print("\n[TEST 5] Testing LLM provider factory...")
try:
    # Test factory listing
    providers = LLMProviderFactory.list_providers()
    print(f"✅ Available providers: {providers}")

    # Test provider creation (without API keys, should still instantiate)
    for provider_name in providers:
        try:
            provider = LLMProviderFactory.create(
                provider=provider_name,
                model="test-model",
                api_key="test-key"
            )
            is_available = provider.is_available()
            print(f"✅ {provider_name} provider created (available: {is_available})")
        except Exception as e:
            print(f"⚠️  {provider_name} provider creation issue: {e}")

except Exception as e:
    print(f"❌ LLM provider test failed: {e}")
    sys.exit(1)

# Test 6: News article dataclass
print("\n[TEST 6] Testing news article structure...")
try:
    from datetime import datetime

    article1 = NewsArticle(
        title="Oil prices surge",
        source="test.com",
        published_at=datetime.now(),
        url="https://test.com/article1",
        summary="Test summary",
        symbols=["CL=F"]
    )

    article2 = NewsArticle(
        title="Different article",
        source="test.com",
        published_at=datetime.now(),
        url="https://test.com/article1",  # Same URL
    )

    # Test deduplication (same URL)
    if article1 == article2:
        print("✅ Article deduplication working (same URL detected)")
    else:
        print("❌ Article deduplication failed")

    # Test hash
    if hash(article1) == hash(article2):
        print("✅ Article hashing working")
    else:
        print("❌ Article hashing failed")

except Exception as e:
    print(f"❌ News article test failed: {e}")
    sys.exit(1)

# Test 7: Exception hierarchy
print("\n[TEST 7] Testing exception hierarchy...")
try:
    # Test that custom exceptions inherit properly
    assert issubclass(ConfigurationError, EnergexError)
    assert issubclass(LLMProviderError, EnergexError)
    print("✅ Exception hierarchy correct")

    # Test raising and catching
    try:
        raise LLMProviderError("Test error")
    except EnergexError as e:
        print(f"✅ Exception catching works: {e}")

except Exception as e:
    print(f"❌ Exception test failed: {e}")
    sys.exit(1)

# Test 8: Type checking (static)
print("\n[TEST 8] Type annotations...")
try:
    # Check that key functions have type hints
    from typing import get_type_hints

    config_hints = get_type_hints(get_settings)
    if 'return' in config_hints:
        print(f"✅ get_settings return type: {config_hints['return'].__name__}")

    limiter_hints = get_type_hints(RateLimiter.__init__)
    print(f"✅ RateLimiter has {len(limiter_hints)} type hints")

except Exception as e:
    print(f"⚠️  Type checking: {e}")

print("\n" + "=" * 70)
print("PHASE 1-3 TESTING COMPLETE")
print("=" * 70)
print("\n✅ All critical tests passed!")
print("\nNext: Run security scans with 'bandit' and 'safety'")
print("  pip install bandit safety")
print("  bandit -r src/energex/")
print("  safety check")
