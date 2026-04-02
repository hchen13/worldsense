"""
Async worker pool for batch persona inference.

Mode B (merged epsilon): each persona evaluation is a single two-phase LLM call.
Phase 1: LLM imagines a concrete person matching the demographic profile (replaces Layer 2.5 epsilon).
Phase 2: LLM evaluates the content from that person's perspective.

The merged JSON response includes an "epsilon" field (the imagined background)
plus all standard evaluation fields.

Concurrency Layer (v2):
- Configurable concurrency limit (prevents GLM 30-50 QPS overflow)
- Exponential backoff with jitter on transient errors
- Per-persona status callbacks for real-time dot-matrix visualization
- Max retries configurable via SystemSettings
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Awaitable, Callable, Optional

from worldsense.core.result import PersonaResult, PurchaseIntent
from worldsense.core.task import ResearchTask
from worldsense.llm import get_backend
from worldsense.llm.backend import LLMBackend
from worldsense.persona.schema import Persona
from worldsense.pipeline.output import (
    MERGED_SYSTEM_PROMPT,
    build_merged_prompt,
)
from worldsense.pipeline.scheduler import ProgressTracker


ResultCallback = Callable[[PersonaResult], Awaitable[None]]


class PersonaStatus(str, Enum):
    PENDING = "pending"      # grey — not started yet
    RUNNING = "running"      # blue breathing animation
    RETRYING = "retrying"    # yellow breathing animation — error, waiting retry
    FAILED = "failed"        # red — max retries exceeded
    DONE = "done"            # green — completed successfully


@dataclass
class PersonaState:
    """Tracks per-persona execution state for dot-matrix visualization."""
    persona_id: str
    index: int
    status: PersonaStatus = PersonaStatus.PENDING
    attempt: int = 0
    error: Optional[str] = None
    result: Optional[PersonaResult] = None
    # LLM call metadata for tooltip display
    llm_model: Optional[str] = None
    llm_elapsed_ms: Optional[int] = None
    llm_prompt_tokens: Optional[int] = None
    llm_completion_tokens: Optional[int] = None
    # Timing metadata
    started_at: Optional[float] = None   # Unix timestamp (seconds)
    completed_at: Optional[float] = None  # Unix timestamp (seconds)
    # Persona summary snapshot (for tooltip during run)
    persona_summary: Optional[dict] = None


StatusCallback = Callable[[PersonaState], Awaitable[None]]


class WorkerPool:
    """Async pool that runs inference for a batch of personas.

    Supports:
    - Configurable concurrency (prevents API QPS overflow)
    - Exponential backoff with jitter on transient errors
    - Per-persona status callbacks for real-time visualization
    - Configurable max_retries from SystemSettings
    """

    def __init__(
        self,
        task: ResearchTask,
        personas: list[Persona],
        backend_name: str = "mock",
        backend_kwargs: Optional[dict] = None,
        max_retries: Optional[int] = None,
        on_status: Optional[StatusCallback] = None,
    ):
        self.task = task
        self.personas = personas
        self.backend_name = backend_name
        self.backend_kwargs = backend_kwargs or {}
        self._tracker = ProgressTracker(total=len(personas))
        self.on_status = on_status

        # Resolve max_retries: explicit arg > settings > hardcoded default
        if max_retries is not None:
            self.max_retries = max_retries
        else:
            try:
                from worldsense.core.settings import load_settings
                self.max_retries = load_settings().llm.max_retries
            except Exception:
                self.max_retries = 3

        # Persona states for visualization
        self._states: dict[str, PersonaState] = {
            p.persona_id: PersonaState(persona_id=p.persona_id, index=i)
            for i, p in enumerate(personas)
        }

    async def _emit_status(self, state: PersonaState) -> None:
        """Fire status callback if registered (non-blocking)."""
        if self.on_status:
            try:
                await self.on_status(state)
            except Exception:
                pass

    async def run(self, on_result: Optional[ResultCallback] = None) -> list[PersonaResult]:
        """
        Run Mode B (merged) inference for all personas.

        Each persona gets a single two-phase LLM call:
          Phase 1: Construct a concrete person from the demographic profile.
          Phase 2: Evaluate the content as that person.

        The response includes epsilon (persona background) + all evaluation fields.
        """
        backend = get_backend(self.backend_name, **self.backend_kwargs)

        # Resolve concurrency from task or settings
        concurrency = self.task.concurrency
        if concurrency <= 0:
            try:
                from worldsense.core.settings import load_settings
                concurrency = load_settings().llm.concurrency_limit
            except Exception:
                concurrency = 10

        semaphore = asyncio.Semaphore(concurrency)
        results: list[PersonaResult] = []

        try:
            async def process_one(persona: Persona) -> PersonaResult:
                async with semaphore:
                    return await self._run_single(backend, persona)

            tasks = [process_one(p) for p in self.personas]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)

            for i, res in enumerate(batch_results):
                if isinstance(res, Exception):
                    persona = self.personas[i]
                    state = self._states[persona.persona_id]
                    state.status = PersonaStatus.FAILED
                    state.error = str(res)
                    await self._emit_status(state)

                    error_result = PersonaResult(
                        persona_id=persona.persona_id,
                        task_id=self.task.task_id,
                        purchase_intent="pass",
                        nps_score=5,
                        sentiment_score=0.0,
                        error=str(res),
                        persona_summary=persona.to_dict_summary(),
                    )
                    results.append(error_result)
                    await self._tracker.increment(success=False)
                else:
                    results.append(res)
                    await self._tracker.increment(success=True)
                    if on_result:
                        await on_result(res)

        finally:
            await backend.close()

        return results

    async def _run_single(self, backend: LLMBackend, persona: Persona) -> PersonaResult:
        """Run inference for a single persona with exponential backoff retry."""
        import time as _time
        state = self._states[persona.persona_id]
        state.status = PersonaStatus.RUNNING
        state.attempt = 0
        state.started_at = _time.time()
        state.persona_summary = persona.to_dict_summary()
        await self._emit_status(state)

        last_error: Optional[Exception] = None

        for attempt in range(self.max_retries + 1):
            state.attempt = attempt
            try:
                t0 = time.monotonic()
                result, llm_meta = await self._infer(backend, persona)
                elapsed_ms = int((time.monotonic() - t0) * 1000)
                state.status = PersonaStatus.DONE
                state.result = result
                state.completed_at = _time.time()
                state.llm_model = llm_meta.get("model")
                state.llm_elapsed_ms = elapsed_ms
                state.llm_prompt_tokens = llm_meta.get("prompt_tokens")
                state.llm_completion_tokens = llm_meta.get("completion_tokens")
                await self._emit_status(state)
                return result
            except Exception as e:
                last_error = e
                if attempt < self.max_retries:
                    # Exponential backoff with full jitter: sleep = random(0, 15 * 2^attempt)
                    # attempt=0 → [0, 15s], attempt=1 → [0, 30s], attempt=2 → [0, 60s]
                    cap = 15 * (2 ** attempt)  # 15, 30, 60 seconds
                    delay = min(random.uniform(0, cap), 120.0)  # full jitter, cap at 120s

                    state.status = PersonaStatus.RETRYING
                    state.error = str(e)
                    await self._emit_status(state)

                    await asyncio.sleep(delay)

                    state.status = PersonaStatus.RUNNING
                    await self._emit_status(state)
                else:
                    state.status = PersonaStatus.FAILED
                    state.error = str(e)
                    await self._emit_status(state)

        raise last_error  # type: ignore[misc]

    async def _infer(self, backend: LLMBackend, persona: Persona) -> tuple[PersonaResult, dict]:
        """Build merged prompt, call backend, parse result (Mode B). Returns (result, llm_meta)."""
        cog = persona.cognitive
        persona_summary = {
            **persona.to_dict_summary(),
            "price_sensitivity": cog.price_sensitivity,
            "risk_appetite": cog.risk_appetite,
            "novelty_seeking": cog.novelty_seeking,
            "emotional_reactivity": cog.emotional_reactivity,
            "wtp_multiplier": cog.wtp_multiplier,
            "personality_type": persona.personality_type,
            "income_bracket": persona.income_bracket,
        }

        language = self.task.language or self.task.metadata.get("language", "English")

        research_type = getattr(self.task, "research_type", "product_purchase") or "product_purchase"

        prompt = build_merged_prompt(
            persona_summary=persona_summary,
            content=self.task.content,
            scenario_context=getattr(self.task, "scenario_context", ""),
            language=language,
            research_type=research_type,
        )

        # Append PERSONA_DATA for MockBackend extraction
        persona_data = json.dumps(persona_summary)
        prompt_with_data = prompt + f"\nPERSONA_DATA: {persona_data}"

        # Resolve temperature from settings if available
        try:
            from worldsense.core.settings import load_settings
            temperature = load_settings().advanced.temperature
        except Exception:
            temperature = 0.9

        # Resolve timeout from settings
        try:
            from worldsense.core.settings import load_settings
            timeout = float(load_settings().llm.request_timeout)
        except Exception:
            timeout = 120.0

        # Resolve per-persona vision images (if vision_mode == "per_persona")
        images = None
        if self.task.metadata.get("vision_mode") == "per_persona":
            images = self.task.metadata.get("image_data_urls", []) or None

        response = await backend.generate(
            prompt=prompt_with_data,
            schema=None,           # Merged call uses json_mode=True (json_object)
            system_prompt=MERGED_SYSTEM_PROMPT,
            temperature=temperature,
            max_tokens=2000,
            extra_body={"enable_thinking": False},
            json_mode=True,
            images=images,
        )

        parsed = response.get("parsed") or {}

        # Store epsilon back on the persona object for any downstream use
        epsilon = parsed.get("epsilon", "")
        if epsilon:
            persona.epsilon = epsilon

        # Write LLM-generated name back to persona (if returned and non-empty)
        llm_name = parsed.get("name", "")
        if llm_name and llm_name.strip():
            persona.name = llm_name.strip()

        # Map to PersonaResult — use raw string so research-type-specific intents are preserved
        intent_raw = parsed.get("purchase_intent", "pass")
        # Normalize synonyms before validation (e.g. old "subscribe" → "follow" for social_follow)
        _INTENT_SYNONYMS = {
            "subscribe": "follow",  # social_follow: LLM may still return old slot2 value
        }
        intent_raw = _INTENT_SYNONYMS.get(intent_raw, intent_raw)
        # Validate against known intent values for this research_type; fallback to "pass"
        from worldsense.pipeline.output import INTENT_PRESETS, DEFAULT_INTENT_PRESET
        research_type = getattr(self.task, "research_type", "product_purchase") or "product_purchase"
        allowed_values = INTENT_PRESETS.get(research_type, DEFAULT_INTENT_PRESET)["values"]
        if intent_raw not in allowed_values:
            intent_raw = allowed_values[2]  # always "pass" slot

        usage = response.get("usage", {})
        llm_meta = {
            "model": getattr(backend, "model", None),
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
        }

        return PersonaResult(
            persona_id=persona.persona_id,
            task_id=self.task.task_id,
            purchase_intent=intent_raw,
            nps_score=int(parsed.get("nps_score", 5)),
            sentiment_score=float(parsed.get("sentiment_score", 0.0)),
            key_attraction=parsed.get("key_attraction", ""),
            key_concern=parsed.get("key_concern", ""),
            verbatim=parsed.get("verbatim", ""),
            willingness_to_pay_multiplier=float(
                parsed.get("willingness_to_pay_multiplier", cog.wtp_multiplier)
            ),
            persona_summary=persona.to_dict_summary(),
            raw_llm_response=response.get("content", ""),
        ), llm_meta
