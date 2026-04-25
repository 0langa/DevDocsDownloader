from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .config import load_config
from .models import CrawlMode
from .pipeline import DocumentationPipeline
from .progress import CrawlProgressTracker
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
) -> None:
    config = load_config(output_dir=output_dir)
    _setup_logging(config.paths.logs_dir / "run.log", verbosity=verbosity)

    async def _runner() -> None:
        tracker = CrawlProgressTracker(console=console)
        pipeline = DocumentationPipeline(config)
        try:
            with tracker.live():
                summary = await pipeline.run(
                    language_name=language,
                    mode=mode,
                    source_name=source,
                    force_refresh=force_refresh,
                    progress_tracker=tracker,
                    validate_only=validate_only,
                    include_topics=include_topics,
                    exclude_topics=exclude_topics,
                )
        finally:
            await pipeline.close()

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
    console.print(Panel(
        "[bold cyan]Documentation Download Wizard[/bold cyan]\n\n"
        "Pulls official documentation from DevDocs, MDN, or Dash/Kapeli and\n"
        "compiles it into clean Markdown in [bold]output/markdown/<language>/[/bold].\n\n"
        "Tip: run [bold]list-languages[/bold] to see every supported language.",
        border_style="cyan",
        expand=False,
    ))
    console.print()

    language = typer.prompt("Language to download").strip()
    if not language:
        console.print("[red]A language is required.[/red]")
        raise typer.Exit(code=1)

    while True:
        mode_input = typer.prompt("Mode", default="important", prompt_suffix=" [important/full]: ", show_default=False).strip().lower()
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
    source: Optional[str] = typer.Option(None, "--source", help="Force a specific source: devdocs, mdn, or dash."),
    force_refresh: bool = typer.Option(False, "--force-refresh", help="Re-download source catalogs before resolving."),
    validate_only: bool = typer.Option(False, "--validate-only", help="Validate an existing output without downloading."),
    include_topic: Optional[list[str]] = typer.Option(None, "--include-topic", help="Only include documents whose normalized topic matches this value. Repeat for multiple topics."),
    exclude_topic: Optional[list[str]] = typer.Option(None, "--exclude-topic", help="Exclude documents whose normalized topic matches this value. Repeat for multiple topics."),
    silent: bool = typer.Option(False, "--silent"),
    debug: bool = typer.Option(False, "--debug"),
    verbose: bool = typer.Option(False, "--verbose"),
    output_dir: Optional[Path] = typer.Option(None, "--output-dir", help="Alternate output directory root."),
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
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


