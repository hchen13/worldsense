# Architecture Decision Record — 问势 · WorldSense

*Last updated: 2026-03-29 | Phase 1*

---

## Overview

WorldSense is an AI-powered user research simulation platform. The core idea: instead of recruiting real participants, we generate thousands of synthetic personas grounded in cultural psychology research, then run structured LLM inference through each persona's cognitive lens to simulate market feedback.

---

## Design Principles

1. **Reproducibility**: Same seed → same personas → same results
2. **Modularity**: Each layer is independently swappable (persona engine, LLM backend, pipeline)
3. **Incrementality**: Start simple (mock backend + small sample) → scale up (real LLM + thousands of personas)
4. **Grounded in research**: Persona generation anchored to Hofstede cultural dimensions + Big Five psychology — not random

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                         CLI (ws)                            │
│         run / personas / report / tasks                     │
└─────────────────────────────────────────────────────────────┘
                              │
                    ┌─────────▼──────────┐
                    │   ResearchEngine   │
                    │  (core/engine.py)  │
                    └─────────┬──────────┘
              ┌───────────────┼───────────────┐
              │               │               │
    ┌─────────▼───────┐ ┌────▼────┐ ┌────────▼────────┐
    │  PersonaEngine  │ │Pipeline │ │  ReportGenerator│
    │  (3 layers)     │ │(workers)│ │  (aggregator)   │
    └─────────────────┘ └────┬────┘ └─────────────────┘
                             │
                    ┌────────▼────────┐
                    │   LLMBackend    │
                    │  (abstraction)  │
                    └────────┬────────┘
           ┌────────────────┼─────────────────┐
           │                │                 │
     ┌─────▼──┐    ┌────────▼──────┐   ┌─────▼─────┐
     │  Mock  │    │OpenAICompat   │   │  Future   │
     │Backend │    │(any endpoint) │   │ backends  │
     └────────┘    └───────────────┘   └───────────┘
