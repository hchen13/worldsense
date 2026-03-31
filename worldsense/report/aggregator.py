"""
Report generator: converts TaskResults into Markdown reports.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from worldsense.core.result import TaskResults

REPORT_DIR = Path.home() / ".worldsense" / "reports"


class ReportGenerator:
    """Generate Markdown and JSON reports from task results."""

    def __init__(self, results: TaskResults, task_meta: Optional[dict] = None):
        self.results = results
        self.task_meta = task_meta or {}

    def generate_markdown(self) -> str:
        r = self.results
        task_id = r.task_id
        content = r.content_snippet
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

        # NPS calculation
        nps = round((r.nps_promoters - r.nps_detractors) * 100, 1)
        nps_color = "🟢" if nps >= 30 else "🟡" if nps >= 0 else "🔴"

        sentiment_label = (
            "Positive" if r.avg_sentiment > 0.2 else
            "Negative" if r.avg_sentiment < -0.2 else
            "Neutral"
        )
        sentiment_emoji = "😊" if r.avg_sentiment > 0.2 else "😞" if r.avg_sentiment < -0.2 else "😐"

        lines = [
            f"# 问势 · WorldSense Research Report",
            f"",
            f"> **Task ID:** `{task_id}` | **Generated:** {now}",
            f"> **Content evaluated:** {content}{'...' if len(content) >= 80 else ''}",
            f"> **Sample size:** {r.total_personas:,} personas",
            f"",
            f"---",
            f"",
            f"## 📊 Executive Summary",
            f"",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| 🛒 Buy Rate | **{r.buy_rate:.1%}** |",
            f"| 🤔 Hesitation Rate | {r.hesitate_rate:.1%} |",
            f"| ❌ Pass Rate | {r.pass_rate:.1%} |",
            f"| {nps_color} NPS Score | **{nps:+.0f}** (avg rating: {r.avg_nps:.1f}/10) |",
            f"| {sentiment_emoji} Avg Sentiment | **{r.avg_sentiment:+.3f}** ({sentiment_label}) |",
            f"| 📣 Promoters (9-10) | {r.nps_promoters:.1%} |",
            f"| 📉 Detractors (0-6) | {r.nps_detractors:.1%} |",
            f"",
        ]

        # Top themes
        if r.top_attractions:
            lines += [
                f"## ✨ Top Attractions",
                f"",
            ]
            for i, a in enumerate(r.top_attractions, 1):
                lines.append(f"{i}. {a}")
            lines.append("")

        if r.top_concerns:
            lines += [
                f"## ⚠️ Top Concerns",
                f"",
            ]
            for i, c in enumerate(r.top_concerns, 1):
                lines.append(f"{i}. {c}")
            lines.append("")

        # Segmentation
        if r.by_nationality:
            lines += [
                f"## 🌍 Results by Nationality (Top 10)",
                f"",
                f"| Country | Count | Buy Rate | Avg NPS | Sentiment |",
                f"|---------|-------|----------|---------|-----------|",
            ]
            sorted_nat = sorted(
                r.by_nationality.items(),
                key=lambda x: x[1].get("count", 0),
                reverse=True,
            )[:10]
            for country, stats in sorted_nat:
                count = stats.get("count", 0)
                buy_rate = stats.get("buy_rate", 0)
                avg_nps = stats.get("avg_nps", 0)
                sentiment = stats.get("avg_sentiment", 0)
                lines.append(f"| {country} | {count} | {buy_rate:.1%} | {avg_nps:.1f} | {sentiment:+.2f} |")
            lines.append("")

        if r.by_age_group:
            lines += [
                f"## 👥 Results by Age Group",
                f"",
                f"| Age Group | Count | Buy Rate | Avg NPS | Sentiment |",
                f"|-----------|-------|----------|---------|-----------|",
            ]
            for age_grp, stats in sorted(r.by_age_group.items()):
                count = stats.get("count", 0)
                buy_rate = stats.get("buy_rate", 0)
                avg_nps = stats.get("avg_nps", 0)
                sentiment = stats.get("avg_sentiment", 0)
                lines.append(f"| {age_grp} | {count} | {buy_rate:.1%} | {avg_nps:.1f} | {sentiment:+.2f} |")
            lines.append("")

        if r.by_mbti:
            lines += [
                f"## 🧠 Results by MBTI Type",
                f"",
                f"| MBTI | Count | Buy Rate | Avg NPS | Sentiment |",
                f"|------|-------|----------|---------|-----------|",
            ]
            sorted_mbti = sorted(
                r.by_mbti.items(),
                key=lambda x: x[1].get("count", 0),
                reverse=True,
            )
            for mbti_type, stats in sorted_mbti:
                count = stats.get("count", 0)
                buy_rate = stats.get("buy_rate", 0)
                avg_nps = stats.get("avg_nps", 0)
                sentiment = stats.get("avg_sentiment", 0)
                lines.append(f"| {mbti_type} | {count} | {buy_rate:.1%} | {avg_nps:.1f} | {sentiment:+.2f} |")
            lines.append("")

        if r.by_income:
            lines += [
                f"## 💰 Results by Income Bracket",
                f"",
                f"| Income | Count | Buy Rate | Avg NPS | Sentiment |",
                f"|--------|-------|----------|---------|-----------|",
            ]
            income_order = ["low", "lower-middle", "middle", "upper-middle", "high"]
            for inc in income_order:
                if inc in r.by_income:
                    stats = r.by_income[inc]
                    count = stats.get("count", 0)
                    buy_rate = stats.get("buy_rate", 0)
                    avg_nps = stats.get("avg_nps", 0)
                    sentiment = stats.get("avg_sentiment", 0)
                    lines.append(f"| {inc} | {count} | {buy_rate:.1%} | {avg_nps:.1f} | {sentiment:+.2f} |")
            lines.append("")

        # Sample verbatims
        if r.sample_verbatims:
            lines += [
                f"## 💬 Sample Verbatims",
                f"",
            ]
            for i, v in enumerate(r.sample_verbatims[:5], 1):
                lines.append(f"> {i}. *\"{v}\"*")
                lines.append("")

        lines += [
            f"---",
            f"",
            f"*Generated by 问势 · WorldSense v0.1 — AI-powered user research simulation*",
        ]

        return "\n".join(lines)

    def save_markdown(self, output_path: Optional[Path] = None) -> Path:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        if output_path is None:
            output_path = REPORT_DIR / f"{self.results.task_id}_report.md"
        output_path.write_text(self.generate_markdown(), encoding="utf-8")
        return output_path

    def save_json(self, output_path: Optional[Path] = None) -> Path:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        if output_path is None:
            output_path = REPORT_DIR / f"{self.results.task_id}_summary.json"
        output_path.write_text(
            json.dumps(self.results.model_dump(mode="json"), indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        return output_path
