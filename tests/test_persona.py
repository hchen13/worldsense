"""Tests for the persona engine."""

import pytest
from worldsense.persona.generator import PersonaGenerator
from worldsense.persona.cognitive import derive_cognitive_profile, derive_mbti, generate_big_five, assign_personality_type
from worldsense.persona.schema import HofstedeProfile
import random


def test_generate_global_personas():
    gen = PersonaGenerator(market="global", seed=42)
    personas = gen.generate(10)
    assert len(personas) == 10
    for p in personas:
        assert p.persona_id.startswith("p_")
        assert p.nationality
        assert p.age >= 18
        assert p.gender in ("male", "female", "non-binary")
        assert p.income_bracket in ("low", "lower-middle", "middle", "upper-middle", "high")
        assert 0 <= p.cognitive.price_sensitivity <= 1
        assert 0 <= p.cognitive.risk_appetite <= 1
        assert 0 <= p.cognitive.wtp_multiplier


def test_generate_us_market():
    gen = PersonaGenerator(market="us", seed=1)
    personas = gen.generate(20)
    for p in personas:
        assert p.nationality == "US"


def test_generate_asia_market():
    gen = PersonaGenerator(market="asia", seed=5)
    personas = gen.generate(50)
    asian_codes = {"CN", "JP", "KR", "IN", "ID", "TH", "VN", "PH", "SG", "MY"}
    for p in personas:
        assert p.nationality in asian_codes


def test_cognitive_model_ranges():
    rng = random.Random(42)
    hofstede = HofstedeProfile(pdi=50, idv=50, mas=50, uai=50, lto=50, ivr=50)
    b5 = generate_big_five(rng, "US", "25-34")
    cog = derive_cognitive_profile(hofstede, b5, "middle", "25-34", rng)

    for field_name in [
        "analytical_vs_intuitive", "individual_vs_social", "authority_trust",
        "peer_influence", "price_sensitivity", "risk_appetite", "novelty_seeking",
        "long_term_thinking", "detail_attention", "emotional_reactivity"
    ]:
        val = getattr(cog, field_name)
        assert 0 <= val <= 1, f"{field_name} out of range: {val}"


def test_personality_assignment():
    rng = random.Random(0)
    b5 = generate_big_five(rng, "US", "25-34")
    ptype = assign_personality_type(b5)
    assert isinstance(ptype, str)
    assert len(ptype) > 0


def test_persona_prompt_context():
    gen = PersonaGenerator(market="us", seed=10)
    p = gen.generate(1)[0]
    ctx = p.to_prompt_context()
    assert "age" in ctx.lower() or str(p.age) in ctx
    assert p.country_name in ctx


def test_invalid_market():
    with pytest.raises(ValueError, match="market"):
        PersonaGenerator(market="moon")


def test_derive_mbti_boundaries():
    """Test MBTI derivation at exactly 50 (boundary) — should map to E/N/F/J."""
    from worldsense.persona.schema import BigFiveProfile
    b5 = BigFiveProfile(openness=50, conscientiousness=50, extraversion=50, agreeableness=50, neuroticism=50)
    assert derive_mbti(b5) == "ENFJ"


def test_derive_mbti_all_high():
    """All traits at 100 → ENFJ."""
    from worldsense.persona.schema import BigFiveProfile
    b5 = BigFiveProfile(openness=100, conscientiousness=100, extraversion=100, agreeableness=100, neuroticism=100)
    assert derive_mbti(b5) == "ENFJ"


def test_derive_mbti_all_low():
    """All traits at 0 → ISTP."""
    from worldsense.persona.schema import BigFiveProfile
    b5 = BigFiveProfile(openness=0, conscientiousness=0, extraversion=0, agreeableness=0, neuroticism=0)
    assert derive_mbti(b5) == "ISTP"


def test_derive_mbti_specific_type():
    """ENTP: high extraversion, high openness, low agreeableness, low conscientiousness."""
    from worldsense.persona.schema import BigFiveProfile
    b5 = BigFiveProfile(openness=80, conscientiousness=30, extraversion=75, agreeableness=25, neuroticism=60)
    assert derive_mbti(b5) == "ENTP"


def test_derive_mbti_intj():
    """INTJ: low extraversion, high openness, low agreeableness, high conscientiousness."""
    from worldsense.persona.schema import BigFiveProfile
    b5 = BigFiveProfile(openness=85, conscientiousness=80, extraversion=30, agreeableness=35, neuroticism=40)
    assert derive_mbti(b5) == "INTJ"


def test_mbti_on_generated_personas():
    """All generated personas should have a valid 4-letter MBTI type."""
    gen = PersonaGenerator(market="global", seed=42)
    personas = gen.generate(50)
    valid_letters = [
        set("EI"), set("SN"), set("TF"), set("JP"),
    ]
    for p in personas:
        assert len(p.mbti) == 4, f"Invalid MBTI length: {p.mbti}"
        for i, letter in enumerate(p.mbti):
            assert letter in valid_letters[i], f"Invalid MBTI letter at pos {i}: {p.mbti}"


def test_mbti_in_summary_dict():
    """MBTI should appear in to_dict_summary() output."""
    gen = PersonaGenerator(seed=7)
    p = gen.generate(1)[0]
    summary = p.to_dict_summary()
    assert "mbti" in summary
    assert len(summary["mbti"]) == 4


def test_persona_summary_dict():
    gen = PersonaGenerator(seed=7)
    p = gen.generate(1)[0]
    summary = p.to_dict_summary()
    assert "persona_id" in summary
    assert "nationality" in summary
    assert "income_bracket" in summary
