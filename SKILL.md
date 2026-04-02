---
name: worldsense
description: Run AI-powered user research simulations with WorldSense. Use this skill when the user wants to test how a product, content, social media post, video, or concept would be received by a target audience. Also trigger when the user mentions persona generation, audience simulation, market testing, NPS prediction, user research without real users, or wants to evaluate content across different demographics. Covers CLI commands (ws run, ws personas, ws report) and API endpoints.
---

# WorldSense — Agent Reference

## CLI

### Persona Preview

```bash
# Default output is JSON (agent-friendly)
ws personas --count 10 --market cn
ws personas --count 50 --market us --seed 42

# Human-readable table
ws personas --count 10 --market cn --table
```

### Run Research

```bash
ws run \
  --content "Product description" \        # inline content
  --content-file path.md \                 # OR read from file (use for long content)
  --personas 50 \                          # number of personas (default: 100)
  --market cn \                            # target market
  --language 中文 \                        # output language (default: English)
  --research-type social_follow \          # see Research Types table
  --profile "MiniMax International" \      # LLM profile name from settings
  --scenario-context "How user encounters this" \
  --dimensions '{"location_weights":{"t1":0.5,"new-t1":0.5}}' \
  --image poster.jpg \                     # optional image (repeatable)
  --vision-mode per_persona \              # per_persona (default) or summary
  --concurrency 30
```

### View Results

```bash
ws report <task-id>       # render report
ws tasks                  # list all tasks (JSON)
```

## Research Types

| ID | Intent Values | Question |
|----|--------------|----------|
| `product_purchase` | buy / hesitate / pass | Would they buy this? |
| `social_follow` | follow / consider / pass | Would they follow this account? |
| `content_reaction` | watch / maybe / pass | Would they watch/read this? |
| `app_trial` | trial / consider / pass | Would they try this app? |
| `concept_test` | resonate / consider / pass | Does this concept resonate? |
| `competitive_switch` | switch / consider / pass | Would they switch? |

## Markets

`global`, `cn`, `us`, `asia`, `europe`, `latam`, `africa`, `mena`, `developed`, `emerging`

China (`cn`) city tiers: `t1`, `new-t1`, `t2`, `t3`, `t4-5`, `rural`

## Dimension Config

JSON string for `--dimensions` or `dimensions_json` API param:

```json
{
  "location_weights": {"t1": 0.5, "new-t1": 0.5},
  "nationality_weights": {"CN": 0.7, "JP": 0.3},
  "age_weights": {"25-34": 0.6, "35-44": 0.4},
  "gender_weights": {"male": 0.5, "female": 0.5},
  "occupation_ids": ["software_dev", "data_scientist"],
  "personality_traits": ["pragmatic_planner", "impulse_explorer"]
}

```

All fields optional. Omitted = default population distribution.

## API Endpoints

Base: `http://localhost:8766/worldsense`

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/run` | Submit research task (multipart form) |
| GET | `/api/tasks` | List all tasks |
| GET | `/api/tasks/{id}` | Task details + results |
| GET | `/api/tasks/{id}/persona-states` | Per-persona states (for live monitoring) |
| POST | `/api/personas` | Generate persona preview (JSON body: `{count, market}`) |
| POST | `/api/prompt-preview` | Preview actual LLM prompt (JSON body: `{content, scenario_context, market, research_type, language}`) |
| POST | `/api/extract-url` | Extract content from URL (JSON body: `{url}`) |
| GET | `/api/settings` | Read settings |
| PUT | `/api/settings` | Update settings |
| GET | `/api/markets` | List available markets |

### Submit Task via API

```python
import httpx, json

resp = httpx.post('http://localhost:8766/worldsense/api/run', data={
    'content': 'Your content here',
    'scenario_context': 'How the user encounters this',
    'personas_count': '50',
    'market': 'cn',
    'language': '中文',
    'research_type': 'social_follow',
    'dimensions_json': json.dumps({'location_weights': {'t1': 0.25, 'new-t1': 0.25}}),
    'concurrency': '30',
    'vision_mode': 'per_persona',
}, timeout=30)

task_id = resp.json()['task_id']
```

### Poll Task Status

```python
resp = httpx.get(f'http://localhost:8766/worldsense/api/tasks/{task_id}')
data = resp.json()
task = data['task']
status = task['status']         # pending / running / completed / failed
progress = task['completed_personas']
total = task['total_personas']
```

### Read Results

```python
data = resp.json()
summary = data['summary']
print(summary['buy_rate'])          # slot1 rate (buy/follow/watch/etc.)
print(summary['hesitate_rate'])     # slot2 rate
print(summary['pass_rate'])
print(summary['avg_nps'])           # 0-10
print(summary['avg_sentiment'])     # -1 to +1
print(summary['by_nationality'])    # segmentation dicts
print(summary['by_age_group'])
print(summary['by_mbti'])

results = data['results']           # per-persona list
for r in results:
    print(r['intent'], r['nps_score'], r['verbatim'])
```

### Extract URL Content

```python
resp = httpx.post('http://localhost:8766/worldsense/api/extract-url',
    json={'url': 'https://www.youtube.com/watch?v=...'})
text = resp.json()['text']          # extracted text
meta = resp.json()['metadata']      # {source, title, ...}
```

Supports: web articles (trafilatura), YouTube/Bilibili/TikTok/Douyin (subtitles via yt-dlp), videos without subtitles (audio transcription via whisper).

## Image Evaluation

Two vision modes:
- `per_persona` (default): each persona's LLM call receives the image directly
- `summary`: system describes image once as text, shared across all personas

CLI: `ws run --image photo.jpg --content "Evaluate this"`
API: upload via `files` field in multipart form, set `vision_mode` param.

## File Locations

| Path | Content |
|------|---------|
| `~/.worldsense/settings.json` | LLM profiles, concurrency, defaults |
| `~/.worldsense/results/{task_id}.json` | Task results |
| `~/.worldsense/results/{task_id}.states.json` | Per-persona execution states |
| `~/.worldsense/reports/` | Generated reports |

## Tips

- CLI defaults to JSON output. Add `--table` only when the human needs to see it.
- Use `-b mock` to test without LLM credits.
- For long content (articles, transcripts), use `--content-file` not `--content`.
- After any code change, restart: `./stop.sh && ./start.sh`
- Results JSON: `{task, summary, results[]}` — summary has aggregates, results has per-persona feedback.
