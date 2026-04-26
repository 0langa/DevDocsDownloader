from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .config import load_config
from .models import BulkConcurrencyPolicy, CacheFreshnessPolicy, CrawlMode
from .progress import CrawlProgressTracker
from .runtime import SourceRuntime
from .services import BulkRunRequest, DocumentationService, RunLanguageRequest
from .sources.presets import PRESETS
from .sources.registry import SourceRegistry

app = typer.Typer(
    help=(
        "Download official programming-language documentation from aggregators "
        "(DevDocs, MDN, Dash/Kapeli) and compile it into clean, AI-friendly Markdown.\n\n"
        "Run [bold]without arguments[/bold] to launch the interactive wizard.\n"
        "Use the [bold]run[/bold] sub-command for scripted or automated invocations."
    ),
    invoke_without_command=True,
    no_args_is_help=False,
    rich_markup_mode="rich",
)
console = Console()


def _setup_logging(log_path: Path, *, verbosity: str) -> None:
    level_map = {
        "silent": logging.ERROR,
        "info": logging.INFO,
        "debug": logging.DEBUG,
        "verbose": logging.DEBUG,
    }
    level = level_map.get(verbosity, logging.INFO)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8")],
        force=True,
    )
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING if verbosity != "verbose" else logging.INFO)


def _execute_run(
    *,
    language: str,
    mode: CrawlMode,
    source: str | None,
    force_refresh: bool,
    validate_only: bool,
    verbosity: str,
    output_dir: Path | None,
    include_topics: list[str] | None = None,
    exclude_topics: list[str] | None = None,
    document_frontmatter: bool = False,
    chunks: bool = False,
    chunk_max_chars: int = 8_000,
    chunk_overlap_chars: int = 400,
    chunk_strategy: str = "chars",
    chunk_max_tokens: int = 1_000,
    chunk_overlap_tokens: int = 100,
    cache_policy: CacheFreshnessPolicy = "use-if-present",
    cache_ttl_hours: int | None = None,
) -> None:
    if chunk_strategy not in {"chars", "tokens"}:
        console.print("[red]--chunk-strategy must be 'chars' or 'tokens'.[/red]")
        raise typer.Exit(code=1)
    config = load_config(output_dir=output_dir)
    _setup_logging(config.paths.logs_dir / "run.log", verbosity=verbosity)

    async def _runner() -> None:
        tracker = CrawlProgressTracker(console=console)
        service = DocumentationService(config)
        with tracker.live():
            summary = await service.run_language(
                RunLanguageRequest(
                    language=language,
                    mode=mode,
                    source=source,
                    force_refresh=force_refresh,
                    validate_only=validate_only,
                    include_topics=include_topics,
                    exclude_topics=exclude_topics,
                    emit_document_frontmatter=document_frontmatter,
                    emit_chunks=chunks,
                    chunk_max_chars=chunk_max_chars,
                    chunk_overlap_chars=chunk_overlap_chars,
                    chunk_strategy=chunk_strategy,  # type: ignore[arg-type]
                    chunk_max_tokens=chunk_max_tokens,
                    chunk_overlap_tokens=chunk_overlap_tokens,
                    cache_policy=cache_policy,
                    cache_ttl_hours=cache_ttl_hours,
                ),
                progress_tracker=tracker,
            )

        table = Table(title="Documentation Download Summary")
        table.add_column("Language")
        table.add_column("Source")
        table.add_column("Documents", justify="right")
        table.add_column("Output")
        table.add_column("Score", justify="right")
        for report in summary.reports:
            score = f"{report.validation.score:.2f}" if report.validation else "N/A"
            table.add_row(
                report.language,
                f"{report.source} ({report.source_slug})",
                f"{report.total_documents:,}",
                str(report.output_path or "N/A"),
                score,
            )
        console.print(table)

        for report in summary.reports:
            if report.failures:
                console.print(f"[red]Failures for {report.language}:[/red]")
                for failure in report.failures:
                    console.print(f"  - {failure}")

    asyncio.run(_runner())


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        _wizard()


