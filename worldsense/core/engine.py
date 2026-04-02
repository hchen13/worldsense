"""Core scheduling engine that orchestrates research runs."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from worldsense.core.task import ResearchTask, TaskStatus
from worldsense.core.result import PersonaResult, TaskResults
from worldsense.persona.generator import PersonaGenerator, DimensionConfig
from worldsense.pipeline.worker import WorkerPool, PersonaState, PersonaStatus

console = Console()

OUTPUT_DIR = Path(os.path.expanduser("~/.worldsense/results"))


class ResearchEngine:
    """Orchestrates end-to-end research simulation runs."""

    def __init__(self, task: ResearchTask):
        self.task = task
        self._results: list[PersonaResult] = []
        self._persona_states: dict[str, dict] = {}  # persona_id -> state dict

    async def run(self) -> TaskResults:
        """Execute the full research pipeline."""
        task = self.task
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.utcnow()

        console.print(f"\n[bold cyan]WorldSense Research Run[/bold cyan] — Task {task.task_id}")
        console.print(f"Content: [dim]{task.content[:80]}...[/dim]" if len(task.content) > 80 else f"Content: [dim]{task.content}[/dim]")
        console.print(f"Personas: [yellow]{task.persona_count}[/yellow] | Market: [yellow]{task.market}[/yellow] | Backend: [yellow]{task.backend}[/yellow]\n")

        try:
            # Step 1: Generate personas (with optional custom dimension config)
            dim_config = None
            if task.metadata.get("dimensions"):
                dim_config = DimensionConfig.from_dict(task.metadata["dimensions"])
            generator = PersonaGenerator(market=task.market, dimensions=dim_config)
            personas = generator.generate(task.persona_count)
            console.print(f"[green]✓[/green] Generated {len(personas)} personas")

            # Pre-populate ALL persona states as pending (so dot matrix shows gray dots immediately)
            for i, p in enumerate(personas):
                self._persona_states[p.persona_id] = {
                    "persona_id": p.persona_id,
                    "index": i,
                    "status": "pending",
                    "attempt": 0,
                    "error": None,
                    "persona": p.to_dict_summary(),
                }
            states_path = OUTPUT_DIR / f"{task.task_id}.states.json"
            try:
                states_path.write_text(
                    json.dumps(list(self._persona_states.values()), ensure_ascii=False)
                )
            except Exception:
                pass

            # Step 2: Run inference pipeline
            # Build backend_kwargs from task metadata llm_profile (set at task creation time)
            backend_kwargs: dict = {}
            llm_profile = task.metadata.get("llm_profile") if task.metadata else None
            if llm_profile:
                if llm_profile.get("model"):
                    backend_kwargs["model"] = llm_profile["model"]
                if llm_profile.get("api_key"):
                    backend_kwargs["api_key"] = llm_profile["api_key"]
                if llm_profile.get("endpoint"):
                    backend_kwargs["base_url"] = llm_profile["endpoint"]

            pool = WorkerPool(
                task=task,
                personas=personas,
                backend_name=task.backend,
                backend_kwargs=backend_kwargs if backend_kwargs else None,
                max_retries=task.max_retries,
                on_status=self._on_persona_status,
            )

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
                TimeElapsedColumn(),
                console=console,
            ) as progress:
                prog_task = progress.add_task("Running inference...", total=len(personas))

                async def on_result(result: PersonaResult) -> None:
                    self._results.append(result)
                    task.completed_personas += 1
                    progress.advance(prog_task)

                await pool.run(on_result=on_result)

            # Step 3: Aggregate
            agg = TaskResults.from_results(
                task_id=task.task_id,
                content=task.content,
                results=self._results,
            )

            # Step 4: Persist (update status before saving so the JSON reflects completion)
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.utcnow()
            output_path = self._save_results(agg)
            task.output_path = str(output_path)

            console.print(f"\n[green]✓[/green] Completed in {task.duration_seconds:.1f}s")
            console.print(f"Results saved: [dim]{output_path}[/dim]")

            return agg

        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            task.completed_at = datetime.utcnow()
            console.print(f"[red]✗ Task failed: {e}[/red]")
            raise

    async def _on_persona_status(self, state: PersonaState) -> None:
        """Persist per-persona status to disk for SSE polling."""
        entry: dict = {
            "persona_id": state.persona_id,
            "index": state.index,
            "status": state.status,
            "attempt": state.attempt,
            "error": state.error,
        }
        # Include LLM call metadata if available (for tooltip display)
        if state.llm_model is not None:
            entry["llm_model"] = state.llm_model
        if state.llm_elapsed_ms is not None:
            entry["llm_elapsed_ms"] = state.llm_elapsed_ms
        if state.llm_prompt_tokens is not None:
            entry["llm_prompt_tokens"] = state.llm_prompt_tokens
        if state.llm_completion_tokens is not None:
            entry["llm_completion_tokens"] = state.llm_completion_tokens
        # Include timing metadata
        if state.started_at is not None:
            entry["started_at"] = state.started_at
        if state.completed_at is not None:
            entry["completed_at"] = state.completed_at
        # Include persona summary snapshot for live tooltip during runs
        if state.persona_summary is not None:
            entry["persona"] = state.persona_summary
        self._persona_states[state.persona_id] = entry
        # Write to a lightweight states file alongside results
        states_path = OUTPUT_DIR / f"{self.task.task_id}.states.json"
        try:
            states_path.write_text(
                json.dumps(list(self._persona_states.values()), ensure_ascii=False)
            )
        except Exception:
            pass

    def _save_results(self, agg: TaskResults) -> Path:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        path = OUTPUT_DIR / f"{self.task.task_id}.json"
        task_data = self.task.model_dump(mode="json")
        # Strip bulky image data from persisted metadata (images are saved as files)
        if "image_data_urls" in task_data.get("metadata", {}):
            del task_data["metadata"]["image_data_urls"]
        data = {
            "task": task_data,
            "summary": agg.model_dump(mode="json"),
            "results": [r.model_dump(mode="json") for r in self._results],
        }
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        return path

    @staticmethod
    def load_results(task_id: str) -> Optional[dict]:
        path = OUTPUT_DIR / f"{task_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text())

    @staticmethod
    def load_persona_states(task_id: str) -> list[dict]:
        """Load per-persona states from disk (for dot-matrix visualization)."""
        path = OUTPUT_DIR / f"{task_id}.states.json"
        if not path.exists():
            return []
        try:
            return json.loads(path.read_text())
        except Exception:
            return []

    @staticmethod
    def list_tasks() -> list[dict]:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        tasks = []
        for p in sorted(OUTPUT_DIR.glob("*.json")):
            try:
                data = json.loads(p.read_text())
                tasks.append(data.get("task", {}))
            except Exception:
                pass
        return tasks
