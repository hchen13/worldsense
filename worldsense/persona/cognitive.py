"""
Layer 2: Cognitive model derivation.

Maps Hofstede cultural dimensions + Big Five personality traits
to consumer decision parameters.

Derivation logic is intentionally simple (table lookup + weighted linear blending).
This is designed to be easily replaced with a more sophisticated model later.
"""

from __future__ import annotations

import random

from typing import Optional

from worldsense.persona.schema import BigFiveProfile, CognitiveProfile, HofstedeProfile


# --- Big Five personality type clusters ---
# Each cluster maps Big Five trait ranges to a named type
# Big Five: O=openness, C=conscientiousness, E=extraversion, A=agreeableness, N=neuroticism
PERSONALITY_CLUSTERS = [
    {
        "id": "pragmatic_planner",
        "label": "Pragmatic Planner",
        "description": "Methodical, risk-aware, deliberate buyer",
        "traits": {"openness": (30, 60), "conscientiousness": (65, 100), "extraversion": (20, 60), "agreeableness": (40, 70), "neuroticism": (20, 55)},
    },
    {
        "id": "social_connector",
        "label": "Social Connector",
        "description": "Peer-influenced, brand-conscious, trend follower",
        "traits": {"openness": (45, 80), "conscientiousness": (30, 65), "extraversion": (65, 100), "agreeableness": (60, 100), "neuroticism": (30, 65)},
    },
    {
        "id": "value_hunter",
        "label": "Value Hunter",
        "description": "Price-sensitive, comparative shopper, cautious",
        "traits": {"openness": (20, 55), "conscientiousness": (55, 90), "extraversion": (20, 55), "agreeableness": (40, 75), "neuroticism": (30, 70)},
    },
    {
        "id": "impulse_explorer",
        "label": "Impulse Explorer",
        "description": "Spontaneous, novelty-seeking, emotionally driven",
        "traits": {"openness": (65, 100), "conscientiousness": (10, 45), "extraversion": (55, 95), "agreeableness": (40, 80), "neuroticism": (50, 85)},
    },
    {
        "id": "skeptical_analyst",
        "label": "Skeptical Analyst",
        "description": "Detail-oriented, distrusts marketing, needs evidence",
        "traits": {"openness": (50, 80), "conscientiousness": (60, 90), "extraversion": (10, 50), "agreeableness": (20, 55), "neuroticism": (35, 65)},
    },
    {
        "id": "loyal_traditionalist",
        "label": "Loyal Traditionalist",
        "description": "Brand loyal, risk-averse, prefers familiar products",
        "traits": {"openness": (10, 40), "conscientiousness": (55, 85), "extraversion": (30, 65), "agreeableness": (55, 85), "neuroticism": (20, 55)},
    },
    {
        "id": "aspirational_achiever",
        "label": "Aspirational Achiever",
        "description": "Status-motivated, premium-seeking, long-term thinker",
        "traits": {"openness": (55, 90), "conscientiousness": (65, 95), "extraversion": (50, 85), "agreeableness": (35, 65), "neuroticism": (25, 60)},
    },
    {
        "id": "cautious_homebody",
        "label": "Cautious Homebody",
        "description": "Conservative, needs trust, slow adopter",
        "traits": {"openness": (10, 40), "conscientiousness": (45, 75), "extraversion": (10, 40), "agreeableness": (50, 80), "neuroticism": (40, 75)},
    },
]


def derive_mbti(b5: BigFiveProfile) -> str:
    """
    Derive MBTI 4-letter type from Big Five trait values.

    Mapping (established in personality psychology literature):
        E/I ← Extraversion (>50 → E)
        N/S ← Openness (>50 → N)
        F/T ← Agreeableness (>50 → F, ≤50 → T)
        J/P ← Conscientiousness (>50 → J)
    """
    e_i = "E" if b5.extraversion > 50 else "I"
    s_n = "N" if b5.openness > 50 else "S"
    t_f = "F" if b5.agreeableness > 50 else "T"
    j_p = "J" if b5.conscientiousness > 50 else "P"
    return f"{e_i}{s_n}{t_f}{j_p}"


