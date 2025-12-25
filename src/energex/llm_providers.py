"""LLM provider abstraction for sentiment analysis."""

import json
import logging
from abc import ABC, abstractmethod
from typing import Any

from energex.exceptions import ConfigurationError, LLMProviderError


class BaseLLMProvider(ABC):
    """Abstract base class for LLM providers."""

    def __init__(self, model: str, api_key: str | None = None):
        """
        Initialize the LLM provider.

        Args:
            model: Model name/identifier for the provider.
            api_key: API key for authentication (if required).
        """
        self.model = model
        self.api_key = api_key
        self.logger = logging.getLogger(__name__)

    @abstractmethod
    def generate_completion(self, system_prompt: str, user_prompt: str) -> str:
        """
        Generate a completion from the LLM.

        Args:
            system_prompt: System prompt defining the LLM's role/behavior.
            user_prompt: User prompt with the actual query/task.

        Returns:
            The LLM's response as a string.

        Raises:
            LLMProviderError: If the API call fails.
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """
        Check if the provider is properly configured and available.

        Returns:
            True if the provider can be used, False otherwise.
        """
        pass


class OpenAIProvider(BaseLLMProvider):
    """OpenAI API provider (GPT-4, GPT-3.5, etc.)."""

    def __init__(self, model: str = "gpt-4", api_key: str | None = None):
        """Initialize OpenAI provider."""
        super().__init__(model, api_key)
        self._client: Any | None = None

    def _get_client(self) -> Any:
        """Lazy load the OpenAI client."""
        if self._client is None:
            try:
                from openai import OpenAI

                self._client = OpenAI(api_key=self.api_key)
            except ImportError as e:
                raise LLMProviderError(
                    "OpenAI package not installed. Install with: pip install energex[sentiment]"
                ) from e
        return self._client

    def is_available(self) -> bool:
        """Check if OpenAI is available."""
        if not self.api_key:
            return False
        try:
            self._get_client()
            return True
        except Exception:
            return False

    def generate_completion(self, system_prompt: str, user_prompt: str) -> str:
        """Generate completion using OpenAI API."""
        if not self.is_available():
            raise LLMProviderError(
                "OpenAI provider not available. Check API key configuration."
            )

        try:
            client = self._get_client()
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
            )
            content = response.choices[0].message.content
            if content is None:
                raise LLMProviderError("OpenAI returned empty response")
            return content

        except Exception as e:
            self.logger.error(f"OpenAI API call failed: {e}")
            raise LLMProviderError(f"OpenAI API error: {str(e)}") from e


class AnthropicProvider(BaseLLMProvider):
    """Anthropic API provider (Claude 3.5, Claude 3 Opus, etc.)."""

    def __init__(
        self, model: str = "claude-3-5-sonnet-20241022", api_key: str | None = None
    ):
        """Initialize Anthropic provider."""
        super().__init__(model, api_key)
        self._client: Any | None = None

    def _get_client(self) -> Any:
        """Lazy load the Anthropic client."""
        if self._client is None:
            try:
                from anthropic import Anthropic

                self._client = Anthropic(api_key=self.api_key)
            except ImportError as e:
                raise LLMProviderError(
                    "Anthropic package not installed. Install with: pip install energex[sentiment]"
                ) from e
        return self._client

    def is_available(self) -> bool:
        """Check if Anthropic is available."""
        if not self.api_key:
            return False
        try:
            self._get_client()
            return True
        except Exception:
            return False

    def generate_completion(self, system_prompt: str, user_prompt: str) -> str:
        """Generate completion using Anthropic API."""
        if not self.is_available():
            raise LLMProviderError(
                "Anthropic provider not available. Check API key configuration."
            )

        try:
            client = self._get_client()
            message = client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                temperature=0.3,
            )

            # Extract text content from response
            content = message.content[0].text if message.content else None
            if not content:
                raise LLMProviderError("Anthropic returned empty response")

            # Claude doesn't guarantee JSON mode, so we need to extract JSON
            # Try to find JSON in the response
            try:
                # Try parsing directly
                json.loads(content)
                return content
            except json.JSONDecodeError:
                # Try to extract JSON from markdown code blocks
                import re

                json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
                if json_match:
                    return json_match.group(1)
                # Try to find JSON object directly
                json_match = re.search(r"\{.*\}", content, re.DOTALL)
                if json_match:
                    return json_match.group(0)
                raise LLMProviderError(
                    f"Could not extract JSON from Claude response: {content}"
                ) from None

        except Exception as e:
            self.logger.error(f"Anthropic API call failed: {e}")
            raise LLMProviderError(f"Anthropic API error: {str(e)}") from e


class OllamaProvider(BaseLLMProvider):
    """Local LLM provider using Ollama."""

    def __init__(
        self, model: str = "llama3", base_url: str = "http://localhost:11434", api_key: str | None = None
    ):
        """Initialize Ollama provider."""
        super().__init__(model, api_key)
        self.base_url = base_url.rstrip("/")

    def is_available(self) -> bool:
        """Check if Ollama is available."""
        try:
            import httpx

            response = httpx.get(f"{self.base_url}/api/tags", timeout=5.0)
            return response.status_code == 200
        except Exception:
            return False

    def generate_completion(self, system_prompt: str, user_prompt: str) -> str:
        """Generate completion using Ollama."""
        if not self.is_available():
            raise LLMProviderError(
                f"Ollama not available at {self.base_url}. Ensure Ollama is running."
            )

        try:
            import httpx

            # Combine prompts for Ollama
            full_prompt = f"{system_prompt}\n\n{user_prompt}\n\nRespond with valid JSON only."

            response = httpx.post(
                f"{self.base_url}/api/generate",
                json={"model": self.model, "prompt": full_prompt, "stream": False, "format": "json"},
                timeout=60.0,
            )
            response.raise_for_status()

            result = response.json()
            content = result.get("response", "")
            if not content:
                raise LLMProviderError("Ollama returned empty response")

            return content

        except ImportError as e:
            raise LLMProviderError(
                "httpx package not installed. Install with: pip install energex[sentiment]"
            ) from e
        except Exception as e:
            self.logger.error(f"Ollama API call failed: {e}")
            raise LLMProviderError(f"Ollama API error: {str(e)}") from e


class LLMProviderFactory:
    """Factory for creating LLM provider instances."""

    _providers = {
        "openai": OpenAIProvider,
        "anthropic": AnthropicProvider,
        "ollama": OllamaProvider,
    }

    @classmethod
    def create(
        cls,
        provider: str,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> BaseLLMProvider:
        """
        Create an LLM provider instance.

        Args:
            provider: Provider name (openai, anthropic, ollama).
            model: Optional model override.
            api_key: Optional API key override.
            base_url: Optional base URL (for Ollama).

        Returns:
            An instance of the requested provider.

        Raises:
            ConfigurationError: If the provider is unknown.

        Example:
            >>> provider = LLMProviderFactory.create("openai", api_key="sk-...")
        """
        provider_lower = provider.lower()
        if provider_lower not in cls._providers:
            raise ConfigurationError(
                f"Unknown LLM provider: {provider}. "
                f"Valid options: {list(cls._providers.keys())}"
            )

        provider_class = cls._providers[provider_lower]

        # Build kwargs based on provider
        kwargs: dict[str, Any] = {}
        if model:
            kwargs["model"] = model
        if api_key:
            kwargs["api_key"] = api_key
        if provider_lower == "ollama" and base_url:
            kwargs["base_url"] = base_url

        return provider_class(**kwargs)

    @classmethod
    def list_providers(cls) -> list[str]:
        """List all available provider names."""
        return list(cls._providers.keys())
