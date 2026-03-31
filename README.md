# 问势 · WorldSense

> AI-powered large-scale user research simulation platform

Generate thousands of virtual personas with diverse backgrounds and collect structured feedback on your product or content — without recruiting a single real participant.

## What It Does

WorldSense simulates user research at scale by:

1. **Generating personas** with realistic demographic and psychological profiles
2. **Running structured feedback** using LLM inference through each persona's cognitive lens
3. **Aggregating results** into actionable insights: conversion rates, NPS, sentiment, segmentation

## Quick Start

```bash
# Install
pip install -e .

# Generate 10 personas for preview
ws personas --count 10 --market global

# Run a full research session (uses MockBackend by default)
ws run --content "Your product description here" --personas 10

# View results
ws report <task-id>
```

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for design decisions.

## Configuration

Copy `.env.example` to `.env` and fill in your LLM API key:

```bash
cp .env.example .env
# Edit .env and set WS_API_KEY, WS_API_BASE_URL, etc.
```

## Project Structure

```
worldsense/
├── worldsense/
│   ├── cli.py          # CLI entry point (typer)
│   ├── core/           # Task engine, task definitions, result types
│   ├── persona/        # 3-layer persona engine
│   ├── llm/            # LLM backend abstraction + rate limiting
│   ├── pipeline/       # Async worker pool + scheduler
│   └── report/         # Result aggregation + markdown reports
├── data/
│   ├── hofstede.json   # Hofstede cultural dimensions (real data, 70+ countries)
│   ├── populations.json # UN world population weights
│   └── occupations.json # Consumer occupation list
└── docs/
    └── ARCHITECTURE.md
```

## Phase Roadmap

- **Phase 1** (current): Core persona engine + CLI + MockBackend demo ✅
- **Phase 2**: OpenAI-compatible backend + parallel inference at scale
- **Phase 3**: FastAPI REST layer + web dashboard
- **Phase 4**: Fine-tuned persona consistency + memory across sessions
