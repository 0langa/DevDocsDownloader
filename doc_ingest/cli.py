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
        "  python documentation_downloader.py run --mode full --language-concurrency 6 --page-concurrency 16\n"
        "  python documentation_downloader.py validate --language rust"
    ),
    no_args_is_help=True,
    rich_markup_mode="rich",
)
console = Console()


class _ProgressConsoleHandler(logging.Handler):
    def __init__(self, tracker_getter, level: int = logging.NOTSET) -> None:
        super().__init__(level)
        self._tracker_getter = tracker_getter

    def emit(self, record: logging.LogRecord) -> None:
        try:
            tracker = self._tracker_getter()
            if tracker is None:
                return
            message = self.format(record)
            tracker.emit_log(record.levelname.lower(), message)
        except Exception:
            self.handleError(record)


def _setup_logging(log_path: Path, *, verbosity: str, progress_tracker: CrawlProgressTracker | None = None) -> None:
    level_map = {
        "silent": logging.ERROR,
        "info": logging.INFO,
        "debug": logging.DEBUG,
        "verbose": logging.DEBUG,
    }
    root_level = level_map.get(verbosity, logging.INFO)
    logging.basicConfig(
        level=root_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8")],
        force=True,
    )
    package_noise_level = logging.INFO if verbosity == "verbose" else logging.WARNING
    logging.getLogger("httpx").setLevel(package_noise_level)
    logging.getLogger("httpcore").setLevel(package_noise_level)
    logging.getLogger("playwright").setLevel(package_noise_level)

    if progress_tracker is not None and verbosity != "silent":
        console_handler = _ProgressConsoleHandler(lambda: progress_tracker, level=root_level)
        console_handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
        logging.getLogger().addHandler(console_handler)


@app.command(help="Crawl documentation sources, extract content, and compile Markdown outputs.")
def run(
    language: str | None = typer.Option(None, "--language", "-l", help="Run a single language by name or slug."),
    mode: CrawlMode = typer.Option("full", "--mode", help="Choose 'important' for core docs only or 'full' for broad coverage."),
    force_refresh: bool = typer.Option(False, "--force-refresh", help="Ignore saved state for selected languages."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show planning only."),
    validate_only: bool = typer.Option(False, "--validate-only", help="Validate existing outputs only."),
    single_terminal: bool = typer.Option(False, "--single-terminal", help="Compatibility flag currently disabled; normal console UI is always used."),
    silent: bool = typer.Option(False, "--silent", help="Only show errors in terminal output."),
    info: bool = typer.Option(False, "--info", help="Show informational runtime logs in terminal output."),
    debug: bool = typer.Option(False, "--debug", help="Show debug-level runtime logs in terminal output."),
    verbose: bool = typer.Option(False, "--verbose", help="Show the most chatty runtime logs, including lower-level library output."),
    splitmode: bool = typer.Option(False, "--splitmode", help="First crawl only for link discovery, then process the discovered URLs in a second phase."),
    smart: bool = typer.Option(False, "--smart", help="Compatibility flag currently disabled; static crawl settings are used."),
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
    - Standard interactive mode: python documentation_downloader.py run --mode full
    - Fast VM run: python documentation_downloader.py run --mode full --language-concurrency 6 --page-concurrency 16 --max-pages 1200 --max-discovered 5000 --per-host-delay 0.03
    """
    config = load_config()
    selected_levels = sum(1 for flag in [silent, info, debug, verbose] if flag)
    if selected_levels > 1:
        raise typer.BadParameter("Use only one of --silent, --info, --debug, or --verbose.")
    verbosity = "info"
    if silent:
        verbosity = "silent"
    elif debug:
        verbosity = "debug"
    elif verbose:
        verbosity = "verbose"
    elif info:
        verbosity = "info"

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
    config.crawl.smart_mode = False

    async def _runner() -> None:
        pipeline = DocumentationPipeline(config)
        progress_tracker = CrawlProgressTracker(console=console, single_terminal=False)
        _setup_logging(config.paths.logs_dir / "run.log", verbosity=verbosity, progress_tracker=progress_tracker)
        if single_terminal:
            logging.getLogger("doc_ingest").warning("--single-terminal is currently disabled; using normal console UI.")
        if smart:
            logging.getLogger("doc_ingest").warning("--smart is currently disabled; using static crawl settings.")
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