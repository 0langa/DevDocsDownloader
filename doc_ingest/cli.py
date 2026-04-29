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

APP_HELP = """
Download official programming-language documentation from DevDocs, MDN, Dash/Kapeli, and installed source plugins,
then compile it into normalized Markdown manuals.

Typical workflows:
  python DevDocsDownloader.py run python
  python DevDocsDownloader.py run javascript --source mdn --mode full --chunks
  python DevDocsDownloader.py bulk webapp --language-concurrency 3
  python DevDocsDownloader.py validate python

Output defaults:
  Markdown bundles: output/markdown/<language>/
  Reports:          output/reports/run_summary.json and .md
  State:            state/<language>.json
  Checkpoints:      state/checkpoints/<language>.json while a failed or incomplete run can be resumed

Run without arguments to launch the interactive wizard. Use sub-command --help for the full option guide.
"""

RUN_HELP = """
Download, convert, validate, and report one language.

Resolution:
  By default the registry chooses the best matching source across DevDocs, MDN, Dash, and plugins.
  Use --source devdocs|mdn|dash to force a source. If a language is not found, suggestions are printed.

Modes:
  important  Builds the source-defined core subset where available.
  full       Builds the complete available inventory for the selected source/language.

Resume and safety:
  Runs write strict state/checkpoint files. If a previous run failed at a safe document boundary, the next matching
  run resumes automatically when checkpoint artifacts are still present. Use --force-refresh to refresh catalogs
  and cache entries before resolving/fetching.

Outputs:
  Always writes per-document Markdown, topic sections, an index, a consolidated manual, _meta.json, reports,
  validation diagnostics, and final state. Optional flags can add YAML frontmatter and retrieval chunks.

Examples:
  python DevDocsDownloader.py run python
  python DevDocsDownloader.py run javascript --source mdn --mode full
  python DevDocsDownloader.py run rust --include-topic std --chunks
  python DevDocsDownloader.py run python --validate-only
"""

BULK_HELP = """
Run multiple languages from a preset or from every configured source catalog.

Targets:
  Presets are named groups from doc_ingest/sources/presets.py, such as webapp, backend, python-stack, and systems.
  The special target all resolves every language advertised by every configured source.

Concurrency:
  --language-concurrency controls how many languages run at once. The default --concurrency-policy static keeps
  this fixed. The opt-in adaptive policy lowers concurrency when failures/retries/system pressure rise and slowly
  increases it after healthy windows. Output report order remains deterministic.

Safety:
  bulk all prints an estimate and asks for confirmation unless --yes is supplied. Each language keeps its own state,
  checkpoint, report records, and output bundle.

Examples:
  python DevDocsDownloader.py bulk webapp
  python DevDocsDownloader.py bulk backend --mode full --chunks
  python DevDocsDownloader.py bulk all --mode important --yes
  python DevDocsDownloader.py bulk webapp --concurrency-policy adaptive --adaptive-max-concurrency 4
"""

