---
name: worldsense
description: Run AI-powered user research simulations with WorldSense. Use this skill when the user wants to test how a product, content, social media post, video, or concept would be received by a target audience. Also trigger when the user mentions persona generation, audience simulation, market testing, NPS prediction, user research without real users, or wants to evaluate content across different demographics. Covers CLI commands (ws run, ws personas, ws report), API endpoints, Web UI, and LLM profile configuration.
---

# WorldSense Skill

WorldSense is an AI-powered user research simulation platform. It generates thousands of virtual personas grounded in cultural psychology (Hofstede + Big Five + MBTI) and runs LLM inference through each persona's cognitive lens to simulate structured market feedback.

Your job: help the user set up, configure, and run research simulations — primarily through the CLI and API, which are designed for agent use.

## When to Use This Skill

- User wants to test how an audience would react to content, a product, or a concept
- User asks to "run a simulation", "test with personas", "get audience feedback"
- User wants to generate persona profiles for a specific market
- User needs to configure LLM backends or manage research tasks
- User shares a URL, image, or document and wants audience reactions

## Quick Reference

### CLI Commands

```bash
# Preview personas (default output: JSON, add --table for human display)
ws personas --count 10 --market cn
ws personas --count 50 --market us --table --seed 42

# Run a research simulation
ws run \
  --content "Product description" \        # or --content-file path.md
  --personas 50 \                          # number of personas
  --market cn \                            # target market
  --language 中文 \                        # output language
  --research-type social_follow \          # see Research Types below
  --profile "MiniMax International" \      # LLM profile name
  --scenario-context "Context description" \
  --dimensions '{"location_weights":{"t1":0.5,"new-t1":0.5}}' \
  --image poster.jpg \                     # optional, enables per-persona vision
  --concurrency 30

# View results
ws report <task-id>
ws tasks  # list all tasks
```

### Research Types

| ID | Intent Values | Use When |
|----|--------------|----------|
| `product_purchase` | buy / hesitate / pass | Would they buy this? |
| `social_follow` | follow / consider / pass | Would they follow this account? |
| `content_reaction` | watch / maybe / pass | Would they watch/read this? |
| `app_trial` | trial / consider / pass | Would they try this app? |
| `concept_test` | resonate / consider / pass | Does this concept resonate? |
| `competitive_switch` | switch / consider / pass | Would they switch from current solution? |

### Markets

`global`, `cn`, `us`, `asia`, `europe`, `latam`, `africa`, `mena`, `developed`, `emerging`

China (`cn`) supports city tiers: `t1`, `new-t1`, `t2`, `t3`, `t4-5`, `rural`

### Dimension Config (JSON)

Control persona sampling weights:

```json
{
  "location_weights": {"t1": 0.5, "new-t1": 0.5},
  "nationality_weights": {"CN": 0.7, "JP": 0.3},
  "age_weights": {"25-34": 0.6, "35-44": 0.4},
  "gender_weights": {"male": 0.5, "female": 0.5}
}
```

### API Endpoints

Base URL: `http://localhost:8766/worldsense`

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/run` | Submit a research task (multipart form) |
| GET | `/api/tasks` | List all tasks |
| GET | `/api/tasks/{id}` | Get task details + results |
| GET | `/api/tasks/{id}/persona-states` | Per-persona execution states |
| POST | `/api/personas` | Generate persona preview |
| POST | `/api/prompt-preview` | Preview the actual LLM prompt |
| POST | `/api/extract-url` | Extract content from URL |
| GET/PUT | `/api/settings` | Read/update system settings |

### Submitting a Task via API (Python)

```python
import httpx, json

resp = httpx.post('http://localhost:8766/worldsense/api/run', data={
    'content': 'Your content here',
    'scenario_context': 'How the user encounters this content',
    'personas_count': '50',
    'market': 'cn',
    'language': '中文',
    'research_type': 'social_follow',
    'dimensions_json': json.dumps({'location_weights': {'t1': 0.25, 'new-t1': 0.25, 't2': 0.25, 't3': 0.25}}),
    'concurrency': '30',
    'vision_mode': 'per_persona',  # or 'summary'
}, timeout=30)

task_id = resp.json()['task_id']
```

### Reading Content from URLs

The `/api/extract-url` endpoint handles:
- **Web articles**: extracts main text via trafilatura
- **YouTube**: extracts subtitles (auto-generated or manual)
- **Bilibili, TikTok, Douyin, Vimeo**: subtitle extraction via yt-dlp
- **Videos without subtitles**: downloads audio and transcribes via whisper

```python
resp = httpx.post('http://localhost:8766/worldsense/api/extract-url',
    json={'url': 'https://www.youtube.com/watch?v=...'})
text = resp.json()['text']
```

### Image Evaluation

Two vision modes:
- `per_persona` (default): each persona's LLM call receives the image directly
- `summary`: system describes the image once as text, shared across all personas

CLI: `ws run --image photo.jpg --content "Evaluate this"`
API: upload via `files` field in multipart form + set `vision_mode`

## Setup Guide

```bash
# 1. Clone and install
git clone https://github.com/hchen13/worldsense.git
cd worldsense
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

# 2. Configure LLM
cp .env.example .env
# Set WS_API_KEY, WS_API_BASE_URL, WS_MODEL

# 3. Start Web UI
./start.sh    # serves on port 8766
./stop.sh     # stop the server

# 4. Verify
curl -s http://localhost:8766/worldsense/api/tasks
ws personas --count 3 --market cn
```

## File Locations

| Path | Content |
|------|---------|
| `~/.worldsense/settings.json` | LLM profiles, concurrency, defaults |
| `~/.worldsense/results/` | Task results (JSON) |
| `~/.worldsense/reports/` | Generated markdown/JSON reports |
| `.env` | API keys and endpoint config |

## Tips for Agents

- CLI output defaults to JSON (machine-readable). Add `--table` for human display.
- Use `--profile` to select LLM models. List available profiles via `ws run --help` or check `~/.worldsense/settings.json`.
- Mock backend (`-b mock`) runs instantly — use it to verify setup before spending LLM credits.
- For long content (articles, transcripts), use `--content-file` instead of `--content`.
- After code changes to WorldSense, always restart: `./stop.sh && ./start.sh`
- Results JSON structure: `{task, summary, results[]}` — summary has aggregate stats, results has per-persona feedback.
