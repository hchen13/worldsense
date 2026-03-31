"""Persona data models.

v2: income derived from occupation; added income_local, income_currency, income_usd.
"""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


class HofstedeProfile(BaseModel):
    """Cultural dimensions derived from Hofstede's model."""
    pdi: float = Field(..., ge=0, le=100, description="Power Distance")
    idv: float = Field(..., ge=0, le=100, description="Individualism")
    mas: float = Field(..., ge=0, le=100, description="Masculinity")
    uai: float = Field(..., ge=0, le=100, description="Uncertainty Avoidance")
    lto: float = Field(..., ge=0, le=100, description="Long-Term Orientation")
    ivr: float = Field(..., ge=0, le=100, description="Indulgence")


class BigFiveProfile(BaseModel):
    """Big Five personality traits (OCEAN model), each 0-100."""
    openness: float = Field(..., ge=0, le=100)
    conscientiousness: float = Field(..., ge=0, le=100)
    extraversion: float = Field(..., ge=0, le=100)
    agreeableness: float = Field(..., ge=0, le=100)
    neuroticism: float = Field(..., ge=0, le=100)


class CognitiveProfile(BaseModel):
    """
    Layer 2 cognitive model.
    Derived from Hofstede + Big Five → consumer decision parameters.
    All values are 0-1 normalized.
    """
    # Decision-making style
    analytical_vs_intuitive: float = Field(
        ..., ge=0, le=1, description="0=pure intuition, 1=pure analysis"
    )
    individual_vs_social: float = Field(
        ..., ge=0, le=1, description="0=social proof dominant, 1=individual decision"
    )

    # Trust & authority
    authority_trust: float = Field(
        ..., ge=0, le=1, description="Trust in brands/institutions"
    )
    peer_influence: float = Field(
        ..., ge=0, le=1, description="Sensitivity to peer/social recommendations"
    )

    # Consumer behavior
    price_sensitivity: float = Field(
        ..., ge=0, le=1, description="0=price insensitive, 1=extremely price-sensitive"
    )
    risk_appetite: float = Field(
        ..., ge=0, le=1, description="0=very risk-averse, 1=risk-loving"
    )
    novelty_seeking: float = Field(
        ..., ge=0, le=1, description="0=prefers familiar, 1=seeks new experiences"
    )
    long_term_thinking: float = Field(
        ..., ge=0, le=1, description="0=short-term gratification, 1=long-term value"
    )

    # Attention & communication
    detail_attention: float = Field(
        ..., ge=0, le=1, description="0=skims/big picture, 1=reads fine print"
    )
    emotional_reactivity: float = Field(
        ..., ge=0, le=1, description="0=stoic/rational, 1=emotionally driven"
    )

    # Derived willingness-to-pay multiplier
    wtp_multiplier: float = Field(
        default=1.0, description="Relative willingness to pay vs. average"
    )