app = typer.Typer(
    help=APP_HELP,
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


@app.command(help=RUN_HELP)
def run(
    language: str = typer.Argument(
        ...,
        help=(
            "Language or documentation family to resolve, for example 'python', 'rust', 'javascript', 'html', "
            "'css', or a source-specific slug."
        ),
    ),
    mode: CrawlMode = typer.Option(
        "important",
        "--mode",
        help=(
            "Compilation scope. 'important' uses the source's curated/core subset when available; 'full' emits every "
            "document in the source inventory."
        ),
    ),
    source: str | None = typer.Option(
        None,
        "--source",
        help="Force a source instead of automatic resolution. Built-ins are devdocs, mdn, and dash.",
    ),
    force_refresh: bool = typer.Option(
        False,
        "--force-refresh",
        help="Ignore reusable source/cache freshness decisions and re-fetch catalogs or archives where supported.",
    ),
    validate_only: bool = typer.Option(
        False,
        "--validate-only",
        help="Validate the existing output bundle and reports for LANGUAGE without downloading or converting documents.",
    ),
    include_topic: list[str] | None = typer.Option(
        None,
        "--include-topic",
        help=(
            "Only emit documents whose normalized topic equals this value. Repeat the option for multiple allowed "
            "topics. Topic filters are applied after source inventory discovery."
        ),
    ),
    exclude_topic: list[str] | None = typer.Option(
        None,
        "--exclude-topic",
        help="Skip documents whose normalized topic equals this value. Repeat for multiple excluded topics.",
    ),
    silent: bool = typer.Option(False, "--silent", help="Suppress routine console output; errors are still shown."),
    debug: bool = typer.Option(False, "--debug", help="Write debug-level runtime logging to logs/run.log."),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        help="Write verbose debug logging, including HTTP client details where available, to logs/run.log.",
    ),
    output_dir: Path | None = typer.Option(
        None,
        "--output-dir",
        help="Use an alternate output root. Markdown, reports, state, cache, logs, and tmp dirs are rooted here.",
    ),
    document_frontmatter: bool = typer.Option(
        False,
        "--document-frontmatter/--no-document-frontmatter",
        help=(
            "Add machine-readable YAML frontmatter to each per-document Markdown file while keeping the existing "
            "human-readable metadata lines."
        ),
    ),
    chunks: bool = typer.Option(
        False,
        "--chunks",
        help="Emit retrieval-oriented chunk Markdown files plus chunks/manifest.jsonl for downstream RAG/indexing.",
    ),
    chunk_max_chars: int = typer.Option(
        8000,
        "--chunk-max-chars",
        min=500,
        help="Maximum characters per chunk when --chunks --chunk-strategy chars is used.",
    ),
    chunk_overlap_chars: int = typer.Option(
        400,
        "--chunk-overlap-chars",
        min=0,
        help="Character overlap between adjacent chunks for context preservation.",
    ),
    chunk_strategy: str = typer.Option(
        "chars",
        "--chunk-strategy",
        help=(
            "Chunk sizing strategy: 'chars' works with baseline dependencies; 'tokens' requires installing the "
            "tokenizer extra."
        ),
    ),
    chunk_max_tokens: int = typer.Option(
        1000,
        "--chunk-max-tokens",
        min=100,
        help="Maximum tokens per chunk when --chunks --chunk-strategy tokens is used.",
    ),
    chunk_overlap_tokens: int = typer.Option(
        100,
        "--chunk-overlap-tokens",
        min=0,
        help="Token overlap between adjacent token chunks.",
    ),
    cache_policy: CacheFreshnessPolicy = typer.Option(
        "use-if-present",
        "--cache-policy",
        help=(
            "Cache freshness policy: use-if-present preserves existing cache, ttl refreshes after --cache-ttl-hours, "
            "always-refresh refetches, validate-if-possible uses validators when the source exposes them."
        ),
    ),
    cache_ttl_hours: int | None = typer.Option(
        None,
        "--cache-ttl-hours",
        min=0,
        help="TTL in hours for --cache-policy ttl. If omitted, the configured default is used.",
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


@app.command(help=BULK_HELP)
def bulk(
    target: str = typer.Argument(
        ...,
        help="Preset name such as webapp/backend/python-stack/systems, or 'all' for every catalog language.",
    ),
    mode: CrawlMode = typer.Option(
        "important",
        "--mode",
        help="Compilation scope for every language: 'important' for curated/core documents, 'full' for all documents.",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt for the large 'all' target."),
    force_refresh: bool = typer.Option(
        False,
        "--force-refresh",
        help="Refresh source catalogs/caches before resolving the bulk target.",
    ),
    language_concurrency: int = typer.Option(
        3,
        "--language-concurrency",
        min=1,
        help="Number of languages to process at once. Static mode keeps this fixed.",
    ),
    concurrency_policy: BulkConcurrencyPolicy = typer.Option(
        "static",
        "--concurrency-policy",
        help="Bulk scheduling policy: static keeps concurrency fixed; adaptive changes it based on failures/retries.",
    ),
    adaptive_min_concurrency: int = typer.Option(
        1,
        "--adaptive-min-concurrency",
        min=1,
        help="Lowest language concurrency adaptive mode may use under pressure.",
    ),
    adaptive_max_concurrency: int = typer.Option(
        6,
        "--adaptive-max-concurrency",
        min=1,
        help="Highest language concurrency adaptive mode may use after healthy windows.",
    ),
    include_topic: list[str] | None = typer.Option(
        None,
        "--include-topic",
        help="Only emit matching normalized topics for every language. Repeat for multiple allowed topics.",
    ),
    exclude_topic: list[str] | None = typer.Option(
        None,
        "--exclude-topic",
        help="Skip matching normalized topics for every language. Repeat for multiple excluded topics.",
    ),
    silent: bool = typer.Option(False, "--silent", help="Suppress routine console output; errors are still shown."),
    debug: bool = typer.Option(False, "--debug", help="Write debug-level runtime logging to logs/run.log."),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        help="Write verbose debug logging, including HTTP client details where available, to logs/run.log.",
    ),
    document_frontmatter: bool = typer.Option(
        False,
        "--document-frontmatter/--no-document-frontmatter",
        help="Add YAML metadata frontmatter to each per-document Markdown file.",
    ),
    chunks: bool = typer.Option(False, "--chunks", help="Emit retrieval chunks and chunks/manifest.jsonl."),
    chunk_max_chars: int = typer.Option(
        8000, "--chunk-max-chars", min=500, help="Maximum characters per chunk for char-based chunking."
    ),
    chunk_overlap_chars: int = typer.Option(
        400, "--chunk-overlap-chars", min=0, help="Character overlap between adjacent chunks."
    ),
    chunk_strategy: str = typer.Option(
        "chars", "--chunk-strategy", help="Chunk strategy: chars or tokens. Token mode requires the tokenizer extra."
    ),
    chunk_max_tokens: int = typer.Option(
        1000, "--chunk-max-tokens", min=100, help="Maximum tokens per chunk for token-based chunking."
    ),
    chunk_overlap_tokens: int = typer.Option(
        100, "--chunk-overlap-tokens", min=0, help="Token overlap between adjacent token chunks."
    ),
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


@app.command(
    "list-presets",
    help=(
        "List predefined bulk presets and their languages. Presets are convenience groups for repeatable bulk runs; "
        "use audit-presets before a release or scheduled run to verify all names still resolve."
    ),
)
def list_presets() -> None:
    service = DocumentationService(load_config())
    for name, langs in service.list_presets().items():
        console.print(f"[bold cyan]{name}[/bold cyan]: {', '.join(langs)}")


@app.command(
    "audit-presets",
    help=(
        "Resolve one or all presets against the current source catalogs without compiling output. Exits with code 2 "
        "when any preset language is missing, which makes it suitable for CI or release checks."
    ),
)
def audit_presets(
    preset: str | None = typer.Argument(None, help="Preset name to audit. Omit to audit every preset."),
    source: str | None = typer.Option(
        None,
        "--source",
        help="Force resolution against one source instead of the normal source priority.",
    ),
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


@app.command(
    "list-languages",
    help=(
        "List every language advertised by configured sources and plugins. Use this before scripted runs to find "
        "display names, source names, source slugs, and versions."
    ),
)
def list_languages(
    source: str | None = typer.Option(
        None, "--source", help="Filter by a single source: devdocs, mdn, dash, or plugin name."
    ),
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


@app.command(
    "refresh-catalogs",
    help=(
        "Force-refresh all configured source catalogs and report structured per-source status. "
        "This is useful before audits, first-time desktop use, or scheduled bulk runs."
    ),
)
def refresh_catalogs() -> None:
    config = load_config()

    async def _runner() -> None:
        service = DocumentationService(config)
        catalogs = await service.refresh_catalogs()
        table = Table(title="Catalog refresh status")
        table.add_column("Source", style="bold cyan")
        table.add_column("Status")
        table.add_column("Entries", justify="right")
        table.add_column("Fallback")
        table.add_column("Notes")
        for row in catalogs:
            notes = "; ".join([*row.warnings[:1], *row.errors[:1]])
            table.add_row(
                row.source,
                row.status,
                str(row.entry_count),
                row.fallback_reason if row.fallback_used else "",
                notes,
            )
        console.print(table)

    asyncio.run(_runner())


@app.command(
    "audit-catalogs",
    help=(
        "Inspect the generated discovery manifests used for built-in source resolution. This shows live-discovery "
        "strategy, cache fallback state, and how many supported versus experimental entries each source exposed."
    ),
)
def audit_catalogs() -> None:
    config = load_config()
    service = DocumentationService(config)
    rows = service.audit_source_catalogs()
    table = Table(title="Source discovery audit")
    table.add_column("Source", style="bold cyan")
    table.add_column("Strategy")
    table.add_column("Fetched")
    table.add_column("Supported")
    table.add_column("Experimental")
    table.add_column("Ignored")
    table.add_column("Fallback")
    for row in rows:
        fallback = row.fallback_reason if row.fallback_used else ""
        table.add_row(
            row.source,
            row.discovery_strategy,
            row.fetched_at,
            str(row.supported_entries),
            str(row.experimental_entries),
            str(row.ignored_entries),
            fallback,
        )
    console.print(table)
    if not rows:
        console.print(
            "[dim]No cached discovery manifests found yet. Run list-languages or refresh-catalogs first.[/dim]"
        )


@app.command(
    help=(
        "Validate an existing output bundle without network fetches or compilation. Reads local _meta.json when "
        "available, writes the same report files as a normal run, and is safe for CI checks on generated artifacts."
    ),
)
def validate(
    language: str = typer.Argument(..., help="Language/output bundle to validate."),
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


@app.command(
    help=(
        "Create the runtime directory tree without downloading anything: output/markdown, output/reports, cache, "
        "logs, state/checkpoints, and tmp."
    ),
)
def init() -> None:
    config = load_config()
    config.paths.ensure()
    console.print(f"Initialized directories under [bold]{config.paths.root}[/bold]")