@app.command(help="Download documentation in bulk: a preset or every available language.")
def bulk(
    target: str = typer.Argument(..., help="Preset name (e.g. 'webapp', 'backend') or 'all' for everything."),
    mode: CrawlMode = typer.Option("important", "--mode", help="'important' for core topics, 'full' for everything."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt for --bulk all."),
    force_refresh: bool = typer.Option(False, "--force-refresh", help="Re-download source catalogs first."),
    language_concurrency: int = typer.Option(3, "--language-concurrency", min=1, help="Languages to process in parallel during bulk runs."),
    include_topic: Optional[list[str]] = typer.Option(None, "--include-topic", help="Only include documents whose normalized topic matches this value. Repeat for multiple topics."),
    exclude_topic: Optional[list[str]] = typer.Option(None, "--exclude-topic", help="Exclude documents whose normalized topic matches this value. Repeat for multiple topics."),
    silent: bool = typer.Option(False, "--silent"),
    debug: bool = typer.Option(False, "--debug"),
    verbose: bool = typer.Option(False, "--verbose"),
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

    target_key = target.strip().lower()
    config = load_config()
    config.language_concurrency = max(1, language_concurrency)
    _setup_logging(config.paths.logs_dir / "run.log", verbosity=verbosity)

    async def _runner() -> None:
        registry = SourceRegistry(cache_dir=config.paths.cache_dir)

        if target_key == "all":
            resolved = await registry.all_languages(force_refresh=force_refresh)
            language_names = [catalog.display_name for _source, catalog in resolved]
            size_bytes, count = _estimate_size(resolved)
            scale = 1.0 if mode == "full" else 0.25
            est = int(size_bytes * scale)
            console.print(Panel(
                f"[bold]--bulk all[/bold]\n"
                f"Languages to download: [bold]{count}[/bold]\n"
                f"Mode: [bold]{mode}[/bold]\n"
                f"Estimated download (compressed): [bold]{_format_bytes(est)}[/bold]\n"
                f"Output tree will live under: [bold]{config.paths.markdown_dir}[/bold]",
                title="Bulk download warning",
                border_style="yellow",
            ))
            if not yes and not typer.confirm("Proceed?", default=False):
                console.print("Aborted.")
                return
        elif target_key in PRESETS:
            language_names = PRESETS[target_key]
            console.print(Panel(
                f"[bold]Preset '{target_key}'[/bold]\n"
                f"Languages: {', '.join(language_names)}\n"
                f"Mode: [bold]{mode}[/bold]",
                title="Bulk preset",
                border_style="cyan",
            ))
        else:
            available = ", ".join(sorted(PRESETS.keys()))
            console.print(f"[red]Unknown target '{target}'.[/red]")
            console.print(f"Available presets: {available}, or 'all'.")
            raise typer.Exit(code=1)

        tracker = CrawlProgressTracker(console=console)
        pipeline = DocumentationPipeline(config)
        try:
            with tracker.live():
                summary = await pipeline.run_many(
                    language_names=language_names,
                    mode=mode,
                    force_refresh=force_refresh,
                    progress_tracker=tracker,
                    language_concurrency=language_concurrency,
                    include_topics=include_topic,
                    exclude_topics=exclude_topic,
                )
        finally:
            await pipeline.close()

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
    for name, langs in sorted(PRESETS.items()):
        console.print(f"[bold cyan]{name}[/bold cyan]: {', '.join(langs)}")


@app.command("audit-presets", help="Check whether preset languages resolve against configured sources.")
def audit_presets(
    preset: Optional[str] = typer.Argument(None, help="Preset name to audit. Omit to audit every preset."),
    source: Optional[str] = typer.Option(None, "--source", help="Force resolution against a specific source."),
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
        registry = SourceRegistry(cache_dir=config.paths.cache_dir)
        table = Table(title="Preset Coverage Audit")
        table.add_column("Preset", style="bold cyan")
        table.add_column("Language")
        table.add_column("Status")
        table.add_column("Source")
        table.add_column("Slug")

        resolved_count = 0
        missing_count = 0
        for preset_name in preset_names:
            for language in PRESETS[preset_name]:
                match = await registry.resolve(language, source_name=source, force_refresh=force_refresh)
                if match is None:
                    missing_count += 1
                    table.add_row(preset_name, language, "[red]missing[/red]", "", "")
                    continue
                resolved_count += 1
                matched_source, catalog = match
                table.add_row(preset_name, language, "[green]resolved[/green]", matched_source.name, catalog.slug)

        console.print(table)
        console.print(f"[dim]Resolved: {resolved_count}  Missing: {missing_count}[/dim]")
        if missing_count:
            raise typer.Exit(code=2)

    asyncio.run(_runner())


@app.command("list-languages", help="List every language available across all configured sources.")
def list_languages(
    source: Optional[str] = typer.Option(None, "--source", help="Filter by a single source."),
    force_refresh: bool = typer.Option(False, "--force-refresh", help="Re-fetch catalogs before listing."),
) -> None:
    config = load_config()

    async def _runner() -> None:
        registry = SourceRegistry(cache_dir=config.paths.cache_dir)
        catalogs = await registry.catalog(force_refresh=force_refresh)

        table = Table(title="Supported languages")
        table.add_column("Language", style="bold cyan")
        table.add_column("Source")
        table.add_column("Slug")
        table.add_column("Version")

        rows: list[tuple[str, str, str, str]] = []
        for source_name, entries in catalogs.items():
            if source and source_name != source:
                continue
            for entry in entries:
                rows.append((entry.display_name, source_name, entry.slug, entry.version or ""))
        for row in sorted(rows, key=lambda r: (r[0].lower(), r[1])):
            table.add_row(*row)
        console.print(table)
        console.print(f"[dim]Total: {len(rows)} entries[/dim]")

    asyncio.run(_runner())


@app.command("refresh-catalogs", help="Force-refresh all source catalogs.")
def refresh_catalogs() -> None:
    config = load_config()

    async def _runner() -> None:
        registry = SourceRegistry(cache_dir=config.paths.cache_dir)
        catalogs = await registry.catalog(force_refresh=True)
        for name, entries in catalogs.items():
            console.print(f"[bold]{name}[/bold]: {len(entries)} entries")

    asyncio.run(_runner())


@app.command(help="Validate an existing compiled output without downloading.")
def validate(
    language: str = typer.Argument(..., help="Language name."),
    source: Optional[str] = typer.Option(None, "--source", help="Resolve against a specific source only if local metadata is unavailable."),
    output_dir: Optional[Path] = typer.Option(None, "--output-dir", help="Alternate output directory root."),
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


@app.command(help="Create the required project directories.")
def init() -> None:
    config = load_config()
    config.paths.ensure()
    console.print(f"Initialized directories under [bold]{config.paths.root}[/bold]")
