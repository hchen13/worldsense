"""Task definitions for WorldSense research sessions."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ResearchTask(BaseModel):
    """Represents a single WorldSense research run."""

    task_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    content: str = Field(..., description="Product/content description to evaluate")
    scenario_context: str = Field(default="", description="Scenario context injected into system prompt")
    persona_count: int = Field(default=100, ge=1, le=100_000)
    market: str = Field(default="global", description="Target market (global/us/cn/asia/etc.)")
    backend: str = Field(default="mock", description="LLM backend to use")
    concurrency: int = Field(default=10, ge=0, le=500)  # 0 = use settings default
    max_retries: int = Field(default=3, ge=0, le=10, description="Max retries per persona (exponential backoff)")
    language: str = Field(default="English", description="Output language for simulation results")
    research_type: str = Field(default="product_purchase", description="Evaluation preset type (e.g. social_follow, product_purchase)")

    # Task lifecycle
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # Progress tracking
    total_personas: int = 0
    completed_personas: int = 0
    failed_personas: int = 0

    # Output
    output_path: Optional[str] = None
    error: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def progress(self) -> float:
        if self.total_personas == 0:
            return 0.0
        return self.completed_personas / self.total_personas

    @property
    def duration_seconds(self) -> Optional[float]:
        if self.started_at is None:
            return None
        end = self.completed_at or datetime.utcnow()
        return (end - self.started_at).total_seconds()

    def model_post_init(self, __context: Any) -> None:
        self.total_personas = self.persona_count

    class Config:
        use_enum_values = True
