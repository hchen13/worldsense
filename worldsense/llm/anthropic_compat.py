"""
Anthropic-compatible LLM backend.

Supports any Anthropic-compatible API endpoint:
- Anthropic native (api.anthropic.com)
- MiniMax International (api.minimax.io/anthropic)
- Any proxy implementing the Anthropic Messages API format

The Anthropic Messages API uses POST /v1/messages (not /v1/chat/completions),
so this backend is required whenever the endpoint speaks Anthropic protocol.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

import httpx

from worldsense.llm.backend import LLMBackend
from worldsense.llm.rate_limiter import RateLimiter


# Load .env from project root if present
def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
        env_path = Path(__file__).parent.parent.parent / ".env"
        if env_path.exists():
            load_dotenv(env_path, override=False)
    except ImportError:
        pass

_load_dotenv()


FEEDBACK_SYSTEM_PROMPT = """\
You are a research participant giving honest feedback about a product or content.
Respond ONLY with a valid JSON object matching the schema provided.
Be authentic to your persona's background, cultural context, and cognitive style.
Do not be uniformly positive — reflect your genuine reaction.
Output ONLY the JSON object, no markdown fences, no extra text.
"""


class AnthropicCompatBackend(LLMBackend):
    """
    Backend for any Anthropic-compatible API endpoint (Messages API format).

    Calls POST {base_url}/v1/messages with Anthropic request format.
    Suitable for:
      - MiniMax International: https://api.minimax.io/anthropic
      - Anthropic native: https://api.anthropic.com

    Configuration via constructor kwargs or environment variables:
        WS_API_KEY, WS_API_BASE_URL, WS_MODEL
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        requests_per_minute: int = 60,
        max_concurrent: int = 10,
        timeout: float = 120.0,
        **kwargs,
    ):
        self.api_key = api_key or os.getenv("WS_API_KEY", "")
        self.base_url = (base_url or os.getenv("WS_API_BASE_URL", "https://api.anthropic.com")).rstrip("/")
        self.model = model or os.getenv("WS_MODEL", "claude-3-5-haiku-20241022")
        self.timeout = timeout

        self._rate_limiter = RateLimiter(
            requests_per_minute=requests_per_minute,
            max_concurrent=max_concurrent,
        )
        self._client = httpx.AsyncClient(
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            timeout=timeout,
        )

    async def generate(
        self,
        prompt: str,
        schema: Optional[dict] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        extra_body: Optional[dict] = None,
        json_mode: bool = True,
        images: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        async with self._rate_limiter:
            # Build user content: text + optional images (Anthropic vision format)
            if images:
                import re
                content_blocks: list[dict] = []
                for img_url in images:
                    # Parse data URL: data:image/png;base64,...
                    m = re.match(r'data:(image/[\w+.-]+);base64,(.+)', img_url)
                    if m:
                        content_blocks.append({
                            "type": "image",
                            "source": {"type": "base64", "media_type": m.group(1), "data": m.group(2)},
                        })
                content_blocks.append({"type": "text", "text": prompt})
                user_content = content_blocks
            else:
                user_content = prompt  # type: ignore[assignment]

            messages = [
                {"role": "user", "content": user_content},
            ]

            payload: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }

            if system_prompt or json_mode:
                payload["system"] = system_prompt or FEEDBACK_SYSTEM_PROMPT

            # Anthropic doesn't support extra_body fields like enable_thinking for most models
            # but we silently ignore them for compatibility

            response = await self._client.post(
                f"{self.base_url}/v1/messages",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

            # Anthropic response format:
            # { "content": [{"type": "text", "text": "..."}], "usage": {...} }
            content_blocks = data.get("content", [])
            content = ""
            for block in content_blocks:
                if block.get("type") == "text":
                    content = block.get("text", "")
                    break

            usage_raw = data.get("usage", {})
            usage = {
                "prompt_tokens": usage_raw.get("input_tokens", 0),
                "completion_tokens": usage_raw.get("output_tokens", 0),
                "total_tokens": usage_raw.get("input_tokens", 0) + usage_raw.get("output_tokens", 0),
            }

            # Strip markdown fences if model wrapped JSON in ```json ... ```
            stripped = content.strip()
            if stripped.startswith("```"):
                lines = stripped.split("\n")
                lines = [l for l in lines if not l.strip().startswith("```")]
                stripped = "\n".join(lines).strip()

            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                import re
                m = re.search(r'\{.*\}', stripped, re.DOTALL)
                if m:
                    try:
                        parsed = json.loads(m.group())
                    except json.JSONDecodeError:
                        parsed = None
                else:
                    parsed = None

            return {
                "content": stripped,
                "parsed": parsed,
                "usage": usage,
            }

    async def close(self) -> None:
        await self._client.aclose()
