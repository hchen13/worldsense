"""Structured output schema and prompt builders for persona feedback responses."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Intent Presets — maps research_type → (label1, label2, label3, description)
# label1 = "positive" intent, label2 = "neutral/uncertain", label3 = "pass"
# ---------------------------------------------------------------------------
INTENT_PRESETS: dict[str, dict] = {
    "product_purchase": {
        "values": ["buy", "hesitate", "pass"],
        "descriptions": {
            "buy": "Would definitely purchase / has strong intent to buy",
            "hesitate": "Interested but uncertain, would consider with more info",
            "pass": "Would not buy / not interested",
        },
        "question": "Would this persona buy the product?",
    },
    "social_follow": {
        "values": ["follow", "consider", "pass"],
        "descriptions": {
            "follow": "Would follow this account without hesitation",
            "consider": "Interested but needs to see more content before deciding to follow",
            "pass": "Would not follow / not interested in this account",
        },
        "question": "Would this persona follow this account?",
    },
    "content_reaction": {
        "values": ["watch", "maybe", "pass"],
        "descriptions": {
            "watch": "Would watch/read this content fully and might share it",
            "maybe": "Might skim or save for later, not fully engaged",
            "pass": "Would scroll past / not interested in this content",
        },
        "question": "Would this persona watch or read this content?",
    },
    "app_trial": {
        "values": ["trial", "consider", "pass"],
        "descriptions": {
            "trial": "Would download and actively try this app/service",
            "consider": "Curious but not ready to commit, would bookmark for later",
            "pass": "Would not try this app/service",
        },
        "question": "Would this persona try this app or service?",
    },
    "concept_test": {
        "values": ["buy", "hesitate", "pass"],
        "descriptions": {
            "buy": "Strongly resonates with this concept / would act on it",
            "hesitate": "Interesting concept but uncertain about real-world viability",
            "pass": "Concept does not resonate",
        },
        "question": "How does this persona respond to this concept?",
    },
    "competitive_switch": {
        "values": ["switch", "consider", "pass"],
        "descriptions": {
            "switch": "Would switch from current solution to this one",
            "consider": "Interested in switching but needs more convincing / time",
            "pass": "Would not switch, prefers current solution",
        },
        "question": "Would this persona switch from their current solution to this?",
    },
}

DEFAULT_INTENT_PRESET = INTENT_PRESETS["product_purchase"]


FEEDBACK_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "purchase_intent": {
            "type": "string",
            "enum": ["buy", "hesitate", "pass"],
            "description": "Would this persona buy the product? (default schema; overridden by research_type in merged prompt)"
        },
        "nps_score": {
            "type": "integer",
            "minimum": 0,
            "maximum": 10,
            "description": "Net Promoter Score (0=extremely unlikely to recommend, 10=extremely likely)"
        },
        "sentiment_score": {
            "type": "number",
            "minimum": -1.0,
            "maximum": 1.0,
            "description": "Overall sentiment (-1=very negative, 0=neutral, 1=very positive)"
        },
        "key_attraction": {
            "type": "string",
            "description": "The main thing that appeals to this persona"
        },
        "key_concern": {
            "type": "string",
            "description": "The main concern or objection"
        },
        "verbatim": {
            "type": "string",
            "description": "Natural-language reaction in 2-3 sentences, authentic to the persona's voice"
        },
        "willingness_to_pay_multiplier": {
            "type": "number",
            "description": "Relative WTP vs. average price (1.0=average, 0.5=half price, 2.0=double)"
        }
    },
    "required": [
        "purchase_intent",
        "nps_score",
        "sentiment_score",
        "key_attraction",
        "key_concern",
        "verbatim"
    ],
    "additionalProperties": False
}


# ---------------------------------------------------------------------------
# Mode B: Merged epsilon+evaluation schema
# ---------------------------------------------------------------------------

MERGED_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "epsilon": {
            "type": "string",
            "description": "2-3 sentence personal background imagined in Phase 1"
        },
        "name": {
            "type": "string",
            "description": "Culturally appropriate full name for this persona (native script + romanization, e.g. '陈浩 (Chen Hao)')"
        },
        **FEEDBACK_JSON_SCHEMA["properties"],
    },
    "required": ["epsilon", "name"] + FEEDBACK_JSON_SCHEMA["required"],
    "additionalProperties": False,
}

MERGED_SYSTEM_PROMPT = (
    "You are a research assistant. First you will construct a concrete, specific person "
    "matching a demographic profile, then evaluate a product from that person's authentic perspective. "
    "Include a culturally authentic name for the person (native script + romanization where applicable, "
    "e.g. '陈浩 (Chen Hao)' for Chinese, 'Kenji Mori (森健二)' for Japanese). "
    "Output ONLY a valid JSON object with no markdown fences and no extra text."
)


def _build_language_instruction(country_name: str, language: str) -> str:
    """Build language output instruction block for merged prompt."""
    if language.lower() == "english":
        return (
            "LANGUAGE: All output fields in English. "
            "verbatim should reflect the persona's authentic voice; "
            "non-native English speakers may show their natural phrasing."
        )
    return (
        f"LANGUAGE INSTRUCTIONS:\n"
        f"- epsilon, key_attraction, key_concern: write in {language}.\n"
        f"- verbatim: FIRST write in the persona's native language "
        f"(they are from {country_name} — use the language native speakers there would naturally use). "
        f"Then, if the native language differs from {language}, append on a new line: "
        f'"[Translation]: <{language} translation of the verbatim>"\n'
        f"- All other fields (purchase_intent enum values, numbers): unchanged."
    )


def build_merged_prompt(
    persona_summary: dict,
    content: str,
    scenario_context: str = "",
    language: str = "English",
    research_type: str = "product_purchase",
) -> str:
    """
    Build Mode B two-phase merged prompt: persona imagination + evaluation in one call.

    Phase 1: LLM imagines a concrete individual matching the demographic profile.
    Phase 2: LLM evaluates the content as that specific person.

    Returns a JSON response with epsilon + all standard evaluation fields.
    The purchase_intent field uses values determined by research_type:
      - product_purchase: buy / hesitate / pass
      - social_follow:    follow / consider / pass
      - content_reaction: watch / maybe / pass
      - app_trial:        trial / consider / pass
      - competitive_switch: switch / consider / pass
    """
    # Resolve intent preset
    intent_preset = INTENT_PRESETS.get(research_type, DEFAULT_INTENT_PRESET)
    v1, v2, v3 = intent_preset["values"]
    d1 = intent_preset["descriptions"][v1]
    d2 = intent_preset["descriptions"][v2]
    d3 = intent_preset["descriptions"][v3]
    intent_question = intent_preset["question"]
    ps = persona_summary

    # Occupation display
    occupation_str = ps.get("occupation_title", "") or ps.get("occupation_label", "")
    local_title = ps.get("occupation_title_local") or {}
    if isinstance(local_title, dict) and local_title:
        local = next(iter(local_title.values()), "")
        if local and local != occupation_str:
            occupation_str = f"{occupation_str} ({local})"

    location = ps.get("city_tier_label") or ps.get("urban_rural", "")
    personality = (ps.get("personality_type") or "").replace("_", " ").title()
    mbti = ps.get("mbti", "")
    if mbti:
        personality = f"{personality} (MBTI: {mbti})"
    novelty = round(float(ps.get("novelty_seeking", 0.5)), 2)
    price_sens = round(float(ps.get("price_sensitivity", 0.5)), 2)
    risk = round(float(ps.get("risk_appetite", 0.5)), 2)

    education = ps.get("occupation_education", "")
    work_ctx = ps.get("occupation_work_context", "")
    income_display = ps.get("income_display", "")

    education_line = f"\nEducation: {education}" if education else ""
    work_line = f"\nWork context: {work_ctx}" if work_ctx else ""

    scenario_block = ""
    if scenario_context and scenario_context.strip():
        scenario_block = f"""
