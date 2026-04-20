from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .config import load_config
from .models import CrawlMode
from .pipeline import DocumentationPipeline
from .progress import CrawlProgressTracker


app = typer.Typer(help="Documentation ingestion and compilation CLI")
console = Console()


def _setup_logging(log_path: Path) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8")],
        force=True,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("playwright").setLevel(logging.WARNING)


@app.command()
def run(
    language: str | None = typer.Option(None, "--language", "-l", help="Run a single language by name or slug."),
    mode: CrawlMode = typer.Option("full", "--mode", help="Choose 'important' for core docs only or 'full' for broad coverage."),
    force_refresh: bool = typer.Option(False, "--force-refresh", help="Ignore saved state for selected languages."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show planning only."),
    validate_only: bool = typer.Option(False, "--validate-only", help="Validate existing outputs only."),
    language_concurrency: int | None = typer.Option(None, "--language-concurrency", help="Number of languages to process in parallel."),
    page_concurrency: int | None = typer.Option(None, "--page-concurrency", help="Number of pages to process concurrently per language."),
    max_pages: int | None = typer.Option(None, "--max-pages", help="Hard cap on processed pages per language."),
    max_discovered: int | None = typer.Option(None, "--max-discovered", help="Hard cap on discovered URLs per language."),
    per_host_delay: float | None = typer.Option(None, "--per-host-delay", help="Delay between requests to the same host in seconds."),
) -> None:
    config = load_config()
    config.planner.crawl_mode = mode
    if language_concurrency is not None:
        config.crawl.language_concurrency = max(1, language_concurrency)
    if page_concurrency is not None:
        config.crawl.max_concurrency = max(1, page_concurrency)
    if max_pages is not None:
        config.crawl.max_pages_per_language = max(1, max_pages)
    if max_discovered is not None:
        config.crawl.max_discovered_urls_per_language = max(1, max_discovered)
    if per_host_delay is not None:
        config.crawl.per_host_delay_seconds = max(0.0, per_host_delay)
    _setup_logging(config.paths.logs_dir / "run.log")

    async def _runner() -> None:
        pipeline = DocumentationPipeline(config)
        progress_tracker = CrawlProgressTracker(console=console)
        try:
            with progress_tracker.live():
                summary = await pipeline.run(
                    language_name=language,
                    force_refresh=force_refresh,
                    dry_run=dry_run,
                    validate_only=validate_only,
                    language_concurrency=language_concurrency,
                    crawl_mode=mode,
                    progress_tracker=progress_tracker,
                )
        finally:
            await pipeline.close()

        table = Table(title="Documentation Ingestion Summary")
        table.add_column("Language")
        table.add_column("Processed")
        table.add_column("Output")
        table.add_column("Score")
        for report in summary.reports:
            table.add_row(
                report.language,
                str(report.pages_processed),
                str(report.output_path or "N/A"),
                str(report.validation.score if report.validation else "N/A"),
            )
        console.print(table)

    asyncio.run(_runner())


@app.command()
def validate(language: str | None = typer.Option(None, "--language", "-l")) -> None:
    run(language=language, validate_only=True)


@app.command()
def init() -> None:
    config = load_config()
    config.paths.ensure()
    console.print(f"Initialized directories under [bold]{config.paths.root}[/bold]")