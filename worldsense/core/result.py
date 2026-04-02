"""Result types for WorldSense research outputs."""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class PurchaseIntent(str, Enum):
    """Legacy enum kept for backward compatibility. New code uses str directly."""
    BUY = "buy"
    HESITATE = "hesitate"
    PASS = "pass"


class PersonaResult(BaseModel):
    """Structured feedback from a single persona."""

    persona_id: str
    task_id: str

    # Core feedback — stored as raw str to support research-type-specific intents
    # (e.g. "follow"/"consider"/"pass" for social_follow, "buy"/"hesitate"/"pass" for product_purchase)
    purchase_intent: str
    nps_score: int = Field(..., ge=0, le=10, description="Net Promoter Score (0-10)")
    sentiment_score: float = Field(..., ge=-1.0, le=1.0, description="-1=negative, 0=neutral, 1=positive")

    # Qualitative feedback
    key_attraction: str = Field(default="", description="Main thing that appeals to this persona")
    key_concern: str = Field(default="", description="Main concern or objection")
    verbatim: str = Field(default="", description="Simulated free-text response")

    # Price sensitivity context
    willingness_to_pay_multiplier: float = Field(
        default=1.0, description="Relative WTP (1.0 = average, 0.5 = half price, 2.0 = double)"
    )

    # Metadata
    persona_summary: dict[str, Any] = Field(default_factory=dict)
    raw_llm_response: Optional[str] = None
    error: Optional[str] = None

    class Config:
        use_enum_values = True


class TaskResults(BaseModel):
    """Aggregated results for a completed research task."""

    task_id: str
    content_snippet: str = ""
    total_personas: int = 0

    # Aggregate stats
    buy_rate: float = 0.0
    hesitate_rate: float = 0.0
    pass_rate: float = 0.0
    avg_nps: float = 0.0
    nps_promoters: float = 0.0   # % scoring 9-10
    nps_detractors: float = 0.0  # % scoring 0-6
    avg_sentiment: float = 0.0

    # Segmentation slices
    by_nationality: dict[str, dict] = Field(default_factory=dict)
    by_age_group: dict[str, dict] = Field(default_factory=dict)
    by_income: dict[str, dict] = Field(default_factory=dict)
    by_occupation: dict[str, dict] = Field(default_factory=dict)
    by_mbti: dict[str, dict] = Field(default_factory=dict)

    # Top themes
    top_attractions: list[str] = Field(default_factory=list)
    top_concerns: list[str] = Field(default_factory=list)
    sample_verbatims: list[str] = Field(default_factory=list)

    # Raw results list
    results: list[PersonaResult] = Field(default_factory=list, exclude=True)

    @classmethod
    def from_results(cls, task_id: str, content: str, results: list[PersonaResult]) -> "TaskResults":
        """Compute aggregated stats from a list of PersonaResult."""
        n = len(results)
        if n == 0:
            return cls(task_id=task_id, content_snippet=content[:80])

        # Intent slot 1 ("positive" intent): buy / follow / trial / etc.
        # Note: "subscribe" is treated as slot1 (same action as "follow") for backward compat with old results.
        # Intent slot 2 ("neutral/uncertain"): hesitate / consider / maybe / etc.
        # Intent slot 3: always "pass"
        _SLOT1 = {"buy", "follow", "subscribe", "trial", "switch", "watch", "resonate"}
        _SLOT2 = {"hesitate", "consider", "maybe"}
        buy = sum(1 for r in results if r.purchase_intent in _SLOT1)
        hesitate = sum(1 for r in results if r.purchase_intent in _SLOT2)
        nps_scores = [r.nps_score for r in results]
        sentiments = [r.sentiment_score for r in results]
        promoters = sum(1 for s in nps_scores if s >= 9)
        detractors = sum(1 for s in nps_scores if s <= 6)

        # Collect segmentation
        by_nationality: dict[str, list] = {}
        by_age: dict[str, list] = {}
        by_income: dict[str, list] = {}
        by_occupation: dict[str, list] = {}
        by_mbti: dict[str, list] = {}

        for r in results:
            ps = r.persona_summary
            nat = ps.get("nationality", "unknown")
            age = ps.get("age_group", "unknown")
            inc = ps.get("income_bracket", "unknown")
            # Use occupation_title (English readable name) as the key for by_occupation
            # Prefer occupation_title, fall back to occupation_label, then occupation_id
            occ = ps.get("occupation_title") or ps.get("occupation_label") or ps.get("occupation_id", "unknown")
            mbti = ps.get("mbti", "unknown")

            for bucket, key in [(by_nationality, nat), (by_age, age), (by_income, inc), (by_occupation, occ), (by_mbti, mbti)]:
                if key not in bucket:
                    bucket[key] = []
                bucket[key].append(r)

        _SLOT1 = {"buy", "follow", "subscribe", "trial", "switch", "watch", "resonate"}

        def _slice_stats(group: list[PersonaResult]) -> dict:
            ng = len(group)
            if ng == 0:
                return {"count": 0}
            return {
                "count": ng,
                "buy_rate": round(sum(1 for x in group if x.purchase_intent in _SLOT1) / ng, 3),
                "avg_nps": round(sum(x.nps_score for x in group) / ng, 2),
                "avg_sentiment": round(sum(x.sentiment_score for x in group) / ng, 3),
            }

        agg = cls(
            task_id=task_id,
            content_snippet=content[:80],
            total_personas=n,
            buy_rate=round(buy / n, 3),
            hesitate_rate=round(hesitate / n, 3),
            pass_rate=round((n - buy - hesitate) / n, 3),
            avg_nps=round(sum(nps_scores) / n, 2),
            nps_promoters=round(promoters / n, 3),
            nps_detractors=round(detractors / n, 3),
            avg_sentiment=round(sum(sentiments) / n, 3),
            by_nationality={k: _slice_stats(v) for k, v in by_nationality.items()},
            by_age_group={k: _slice_stats(v) for k, v in by_age.items()},
            by_income={k: _slice_stats(v) for k, v in by_income.items()},
            by_occupation={k: _slice_stats(v) for k, v in by_occupation.items()},
            by_mbti={k: _slice_stats(v) for k, v in by_mbti.items()},
            top_attractions=_extract_top_themes([r.key_attraction for r in results], 5),
            top_concerns=_extract_top_themes([r.key_concern for r in results], 5),
            sample_verbatims=[r.verbatim for r in results[:5] if r.verbatim],
        )
        agg.results = results
        return agg


def _extract_top_themes(texts: list[str], top_k: int) -> list[str]:
    """Simple frequency-based theme extraction."""
    from collections import Counter

    # Deduplicate and count non-empty entries
    counter = Counter(t.strip() for t in texts if t.strip())
    return [item for item, _ in counter.most_common(top_k)]