def assign_personality_type(b5: BigFiveProfile) -> str:
    """Assign a personality cluster based on Big Five trait values."""
    scores = {}
    b5_dict = {
        "openness": b5.openness,
        "conscientiousness": b5.conscientiousness,
        "extraversion": b5.extraversion,
        "agreeableness": b5.agreeableness,
        "neuroticism": b5.neuroticism,
    }

    for cluster in PERSONALITY_CLUSTERS:
        score = 0
        for trait, (lo, hi) in cluster["traits"].items():
            val = b5_dict[trait]
            if lo <= val <= hi:
                # Score by how close to center of range
                center = (lo + hi) / 2
                closeness = 1 - abs(val - center) / ((hi - lo) / 2 + 1)
                score += closeness
        scores[cluster["id"]] = score

    return max(scores, key=lambda k: scores[k])


def generate_big_five(rng: random.Random, nationality: str, age_group: str) -> BigFiveProfile:
    """
    Generate a Big Five profile with some cultural/demographic biasing.
    Base values are random, then shifted by nationality/age patterns.
    """
    # Base random values
    o = rng.gauss(55, 18)
    c = rng.gauss(55, 18)
    e = rng.gauss(50, 20)
    a = rng.gauss(55, 18)
    n = rng.gauss(45, 18)

    # Age adjustments (very approximate — research-backed trends)
    if age_group in ("55-64", "65+"):
        c += 5   # Higher conscientiousness with age
        n -= 8   # Lower neuroticism
        o -= 5   # Lower openness to experience
        e -= 3   # Slightly more introverted
    elif age_group == "18-24":
        o += 5   # More open to experience
        n += 8   # Higher neuroticism (identity formation)
        e += 5   # More extraverted

    # Clamp to 0-100
    def clamp(x: float) -> float:
        return max(0.0, min(100.0, x))

    return BigFiveProfile(
        openness=clamp(o),
        conscientiousness=clamp(c),
        extraversion=clamp(e),
        agreeableness=clamp(a),
        neuroticism=clamp(n),
    )


