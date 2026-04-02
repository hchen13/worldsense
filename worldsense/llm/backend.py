"""
LLMBackend abstract interface + MockBackend.

All backends implement:
    async generate(prompt: str, schema: dict | None) -> dict
"""

from __future__ import annotations

import json
import random
from abc import ABC, abstractmethod
from typing import Any, Optional


class LLMBackend(ABC):
    """Abstract base class for LLM inference backends."""

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        schema: Optional[dict] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 512,
        extra_body: Optional[dict] = None,
        json_mode: bool = True,
        images: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """
        Generate a response for the given prompt.

        Args:
            prompt: The user prompt
            schema: Optional JSON schema to enforce structured output
            system_prompt: Optional system-level instruction
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            images: Optional list of base64-encoded image data URLs (data:image/...;base64,...)

        Returns:
            dict with at least:
                - "content": str  (raw text response)
                - "parsed": dict | None  (parsed JSON if schema provided)
                - "usage": dict  (token counts)
        """
        ...

    @abstractmethod
    async def close(self) -> None:
        """Clean up resources (close HTTP sessions, etc.)."""
        ...


# --- Mock backend ---

_PURCHASE_INTENTS = ["buy", "hesitate", "pass"]

_ATTRACTIONS_BY_PERSONALITY = {
    "pragmatic_planner": [
        "Clear value proposition and ROI", "Detailed feature specifications",
        "Long-term reliability guarantees", "Transparent pricing structure"
    ],
    "social_connector": [
        "Strong community and user reviews", "Social sharing features",
        "Trendy design and brand perception", "Influencer endorsements"
    ],
    "value_hunter": [
        "Competitive price point", "Good quality-to-price ratio",
        "Free trial or demo option", "Bundle deals and discounts"
    ],
    "impulse_explorer": [
        "Exciting new features", "Novelty and innovation", "Immediate gratification",
        "Emotional appeal and storytelling"
    ],
    "skeptical_analyst": [
        "Independent third-party reviews", "Technical documentation depth",
        "Transparent company information", "Evidence-based claims"
    ],
    "loyal_traditionalist": [
        "Brand heritage and trust", "Familiar and intuitive interface",
        "Reliable customer support", "Clear product history"
    ],
    "aspirational_achiever": [
        "Premium quality signals", "Status and exclusivity",
        "Long-term investment value", "Professional-grade features"
    ],
    "cautious_homebody": [
        "Clear return/refund policy", "Easy setup and low complexity",
        "Safety and privacy features", "Trusted brand reputation"
    ],
}

_CONCERNS_BY_INCOME = {
    "low": ["Too expensive for my budget", "Can't afford if it doesn't work out",
            "Hidden costs and fees", "No free tier available"],
    "lower-middle": ["Price feels high for what I get", "Worried about long-term costs",
                     "Monthly subscription adds up", "Better free alternatives exist"],
    "middle": ["Feature depth vs price balance", "Competitor alternatives worth comparing",
               "Switching costs from current solution", "Not sure it solves my main problem"],
    "upper-middle": ["Implementation complexity", "Integration with existing tools",
                     "Vendor lock-in concerns", "Support quality at scale"],
    "high": ["Enterprise readiness", "Security and compliance",
             "Customization limitations", "Long-term roadmap visibility"],
}

_VERBATIM_TEMPLATES = [
    "Honestly, {attraction}. But {concern} makes me think twice.",
    "My first impression was positive — {attraction}. The main thing holding me back: {concern}.",
    "{attraction} is what stands out most. If they could address {concern}, I'd be a buyer.",
    "I've seen similar products. {attraction} differentiates this one. Still, {concern}.",
    "As someone in my situation, {attraction} matters a lot. {concern} is a real sticking point.",
]


