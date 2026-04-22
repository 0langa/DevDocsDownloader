from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .config import load_config
from .models import CrawlMode
from .pipeline import DocumentationPipeline
from .progress import CrawlProgressTracker


app = typer.Typer(
    help=(
        "Ingest official programming-language documentation into normalized Markdown.\n\n"
        "Run [bold]without arguments[/bold] to launch the interactive setup wizard.\n"
        "Use the [bold]run[/bold] sub-command for scripted or automated invocations.\n\n"
        "Examples:\n"
        "  python DevDocsDownloader.py\n"
        "  python DevDocsDownloader.py run --language python --mode important\n"
        "  python DevDocsDownloader.py validate --language rust\n"
        "  python DevDocsDownloader.py init"
    ),
    invoke_without_command=True,
    no_args_is_help=False,
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


def _execute_run(
    *,
    language: str | None,
    mode: CrawlMode,
    force_refresh: bool,
    resume: bool,
    dry_run: bool,
    validate_only: bool,
    verbosity: str,
    language_concurrency: int | None,
    page_concurrency: int | None,
    extraction_workers: int | None,
    max_pending_extractions: int | None,
    compile_streaming: bool | None,
    normalized_cache_format: str | None,
    extract_executor: str | None,
    extract_process_workers: int | None,
    adaptive_extraction_workers: bool | None,
    extract_target_cpu_percent: float | None,
    max_pages: int | None,
    max_discovered: int | None,
    per_host_delay: float | None,
    input_file: Path | None,
    output_dir: Path | None,
) -> None:
    config = load_config(input_file=input_file, output_dir=output_dir)
    config.planner.crawl_mode = mode
    if language_concurrency is not None:
        config.crawl.language_concurrency = max(1, language_concurrency)
    if page_concurrency is not None:
        config.crawl.max_concurrency = max(1, page_concurrency)
    if extraction_workers is not None:
        config.crawl.max_extraction_workers = max(1, extraction_workers)
    if max_pending_extractions is not None:
        config.crawl.max_pending_extractions_per_language = max(1, max_pending_extractions)
    if compile_streaming is not None:
        config.crawl.compile_streaming = bool(compile_streaming)
    if normalized_cache_format is not None:
        config.crawl.normalized_cache_format = normalized_cache_format
    if extract_executor is not None:
        config.crawl.extract_executor = extract_executor
    if extract_process_workers is not None:
        config.crawl.extract_process_workers = max(0, extract_process_workers)
    if adaptive_extraction_workers is not None:
        config.crawl.adaptive_extraction_workers = bool(adaptive_extraction_workers)
    if extract_target_cpu_percent is not None:
        config.crawl.extract_target_cpu_percent = max(10.0, min(98.0, extract_target_cpu_percent))
    if max_pages is not None:
        config.crawl.max_pages_per_language = max(1, max_pages)
    if max_discovered is not None:
        config.crawl.max_discovered_urls_per_language = max(1, max_discovered)
    if per_host_delay is not None:
        config.crawl.per_host_delay_seconds = max(0.0, per_host_delay)

    async def _runner() -> None:
        progress_tracker = CrawlProgressTracker(console=console, single_terminal=False)
        _setup_logging(config.paths.logs_dir / "run.log", verbosity=verbosity, progress_tracker=progress_tracker)
        pipeline = DocumentationPipeline(config)
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
        table.add_column("Quality")
        table.add_column("Output")
        table.add_column("Score")
        for report in summary.reports:
            table.add_row(
                report.language,
                str(report.pages_processed),
                str(report.validation.quality_score if report.validation else "N/A"),
                str(report.output_path or "N/A"),
                str(report.validation.score if report.validation else "N/A"),
            )
        console.print(table)

    asyncio.run(_runner())


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        _wizard()


def _wizard() -> None:
    console.print()
    console.print(Panel(
        "[bold cyan]Documentation Ingestion Wizard[/bold cyan]\n\n"
        "Press [bold]Enter[/bold] to accept the default shown in [dim][brackets][/dim].\n"
        "All settings are also available as flags on the [bold]run[/bold] sub-command for automation.",
        border_style="cyan",
        expand=False,
    ))
    console.print()

    lang_input = typer.prompt("Language to crawl (press Enter for all languages)", default="")
    language = lang_input.strip() or None

    while True:
        mode_input = typer.prompt("Crawl mode", default="important", prompt_suffix=" [important/full]: ", show_default=False)
        mode_str = mode_input.strip().lower()
        if mode_str in ("important", "full"):
            mode = CrawlMode(mode_str)
            break
        console.print("[red]Please type 'important' or 'full'.[/red]")

    page_concurrency: int = typer.prompt("Parallel pages per language", default=4, type=int)
    lang_concurrency: int = typer.prompt("Languages crawled in parallel", default=2, type=int)
    max_pages: int = typer.prompt("Max pages per language", default=1000, type=int)
    per_host_delay: float = typer.prompt("Delay between requests to the same host (seconds)", default=0.15, type=float)
    force_refresh: bool = typer.confirm("Discard existing crawl state and re-crawl from scratch?", default=False)

    console.print()
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="bold white")
    grid.add_column(style="cyan")
    grid.add_row("Language:", language or "[all]")
    grid.add_row("Mode:", mode.value)
    grid.add_row("Page concurrency:", str(page_concurrency))
    grid.add_row("Language concurrency:", str(lang_concurrency))
    grid.add_row("Max pages:", f"{max_pages:,}")
    grid.add_row("Request delay:", f"{per_host_delay}s")
    grid.add_row("Force refresh:", "yes" if force_refresh else "no")
    console.print(Panel(grid, title="Crawl configuration", border_style="green", expand=False))
    console.print()

    if not typer.confirm("Start crawl?", default=True):
        console.print("Aborted.")
        raise typer.Exit()

    _execute_run(
        language=language,
        mode=mode,
        force_refresh=force_refresh,
        resume=True,
        dry_run=False,
        validate_only=False,
        verbosity="info",
        language_concurrency=lang_concurrency,
        page_concurrency=page_concurrency,
        extraction_workers=None,
        max_pending_extractions=None,
        compile_streaming=None,
        normalized_cache_format=None,
        extract_executor=None,
        extract_process_workers=None,
        adaptive_extraction_workers=None,
        extract_target_cpu_percent=None,
        max_pages=max_pages,
        max_discovered=None,
        per_host_delay=per_host_delay,
        input_file=None,
        output_dir=None,
    )


