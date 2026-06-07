"""Tests for config hardening: env prefixes, secret handling, validated overrides (R9)."""

import pytest
from pydantic import SecretStr, ValidationError

from energex.config import LLMConfig, NewsConfig


def test_llm_config_reads_llm_prefixed_env(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "custom-model")
    assert LLMConfig().model == "custom-model"


def test_bare_env_vars_do_not_inject_into_llm_config(monkeypatch):
    # The previous env_prefix="" bound bare API_KEY / MODEL (secret injection).
    monkeypatch.setenv("API_KEY", "leaked-key")
    monkeypatch.setenv("MODEL", "evil-model")
    cfg = LLMConfig()
    assert cfg.api_key is None
    assert cfg.model == "gpt-4"


def test_api_key_is_secret_and_hidden_in_repr():
    cfg = LLMConfig(api_key="sk-supersecret")
    assert isinstance(cfg.api_key, SecretStr)
    assert "sk-supersecret" not in repr(cfg)
    assert cfg.api_key.get_secret_value() == "sk-supersecret"


def test_invalid_provider_assignment_is_rejected():
    cfg = LLMConfig()
    with pytest.raises(ValidationError):
        cfg.provider = "totally_invalid"  # type: ignore[assignment]


def test_news_config_reads_intuitive_news_api_key(monkeypatch):
    monkeypatch.setenv("NEWS_API_KEY", "news-k123")
    cfg = NewsConfig()
    assert cfg.news_api_key is not None
    assert cfg.news_api_key.get_secret_value() == "news-k123"