def _wizard() -> None:
    console.print()
    console.print(
        Panel(
            "[bold cyan]Documentation Download Wizard[/bold cyan]\n\n"
            "Pulls official documentation from DevDocs, MDN, or Dash/Kapeli and\n"
            "compiles it into clean Markdown in [bold]output/markdown/<language>/[/bold].\n\n"
            "Tip: run [bold]list-languages[/bold] to see every supported language.",
            border_style="cyan",
            expand=False,
        )
    )
    console.print()

    language = typer.prompt("Language to download").strip()
    if not language:
        console.print("[red]A language is required.[/red]")
        raise typer.Exit(code=1)

    while True:
        mode_input = (
            typer.prompt("Mode", default="important", prompt_suffix=" [important/full]: ", show_default=False)
            .strip()
            .lower()
        )
        if mode_input in ("important", "full"):
            mode: CrawlMode = mode_input  # type: ignore[assignment]
            break
        console.print("[red]Type 'important' or 'full'.[/red]")

    source = typer.prompt("Preferred source (leave blank for auto)", default="").strip() or None
    force_refresh = typer.confirm("Force refresh source catalogs?", default=False)

    if not typer.confirm(f"Download {language} ({mode})?", default=True):
        console.print("Aborted.")
        raise typer.Exit()

    _execute_run(
        language=language,
        mode=mode,
        source=source,
        force_refresh=force_refresh,
        validate_only=False,
        verbosity="info",
        output_dir=None,
    )


@app.command(help="Download documentation for a single language.")
def run(
    language: str = typer.Argument(..., help="Language name (e.g. 'python', 'rust', 'javascript')."),
    mode: CrawlMode = typer.Option("important", "--mode", help="'important' for core topics, 'full' for everything."),
    source: str | None = typer.Option(None, "--source", help="Force a specific source: devdocs, mdn, or dash."),
    force_refresh: bool = typer.Option(False, "--force-refresh", help="Re-download source catalogs before resolving."),
    validate_only: bool = typer.Option(
        False, "--validate-only", help="Validate an existing output without downloading."
    ),
    include_topic: list[str] | None = typer.Option(
        None,
        "--include-topic",
        help="Only include documents whose normalized topic matches this value. Repeat for multiple topics.",
    ),
    exclude_topic: list[str] | None = typer.Option(
        None,
        "--exclude-topic",
        help="Exclude documents whose normalized topic matches this value. Repeat for multiple topics.",
    ),
    silent: bool = typer.Option(False, "--silent"),
    debug: bool = typer.Option(False, "--debug"),
    verbose: bool = typer.Option(False, "--verbose"),
    output_dir: Path | None = typer.Option(None, "--output-dir", help="Alternate output directory root."),
    document_frontmatter: bool = typer.Option(
        False,
        "--document-frontmatter/--no-document-frontmatter",
        help="Emit YAML frontmatter in each per-document Markdown file.",
    ),
    chunks: bool = typer.Option(False, "--chunks", help="Emit retrieval chunks and chunks/manifest.jsonl."),
    chunk_max_chars: int = typer.Option(8000, "--chunk-max-chars", min=500, help="Maximum characters per chunk."),
    chunk_overlap_chars: int = typer.Option(400, "--chunk-overlap-chars", min=0, help="Characters of chunk overlap."),
    chunk_strategy: str = typer.Option("chars", "--chunk-strategy", help="Chunk strategy: chars or tokens."),
    chunk_max_tokens: int = typer.Option(1000, "--chunk-max-tokens", min=100, help="Maximum tokens per token chunk."),
    chunk_overlap_tokens: int = typer.Option(100, "--chunk-overlap-tokens", min=0, help="Token overlap for chunks."),
    cache_policy: CacheFreshnessPolicy = typer.Option(
        "use-if-present",
        "--cache-policy",
        help="Cache policy: use-if-present, ttl, always-refresh, or validate-if-possible.",
    ),
    cache_ttl_hours: int | None = typer.Option(
        None, "--cache-ttl-hours", min=0, help="TTL hours for --cache-policy ttl."
    ),
) -> None:
    """Download and compile documentation for a language.

    Examples:
      python DevDocsDownloader.py run python
      python DevDocsDownloader.py run javascript --source mdn --mode full
      python DevDocsDownloader.py run swift --source dash
    """
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
        source=source,
        force_refresh=force_refresh,
        validate_only=validate_only,
        verbosity=verbosity,
        output_dir=output_dir,
        include_topics=include_topic,
        exclude_topics=exclude_topic,
        document_frontmatter=document_frontmatter,
        chunks=chunks,
        chunk_max_chars=chunk_max_chars,
        chunk_overlap_chars=chunk_overlap_chars,
        chunk_strategy=chunk_strategy,
        chunk_max_tokens=chunk_max_tokens,
        chunk_overlap_tokens=chunk_overlap_tokens,
        cache_policy=cache_policy,
        cache_ttl_hours=cache_ttl_hours,
    )


