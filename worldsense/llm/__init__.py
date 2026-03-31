"""LLM backend abstraction layer."""

from .backend import LLMBackend, MockBackend
from .openai_compat import OpenAICompatBackend
from .anthropic_compat import AnthropicCompatBackend

__all__ = ["LLMBackend", "MockBackend", "OpenAICompatBackend", "AnthropicCompatBackend"]


def get_backend(name: str, **kwargs) -> LLMBackend:
    """Factory: create a backend by name."""
    if name == "mock":
        return MockBackend(**kwargs)
    elif name == "anthropic":
        # Anthropic Messages API format (/v1/messages)
        # Used for: Anthropic native, MiniMax International (api.minimax.io/anthropic)
        return AnthropicCompatBackend(**kwargs)
    elif name in ("openai_compat", "openai", "glm"):
        # OpenAI-compatible endpoints use /chat/completions
        return OpenAICompatBackend(**kwargs)
    else:
        raise ValueError(f"Unknown backend: {name}. Available: mock, openai_compat, openai, glm, anthropic")
