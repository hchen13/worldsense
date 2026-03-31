"""
Vision probe: detect whether an LLM profile supports image inputs.

Sends a 1×1 transparent PNG as a base64 data URL and asks the model to
"Describe this image in one word". A successful response (any text back)
means supports_vision=True. A 400/422/unsupported-content-type error means
supports_vision=False.

Compatible with:
  - OpenAI-compatible endpoints  (/chat/completions, multipart image_url)
  - Anthropic-compatible endpoints (/v1/messages, base64 source block)
  - Mock provider (always returns False to keep tests deterministic)
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

# Minimal 1×1 transparent PNG, base64-encoded (67 bytes)
_PROBE_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)
_PROBE_DATA_URL = f"data:image/png;base64,{_PROBE_PNG_B64}"
_PROBE_PROMPT = "Describe this image in one word."


async def probe_vision(
    provider: str,
    api_key: str,
    endpoint: str,
    model: str,
    timeout: float = 20.0,
) -> bool:
    """
    Return True if the given LLM profile accepts image content, False otherwise.

    Args:
        provider: "openai" / "anthropic" / "custom" / "mock"
        api_key:  API key (may be empty — uses env var fallback outside)
        endpoint: Base URL for the API
        model:    Model name string
        timeout:  HTTP request timeout in seconds

    Returns:
        True  → model accepted the image input (supports vision)
        False → model rejected or errored (text-only)
    """
    if provider == "mock":
        return False  # Mock backend is text-only by definition

    if provider == "anthropic":
        return await _probe_anthropic(api_key, endpoint, model, timeout)
    else:
        # openai / openai_compat / glm / custom → all use /chat/completions
        return await _probe_openai_compat(api_key, endpoint, model, timeout)


async def _probe_openai_compat(
    api_key: str,
    endpoint: str,
    model: str,
    timeout: float,
) -> bool:
    """Probe an OpenAI-compatible endpoint using image_url content block."""
    base_url = (endpoint or "https://api.openai.com/v1").rstrip("/")
    url = f"{base_url}/chat/completions"

    payload = {
        "model": model or "gpt-4o-mini",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": _PROBE_DATA_URL},
                    },
                    {"type": "text", "text": _PROBE_PROMPT},
                ],
            }
        ],
        "max_tokens": 10,
        "temperature": 0,
    }

    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)

        if resp.status_code in (200, 201):
            return True

        # 400 / 422 / 415 → unsupported content type or bad request
        if resp.status_code in (400, 415, 422):
            body = resp.text.lower()
            # Check for explicit "vision not supported" signals
            vision_keywords = [
                "vision", "image", "multimodal", "not support",
                "unsupported", "invalid", "content_type",
            ]
            if any(kw in body for kw in vision_keywords):
                logger.debug("Vision probe rejected (status %d): %s", resp.status_code, resp.text[:200])
                return False
            # Generic 400 (bad request not related to vision) — treat as unsupported
            return False

        # 401/403 → auth issue — can't determine vision capability; assume False
        logger.debug("Vision probe auth error (status %d)", resp.status_code)
        return False

    except (httpx.TimeoutException, httpx.ConnectError) as e:
        logger.debug("Vision probe connection error: %s", e)
        return False
    except Exception as e:
        logger.debug("Vision probe unexpected error: %s", e)
        return False


async def _probe_anthropic(
    api_key: str,
    endpoint: str,
    model: str,
    timeout: float,
) -> bool:
    """Probe an Anthropic-compatible endpoint using base64 source block."""
    base_url = (endpoint or "https://api.anthropic.com").rstrip("/")
    url = f"{base_url}/v1/messages"

    payload = {
        "model": model or "claude-3-haiku-20240307",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": _PROBE_PNG_B64,
                        },
                    },
                    {"type": "text", "text": _PROBE_PROMPT},
                ],
            }
        ],
        "max_tokens": 10,
    }

    headers: dict[str, str] = {
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    if api_key:
        headers["x-api-key"] = api_key

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)

        if resp.status_code in (200, 201):
            return True

        if resp.status_code in (400, 415, 422):
            return False

        logger.debug("Anthropic vision probe status %d", resp.status_code)
        return False

    except (httpx.TimeoutException, httpx.ConnectError) as e:
        logger.debug("Anthropic vision probe connection error: %s", e)
        return False
    except Exception as e:
        logger.debug("Anthropic vision probe unexpected error: %s", e)
        return False