class MockBackend(LLMBackend):
    """
    Mock backend for testing and demos.

    Generates deterministic-ish structured responses based on persona cognitive profile.
    No API calls made — all responses are procedurally generated.
    """

    def __init__(self, **kwargs):
        self._rng = random.Random()

    async def generate(
        self,
        prompt: str,
        schema: Optional[dict] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 512,
        extra_body: Optional[dict] = None,
        json_mode: bool = True,
        images: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Generate a mock structured response based on prompt content."""
        # If not json_mode, this is a standalone epsilon preview call — return a canned backstory
        if not json_mode:
            return {
                "content": (
                    "Married with two school-age children, currently saving for a family vacation. "
                    "Gets most information from WeChat groups and friends' recommendations. "
                    "Tends to compare prices carefully before any purchase over ¥200."
                ),
                "parsed": None,
                "usage": {"prompt_tokens": len(prompt.split()), "completion_tokens": 40, "total_tokens": len(prompt.split()) + 40},
            }

        # Detect Mode B merged prompt (system_prompt contains "construct a concrete")
        is_merged = system_prompt and "construct a concrete" in system_prompt.lower()

        # Extract persona context from prompt if available
        persona_data = self._parse_persona_from_prompt(prompt)

        # Determine purchase intent based on cognitive parameters
        intent, nps, sentiment = self._simulate_response(persona_data)

        personality = persona_data.get("personality_type", "pragmatic_planner")
        income = persona_data.get("income_bracket", "middle")

        attractions = _ATTRACTIONS_BY_PERSONALITY.get(
            personality, _ATTRACTIONS_BY_PERSONALITY["pragmatic_planner"]
        )
        concerns = _CONCERNS_BY_INCOME.get(income, _CONCERNS_BY_INCOME["middle"])

        attraction = self._rng.choice(attractions)
        concern = self._rng.choice(concerns)
        verbatim_template = self._rng.choice(_VERBATIM_TEMPLATES)
        verbatim = verbatim_template.format(attraction=attraction.lower(), concern=concern.lower())

        wtp_multiplier = persona_data.get("wtp_multiplier", 1.0)

        # Map simulated intent to research-type-specific values by detecting from prompt
        # Look for INTENT VALUES block injected by build_merged_prompt
        intent_map = self._extract_intent_values_from_prompt(prompt)
        if intent_map:
            slot1, slot2, slot3 = intent_map
            if intent == "buy":
                intent = slot1
            elif intent == "hesitate":
                intent = slot2
            else:
                intent = slot3

        parsed = {
            "intent": intent,
            "nps_score": nps,
            "sentiment_score": round(sentiment, 3),
            "key_attraction": attraction,
            "key_concern": concern,
            "verbatim": verbatim,
            "willingness_to_pay_multiplier": round(wtp_multiplier, 3),
        }

        # Mode B: include epsilon and name fields in response
        if is_merged:
            parsed["epsilon"] = (
                "Married with two school-age children, currently saving for a family vacation. "
                "Gets most information from WeChat groups and friends' recommendations. "
                "Tends to compare prices carefully before any purchase over ¥200."
            )
            # Fallback name from persona_data (already set by generator) — mock doesn't call LLM
            parsed["name"] = persona_data.get("name", "")

        return {
            "content": json.dumps(parsed),
            "parsed": parsed,
            "usage": {"prompt_tokens": len(prompt.split()), "completion_tokens": 80, "total_tokens": len(prompt.split()) + 80},
        }

    def _extract_intent_values_from_prompt(self, prompt: str) -> Optional[tuple]:
        """Extract (slot1, slot2, slot3) intent values from INTENT VALUES block in prompt."""
        import re
        m = re.search(r'- "([^"]+)": .*\n- "([^"]+)": .*\n- "([^"]+)":', prompt)
        if m:
            return m.group(1), m.group(2), m.group(3)
        return None

    def _parse_persona_from_prompt(self, prompt: str) -> dict:
        """Try to extract structured data embedded in a prompt."""
        data = {}
        lines = prompt.split("\n")
        for line in lines:
            if "PERSONA_DATA:" in line:
                try:
                    json_str = line.split("PERSONA_DATA:")[1].strip()
                    data = json.loads(json_str)
                except Exception:
                    pass
        return data

    def _simulate_response(self, persona_data: dict) -> tuple[str, int, float]:
        """Simulate purchase intent + NPS + sentiment from cognitive profile."""
        # Use cognitive parameters if available
        price_sensitivity = persona_data.get("price_sensitivity", 0.5)
        risk_appetite = persona_data.get("risk_appetite", 0.5)
        novelty_seeking = persona_data.get("novelty_seeking", 0.5)
        emotional_reactivity = persona_data.get("emotional_reactivity", 0.5)

        # Score = rough "likelihood to buy" signal
        buy_score = (
            0.3 * (1 - price_sensitivity)
            + 0.25 * risk_appetite
            + 0.25 * novelty_seeking
            + 0.2 * emotional_reactivity
            + self._rng.gauss(0, 0.1)
        )
        buy_score = max(0, min(1, buy_score))

        if buy_score > 0.6:
            intent = "buy"
            nps = self._rng.randint(8, 10)
            sentiment = self._rng.uniform(0.3, 0.9)
        elif buy_score > 0.35:
            intent = "hesitate"
            nps = self._rng.randint(5, 8)
            sentiment = self._rng.uniform(-0.1, 0.4)
        else:
            intent = "pass"
            nps = self._rng.randint(0, 5)
            sentiment = self._rng.uniform(-0.7, 0.1)

        return intent, nps, sentiment

    async def close(self) -> None:
        pass
