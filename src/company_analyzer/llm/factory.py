from __future__ import annotations

from company_analyzer.config import Settings
from company_analyzer.llm.base import LLMProvider
from company_analyzer.llm.mock_provider import MockLLMProvider


def get_llm_provider(settings: Settings) -> LLMProvider:
    provider = settings.llm_provider
    if provider == "mock":
        return MockLLMProvider()
    if provider == "anthropic":
        from company_analyzer.llm.anthropic_provider import AnthropicProvider

        api_key = settings.require_llm_key_for("anthropic")
        return AnthropicProvider(api_key)
    if provider == "openai":
        from company_analyzer.llm.openai_provider import OpenAIProvider

        api_key = settings.require_llm_key_for("openai")
        return OpenAIProvider(api_key)
    from company_analyzer.config import ConfigError

    raise ConfigError(f"Unknown LLM_PROVIDER '{provider}'. Expected one of: mock, anthropic, openai.")