---
SCENARIO CONTEXT (how you encounter this content):
{scenario_context.strip()}
"""

    language_instruction = _build_language_instruction(
        ps.get("country_name", ""), language
    )

    return f"""\
## PHASE 1 — Construct a Concrete Person

Given this demographic profile, first imagine a specific real-feeling individual:

Profile: {ps.get('age', '')}-year-old {ps.get('gender', '')} from {ps.get('country_name', '')}, {occupation_str}, {income_display}, {location}, {personality} personality.
Cognitive traits: novelty-seeking={novelty} (0=very conservative, 1=loves new things), price-sensitivity={price_sens} (0=spends freely, 1=very frugal), risk-appetite={risk} (0=risk-averse, 1=risk-taker).{education_line}{work_line}

Pick 2-3 specific personal details (family situation, hobby, a recent purchase or goal, social media habit). Then separately identify 2-3 LEISURE INTERESTS — topics this person follows outside of work (e.g. investing/finance, cooking, gaming, fitness, parenting, travel, tech gadgets, celebrity gossip, sports, politics, fashion, pets, cars, etc.). These should feel natural for their age, income, and personality — not random.
IMPORTANT: Background and interests MUST be consistent with the cognitive traits above (high novelty-seeker = explores diverse topics; low risk-appetite = sticks to safe/mainstream interests; high openness = wide-ranging curiosity).
Also give this person a culturally authentic full name. For non-English names, use native script as the primary form with romanization in parentheses (e.g. "陈浩 (Chen Hao)", "森健二 (Mori Kenji)", "김민준 (Kim Minjun)").

