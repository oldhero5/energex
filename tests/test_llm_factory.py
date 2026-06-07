"""Tests for the LLM provider factory."""

import pytest

from energex.exceptions import ConfigurationError
from energex.llm_providers import (
    AnthropicProvider,
    BaseLLMProvider,
    LLMProviderFactory,
    OllamaProvider,
    OpenAIProvider,
)


def test_lists_known_providers():
    assert set(LLMProviderFactory.list_providers()) == {"openai", "anthropic", "ollama"}


@pytest.mark.parametrize(
    "name,cls",
    [
        ("openai", OpenAIProvider),
        ("anthropic", AnthropicProvider),
        ("ollama", OllamaProvider),
    ],
)
def test_create_returns_expected_provider(name, cls):
    provider = LLMProviderFactory.create(name, api_key="test-key")
    assert isinstance(provider, cls)
    assert isinstance(provider, BaseLLMProvider)


def test_create_is_case_insensitive():
    assert isinstance(LLMProviderFactory.create("OpenAI", api_key="k"), OpenAIProvider)


def test_unknown_provider_raises_configuration_error():
    with pytest.raises(ConfigurationError):
        LLMProviderFactory.create("not-a-provider")
