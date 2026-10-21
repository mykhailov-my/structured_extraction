"""Model backends behind one interface (see base.Provider)."""

import inspect

from extraction.config import ModelConfig
from extraction.providers.base import (
    Completion,
    Message,
    Provider,
    ProviderError,
    TransientError,
)
from extraction.providers.ollama import OllamaProvider
from extraction.providers.openrouter import OpenRouterProvider

__all__ = [
    "Completion",
    "Message",
    "Provider",
    "ProviderError",
    "TransientError",
    "create_provider",
]

PROVIDERS: dict[str, type] = {"openrouter": OpenRouterProvider, "ollama": OllamaProvider}


def create_provider(config: ModelConfig) -> Provider:
    """Build the provider for a config.yaml model; provider-specific keys become options."""
    provider_class = PROVIDERS[config.provider]
    accepted = set(inspect.signature(provider_class).parameters) - {
        "model",
        "max_tokens",
        "timeout_s",
    }
    unknown = sorted(set(config.options) - accepted)
    if unknown:
        raise ProviderError(
            f"{config.provider} doesn't take {', '.join(unknown)}"
            f" (its options: {', '.join(sorted(accepted)) or 'none'})"
        )
    return provider_class(
        config.model, max_tokens=config.max_tokens, timeout_s=config.timeout_s, **config.options
    )
