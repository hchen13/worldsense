"""
WorldSense CLI — ws command

Usage:
    ws run --content "..." --personas 100 --market global
    ws personas --count 10 --market us
    ws report <task-id>
    ws tasks
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich import box

app = typer.Typer(
    name="ws",
    help="问势 · WorldSense — AI-powered large-scale user research simulation",
    add_completion=False,
    rich_markup_mode="rich",
)
console = Console()


@app.command("run")
def cmd_run(
    content: str = typer.Option(..., "--content", "-c", help="Product/content description to evaluate"),
    personas: int = typer.Option(100, "--personas", "-n", help="Number of personas to simulate"),
    market: str = typer.Option("global", "--market", "-m", help="Target market (global/us/cn/asia/europe/latam/africa/mena/developed/emerging)"),
    backend: str = typer.Option("mock", "--backend", "-b", help="LLM backend (mock/openai_compat)"),
    concurrency: int = typer.Option(10, "--concurrency", help="Max concurrent LLM calls"),
    report: bool = typer.Option(True, "--report/--no-report", help="Generate Markdown report after run"),
    language: str = typer.Option("English", "--language", "-l", help="Output language for LLM responses (e.g. English, Chinese, Japanese)"),
    scenario_context: Optional[str] = typer.Option(None, "--scenario-context", "-s", help="Scenario context describing how personas encounter the content"),
):
    """Run a full research simulation."""
    from worldsense.core.task import ResearchTask
    from worldsense.core.engine import ResearchEngine
    from worldsense.report.aggregator import ReportGenerator

    task = ResearchTask(
        content=content,
        persona_count=personas,
        market=market,
        backend=backend,
        concurrency=concurrency,
        language=language,
        scenario_context=scenario_context or "",
        metadata={"language": language},
    )

    engine = ResearchEngine(task)

    try:
        agg = asyncio.run(engine.run())
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)

    # Print summary table
    _print_summary(agg)

    # Generate report
    if report:
        gen = ReportGenerator(agg, task_meta=task.model_dump(mode="json"))
        md_path = gen.save_markdown()
        json_path = gen.save_json()
        console.print(f"\n[bold green]Report saved:[/bold green]")
        console.print(f"  Markdown: [dim]{md_path}[/dim]")
        console.print(f"  JSON:     [dim]{json_path}[/dim]")

    console.print(f"\n[bold]Task ID:[/bold] {task.task_id}")
    console.print(f"Run [cyan]ws report {task.task_id}[/cyan] to view the full report.")


@app.command("personas")
def cmd_personas(
    count: int = typer.Option(10, "--count", "-n", help="Number of personas to generate"),
    market: str = typer.Option("global", "--market", "-m", help="Target market"),
    seed: Optional[int] = typer.Option(None, "--seed", help="Random seed for reproducibility"),
    table_output: bool = typer.Option(False, "--table", "-t", help="Display as Rich table (human-readable)"),
):
    """Generate and preview personas without running inference."""
    from worldsense.persona.generator import PersonaGenerator

    try:
        gen = PersonaGenerator(market=market, seed=seed)
        persona_list = gen.generate(count)
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]", stderr=True)
        raise typer.Exit(1)

    if not table_output:
        data = [p.model_dump(mode="json") for p in persona_list]
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return

    # Rich table output
    console.print(f"\n[bold cyan]Generating {count} personas[/bold cyan] | Market: [yellow]{market}[/yellow]\n")

    table = Table(
        title=f"Generated Personas ({market} market)",
        box=box.SIMPLE_HEAVY,
        expand=True,
    )
    table.add_column("Age", justify="right", no_wrap=True)
    table.add_column("G", no_wrap=True)
    table.add_column("Ctry", no_wrap=True)
    table.add_column("MBTI", no_wrap=True)
    table.add_column("Occupation", ratio=3)
    table.add_column("Income", ratio=2)
    table.add_column("Personality", ratio=2)
    table.add_column("P.S.", justify="right", no_wrap=True)
    table.add_column("Risk", justify="right", no_wrap=True)

    for p in persona_list:
        cog = p.cognitive
        # Build display occupation with local name if available
        local = p.occupation_title_local.get(p.nationality, "")
        occ_display = p.occupation_title or p.occupation_label
        if local:
            occ_display = f"{occ_display} ({local})"
        # Build income display
        income_display = p._format_income().replace("Income: ", "")
        # Gender shorthand
        gen_short = {"male": "M", "female": "F", "non-binary": "NB"}.get(p.gender, p.gender[:2])
        table.add_row(
            str(p.age),
            gen_short,
            p.nationality,
            p.mbti or "—",
            occ_display,
            income_display,
            p.personality_type.replace("_", " ").title(),
            f"{cog.price_sensitivity:.1f}",
            f"{cog.risk_appetite:.1f}",
        )

    console.print(table)
    console.print(f"\n[dim]Generated {count} personas for market: {market}[/dim]")

    # Show one full example
    if table_output and count > 0:
        example = persona_list[0]
        console.print(f"\n[bold]Example Persona Prompt Context:[/bold]")
        console.print(f"[dim]{example.to_prompt_context()}[/dim]")


@app.command("report")
def cmd_report(
    task_id: str = typer.Argument(..., help="Task ID from a previous run"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output path for report"),
    format: str = typer.Option("markdown", "--format", "-f", help="Output format (markdown/json/print)"),
):
    """View or export the report for a completed task."""
    from worldsense.core.engine import ResearchEngine
    from worldsense.core.result import TaskResults
    from worldsense.report.aggregator import ReportGenerator

    data = ResearchEngine.load_results(task_id)
    if data is None:
        console.print(f"[red]Task '{task_id}' not found.[/red]")
        console.print("Run [cyan]ws tasks[/cyan] to list available tasks.")
        raise typer.Exit(1)

    summary = data.get("summary", {})
    results_raw = data.get("results", [])

    from worldsense.core.result import PersonaResult
    results = [PersonaResult(**r) for r in results_raw]
    task_results = TaskResults(**{k: v for k, v in summary.items() if k != "results"})
    task_results.results = results

    gen = ReportGenerator(task_results, task_meta=data.get("task", {}))

    if format == "markdown" or format == "print":
        md = gen.generate_markdown()
        if format == "print":
            console.print(md)
        else:
            out_path = output or gen.save_markdown()
            if output:
                output.write_text(md, encoding="utf-8")
                out_path = output
            console.print(f"Report saved: [dim]{out_path}[/dim]")

    elif format == "json":
        out_path = output or gen.save_json()
        if output:
            import json as _json
            output.write_text(_json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
            out_path = output
        console.print(f"JSON saved: [dim]{out_path}[/dim]")

    # Always print summary to console
    _print_summary(task_results)


@app.command("tasks")
def cmd_tasks():
    """List all completed research tasks."""
    from worldsense.core.engine import ResearchEngine

    tasks = ResearchEngine.list_tasks()
    if not tasks:
        console.print("[dim]No tasks found. Run [cyan]ws run[/cyan] to start.[/dim]")
        return

    table = Table(title="WorldSense Research Tasks", box=box.ROUNDED)
    table.add_column("Task ID", style="cyan", width=12)
    table.add_column("Status", width=10)
    table.add_column("Personas", justify="right", width=10)
    table.add_column("Market", width=10)
    table.add_column("Backend", width=14)
    table.add_column("Created", width=20)
    table.add_column("Content", width=30)

    for t in tasks:
        status = t.get("status", "unknown")
        status_color = {"completed": "green", "failed": "red", "running": "yellow"}.get(status, "white")
        table.add_row(
            t.get("task_id", "?"),
            f"[{status_color}]{status}[/{status_color}]",
            str(t.get("persona_count", 0)),
            t.get("market", "?"),
            t.get("backend", "?"),
            t.get("created_at", "?")[:16],
            t.get("content", "")[:28],
        )

    console.print(table)


def _print_summary(agg) -> None:
    """Print a compact summary table to console."""
    nps = round((agg.nps_promoters - agg.nps_detractors) * 100, 1)

    table = Table(title="Research Summary", box=box.SIMPLE_HEAVY)
    table.add_column("Metric", style="bold")
    table.add_column("Value")

    table.add_row("Total Personas", f"{agg.total_personas:,}")
    table.add_row("Buy Rate", f"[green]{agg.buy_rate:.1%}[/green]")
    table.add_row("Hesitate Rate", f"[yellow]{agg.hesitate_rate:.1%}[/yellow]")
    table.add_row("Pass Rate", f"[red]{agg.pass_rate:.1%}[/red]")
    table.add_row("NPS Score", f"{nps:+.0f} (promoters: {agg.nps_promoters:.1%}, detractors: {agg.nps_detractors:.1%})")
    table.add_row("Avg Rating", f"{agg.avg_nps:.1f}/10")
    table.add_row("Avg Sentiment", f"{agg.avg_sentiment:+.3f}")

    console.print(table)


if __name__ == "__main__":
    app()
