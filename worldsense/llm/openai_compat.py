"""
OpenAI-compatible LLM backend.

Supports any OpenAI-compatible API endpoint:
- OpenAI (api.openai.com)
- Anthropic (via openai-compat proxy)
- DeepSeek (api.deepseek.com/v1)
- GLM-5.1 (open.bigmodel.cn/api/coding/paas/v4)  — thinking model
- Local Ollama (localhost:11434/v1)
- Any custom endpoint

NOTE for GLM-5.1 (thinking model):
  - Use the coding endpoint: /api/coding/paas/v4  (NOT /api/paas/v4 — returns 403)
  - response_format=json_schema is NOT supported; use json_object instead
  - The response message.content may be empty/null when thinking is active;
    actual answer is in message.reasoning_content or appears after thinking completes.
    We fall back to reasoning_content if content is blank.
  - Give it plenty of max_tokens (>=2000) so it doesn't cut off mid-JSON.
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

FEEDBACK_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": ["buy", "hesitate", "pass"]},
        "nps_score": {"type": "integer", "minimum": 0, "maximum": 10},
        "sentiment_score": {"type": "number", "minimum": -1.0, "maximum": 1.0},
        "key_attraction": {"type": "string", "description": "Main appeal to you"},
        "key_concern": {"type": "string", "description": "Main concern or objection"},
        "verbatim": {"type": "string", "description": "Your natural-language reaction (2-3 sentences)"},
        "willingness_to_pay_multiplier": {"type": "number", "description": "Relative WTP vs average price"}
    },
    "required": ["intent", "nps_score", "sentiment_score", "key_attraction", "key_concern", "verbatim"]
}


def _extract_content(message: dict) -> str:
    """
    Extract text content from a chat completion message.

    For GLM-5.1 (thinking model), message.content can be empty/null while
    thinking is happening, and the real answer ends up in message.content
    after the thinking phase. If content is empty, fall back to
    reasoning_content (which may contain the full response for some versions).
    """
    content = message.get("content") or ""
    if not content.strip():
        # GLM-5.1 thinking fallback
        content = message.get("reasoning_content") or ""
    return content.strip()


class OpenAICompatBackend(LLMBackend):
    """
    Backend for any OpenAI-compatible API endpoint.

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
        timeout: float = 120.0,  # GLM-5.1 thinking can be slow
        **kwargs,
    ):
        self.api_key = api_key or os.getenv("WS_API_KEY", "")
        self.base_url = (base_url or os.getenv("WS_API_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
        self.model = model or os.getenv("WS_MODEL", "gpt-4o-mini")
        self.timeout = timeout

        self._rate_limiter = RateLimiter(
            requests_per_minute=requests_per_minute,
            max_concurrent=max_concurrent,
        )
        self._client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=timeout,
        )

    async def generate(
        self,
        prompt: str,
        schema: Optional[dict] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,  # GLM-5.1 uses ~200-500 tokens for reasoning before actual output
        extra_body: Optional[dict] = None,
        json_mode: bool = True,
        images: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        async with self._rate_limiter:
            # Build user content: text + optional images (OpenAI vision format)
            if images:
                user_content: list[dict] = []
                for img_url in images:
                    user_content.append({"type": "image_url", "image_url": {"url": img_url}})
                user_content.append({"type": "text", "text": prompt})
            else:
                user_content = prompt  # type: ignore[assignment]

            messages = [
                {"role": "system", "content": system_prompt or FEEDBACK_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ]

            payload: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }

            # json_object mode only for structured evaluation calls; skip for epsilon
            if json_mode:
                # Use json_object — GLM-5.1 does not support json_schema response_format
                payload["response_format"] = {"type": "json_object"}

            # Merge any extra_body parameters (e.g. enable_thinking=False for epsilon calls)
            if extra_body:
                payload.update(extra_body)

            response = await self._client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

            message = data["choices"][0]["message"]
            content = _extract_content(message)
            usage = data.get("usage", {})

            # Strip markdown fences if model wrapped JSON in ```json ... ```
            stripped = content.strip()
            if stripped.startswith("```"):
                lines = stripped.split("\n")
                # Remove first and last fence lines
                lines = [l for l in lines if not l.strip().startswith("```")]
                stripped = "\n".join(lines).strip()

            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                # Try to find a JSON object within the text
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