def derive_cognitive_profile(
    hofstede: HofstedeProfile,
    big_five: BigFiveProfile,
    age_group: str,
    rng: random.Random,
    # v2: income from occupation
    income_usd: int = 0,
    income_quantiles: Optional[list] = None,
    derived_price_sensitivity: Optional[float] = None,
    derived_wtp: Optional[float] = None,
    # legacy: kept for backward compat
    income_bracket: Optional[str] = None,
) -> CognitiveProfile:
    """
    Derive consumer cognitive parameters from Hofstede + Big Five + demographics.

    Each parameter is a weighted blend of relevant cultural/personality signals,
    plus a small noise term for individuation.
    """
    def n01(x: float) -> float:
        """Normalize 0-100 to 0-1."""
        return x / 100.0

    def noise(scale: float = 0.05) -> float:
        return rng.gauss(0, scale)

    def clamp01(x: float) -> float:
        return max(0.0, min(1.0, x))

    # --- analytical_vs_intuitive ---
    # High UAI (uncertainty avoidance) → more analytical/methodical
    # High conscientiousness → more analytical
    # Low neuroticism → more analytical
    analytical = (
        0.4 * n01(hofstede.uai)
        + 0.4 * n01(big_five.conscientiousness)
        + 0.2 * (1 - n01(big_five.neuroticism))
        + noise()
    )

    # --- individual_vs_social ---
    # High IDV (individualism) → individual decisions
    # Low agreeableness → individual
    individual = (
        0.6 * n01(hofstede.idv)
        + 0.4 * (1 - n01(big_five.agreeableness))
        + noise()
    )

    # --- authority_trust ---
    # High PDI (power distance) → trust authority/brands
    # High agreeableness → trust institutions
    authority_trust = (
        0.5 * n01(hofstede.pdi)
        + 0.3 * n01(big_five.agreeableness)
        + 0.2 * (1 - n01(big_five.openness))
        + noise()
    )

    # --- peer_influence ---
    # Low IDV (collectivist) → higher peer influence
    # High agreeableness → follows peers
    # High extraversion → social connections
    peer_influence = (
        0.4 * (1 - n01(hofstede.idv))
        + 0.3 * n01(big_five.agreeableness)
        + 0.3 * n01(big_five.extraversion)
        + noise()
    )

    # --- price_sensitivity ---
    # v2: use derived_price_sensitivity from occupation income if available
    # Otherwise fall back to legacy income_bracket mapping
    if derived_price_sensitivity is not None:
        income_factor = derived_price_sensitivity
    else:
        income_price_map = {
            "low": 0.85, "lower-middle": 0.65, "middle": 0.45,
            "upper-middle": 0.25, "high": 0.10
        }
        income_factor = income_price_map.get(income_bracket or "middle", 0.5)
    # High conscientiousness → price aware
    # Low MAS (feminine) → care about value
    price_sensitivity = (
        0.5 * income_factor
        + 0.3 * n01(big_five.conscientiousness)
        + 0.2 * (1 - n01(hofstede.mas))
        + noise()
    )

    # --- risk_appetite ---
    # Low UAI → risk tolerant
    # High openness → risk tolerant
    # Age: younger = more risk tolerant
    age_risk_map = {"18-24": 0.65, "25-34": 0.55, "35-44": 0.50, "45-54": 0.40, "55-64": 0.30, "65+": 0.25}
    age_factor = age_risk_map.get(age_group, 0.45)
    risk_appetite = (
        0.3 * (1 - n01(hofstede.uai))
        + 0.3 * n01(big_five.openness)
        + 0.2 * age_factor
        + 0.2 * (1 - n01(big_five.neuroticism))
        + noise()
    )

    # --- novelty_seeking ---
    # High openness → novelty
    # Low UAI → novelty
    # High IDV → novelty
    # High IVR (indulgence) → novelty
    novelty_seeking = (
        0.35 * n01(big_five.openness)
        + 0.25 * (1 - n01(hofstede.uai))
        + 0.20 * n01(hofstede.ivr)
        + 0.20 * n01(hofstede.idv)
        + noise()
    )

    # --- long_term_thinking ---
    # High LTO → long-term
    # High conscientiousness → long-term
    long_term = (
        0.5 * n01(hofstede.lto)
        + 0.5 * n01(big_five.conscientiousness)
        + noise()
    )

    # --- detail_attention ---
    # High UAI → reads fine print
    # High conscientiousness → attention to detail
    # Low neuroticism → focused
    detail_attention = (
        0.4 * n01(hofstede.uai)
        + 0.4 * n01(big_five.conscientiousness)
        + 0.2 * (1 - n01(big_five.neuroticism))
        + noise()
    )

    # --- emotional_reactivity ---
    # High neuroticism → emotional
    # High IVR (indulgence) → emotional expression
    # Low UAI → less fear-driven but more spontaneous
    emotional_reactivity = (
        0.5 * n01(big_five.neuroticism)
        + 0.3 * n01(hofstede.ivr)
        + 0.2 * n01(big_five.extraversion)
        + noise()
    )

    # --- wtp_multiplier ---
    # v2: use derived_wtp from occupation income quantile if available
    if derived_wtp is not None:
        base_wtp = derived_wtp
    else:
        income_wtp_map = {
            "low": 0.4, "lower-middle": 0.7, "middle": 1.0,
            "upper-middle": 1.5, "high": 2.5
        }
        base_wtp = income_wtp_map.get(income_bracket or "middle", 1.0)
    wtp_multiplier = base_wtp * (1 + rng.gauss(0, 0.15))
    wtp_multiplier = max(0.1, wtp_multiplier)

    return CognitiveProfile(
        analytical_vs_intuitive=clamp01(analytical),
        individual_vs_social=clamp01(individual),
        authority_trust=clamp01(authority_trust),
        peer_influence=clamp01(peer_influence),
        price_sensitivity=clamp01(price_sensitivity),
        risk_appetite=clamp01(risk_appetite),
        novelty_seeking=clamp01(novelty_seeking),
        long_term_thinking=clamp01(long_term),
        detail_attention=clamp01(detail_attention),
        emotional_reactivity=clamp01(emotional_reactivity),
        wtp_multiplier=round(wtp_multiplier, 3),
    )