def _estimate_size(catalogs: list) -> tuple[int, int]:
    """Return (total_bytes_estimate, count)."""
    total = 0
    count = 0
    for source, catalog in catalogs:
        count += 1
        if catalog.size_hint:
            total += catalog.size_hint
        elif source.name == "mdn":
            total += 30_000_000
        else:
            total += 80_000_000
    return total, count


def _format_bytes(n: int) -> str:
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} PB"


@app.command(help="Download documentation in bulk: a preset or every available language.")
def bulk(
    target: str = typer.Argument(..., help="Preset name (e.g. 'webapp', 'backend') or 'all' for everything."),
    mode: CrawlMode = typer.Option("important", "--mode", help="'important' for core topics, 'full' for everything."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt for --bulk all."),
    force_refresh: bool = typer.Option(False, "--force-refresh", help="Re-download source catalogs first."),
    language_concurrency: int = typer.Option(
        3, "--language-concurrency", min=1, help="Languages to process in parallel during bulk runs."
    ),
    concurrency_policy: BulkConcurrencyPolicy = typer.Option(
        "static",
        "--concurrency-policy",
        help="Bulk concurrency policy: static or adaptive.",
    ),
    adaptive_min_concurrency: int = typer.Option(
        1,
        "--adaptive-min-concurrency",
        min=1,
        help="Minimum adaptive language concurrency.",
    ),
    adaptive_max_concurrency: int = typer.Option(
        6,
        "--adaptive-max-concurrency",
        min=1,
        help="Maximum adaptive language concurrency.",
    ),
    include_topic: list[str] | None = typer.Option(
        None,
        "--include-topic",
        help="Only include documents whose normalized topic matches this value. Repeat for multiple topics.",
    ),
    exclude_topic: list[str] | None = typer.Option(
        None,
        "--exclude-topic",
        help="Exclude documents whose normalized topic matches this value. Repeat for multiple topics.",
    ),
    silent: bool = typer.Option(False, "--silent"),
    debug: bool = typer.Option(False, "--debug"),
    verbose: bool = typer.Option(False, "--verbose"),
    document_frontmatter: bool = typer.Option(
        False,
        "--document-frontmatter/--no-document-frontmatter",
        help="Emit YAML frontmatter in each per-document Markdown file.",
    ),
    chunks: bool = typer.Option(False, "--chunks", help="Emit retrieval chunks and chunks/manifest.jsonl."),
    chunk_max_chars: int = typer.Option(8000, "--chunk-max-chars", min=500, help="Maximum characters per chunk."),
    chunk_overlap_chars: int = typer.Option(400, "--chunk-overlap-chars", min=0, help="Characters of chunk overlap."),
    chunk_strategy: str = typer.Option("chars", "--chunk-strategy", help="Chunk strategy: chars or tokens."),
    chunk_max_tokens: int = typer.Option(1000, "--chunk-max-tokens", min=100, help="Maximum tokens per token chunk."),
    chunk_overlap_tokens: int = typer.Option(100, "--chunk-overlap-tokens", min=0, help="Token overlap for chunks."),
    cache_policy: CacheFreshnessPolicy = typer.Option(
        "use-if-present",
        "--cache-policy",
        help="Cache policy: use-if-present, ttl, always-refresh, or validate-if-possible.",
    ),
    cache_ttl_hours: int | None = typer.Option(
        None, "--cache-ttl-hours", min=0, help="TTL hours for --cache-policy ttl."
    ),
) -> None:
    """Run downloads for a predefined set of languages or for everything available.

    Examples:
      python DevDocsDownloader.py bulk webapp
      python DevDocsDownloader.py bulk python-stack --mode full
      python DevDocsDownloader.py bulk all --mode important
    """
    verbosity = "info"
    if silent:
        verbosity = "silent"
    elif debug:
        verbosity = "debug"
    elif verbose:
        verbosity = "verbose"

    if chunk_strategy not in {"chars", "tokens"}:
        console.print("[red]--chunk-strategy must be 'chars' or 'tokens'.[/red]")
        raise typer.Exit(code=1)

    target_key = target.strip().lower()
    config = load_config()
    config.language_concurrency = max(1, language_concurrency)
    config.bulk_concurrency_policy = concurrency_policy
    config.adaptive_min_concurrency = max(1, adaptive_min_concurrency)
    config.adaptive_max_concurrency = max(config.adaptive_min_concurrency, adaptive_max_concurrency)
    _setup_logging(config.paths.logs_dir / "run.log", verbosity=verbosity)

    async def _runner() -> None:
        registry = SourceRegistry(
            cache_dir=config.paths.cache_dir,
            runtime=SourceRuntime(cache_policy=cache_policy, cache_ttl_hours=cache_ttl_hours),
        )

        if target_key == "all":
            try:
                resolved = await registry.all_languages(force_refresh=force_refresh)
            finally:
                await registry.runtime.close()
            language_names = [catalog.display_name for _source, catalog in resolved]
            size_bytes, count = _estimate_size(resolved)
            scale = 1.0 if mode == "full" else 0.25
            est = int(size_bytes * scale)
            console.print(
                Panel(
                    f"[bold]--bulk all[/bold]\n"
                    f"Languages to download: [bold]{count}[/bold]\n"
                    f"Mode: [bold]{mode}[/bold]\n"
                    f"Estimated download (compressed): [bold]{_format_bytes(est)}[/bold]\n"
                    f"Output tree will live under: [bold]{config.paths.markdown_dir}[/bold]",
                    title="Bulk download warning",
                    border_style="yellow",
                )
            )
            if not yes and not typer.confirm("Proceed?", default=False):
                console.print("Aborted.")
                return
        elif target_key in PRESETS:
            language_names = PRESETS[target_key]
            console.print(
                Panel(
                    f"[bold]Preset '{target_key}'[/bold]\n"
                    f"Languages: {', '.join(language_names)}\n"
                    f"Mode: [bold]{mode}[/bold]",
                    title="Bulk preset",
                    border_style="cyan",
                )
            )
        else:
            available = ", ".join(sorted(PRESETS.keys()))
            console.print(f"[red]Unknown target '{target}'.[/red]")
            console.print(f"Available presets: {available}, or 'all'.")
            raise typer.Exit(code=1)

        tracker = CrawlProgressTracker(console=console)
        service = DocumentationService(config)
        with tracker.live():
            summary = await service.run_bulk(
                BulkRunRequest(
                    languages=language_names,
                    mode=mode,
                    force_refresh=force_refresh,
                    language_concurrency=language_concurrency,
                    concurrency_policy=concurrency_policy,
                    adaptive_min_concurrency=adaptive_min_concurrency,
                    adaptive_max_concurrency=adaptive_max_concurrency,
                    include_topics=include_topic,
                    exclude_topics=exclude_topic,
                    emit_document_frontmatter=document_frontmatter,
                    emit_chunks=chunks,
                    chunk_max_chars=chunk_max_chars,
                    chunk_overlap_chars=chunk_overlap_chars,
                    chunk_strategy=chunk_strategy,  # type: ignore[arg-type]
                    chunk_max_tokens=chunk_max_tokens,
                    chunk_overlap_tokens=chunk_overlap_tokens,
                    cache_policy=cache_policy,
                    cache_ttl_hours=cache_ttl_hours,
                ),
                progress_tracker=tracker,
            )

        table = Table(title="Bulk Download Summary")
        table.add_column("Language")
        table.add_column("Source")
        table.add_column("Documents", justify="right")
        table.add_column("Output")
        for report in summary.reports:
            output = str(report.output_path) if report.output_path else "N/A"
            table.add_row(
                report.language,
                f"{report.source} ({report.source_slug})" if report.source != "none" else "—",
                f"{report.total_documents:,}",
                output,
            )
        console.print(table)

        missing = [r for r in summary.reports if r.failures]
        if missing:
            console.print(f"[yellow]{len(missing)} language(s) had issues:[/yellow]")
            for report in missing:
                for failure in report.failures:
                    console.print(f"  - {report.language}: {failure}")

    asyncio.run(_runner())


@app.command("list-presets", help="List predefined bulk presets and the languages they contain.")
def list_presets() -> None:
    service = DocumentationService(load_config())
    for name, langs in service.list_presets().items():
        console.print(f"[bold cyan]{name}[/bold cyan]: {', '.join(langs)}")


@app.command("audit-presets", help="Check whether preset languages resolve against configured sources.")
def audit_presets(
    preset: str | None = typer.Argument(None, help="Preset name to audit. Omit to audit every preset."),
    source: str | None = typer.Option(None, "--source", help="Force resolution against a specific source."),
    force_refresh: bool = typer.Option(False, "--force-refresh", help="Re-fetch catalogs before auditing."),
) -> None:
    config = load_config()
    preset_names = [preset.strip().lower()] if preset else sorted(PRESETS.keys())
    unknown = [name for name in preset_names if name not in PRESETS]
    if unknown:
        console.print(f"[red]Unknown preset '{unknown[0]}'.[/red]")
        console.print(f"Available presets: {', '.join(sorted(PRESETS.keys()))}")
        raise typer.Exit(code=1)

    async def _runner() -> None:
        service = DocumentationService(config)
        table = Table(title="Preset Coverage Audit")
        table.add_column("Preset", style="bold cyan")
        table.add_column("Language")
        table.add_column("Status")
        table.add_column("Source")
        table.add_column("Slug")

        resolved_count = 0
        missing_count = 0
        for result in await service.audit_presets(presets=preset_names, source=source, force_refresh=force_refresh):
            if result.resolved:
                resolved_count += 1
                table.add_row(result.preset, result.language, "[green]resolved[/green]", result.source, result.slug)
            else:
                missing_count += 1
                table.add_row(result.preset, result.language, "[red]missing[/red]", "", "")

        console.print(table)
        console.print(f"[dim]Resolved: {resolved_count}  Missing: {missing_count}[/dim]")
        if missing_count:
            raise typer.Exit(code=2)

    asyncio.run(_runner())


@app.command("list-languages", help="List every language available across all configured sources.")
def list_languages(
    source: str | None = typer.Option(None, "--source", help="Filter by a single source."),
    force_refresh: bool = typer.Option(False, "--force-refresh", help="Re-fetch catalogs before listing."),
) -> None:
    config = load_config()

    async def _runner() -> None:
        service = DocumentationService(config)

        table = Table(title="Supported languages")
        table.add_column("Language", style="bold cyan")
        table.add_column("Source")
        table.add_column("Slug")
        table.add_column("Version")

        rows = await service.list_languages(source=source, force_refresh=force_refresh)
        for row in rows:
            table.add_row(row.language, row.source, row.slug, row.version)
        console.print(table)
        console.print(f"[dim]Total: {len(rows)} entries[/dim]")

    asyncio.run(_runner())


@app.command("refresh-catalogs", help="Force-refresh all source catalogs.")
def refresh_catalogs() -> None:
    config = load_config()

    async def _runner() -> None:
        service = DocumentationService(config)
        catalogs = await service.refresh_catalogs()
        for name, count in catalogs.items():
            console.print(f"[bold]{name}[/bold]: {count} entries")

    asyncio.run(_runner())


@app.command(help="Validate an existing compiled output without downloading.")
def validate(
    language: str = typer.Argument(..., help="Language name."),
    source: str | None = typer.Option(
        None, "--source", help="Resolve against a specific source only if local metadata is unavailable."
    ),
    output_dir: Path | None = typer.Option(None, "--output-dir", help="Alternate output directory root."),
) -> None:
    _execute_run(
        language=language,
        mode="important",
        source=source,
        force_refresh=False,
        validate_only=True,
        verbosity="info",
        output_dir=output_dir,
        include_topics=None,
        exclude_topics=None,
    )


@app.command(help="Launch the optional local NiceGUI operator interface.")
def gui(
    host: str = typer.Option("127.0.0.1", "--host", help="Host interface for the local GUI server."),
    port: int = typer.Option(8080, "--port", min=1, max=65535, help="Port for the local GUI server."),
    reload: bool = typer.Option(False, "--reload", help="Enable NiceGUI reload while developing the GUI."),
    native: bool = typer.Option(False, "--native", help="Launch NiceGUI in native window mode when available."),
    output_dir: Path | None = typer.Option(None, "--output-dir", help="Alternate output directory root."),
) -> None:
    config = load_config(output_dir=output_dir)
    try:
        from .gui.app import run_gui

        run_gui(config, host=host, port=port, reload=reload, native=native)
    except RuntimeError as exc:
        console.print(str(exc), style="red", markup=False)
        raise typer.Exit(code=1) from exc


@app.command(help="Create the required project directories.")
def init() -> None:
    config = load_config()
    config.paths.ensure()
    console.print(f"Initialized directories under [bold]{config.paths.root}[/bold]")
