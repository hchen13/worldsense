# WorldSense

[中文](README.md) | [English](README.EN.md)

> AI-powered large-scale user research simulation platform

Generate thousands of virtual personas with diverse cultural backgrounds and collect structured feedback on your product or content — without recruiting a single real participant.

## Core Features

- **3-Layer Persona Engine** — Demographics (30+ countries, 342+ occupations) + Hofstede cultural dimensions & Big Five personality → 10-dimensional cognitive model + MBTI + LLM-generated personal background
- **6 Research Types** — Product purchase, social follow, content reaction, app trial, concept test, competitive switch
- **Multimodal Input** — Text, URLs (auto-extract web articles / YouTube / Bilibili subtitles or transcription), images (per-persona vision or system summary), PDF/Word/Markdown
- **Multiple LLM Backends** — OpenAI-compatible / Anthropic-compatible / Mock (for testing), with multi-profile switching
- **Async Concurrent Inference** — Token bucket rate limiting + exponential backoff retry + real-time dot-matrix visualization
- **Structured Reports** — Conversion rate, NPS, sentiment analysis + segmentation by nationality / age / income / occupation / MBTI

## Quick Start

```bash
# Install
git clone https://github.com/hchen13/worldsense.git
cd worldsense
pip install -e .

# Configure LLM
cp .env.example .env
# Edit .env with your API key and endpoint

# Start Web UI
./start.sh
# Visit http://localhost:8766/worldsense/

# Or use CLI
ws personas --count 10 --market global --table   # Preview personas
ws run -f content.md -n 50 -m us -r social_follow  # Run research
ws report <task-id>                                 # View report
```

## CLI Examples

```bash
# Read content from file, China market, 50 personas, social follow type
ws run \
  --content-file article.md \
  --personas 50 --market cn --language 中文 \
  --research-type social_follow \
  --scenario-context "You see this post while scrolling Xiaohongshu" \
  --dimensions '{"location_weights":{"t1":0.5,"new-t1":0.5}}'

# Image evaluation (each persona sees the image directly)
ws run \
  --content "Evaluate the appeal of this poster" \
  --image poster.jpg \
  --personas 20 --market us
```

## Web UI

Features include:
- Two-column research creation page (content input + config/preview)
- URL auto-extraction (web articles, video subtitles/transcription)
- File uploads (images, PDF, Word) + vision mode selector
- Real-time Persona Matrix dot visualization (hover for per-persona details and feedback)
- Prompt Preview (see the exact prompt sent to the LLM)
- One-click Rerun (copy historical task parameters for a new run)

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    CLI (ws) / FastAPI Web UI                │
└─────────────────────────────────────────────────────────────┘
                              │
                    ┌─────────▼──────────┐
                    │   ResearchEngine   │
                    └─────────┬──────────┘
              ┌───────────────┼───────────────┐
              │               │               │
    ┌─────────▼───────┐ ┌────▼────┐ ┌────────▼────────┐
    │  Persona Engine  │ │Pipeline │ │ Report Generator │
    │  (3+1 layers)    │ │(async)  │ │  (aggregator)    │
    └─────────────────┘ └────┬────┘ └──────────────────┘
                             │
                    ┌────────▼────────┐
                    │   LLM Backend   │
                    └────────┬────────┘
           ┌────────────────┼─────────────────┐
     ┌─────▼──┐    ┌───────▼────────┐  ┌─────▼──────────┐
     │  Mock  │    │ OpenAI Compat  │  │Anthropic Compat│
     └────────┘    └────────────────┘  └────────────────┘
```

### Persona Engine

| Layer | Module | Function |
|-------|--------|----------|
| Layer 1 | `persona/generator.py` | Weighted sampling by UN population data: nationality, age, gender, occupation (342+ BLS jobs), income (derived from occupation) |
| Layer 2 | `persona/cognitive.py` | Hofstede 6D cultural dimensions + Big Five → 10 consumer decision parameters + MBTI |
| Layer 2.5 | `persona/epsilon.py` | LLM-generated personal background + leisure interests |
| Pipeline | `pipeline/output.py` | Mode B: single LLM call for persona construction + content evaluation |

## Supported Markets

| Market | Countries |
|--------|-----------|
| `global` | All 30+ countries |
| `cn` | China (with city tiers: Tier 1 / New Tier 1 / Tier 2-5 / Rural) |
| `us` | United States |
| `asia` | CN, JP, KR, IN, Southeast Asia |
| `europe` | DE, FR, GB, IT, ES, NL, SE, RU |
| `developed` / `emerging` | Developed / Emerging markets |

## Requirements

- Python 3.11+
- Core: typer, rich, pydantic, httpx, FastAPI, trafilatura
- Optional: yt-dlp (video subtitle extraction), whisper (audio transcription)

## License

MIT
