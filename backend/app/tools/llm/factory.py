"""Provider selection + gateway singleton."""
from __future__ import annotations

from functools import lru_cache

from app.core.config import settings
from app.core.errors import ConfigurationError
from app.core.logging import get_logger
from app.tools.llm.anthropic_provider import AnthropicProvider
from app.tools.llm.base import LLMProvider
from app.tools.llm.gateway import LLMGateway
from app.tools.llm.ollama_provider import OllamaProvider
from app.tools.llm.openai_provider import OpenAIProvider

logger = get_logger("devforge.llm.factory")

PROVIDERS: dict[str, type[LLMProvider]] = {
    "openai": OpenAIProvider,
    "azure_openai": OpenAIProvider,
    "openai_compatible": OpenAIProvider,
    "groq": OpenAIProvider,
    "openrouter": OpenAIProvider,
    "together": OpenAIProvider,
    "vllm": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "claude": AnthropicProvider,
    "ollama": OllamaProvider,
}

KEYLESS_PROVIDERS = {"ollama"}


def build_provider() -> tuple[LLMProvider, str]:
    """Return ``(provider, mode)`` according to configuration."""
    provider_key = (settings.llm_provider or "openai").strip().lower()

    common = {
        "api_key": settings.llm_api_key,
        "model": settings.llm_model,
        "base_url": settings.llm_base_url,
        "temperature": settings.llm_temperature,
        "max_tokens": settings.llm_max_tokens,
        "timeout": settings.llm_timeout_seconds,
    }

    provider_class = PROVIDERS.get(provider_key)
    if provider_class is None:
        raise ConfigurationError(
            f"Unknown LLM_PROVIDER '{settings.llm_provider}'. "
            f"Supported: {', '.join(sorted(PROVIDERS))}."
        )

    if provider_key not in KEYLESS_PROVIDERS and not settings.llm_api_key.strip():
        raise ConfigurationError(
            "Live AI requires LLM_API_KEY to be configured."
        )

    return provider_class(**common), "live"


@lru_cache
def get_llm_gateway() -> LLMGateway:
    """Cached gateway instance shared by all agents."""
    provider, mode = build_provider()
    gateway = LLMGateway(provider, mode=mode)
    logger.info("LLM gateway ready: provider=%s model=%s mode=%s",
                gateway.provider_name, gateway.model, gateway.mode)
    return gateway


def reset_llm_gateway() -> None:
    """Clear the cached gateway (used by tests and config reloads)."""
    get_llm_gateway.cache_clear()