```

---

## Persona Engine: 3-Layer Architecture

### Layer 1 — Demographic Skeleton (`generator.py`)

Samples real demographics weighted by UN world population data:
- **Nationality**: 30 countries weighted by population
- **Age group**: 6 bands (18-24 through 65+) with real distribution
- **Gender**: 3 options, near-equal split
- **Income bracket**: 5 tiers, weighted by global income distribution
- **Occupation**: 25 consumer-relevant occupations with real frequency weights
- **Urban/rural**: Biased by occupation type and country

**Key decision**: Use weighted sampling, not grid enumeration. With 1000 personas, grid enumeration would miss long-tail demographics. Sampling naturally handles it.

### Layer 2 — Cognitive Model (`cognitive.py`)

Derives 10 consumer decision parameters from:

**Hofstede Cultural Dimensions** (per country, public data):
- PDI (Power Distance) → authority trust
- IDV (Individualism) → individual vs. social decision
- MAS (Masculinity) → value orientation
- UAI (Uncertainty Avoidance) → risk appetite, analytical tendency
- LTO (Long-Term Orientation) → planning horizon
- IVR (Indulgence) → novelty seeking, emotional reactivity

**Big Five Personality (OCEAN)**:
- Generated per-person with demographic noise applied
- Mapped via cluster assignment to 8 named personality types

**Derived cognitive parameters**:
```
analytical_vs_intuitive   = f(UAI, conscientiousness, neuroticism)
individual_vs_social      = f(IDV, agreeableness)
authority_trust           = f(PDI, agreeableness, openness)
peer_influence            = f(IDV, agreeableness, extraversion)
price_sensitivity         = f(income, conscientiousness, MAS)
risk_appetite             = f(UAI, openness, age, neuroticism)
novelty_seeking           = f(openness, UAI, IVR, IDV)
long_term_thinking        = f(LTO, conscientiousness)
detail_attention          = f(UAI, conscientiousness, neuroticism)
emotional_reactivity      = f(neuroticism, IVR, extraversion)
```

All weights are researcher-reviewed heuristics. This is designed to be iteratively improved.

### Layer 2.5 — LLM Epsilon (`enricher.py`)

Optional backstory generation via LLM call. Adds unique individual narrative:
- Configurable epsilon (0.0 = off, 1.0 = enrich all personas)
- Batched with concurrency control
- Failure silently skipped — enrichment is never blocking

**Why optional?** For 1000+ personas, enrichment costs ~$2-5 per run with GPT-4o-mini. Useful for qualitative research but not required for quantitative signals.

---

## LLM Backend Design

### Interface

```python
async def generate(prompt, schema, system_prompt, temperature, max_tokens) -> dict
```

Returns: `{"content": str, "parsed": dict|None, "usage": dict}`

### Backend implementations

| Backend | Description | When to use |
|---------|-------------|-------------|
| `MockBackend` | Deterministic procedural generation | Testing, demos, CI |
| `OpenAICompatBackend` | Any OpenAI-compatible API | Production runs |

**Key decision**: OpenAI-compatible format was chosen because it covers OpenAI, Anthropic (via proxy), DeepSeek, Ollama, and most hosted inference providers. No need for separate Anthropic SDK.

### Rate Limiter

Token bucket algorithm, per-backend:
- `requests_per_minute`: prevents API throttling
- `max_concurrent`: prevents connection pool exhaustion
- Wrapped around each request, released after response

---

## Pipeline Architecture

### Async Worker Pool

```python
asyncio.Semaphore(concurrency) + asyncio.gather(...)
```

- No threads — pure asyncio. Sufficient because LLM calls are I/O-bound.
- Each worker retries up to 3 times with exponential backoff.
- Failures are isolated: one bad persona doesn't kill the batch.
- `on_result` callback fires after each completion → powers the progress bar.

### Progress tracking

Rich progress bar with:
- Current count / total
- Elapsed time
- ETA estimation

---

## Data Storage

Phase 1: **Flat JSON files** in `~/.worldsense/results/`

Format: `<task_id>.json` containing:
```json
{
  "task": { ...ResearchTask fields... },
  "summary": { ...TaskResults aggregate... },
  "results": [ ...individual PersonaResult list... ]
}
```

**Why not SQLite yet?** For Phase 1 (≤1000 personas, single user), flat JSON is simpler, immediately inspectable, and zero dependencies. Phase 2 migration to SQLite/PostgreSQL is straightforward since all data flows through Pydantic models.

---

## Inference Prompt Design

Each persona gets a prompt with:
1. **Context block**: age, nationality, occupation, personality type
2. **Cognitive profile**: key consumer behavior parameters in plain English
3. **Optional backstory**: LLM-generated individual narrative
4. **Structured data tag**: JSON-encoded parameters for MockBackend extraction
5. **Content to evaluate**: product/content description
6. **Output instructions**: JSON schema enforcement

MockBackend reads the `PERSONA_DATA:` tag for deterministic response generation. Real backends use standard JSON schema enforcement.

---

## Report Structure

Output: Markdown report with:
- Executive summary table (buy rate, NPS, sentiment)
- Top attractions and concerns (frequency-ranked)
- Segmentation tables: by nationality, age, income, occupation
- Sample verbatims

**NPS calculation**: `(promoters% - detractors%) × 100`, standard methodology.

---

## Validated Markets

| Market key | Countries |
|------------|-----------|
| `global` | All 30 countries |
| `us` | US only |
| `cn` | China only |
| `asia` | CN, JP, KR, IN, ID, TH, VN, PH, SG, MY |
| `europe` | DE, FR, GB, IT, ES, NL, SE, RU |
| `latam` | BR, MX, AR |
| `africa` | NG, ZA, EG |
| `mena` | SA, EG, TR |
| `developed` | US, CA, GB, DE, FR, JP, AU, KR, SG, NL, SE |
| `emerging` | CN, IN, BR, MX, ID, TR, RU, ZA, NG, VN, PH |

---

## Phase Roadmap

| Phase | Status | Scope |
|-------|--------|-------|
| 1 | ✅ Complete | Core engine, MockBackend, CLI, demo |
| 2 | Planned | OpenAI backend, SQLite persistence, 10k+ scale |
| 3 | Future | FastAPI REST, web dashboard |
| 4 | Future | Persona consistency across runs, fine-tuning |

---

## Known Limitations & Future Improvements

1. **Cognitive weights are heuristic**: Hofstede→behavior mappings are reasonable approximations, not validated empirically. Priority improvement: A/B test cognitive parameter weights against known consumer research benchmarks.

2. **No cultural language variation**: All prompts are in English. A Japanese persona's response will be in English. Phase 2: add language variation.

3. **Flat file storage**: Doesn't scale beyond ~10k results. Phase 2: SQLite with proper indexing.

4. **NPS simulation skew**: MockBackend uses simple score thresholds. Real LLM responses show more nuanced distributions. Calibration needed against real survey data.

5. **Missing: historical bias injection**: Personas don't "remember" past experiences with this product or category. Future: long-term memory via vector store.
