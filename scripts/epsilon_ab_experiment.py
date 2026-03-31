"""
Epsilon A/B Experiment: Compare two persona evaluation modes.

Mode A (current): 
  Call 1: Generate epsilon background (Layer 2.5, epsilon.py)
  Call 2: Evaluation with epsilon embedded in prompt context

Mode B (merged):
  Single call: Two-phase prompt — "first imagine a concrete person, then evaluate from their POV"

Usage:
  cd ~/projects/worldsense
  python scripts/epsilon_ab_experiment.py

Output: prints structured comparison table + saves to scripts/epsilon_ab_result.json
"""

from __future__ import annotations

import asyncio
import json
import time
import sys
import os
from pathlib import Path

# Allow running from scripts/ dir
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env", override=False)

from worldsense.persona.epsilon import EPSILON_SYSTEM_PROMPT, EPSILON_PROMPT_TEMPLATE, _build_epsilon_prompt
from worldsense.pipeline.output import build_feedback_prompt, FEEDBACK_JSON_SCHEMA
from worldsense.llm import get_backend

# ─── Fixed test persona (same for both modes) ───────────────────────────────

PERSONA_SUMMARY = {
    "persona_id": "test_ab_001",
    "name": "Wei Jianming",
    "flag": "🇨🇳",
    "nationality": "CN",
    "country_name": "China",
    "age": 34,
    "age_group": "25-34",
    "gender": "male",
    "income_bracket": "middle",
    "income_local": 120000,
    "income_currency": "CNY",
    "income_usd": 17000,
    "income_display": "Income: ~¥120,000/yr (~$17,000 USD)",
    "occupation_id": "software_developer",
    "occupation_label": "Software Developer",
    "occupation_title": "Software Developer",
    "occupation_title_local": {"CN": "软件工程师"},
    "occupation_category": "computer_and_mathematical",
    "occupation_education": "Bachelor's degree in Computer Science",
    "occupation_work_context": "Works on backend systems for a mid-size tech company in Beijing, collaborating with a team of 8 engineers.",
    "urban_rural": "urban",
    "city_tier": "t1",
    "city_tier_label": "Tier 1 (Beijing/Shanghai/Guangzhou/Shenzhen)",
    "personality_type": "pragmatic_planner",
    "decision_style": "Analytical",
    "trust_chain": "Self-reliant",
    "price_sensitivity": 0.45,
    "risk_appetite": 0.38,
    "novelty_seeking": 0.62,
    "personal_background": "",
}

# Cognitive profile in string form (for to_prompt_context equivalent)
def build_persona_context_without_epsilon(persona_summary: dict, epsilon: str = "") -> str:
    """Replicate Persona.to_prompt_context() from dict summary."""
    lines = [
        f"You are a {persona_summary['age']}-year-old {persona_summary['gender']} from {persona_summary['country_name']}.",
        f"Occupation: {persona_summary['occupation_title']} ({persona_summary['occupation_title_local'].get('CN', '')})",
        persona_summary["income_display"],
        f"Education: {persona_summary['occupation_education']}",
        f"Work context: {persona_summary['occupation_work_context']}",
    ]
    if epsilon:
        lines.append(f"Personal background: {epsilon}")
    location = persona_summary.get("city_tier_label") or persona_summary.get("urban_rural", "")
    personality = persona_summary.get("personality_type", "").replace("_", " ").title()
    lines += [
        f"Location: {location}",
        f"Personality: {personality}",
        "",
        "Your cognitive profile:",
        f"- Decision style: analytical",
        f"- Social influence: weak",
        f"- Price sensitivity: moderate",
        f"- Risk appetite: low",
        f"- Novelty seeking: high",
        f"- Emotional reactivity: moderate",
    ]
    return "\n".join(lines)


# Fixed product to evaluate
PRODUCT_CONTENT = """\
Product: Notion AI
A writing and productivity assistant built into Notion workspace.
Key features: AI writing help, summarization, translation, task extraction from notes.
Price: $10/month add-on to existing Notion plan.
Target use: Knowledge workers, developers, project managers who already use Notion.
"""

# ─── Mode B merged prompt ────────────────────────────────────────────────────

MERGED_SYSTEM_PROMPT = """\
You are a research assistant. First you will construct a concrete, specific person matching a demographic profile, then evaluate a product from that person's authentic perspective.
Output ONLY a valid JSON object with no markdown fences and no extra text."""