@app.command(help="Crawl documentation sources, extract content, and compile Markdown outputs.")
def run(
    language: str | None = typer.Option(None, "--language", "-l", help="Single language by name or slug."),
    mode: CrawlMode = typer.Option("full", "--mode", help="'important' for core docs only, 'full' for broad coverage."),
    force_refresh: bool = typer.Option(False, "--force-refresh", help="Ignore saved state for selected languages."),
    resume: bool = typer.Option(True, "--resume/--no-resume", help="Resume from saved crawl state when available."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show planning only, do not crawl."),
    validate_only: bool = typer.Option(False, "--validate-only", help="Validate existing outputs without crawling."),
    silent: bool = typer.Option(False, "--silent", help="Only show errors in terminal output."),
    info: bool = typer.Option(False, "--info", help="Show informational runtime logs."),
    debug: bool = typer.Option(False, "--debug", help="Show debug-level runtime logs."),
    verbose: bool = typer.Option(False, "--verbose", help="Show the most detailed logs, including library output."),
    language_concurrency: int | None = typer.Option(None, "--language-concurrency", help="Languages to process in parallel."),
    page_concurrency: int | None = typer.Option(None, "--page-concurrency", help="Pages to process concurrently per language."),
    extraction_workers: int | None = typer.Option(None, "--extraction-workers", help="Concurrent HTML/document transformation workers per language."),
    max_pending_extractions: int | None = typer.Option(None, "--max-pending-extractions", help="Backpressure cap for queued extraction jobs per language."),
    compile_streaming: bool | None = typer.Option(None, "--compile-streaming/--no-compile-streaming", help="Stream compile input from cache to reduce peak memory."),
    normalized_cache_format: str | None = typer.Option(None, "--normalized-cache-format", help="Normalized cache format: json, json_compact, or msgpack."),
    extract_executor: str | None = typer.Option(None, "--extract-executor", help="Extraction executor mode: thread, process, or auto."),
    extract_process_workers: int | None = typer.Option(None, "--extract-process-workers", help="Process worker count when --extract-executor=process."),
    adaptive_extraction_workers: bool | None = typer.Option(None, "--adaptive-extraction-workers/--no-adaptive-extraction-workers", help="Enable adaptive extraction worker scaling."),
    extract_target_cpu_percent: float | None = typer.Option(None, "--extract-target-cpu-percent", help="Target CPU percentage for adaptive extraction scaling."),
    max_pages: int | None = typer.Option(None, "--max-pages", help="Hard cap on processed pages per language."),
    max_discovered: int | None = typer.Option(None, "--max-discovered", help="Hard cap on discovered URLs per language."),
    per_host_delay: float | None = typer.Option(None, "--per-host-delay", help="Delay between requests to the same host (seconds)."),
    input_file: Path | None = typer.Option(None, "--input-file", help="Alternate language input file."),
    output_dir: Path | None = typer.Option(None, "--output-dir", help="Alternate output directory root."),
) -> None:
    """Run the documentation ingestion pipeline.

    Output locations:
    - Markdown manuals: output/markdown/
    - Reports:          output/reports/
    - Logs:             logs/run.log

    Examples:
            python DevDocsDownloader.py run --language python
            python DevDocsDownloader.py run --mode important --language-concurrency 3 --page-concurrency 8
            python DevDocsDownloader.py run --mode full --page-concurrency 16 --max-pages 1200 --per-host-delay 0.05
    """
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

    _execute_run(
        language=language,
        mode=mode,
        force_refresh=force_refresh,
        resume=resume,
        dry_run=dry_run,
        validate_only=validate_only,
        verbosity=verbosity,
        language_concurrency=language_concurrency,
        page_concurrency=page_concurrency,
        extraction_workers=extraction_workers,
        max_pending_extractions=max_pending_extractions,
        compile_streaming=compile_streaming,
        normalized_cache_format=normalized_cache_format,
        extract_executor=extract_executor,
        extract_process_workers=extract_process_workers,
        adaptive_extraction_workers=adaptive_extraction_workers,
        extract_target_cpu_percent=extract_target_cpu_percent,
        max_pages=max_pages,
        max_discovered=max_discovered,
        per_host_delay=per_host_delay,
        input_file=input_file,
        output_dir=output_dir,
    )


@app.command(help="Validate existing compiled Markdown outputs without crawling.")
def validate(language: str | None = typer.Option(None, "--language", "-l", help="Single language by name or slug.")) -> None:
    """Validate generated Markdown files and report quality scores."""
    config = load_config()

    async def _runner() -> None:
        progress_tracker = CrawlProgressTracker(console=console, single_terminal=False)
        _setup_logging(config.paths.logs_dir / "run.log", verbosity="info", progress_tracker=progress_tracker)
        pipeline = DocumentationPipeline(config)
        try:
            with progress_tracker.live():
                summary = await pipeline.run(language_name=language, validate_only=True, progress_tracker=progress_tracker)
        finally:
            await pipeline.close()

        table = Table(title="Validation Summary")
        table.add_column("Language")
        table.add_column("Score")
        table.add_column("Issues")
        table.add_column("Output")
        for report in summary.reports:
            score = str(report.validation.score if report.validation else "N/A")
            issues = str(len(report.validation.issues) if report.validation else "N/A")
            table.add_row(report.language, score, issues, str(report.output_path or "N/A"))
        console.print(table)

    asyncio.run(_runner())


@app.command(help="Create the required project directories under the configured root.")
def init() -> None:
    """Initialize output, cache, logs, state, and temporary directories."""
    config = load_config()
    config.paths.ensure()
    console.print(f"Initialized directories under [bold]{config.paths.root}[/bold]")
