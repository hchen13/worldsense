"""
Layer 2.5: Real-time epsilon generation via LLM.

Generates a unique 2-3 sentence personal background for each persona.

## Current usage (Mode B)

After A/B testing, Mode B (merged epsilon + evaluation in one call) won.
The merged approach is now used for all simulation runs via `build_merged_prompt()`
in pipeline/output.py — the LLM imagines the persona background as Phase 1, then
evaluates as that person in Phase 2.

This module (`generate_epsilon`) is now used ONLY for the WebUI persona preview
feature, where a lightweight standalone call is needed to display persona backgrounds
before a full simulation run. It is NOT called during actual simulation.

Design principles (preview use):
- enable_thinking=False (fast path, no reasoning needed)
- temperature=0.9 (high randomness so same occupation → different backgrounds)
- Graceful degradation: any failure returns "" and preview continues normally
"""

from __future__ import annotations


EPSILON_SYSTEM_PROMPT = (
    "You are generating realistic personal backgrounds for market research personas. "
    "Output only 2-3 sentences of plain English text. No JSON, no bullet points, no labels."
)

EPSILON_PROMPT_TEMPLATE = """\
Given this person's profile, generate a unique 2-3 sentence personal background.
Pick 2-3 details from this list (vary your selection each time, do NOT always pick the same ones):
- Family situation (single/married/divorced, kids or not)
- A hobby, interest, or side passion
- How they discover new products or get recommendations
- A recent purchase they were excited about
- A personal goal or aspiration
- A social media habit or entertainment preference
Be specific and realistic. Vary the tone naturally — some people have worries, some are content, some are ambitious, some are carefree. Reflect what's realistic for their income and life stage.
IMPORTANT: The background MUST be consistent with this person's cognitive traits below. A low novelty-seeker sticks to familiar brands/routines. A high novelty-seeker actively tries new things. A high risk-taker makes bold choices. Reflect these traits naturally in the background details.
Do NOT repeat the occupation or income info already given.

Profile: {age}-year-old {gender} from {country_name}, {occupation_title}, ~{income_display}, {location_label}, {personality_label} personality.
Cognitive traits: novelty-seeking={novelty_seeking} (0=very conservative, 1=loves new things), price-sensitivity={price_sensitivity} (0=spends freely, 1=very frugal), risk-appetite={risk_appetite} (0=risk-averse, 1=risk-taker)."""


def _build_epsilon_prompt(persona_summary: dict) -> str:
    age = persona_summary.get("age", "")
    gender = persona_summary.get("gender", "")
    country_name = persona_summary.get("country_name", "")
    occupation_title = (
        persona_summary.get("occupation_title")
        or persona_summary.get("occupation_label", "")
    )
    income_display = persona_summary.get("income_display", "")
    city_tier_label = persona_summary.get("city_tier_label", "")
    urban_rural = persona_summary.get("urban_rural", "")
    location_label = city_tier_label if city_tier_label else urban_rural
    personality_type = persona_summary.get("personality_type", "")
    personality_label = personality_type.replace("_", " ").title()

    novelty_seeking = round(persona_summary.get("novelty_seeking", 0.5), 2)
    price_sensitivity = round(persona_summary.get("price_sensitivity", 0.5), 2)
    risk_appetite = round(persona_summary.get("risk_appetite", 0.5), 2)

    return EPSILON_PROMPT_TEMPLATE.format(
        age=age,
        gender=gender,
        country_name=country_name,
        occupation_title=occupation_title,
        income_display=income_display,
        location_label=location_label,
        personality_label=personality_label,
        novelty_seeking=novelty_seeking,
        price_sensitivity=price_sensitivity,
        risk_appetite=risk_appetite,
    )


async def generate_epsilon(persona_summary: dict, llm_backend) -> str:
    """
    Generate a unique 2-3 sentence personal background for a persona.

    Args:
        persona_summary: dict from Persona.to_dict_summary()
        llm_backend: any LLMBackend instance

    Returns:
        2-3 sentence personal background string, or "" on any failure.
    """
    prompt = _build_epsilon_prompt(persona_summary)
    try:
        response = await llm_backend.generate(
            prompt=prompt,
            schema=None,
            system_prompt=EPSILON_SYSTEM_PROMPT,
            temperature=0.9,
            max_tokens=150,
            extra_body={"enable_thinking": False},
            json_mode=False,
        )
        content = response.get("content", "").strip()
        return content
    except Exception:
        return ""
