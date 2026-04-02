"""Tests for the inference pipeline and mock backend."""

import asyncio
import pytest
from worldsense.llm.backend import MockBackend
from worldsense.core.result import TaskResults
from worldsense.persona.generator import PersonaGenerator
from worldsense.core.task import ResearchTask
from worldsense.pipeline.worker import WorkerPool


@pytest.mark.asyncio
async def test_mock_backend_basic():
    backend = MockBackend()
    response = await backend.generate("Test prompt")
    assert "content" in response
    assert "parsed" in response
    parsed = response["parsed"]
    assert "intent" in parsed
    assert parsed["intent"] in ("buy", "hesitate", "pass")
    assert 0 <= parsed["nps_score"] <= 10
    assert -1 <= parsed["sentiment_score"] <= 1


@pytest.mark.asyncio
async def test_mock_backend_with_persona_data():
    import json
    backend = MockBackend()
    persona_data = {
        "price_sensitivity": 0.8,
        "risk_appetite": 0.2,
        "novelty_seeking": 0.3,
        "emotional_reactivity": 0.4,
        "wtp_multiplier": 0.5,
        "personality_type": "value_hunter",
        "income_bracket": "low",
    }
    prompt = f"Test content\nPERSONA_DATA: {json.dumps(persona_data)}"
    response = await backend.generate(prompt)
    # With high price sensitivity and low risk, should lean toward pass/hesitate
    assert response["parsed"]["intent"] in ("buy", "hesitate", "pass")


@pytest.mark.asyncio
async def test_worker_pool_small():
    gen = PersonaGenerator(market="us", seed=42)
    personas = gen.generate(5)

    task = ResearchTask(
        content="A new AI coding assistant for developers",
        persona_count=5,
        market="us",
        backend="mock",
        concurrency=3,
    )

    results = []

    async def collect(result):
        results.append(result)

    pool = WorkerPool(task=task, personas=personas, backend_name="mock")
    batch = await pool.run(on_result=collect)

    assert len(batch) == 5
    assert len(results) == 5
    for r in batch:
        assert r.persona_id.startswith("p_")
        assert r.intent in ("buy", "hesitate", "pass")


def test_task_results_aggregation():
    from worldsense.core.result import PersonaResult

    results = [
        PersonaResult(
            persona_id=f"p_{i:04d}",
            task_id="test",
            intent="buy",
            nps_score=9,
            sentiment_score=0.7,
            key_attraction="Great value",
            key_concern="Shipping cost",
            verbatim="I liked it",
            persona_summary={"nationality": "US", "age_group": "25-34", "income_bracket": "middle", "occupation_id": "teacher"},
        )
        for i in range(7)
    ] + [
        PersonaResult(
            persona_id=f"p_{i:04d}",
            task_id="test",
            intent="pass",
            nps_score=3,
            sentiment_score=-0.5,
            key_attraction="Nothing",
            key_concern="Too expensive",
            verbatim="Not for me",
            persona_summary={"nationality": "CN", "age_group": "35-44", "income_bracket": "low", "occupation_id": "farmer"},
        )
        for i in range(7, 10)
    ]

    agg = TaskResults.from_results("test", "test content", results)
    assert agg.total_personas == 10
    assert abs(agg.buy_rate - 0.7) < 0.01
    assert abs(agg.pass_rate - 0.3) < 0.01
    assert agg.avg_nps > 5
    assert "US" in agg.by_nationality
    assert "CN" in agg.by_nationality