def build_merged_prompt(persona_summary: dict, product_content: str) -> str:
    """
    Two-phase merged prompt:
    Phase 1: Construct a concrete person (replaces epsilon call)
    Phase 2: Evaluate from their perspective (replaces evaluation call)
    """
    ps = persona_summary
    return f"""\
## PHASE 1 — Construct a Concrete Person

Given this demographic profile, first imagine a specific real-feeling individual:

Profile: {ps['age']}-year-old {ps['gender']} from {ps['country_name']}, {ps['occupation_title']} ({ps['occupation_title_local'].get('CN', '')}), {ps['income_display']}, {ps.get('city_tier_label', ps.get('urban_rural', ''))}, {ps['personality_type'].replace('_', ' ').title()} personality.
Cognitive traits: novelty-seeking={ps['novelty_seeking']} (0=very conservative, 1=loves new things), price-sensitivity={ps['price_sensitivity']} (0=spends freely, 1=very frugal), risk-appetite={ps['risk_appetite']} (0=risk-averse, 1=risk-taker).

Pick 2-3 specific personal details (family situation, hobby, how they discover products, recent purchase, goal, social media habit). Be specific and realistic.

## PHASE 2 — Evaluate as This Person

Now, AS this specific person you just imagined, evaluate the following product honestly:

CONTENT TO EVALUATE:
{product_content}

EVALUATION FOCUS:
- Overall impression: What impressed you most and least?
- Pay willingness: Would you pay for this? What price range is acceptable?
- Share willingness: Would you share this with friends or colleagues?

REQUIRED RESPONSE FORMAT:
Respond ONLY with a valid JSON object with exactly these fields:
{{
  "epsilon": "<2-3 sentence personal background you imagined in Phase 1>",
  "purchase_intent": "buy" | "hesitate" | "pass",
  "nps_score": <integer 0-10>,
  "sentiment_score": <float -1.0 to 1.0>,
  "key_attraction": "<what most appeals to you>",
  "key_concern": "<your main worry or objection>",
  "verbatim": "<your authentic 2-3 sentence reaction in your own voice>",
  "willingness_to_pay_multiplier": <float, 1.0 = average, 0.5 = half, 2.0 = double>
}}

Be honest and authentic — not uniformly positive. Reflect your real cognitive style, cultural background, and financial situation."""


# ─── Experiment runner ───────────────────────────────────────────────────────

async def run_mode_a(backend) -> dict:
    """Mode A: epsilon call → evaluation call (two serial LLM calls)."""
    result = {"mode": "A", "calls": 2}
    
    # Call 1: Generate epsilon
    t0 = time.perf_counter()
    epsilon_prompt = _build_epsilon_prompt(PERSONA_SUMMARY)
    epsilon_resp = await backend.generate(
        prompt=epsilon_prompt,
        schema=None,
        system_prompt=EPSILON_SYSTEM_PROMPT,
        temperature=0.9,
        max_tokens=150,
        extra_body={"enable_thinking": False},
        json_mode=False,
    )
    t1 = time.perf_counter()
    
    epsilon_text = epsilon_resp.get("content", "").strip()
    epsilon_usage = epsilon_resp.get("usage", {})
    result["epsilon_latency_s"] = round(t1 - t0, 2)
    result["epsilon_text"] = epsilon_text
    result["epsilon_tokens"] = epsilon_usage.get("total_tokens", 0)
    
    # Call 2: Evaluation with epsilon in context
    t2 = time.perf_counter()
    persona_context = build_persona_context_without_epsilon(PERSONA_SUMMARY, epsilon=epsilon_text)
    eval_prompt = build_feedback_prompt(
        persona_context=persona_context,
        content=PRODUCT_CONTENT,
    )
    eval_resp = await backend.generate(
        prompt=eval_prompt,
        schema=FEEDBACK_JSON_SCHEMA,
    )
    t3 = time.perf_counter()
    
    eval_usage = eval_resp.get("usage", {})
    eval_parsed = eval_resp.get("parsed") or {}
    result["eval_latency_s"] = round(t3 - t2, 2)
    result["total_latency_s"] = round(t3 - t0, 2)
    result["eval_tokens"] = eval_usage.get("total_tokens", 0)
    result["total_tokens"] = result["epsilon_tokens"] + result["eval_tokens"]
    result["eval_output"] = eval_parsed
    result["eval_raw"] = eval_resp.get("content", "")
    
    return result