class Persona(BaseModel):
    """Complete persona with demographics + cognitive model.

    v2 changes:
      - income_bracket retained but now derived from income percentile (not sampled)
      - Added: income_local, income_currency, income_usd
      - Added: occupation_title, occupation_title_local, occupation_category,
               occupation_education, occupation_work_context
      - occupation_label kept as property for backward compat
    """

    persona_id: str

    # Display fields
    name: str = ""
    flag: str = ""

    # Layer 1: Demographics
    nationality: str
    country_name: str
    age_group: str  # "18-24", "25-34", etc.
    age: int
    gender: str  # "male", "female", "non-binary"

    # Income — derived from occupation, not independently sampled
    income_bracket: str  # "low", "lower-middle", "middle", "upper-middle", "high" (derived)
    income_local: int = 0          # annual pay in local currency
    income_currency: str = "USD"   # ISO currency code
    income_usd: int = 0            # annual pay in USD (for comparison)

    # Occupation — new expanded fields
    occupation_id: str
    occupation_title: str = ""             # English title
    occupation_title_local: dict = Field(default_factory=dict)  # {"CN": "外卖骑手", ...}
    occupation_category: str = ""          # BLS category slug
    occupation_education: str = ""         # Entry education requirement
    occupation_work_context: str = ""      # 1-2 sentence work context description

    # Legacy field — kept for backward compat, maps to occupation_title
    occupation_label: str = ""

    urban_rural: str  # "urban", "suburban", "rural"

    # City tier (set when country has city_tiers defined)
    city_tier: str = ""        # tier id, e.g. "t1", "metro-coastal"
    city_tier_label: str = ""  # human-readable label, e.g. "Tier 1 (Beijing/...)"

    # Layer 1.5: Personality labels (derived from Big Five clusters)
    personality_type: str  # e.g. "pragmatic_planner", "social_connector", etc.

    # Layer 2: Cognitive profiles
    hofstede: HofstedeProfile
    big_five: BigFiveProfile
    cognitive: CognitiveProfile

    # Layer 2.5: LLM-enriched backstory (optional, legacy enricher)
    backstory: Optional[str] = None
    enriched: bool = False

    # Layer 2.5 epsilon: real-time GLM-generated unique personal background
    epsilon: str = ""

    def model_post_init(self, __context):
        """Sync occupation_label with occupation_title for backward compat."""
        if not self.occupation_label and self.occupation_title:
            object.__setattr__(self, 'occupation_label', self.occupation_title)
        elif not self.occupation_title and self.occupation_label:
            object.__setattr__(self, 'occupation_title', self.occupation_label)

    def _get_display_title(self) -> str:
        """Get occupation display title with local name if available."""
        local = self.occupation_title_local.get(self.nationality)
        base = self.occupation_title or self.occupation_label or self.occupation_id
        if local and local != base:
            return f"{base} ({local})"
        return base

    def _format_income(self) -> str:
        """Format income for display."""
        currency_symbols = {
            "USD": "$", "CNY": "¥", "EUR": "€", "GBP": "£",
            "JPY": "¥", "KRW": "₩", "INR": "₹", "BRL": "R$",
            "CAD": "CA$", "AUD": "A$", "SGD": "S$",
        }
        sym = currency_symbols.get(self.income_currency, self.income_currency + " ")

        if self.income_local <= 0:
            return "Income: N/A"

        # Format with commas
        local_str = f"{self.income_local:,}"

        if self.income_currency == "USD":
            return f"Income: ~{sym}{local_str}/yr"
        elif self.income_usd > 0 and self.income_usd != self.income_local:
            usd_str = f"{self.income_usd:,}"
            return f"Income: ~{sym}{local_str}/yr (~${usd_str} USD)"
        else:
            return f"Income: ~{sym}{local_str}/yr"

    def to_prompt_context(self) -> str:
        """Generate a prompt-friendly description of this persona."""
        display_title = self._get_display_title()
        income_str = self._format_income()

        lines = [
            f"You are a {self.age}-year-old {self.gender} from {self.country_name}.",
            f"Occupation: {display_title}",
            income_str,
        ]

        if self.occupation_education:
            lines.append(f"Education: {self.occupation_education}")

        if self.occupation_work_context:
            lines.append(f"Work context: {self.occupation_work_context}")

        if self.epsilon:
            lines.append(f"Personal background: {self.epsilon}")

        location_str = self.city_tier_label if self.city_tier_label else self.urban_rural
        lines += [
            f"Location: {location_str}",
            f"Personality: {self.personality_type.replace('_', ' ').title()}",
            "",
            "Your cognitive profile:",
            f"- Decision style: {'analytical' if self.cognitive.analytical_vs_intuitive > 0.6 else 'intuitive' if self.cognitive.analytical_vs_intuitive < 0.4 else 'balanced'}",
            f"- Social influence: {'strong' if self.cognitive.peer_influence > 0.6 else 'weak'}",
            f"- Price sensitivity: {'high' if self.cognitive.price_sensitivity > 0.6 else 'low' if self.cognitive.price_sensitivity < 0.4 else 'moderate'}",
            f"- Risk appetite: {'high' if self.cognitive.risk_appetite > 0.6 else 'low' if self.cognitive.risk_appetite < 0.4 else 'moderate'}",
            f"- Novelty seeking: {'high' if self.cognitive.novelty_seeking > 0.6 else 'low'}",
            f"- Emotional reactivity: {'high' if self.cognitive.emotional_reactivity > 0.6 else 'moderate'}",
        ]
        if self.backstory:
            lines += ["", f"Background: {self.backstory}"]
        return "\n".join(lines)

    def to_dict_summary(self) -> dict:
        """Summary for API preview — includes cognitive profile for UI rendering."""
        vibe = self._build_vibe()
        decision_style = (
            "Analytical" if self.cognitive.analytical_vs_intuitive > 0.6
            else "Intuitive" if self.cognitive.analytical_vs_intuitive < 0.4
            else "Balanced"
        )
        trust_chain = (
            "Brand-trusting" if self.cognitive.authority_trust > 0.6
            else "Peer-driven" if self.cognitive.peer_influence > 0.6
            else "Self-reliant"
        )
        return {
            "persona_id": self.persona_id,
            "name": self.name or f"P-{self.persona_id[-4:]}",
            "flag": self.flag or "🌐",
            "nationality": self.nationality,
            "country_name": self.country_name,
            "age": self.age,
            "age_group": self.age_group,
            "gender": self.gender,
            "income_bracket": self.income_bracket,
            "income_local": self.income_local,
            "income_currency": self.income_currency,
            "income_usd": self.income_usd,
            "income_display": self._format_income(),
            "occupation_id": self.occupation_id,
            "occupation_label": self._get_display_title(),
            "occupation_title": self.occupation_title,
            "occupation_title_local": self.occupation_title_local,
            "occupation_category": self.occupation_category,
            "occupation_education": self.occupation_education,
            "occupation_work_context": self.occupation_work_context,
            "urban_rural": self.urban_rural,
            "city_tier": self.city_tier,
            "city_tier_label": self.city_tier_label,
            "personality_type": self.personality_type,
            # Cognitive highlights for preview card
            "decision_style": decision_style,
            "trust_chain": trust_chain,
            "price_sensitivity": round(self.cognitive.price_sensitivity, 2),
            "risk_appetite": round(self.cognitive.risk_appetite, 2),
            "novelty_seeking": round(self.cognitive.novelty_seeking, 2),
            "vibe": vibe,
            "personal_background": self.epsilon,
        }

    def _build_vibe(self) -> str:
        """One-sentence vibe description derived from cognitive profile."""
        c = self.cognitive
        parts = []
        pt = self.personality_type.replace("_", " ").title()

        if c.price_sensitivity > 0.7:
            parts.append("very price-conscious")
        elif c.price_sensitivity < 0.3:
            parts.append("price-insensitive")

        if c.novelty_seeking > 0.7:
            parts.append("loves trying new things")
        elif c.novelty_seeking < 0.3:
            parts.append("prefers familiar choices")

        if c.risk_appetite > 0.7:
            parts.append("risk-tolerant")
        elif c.risk_appetite < 0.3:
            parts.append("risk-averse")

        if c.peer_influence > 0.7:
            parts.append("heavily peer-influenced")

        if c.emotional_reactivity > 0.7:
            parts.append("emotionally driven")

        if parts:
            return f"{pt} — {', '.join(parts[:2])}."
        return f"{pt} with balanced consumer tendencies."