## PHASE 2 — Evaluate as This Person

Now, AS the specific person you just imagined (including your leisure interests, not just your job), evaluate the following honestly. Consider whether this content connects to ANY of your interests — professional OR personal:{scenario_block}

CONTENT TO EVALUATE:
{content}

EVALUATION FOCUS:
- {intent_question}
- Overall impression: What impressed you most and least?
- Share willingness: Would you share this with friends or colleagues?

{language_instruction}

INTENT VALUES — Use exactly one of these for "purchase_intent":
- "{v1}": {d1}
- "{v2}": {d2}
- "{v3}": {d3}

REQUIRED RESPONSE FORMAT — Respond ONLY with a valid JSON object. No markdown fences. No explanation.

{{
  "epsilon": "<2-3 sentence personal background + leisure interests you imagined in Phase 1>",
  "name": "<culturally authentic full name, native script + romanization if non-Latin, e.g. '陈浩 (Chen Hao)'>",
  "purchase_intent": "{v1}" | "{v2}" | "{v3}",
  "nps_score": <integer 0-10>,
  "sentiment_score": <float -1.0 to 1.0>,
  "key_attraction": "<what most appeals to you>",
  "key_concern": "<your main worry or objection>",
  "verbatim": "<your authentic reaction — see language instructions>",
  "willingness_to_pay_multiplier": <float, 1.0 = average, 0.5 = half, 2.0 = double>
}}

Be honest and authentic — not uniformly positive. Reflect your real cognitive style, cultural background, financial situation, and personal interests. Do NOT evaluate solely based on your job — consider your full identity as a person with hobbies, curiosities, and a life outside work."""


def build_feedback_prompt(persona_context: str, content: str, scenario_context: str = "") -> str:
    """
    Legacy: Build the inference prompt for a single persona (Mode A style).
    Kept for backward compatibility / testing. Production uses build_merged_prompt().
    """
    scenario_block = ""
    if scenario_context and scenario_context.strip():
        scenario_block = f"""
---

SCENARIO CONTEXT (how you encounter this content):
{scenario_context.strip()}
"""

    return f"""\
{persona_context}{scenario_block}

---

Please evaluate the following product/content from your perspective as described above.

CONTENT TO EVALUATE:
{content}

---

EVALUATION FOCUS:
Address these questions from your personal perspective:
- Overall impression (rate 1-10): What impressed you most and least?
- Pay willingness: Would you pay for this? What price range is acceptable?
- Share willingness: Would you share this with friends or colleagues?

REQUIRED RESPONSE FORMAT:
Respond ONLY with a valid JSON object. No markdown fences. No explanation text.

The JSON must have exactly these fields:
{{
  "purchase_intent": "buy" | "hesitate" | "pass",
  "nps_score": <integer 0-10>,
  "sentiment_score": <float -1.0 to 1.0>,
  "key_attraction": "<what most appeals to you>",
  "key_concern": "<your main worry or objection>",
  "verbatim": "<your authentic 2-3 sentence reaction in your own voice>",
  "willingness_to_pay_multiplier": <float, 1.0 = average, 0.5 = half, 2.0 = double>
}}

Be honest and authentic — not uniformly positive. Reflect your real cognitive style, cultural background, and financial situation.
"""