async def run_mode_b(backend) -> dict:
    """Mode B: single merged call (epsilon + evaluation in one prompt)."""
    result = {"mode": "B", "calls": 1}
    
    t0 = time.perf_counter()
    merged_prompt = build_merged_prompt(PERSONA_SUMMARY, PRODUCT_CONTENT)
    merged_resp = await backend.generate(
        prompt=merged_prompt,
        schema=None,
        system_prompt=MERGED_SYSTEM_PROMPT,
        temperature=0.9,
        max_tokens=600,
        extra_body={"enable_thinking": False},
        json_mode=True,
    )
    t1 = time.perf_counter()
    
    usage = merged_resp.get("usage", {})
    parsed = merged_resp.get("parsed") or {}
    result["total_latency_s"] = round(t1 - t0, 2)
    result["total_tokens"] = usage.get("total_tokens", 0)
    
    # Extract epsilon from merged output
    result["epsilon_text"] = parsed.get("epsilon", "")
    
    # Evaluation fields (same schema minus the epsilon field)
    eval_output = {k: v for k, v in parsed.items() if k != "epsilon"}
    result["eval_output"] = eval_output
    result["eval_raw"] = merged_resp.get("content", "")
    
    return result


async def main():
    print("=" * 70)
    print("Epsilon A/B Experiment — GLM-5.1")
    print("=" * 70)
    print(f"Persona: {PERSONA_SUMMARY['name']}, {PERSONA_SUMMARY['age']}yo {PERSONA_SUMMARY['gender']} | {PERSONA_SUMMARY['occupation_title']} | {PERSONA_SUMMARY['country_name']}")
    print(f"Product: Notion AI ($10/mo)")
    print()
    
    backend = get_backend("openai_compat")
    
    try:
        print("Running Mode A (epsilon separate → evaluation)...")
        result_a = await run_mode_a(backend)
        print(f"  Epsilon latency: {result_a['epsilon_latency_s']}s | Eval latency: {result_a['eval_latency_s']}s | Total: {result_a['total_latency_s']}s")
        print(f"  Tokens: epsilon={result_a['epsilon_tokens']} + eval={result_a['eval_tokens']} = {result_a['total_tokens']}")
        print()
        
        print("Running Mode B (merged single call)...")
        result_b = await run_mode_b(backend)
        print(f"  Total latency: {result_b['total_latency_s']}s")
        print(f"  Tokens: {result_b['total_tokens']}")
        print()
        
    finally:
        await backend.close()
    
    # ─── Print comparison ────────────────────────────────────────────────
    print("=" * 70)
    print("COMPARISON RESULTS")
    print("=" * 70)
    
    print("\n[EPSILON / PERSONAL BACKGROUND]")
    print(f"Mode A: {result_a['epsilon_text']}")
    print(f"Mode B: {result_b['epsilon_text']}")
    
    a_eval = result_a["eval_output"]
    b_eval = result_b["eval_output"]
    
    print("\n[EVALUATION OUTPUTS]")
    fields = ["purchase_intent", "nps_score", "sentiment_score", "key_attraction", "key_concern", "willingness_to_pay_multiplier"]
    for f in fields:
        av = a_eval.get(f, "N/A")
        bv = b_eval.get(f, "N/A")
        print(f"  {f:<32} | A: {str(av):<25} | B: {bv}")
    
    print("\n[VERBATIM]")
    print(f"Mode A: {a_eval.get('verbatim', 'N/A')}")
    print(f"Mode B: {b_eval.get('verbatim', 'N/A')}")
    
    print("\n[METRICS SUMMARY]")
    print(f"  {'Metric':<30} | {'Mode A':>12} | {'Mode B':>12} | {'Delta':>10}")
    print(f"  {'-'*30}-+-{'-'*12}-+-{'-'*12}-+-{'-'*10}")
    
    latency_delta = result_b["total_latency_s"] - result_a["total_latency_s"]
    token_delta = result_b["total_tokens"] - result_a["total_tokens"]
    
    print(f"  {'Total latency (s)':<30} | {result_a['total_latency_s']:>12.2f} | {result_b['total_latency_s']:>12.2f} | {latency_delta:>+10.2f}")
    print(f"  {'Total tokens':<30} | {result_a['total_tokens']:>12} | {result_b['total_tokens']:>12} | {token_delta:>+10}")
    print(f"  {'LLM calls':<30} | {result_a['calls']:>12} | {result_b['calls']:>12} | {result_b['calls']-result_a['calls']:>+10}")
    
    # ─── Save results ────────────────────────────────────────────────────
    output = {
        "persona": PERSONA_SUMMARY["name"],
        "product": "Notion AI",
        "mode_a": result_a,
        "mode_b": result_b,
        "summary": {
            "latency_a_s": result_a["total_latency_s"],
            "latency_b_s": result_b["total_latency_s"],
            "latency_delta_s": round(latency_delta, 2),
            "tokens_a": result_a["total_tokens"],
            "tokens_b": result_b["total_tokens"],
            "tokens_delta": token_delta,
            "calls_a": result_a["calls"],
            "calls_b": result_b["calls"],
        }
    }
    
    out_path = Path(__file__).parent / "epsilon_ab_result.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\nFull results saved to: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
