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


app = typer.Typer(
    help=(
        "Ingest official programming-language documentation and compile one normalized Markdown manual per language.\n\n"
        "Typical workflow:\n"
        "  1. python documentation_downloader.py init\n"
        "  2. python documentation_downloader.py run --mode full\n"
        "  3. python documentation_downloader.py validate\n\n"
        "Examples:\n"
        "  python documentation_downloader.py run --language python --mode important\n"
        "  python documentation_downloader.py run --mode full --single-terminal --language-concurrency 6 --page-concurrency 16\n"
        "  python documentation_downloader.py validate --language rust"
    ),
    no_args_is_help=True,
    rich_markup_mode="rich",
)
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


@app.command(help="Crawl documentation sources, extract content, and compile Markdown outputs.")
def run(
    language: str | None = typer.Option(None, "--language", "-l", help="Run a single language by name or slug."),
    mode: CrawlMode = typer.Option("full", "--mode", help="Choose 'important' for core docs only or 'full' for broad coverage."),
    force_refresh: bool = typer.Option(False, "--force-refresh", help="Ignore saved state for selected languages."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show planning only."),
    validate_only: bool = typer.Option(False, "--validate-only", help="Validate existing outputs only."),
    single_terminal: bool = typer.Option(False, "--single-terminal", help="Disable the live dashboard and print periodic progress lines for SSH or plain terminals."),
    splitmode: bool = typer.Option(False, "--splitmode", help="First crawl only for link discovery, then process the discovered URLs in a second phase."),
    language_concurrency: int | None = typer.Option(None, "--language-concurrency", help="Number of languages to process in parallel."),
    page_concurrency: int | None = typer.Option(None, "--page-concurrency", help="Number of pages to process concurrently per language."),
    max_pages: int | None = typer.Option(None, "--max-pages", help="Hard cap on processed pages per language."),
    max_discovered: int | None = typer.Option(None, "--max-discovered", help="Hard cap on discovered URLs per language."),
    per_host_delay: float | None = typer.Option(None, "--per-host-delay", help="Delay between requests to the same host in seconds."),
) -> None:
    """Run the documentation ingestion pipeline.

    This command plans crawl roots, fetches documentation pages and assets,
    extracts normalized Markdown, merges them per language, and writes
    validation/report outputs.

    Output locations:
    - Markdown manuals: output/markdown/
    - Reports: output/reports/
    - Logs: logs/run.log

    Recommended examples:
    - Full crawl: python documentation_downloader.py run --mode full
    - One language: python documentation_downloader.py run --language python
    - SSH-safe mode: python documentation_downloader.py run --mode full --single-terminal
    - Fast VM run: python documentation_downloader.py run --mode full --language-concurrency 6 --page-concurrency 16 --max-pages 1200 --max-discovered 5000 --per-host-delay 0.03
    """
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
        progress_tracker = CrawlProgressTracker(console=console, single_terminal=single_terminal)
        try:
            with progress_tracker.live():
                summary = await pipeline.run(
                    language_name=language,
                    force_refresh=force_refresh,
                    dry_run=dry_run,
                    validate_only=validate_only,
                    language_concurrency=language_concurrency,
                    crawl_mode=mode,
                    split_mode=splitmode,
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


@app.command(help="Validate existing compiled Markdown outputs without crawling.")
def validate(language: str | None = typer.Option(None, "--language", "-l")) -> None:
    """Validate generated Markdown files and report quality scores.

    Use this after a crawl to check whether outputs exist and how complete they
    appear to be.
    """
    run(language=language, validate_only=True)


@app.command(help="Create the required project directories under the configured root.")
def init() -> None:
    """Initialize output, cache, logs, state, and temporary directories."""
    config = load_config()
    config.paths.ensure()
    console.print(f"Initialized directories under [bold]{config.paths.root}[/bold]")