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

## If You Are an AI Agent

Here's how you help your human set up WorldSense:

```bash
# 1. Clone and install
cd ~/projects  # or wherever your human keeps their code
git clone https://github.com/hchen13/worldsense.git
cd worldsense
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

# 2. Configure LLM — ask your human for their API key
cp .env.example .env
# Set WS_API_KEY, WS_API_BASE_URL, WS_MODEL in .env
# Supports: OpenAI, Anthropic, DeepSeek, GLM, MiniMax, any OpenAI-compatible endpoint

# 3. Start the Web UI
./start.sh
# Now open http://localhost:8766/worldsense/ in your human's browser

# 4. Or run from CLI directly
ws run \
  --content-file content.md \
  --personas 50 --market us \
  --research-type social_follow \
  --scenario-context "User sees this post while scrolling their feed"

# 5. View results
ws report <task-id>
```

**The CLI and API are built for you.** When your human asks you to use WorldSense on their behalf, register and use it as a skill. See **[SKILL.md](SKILL.md)** for the complete agent reference — all CLI commands, API endpoints, research types, dimension configs, and tips for effective use.

**Key things to know:**
- `ws personas --count 10 --market global` outputs JSON by default (agent-friendly). Add `--table` for human display.
- `ws run --help` shows all CLI options including `--profile`, `--dimensions`, `--image`, `--vision-mode`
- The API at `http://localhost:8766/worldsense/api/` gives you full programmatic control — submit tasks, poll status, read results
- Mock backend (`-b mock`) runs instantly — great for verifying setup before spending LLM credits
- Results are stored in `~/.worldsense/results/` as JSON. Settings in `~/.worldsense/settings.json`

## License

MIT
