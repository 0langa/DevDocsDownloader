from __future__ import annotations

import importlib.util
import json
import pkgutil
from typing import Any, cast

from ..config import AppConfig
from ..models import CacheFreshnessPolicy, CrawlMode
from ..services import BulkRunRequest, DocumentationService, RunLanguageRequest
from ..sources.presets import PRESETS
from .state import GuiJobQueue

INSTALL_MESSAGE = "NiceGUI support is not installed. Run: python -m pip install -e .[gui]"
CACHE_POLICIES: list[CacheFreshnessPolicy] = ["use-if-present", "ttl", "always-refresh", "validate-if-possible"]
MODES: list[CrawlMode] = ["important", "full"]
SOURCES = ["auto", "devdocs", "mdn", "dash"]


def create_gui_app(
    config: AppConfig,
    *,
    service: DocumentationService | None = None,
    queue: GuiJobQueue | None = None,
) -> Any:
    _install_nicegui_python314_shim()
    try:
        from nicegui import app, ui
    except ImportError as exc:  # pragma: no cover - exercised through CLI error handling.
        raise RuntimeError(INSTALL_MESSAGE) from exc

    service = service or DocumentationService(config)
    queue = queue or GuiJobQueue()

    def split_topics(value: str | None) -> list[str] | None:
        topics = [item.strip() for item in (value or "").split(",") if item.strip()]
        return topics or None

    def source_value(value: str | None) -> str | None:
        return value if value in {"devdocs", "mdn", "dash"} else None

    def render_jobs(container: Any) -> None:
        container.clear()
        with container:
            rows = [
                {
                    "id": job.id[:8],
                    "label": job.label,
                    "kind": job.kind,
                    "status": job.status,
                    "progress": f"{job.progress:.0%}",
                    "error": job.error,
                }
                for job in queue.jobs
            ]
            ui.table(
                columns=[
                    {"name": "id", "label": "ID", "field": "id", "align": "left"},
                    {"name": "label", "label": "Job", "field": "label", "align": "left"},
                    {"name": "kind", "label": "Kind", "field": "kind", "align": "left"},
                    {"name": "status", "label": "Status", "field": "status", "align": "left"},
                    {"name": "progress", "label": "Progress", "field": "progress", "align": "right"},
                    {"name": "error", "label": "Error", "field": "error", "align": "left"},
                ],
                rows=rows,
                row_key="id",
            ).classes("w-full")
            if queue.jobs:
                with ui.row().classes("items-center gap-2"):
                    ui.button("Clear finished jobs", on_click=queue.clear_finished).props("flat dense")
                    for job in queue.jobs:
                        if job.status in {"pending", "running"}:
                            ui.button(
                                f"Cancel {job.id[:8]}",
                                on_click=lambda job_id=job.id: queue.cancel_job(job_id),
                            ).props("flat dense color=negative")
                latest_events = queue.jobs[-1].events[-60:]
                with ui.expansion("Latest event log", value=True).classes("w-full"):
                    for event in latest_events:
                        ui.label(
                            f"{event.event_type} {event.language or ''} {event.phase or ''} {event.message or ''}"
                        ).classes("text-xs")

    def render_runtime(container: Any) -> None:
        container.clear()
        with container:
            snapshot = service.inspect_runtime()
            ui.label(f"State files: {len(snapshot.states)}")
            ui.label(f"Active checkpoints: {len(snapshot.checkpoints)}")
            ui.label(f"Latest reports: {len(snapshot.reports)}")
            ui.label(f"History reports: {len(snapshot.history_reports)}")
            ui.label(f"Trend/report detail files: {len(snapshot.trend_reports)}")

    async def run_single(
        language: str,
        mode: CrawlMode,
        source: str,
        validate_only: bool,
        force_refresh: bool,
        include_topics: str,
        exclude_topics: str,
        document_frontmatter: bool,
        chunks: bool,
        chunk_max_chars: int,
        chunk_overlap_chars: int,
        chunk_strategy: str,
        chunk_max_tokens: int,
        chunk_overlap_tokens: int,
        cache_policy: CacheFreshnessPolicy,
        cache_ttl_hours: int | None,
    ) -> None:
        if not language.strip():
            ui.notify("Language is required", type="negative")
            return
        request = RunLanguageRequest(
            language=language.strip(),
            mode=mode,
            source=source_value(source),
            force_refresh=force_refresh,
            validate_only=validate_only,
            include_topics=split_topics(include_topics),
            exclude_topics=split_topics(exclude_topics),
            emit_document_frontmatter=document_frontmatter,
            emit_chunks=chunks,
            chunk_max_chars=chunk_max_chars,
            chunk_overlap_chars=chunk_overlap_chars,
            chunk_strategy=chunk_strategy,  # type: ignore[arg-type]
            chunk_max_tokens=chunk_max_tokens,
            chunk_overlap_tokens=chunk_overlap_tokens,
            cache_policy=cache_policy,
            cache_ttl_hours=cache_ttl_hours,
        )
        queue.submit_run(service, request)
        ui.notify(f"Queued {language.strip()}")

    async def run_bulk(
        target: str,
        mode: CrawlMode,
        force_refresh: bool,
        include_topics: str,
        exclude_topics: str,
        document_frontmatter: bool,
        chunks: bool,
        chunk_max_chars: int,
        chunk_overlap_chars: int,
        chunk_strategy: str,
        chunk_max_tokens: int,
        chunk_overlap_tokens: int,
        cache_policy: CacheFreshnessPolicy,
        cache_ttl_hours: int | None,
        language_concurrency: int,
        concurrency_policy: str,
        adaptive_min_concurrency: int,
        adaptive_max_concurrency: int,
    ) -> None:
        target = target.strip().lower()
        if target == "all":
            rows = await service.list_languages(force_refresh=force_refresh)
            languages = sorted({row.language for row in rows})
        elif target in PRESETS:
            languages = list(PRESETS[target])
        else:
            ui.notify("Choose a known preset or 'all'", type="negative")
            return
        request = BulkRunRequest(
            languages=languages,
            mode=mode,
            force_refresh=force_refresh,
            language_concurrency=language_concurrency,
            concurrency_policy=concurrency_policy,  # type: ignore[arg-type]
            adaptive_min_concurrency=adaptive_min_concurrency,
            adaptive_max_concurrency=adaptive_max_concurrency,
            include_topics=split_topics(include_topics),
            exclude_topics=split_topics(exclude_topics),
            emit_document_frontmatter=document_frontmatter,
            emit_chunks=chunks,
            chunk_max_chars=chunk_max_chars,
            chunk_overlap_chars=chunk_overlap_chars,
            chunk_strategy=chunk_strategy,  # type: ignore[arg-type]
            chunk_max_tokens=chunk_max_tokens,
            chunk_overlap_tokens=chunk_overlap_tokens,
            cache_policy=cache_policy,
            cache_ttl_hours=cache_ttl_hours,
        )
        queue.submit_bulk(service, request, label=f"bulk: {target}")
        ui.notify(f"Queued bulk target {target}")

    @ui.page("/")
    def dashboard() -> None:
        ui.add_head_html(
            """
            <style>
              body { background: #f7f8fa; }
              .dense-panel { border: 1px solid #d8dde6; border-radius: 6px; padding: 12px; background: white; }
              .mono { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }
              @media (max-width: 700px) {
                .q-drawer { display: none !important; }
                .q-page-container { padding-left: 0 !important; }
                .q-tab { min-width: 92px; padding-left: 8px; padding-right: 8px; }
              }
            </style>
            """
        )
        with ui.header().classes("items-center justify-between"):
            ui.label("DevDocsDownloader Operator").classes("text-lg font-semibold")
            status = ui.label("Idle").classes("text-sm")
        with ui.left_drawer(value=True).props("width=220 breakpoint=0").classes("bg-slate-900 text-white"):
            ui.label("Operations").classes("text-sm uppercase tracking-wide opacity-70")
            for label in [
                "Run",
                "Bulk",
                "Languages",
                "Presets/Audit",
                "Reports",
                "Output Browser",
                "Checkpoints",
                "Cache",
                "Settings/Help",
            ]:
                ui.label(label).classes("py-1")

        with ui.column().classes("w-full gap-3 p-3"):
            runtime_container = ui.column().classes("dense-panel w-full")
            job_container = ui.column().classes("dense-panel w-full")
            with ui.tabs().classes("w-full") as tabs:
                run_tab = ui.tab("Run")
                bulk_tab = ui.tab("Bulk")
                languages_tab = ui.tab("Languages")
                presets_tab = ui.tab("Presets/Audit")
                reports_tab = ui.tab("Reports")
                output_tab = ui.tab("Output Browser")
                checkpoints_tab = ui.tab("Checkpoints")
                cache_tab = ui.tab("Cache")
                settings_tab = ui.tab("Settings/Help")

            with ui.tab_panels(tabs, value=run_tab).classes("w-full"):
                with ui.tab_panel(run_tab).classes("dense-panel"):
                    language = ui.input("Language").classes("w-full")
                    with ui.row().classes("w-full"):
                        mode = ui.select(MODES, value="important", label="Mode")
                        source = ui.select(SOURCES, value="auto", label="Source")
                        validate_only = ui.checkbox("Validate only", value=False)
                        force_refresh = ui.checkbox("Force refresh", value=False)
                    with ui.row().classes("w-full"):
                        include_topics = ui.input("Include topics, comma-separated").classes("grow")
                        exclude_topics = ui.input("Exclude topics, comma-separated").classes("grow")
                    with ui.row().classes("w-full"):
                        document_frontmatter = ui.checkbox("Document frontmatter", value=False)
                        chunks = ui.checkbox("Chunks", value=False)
                        chunk_strategy = ui.select(["chars", "tokens"], value="chars", label="Chunk strategy")
                        chunk_max_chars = ui.number("Chunk max chars", value=8000, min=500, step=500)
                        chunk_overlap_chars = ui.number("Chunk overlap chars", value=400, min=0, step=50)
                        chunk_max_tokens = ui.number("Chunk max tokens", value=1000, min=100, step=100)
                        chunk_overlap_tokens = ui.number("Chunk overlap tokens", value=100, min=0, step=25)
                    with ui.row().classes("w-full"):
                        cache_policy = ui.select(CACHE_POLICIES, value="use-if-present", label="Cache policy")
                        cache_ttl_hours = ui.number("Cache TTL hours", value=24, min=0, step=1)
                    ui.button(
                        "Queue run",
                        on_click=lambda: run_single(
                            language.value,
                            mode.value,
                            source.value,
                            validate_only.value,
                            force_refresh.value,
                            include_topics.value,
                            exclude_topics.value,
                            document_frontmatter.value,
                            chunks.value,
                            int(chunk_max_chars.value or 8000),
                            int(chunk_overlap_chars.value or 0),
                            chunk_strategy.value,
                            int(chunk_max_tokens.value or 1000),
                            int(chunk_overlap_tokens.value or 0),
                            cache_policy.value,
                            int(cache_ttl_hours.value) if cache_ttl_hours.value is not None else None,
                        ),
                    )

                with ui.tab_panel(bulk_tab).classes("dense-panel"):
                    target = ui.select(["all", *sorted(PRESETS.keys())], value="webapp", label="Preset or all")
                    with ui.row().classes("w-full"):
                        bulk_mode = ui.select(MODES, value="important", label="Mode")
                        bulk_force = ui.checkbox("Force refresh", value=False)
                        concurrency = ui.number("Language concurrency", value=3, min=1, step=1)
                        concurrency_policy = ui.select(
                            ["static", "adaptive"], value="static", label="Concurrency policy"
                        )
                        adaptive_min = ui.number("Adaptive min", value=1, min=1, step=1)
                        adaptive_max = ui.number("Adaptive max", value=6, min=1, step=1)
                    with ui.row().classes("w-full"):
                        bulk_include = ui.input("Include topics, comma-separated").classes("grow")
                        bulk_exclude = ui.input("Exclude topics, comma-separated").classes("grow")
                    with ui.row().classes("w-full"):
                        bulk_frontmatter = ui.checkbox("Document frontmatter", value=False)
                        bulk_chunks = ui.checkbox("Chunks", value=False)
                        bulk_chunk_strategy = ui.select(["chars", "tokens"], value="chars", label="Chunk strategy")
                        bulk_chunk_max = ui.number("Chunk max chars", value=8000, min=500, step=500)
                        bulk_chunk_overlap = ui.number("Chunk overlap chars", value=400, min=0, step=50)
                        bulk_chunk_max_tokens = ui.number("Chunk max tokens", value=1000, min=100, step=100)
                        bulk_chunk_overlap_tokens = ui.number("Chunk overlap tokens", value=100, min=0, step=25)
                    with ui.row().classes("w-full"):
                        bulk_cache_policy = ui.select(CACHE_POLICIES, value="use-if-present", label="Cache policy")
                        bulk_cache_ttl = ui.number("Cache TTL hours", value=24, min=0, step=1)
                    ui.button(
                        "Queue bulk run",
                        on_click=lambda: run_bulk(
                            target.value,
                            bulk_mode.value,
                            bulk_force.value,
                            bulk_include.value,
                            bulk_exclude.value,
                            bulk_frontmatter.value,
                            bulk_chunks.value,
                            int(bulk_chunk_max.value or 8000),
                            int(bulk_chunk_overlap.value or 0),
                            bulk_chunk_strategy.value,
                            int(bulk_chunk_max_tokens.value or 1000),
                            int(bulk_chunk_overlap_tokens.value or 0),
                            bulk_cache_policy.value,
                            int(bulk_cache_ttl.value) if bulk_cache_ttl.value is not None else None,
                            int(concurrency.value or 1),
                            concurrency_policy.value,
                            int(adaptive_min.value or 1),
                            int(adaptive_max.value or 1),
                        ),
                    )

                with ui.tab_panel(languages_tab).classes("dense-panel"):
                    language_rows = ui.column().classes("w-full")

                    async def refresh_languages() -> None:
                        rows = await service.list_languages()
                        language_rows.clear()
                        with language_rows:
                            ui.table(
                                columns=[
                                    {"name": "language", "label": "Language", "field": "language"},
                                    {"name": "source", "label": "Source", "field": "source"},
                                    {"name": "slug", "label": "Slug", "field": "slug"},
                                    {"name": "version", "label": "Version", "field": "version"},
                                ],
                                rows=[row.model_dump() for row in rows],
                            ).classes("w-full")

                    ui.button("Refresh language list", on_click=refresh_languages)

                with ui.tab_panel(presets_tab).classes("dense-panel"):
                    ui.label(", ".join(f"{name}: {len(langs)}" for name, langs in sorted(PRESETS.items())))
                    audit_rows = ui.column().classes("w-full")

                    async def audit_all() -> None:
                        results = await service.audit_presets()
                        audit_rows.clear()
                        with audit_rows:
                            ui.table(
                                columns=[
                                    {"name": "preset", "label": "Preset", "field": "preset"},
                                    {"name": "language", "label": "Language", "field": "language"},
                                    {"name": "resolved", "label": "Resolved", "field": "resolved"},
                                    {"name": "source", "label": "Source", "field": "source"},
                                    {"name": "slug", "label": "Slug", "field": "slug"},
                                ],
                                rows=[row.model_dump() for row in results],
                            ).classes("w-full")

                    ui.button("Audit all presets", on_click=audit_all)
                    ui.button("Queue catalog refresh", on_click=lambda: queue.submit_refresh_catalogs(service))

                with ui.tab_panel(reports_tab).classes("dense-panel"):
                    reports_box = ui.column().classes("w-full")

                    def refresh_reports() -> None:
                        bundle = service.read_reports()
                        reports_box.clear()
                        with reports_box:
                            ui.label(f"Latest JSON: {bundle.latest_json_path or 'none'}").classes("mono text-xs")
                            ui.label(f"Validation document records: {len(bundle.validation_documents)}")
                            ui.label(f"History reports: {len(bundle.history_reports)}")
                            ui.label(f"Trend languages: {len(bundle.trends_json.get('languages', {}))}")
                            ui.textarea("run_summary.md", value=bundle.latest_markdown).classes("w-full mono")

                    ui.button("Refresh reports", on_click=refresh_reports)

                with ui.tab_panel(output_tab).classes("dense-panel"):
                    output_box = ui.column().classes("w-full")
                    file_preview = ui.textarea("Preview").classes("w-full mono")

                    def refresh_output() -> None:
                        bundles = service.list_output_bundles()
                        output_box.clear()
                        with output_box:
                            for bundle in bundles:
                                with ui.expansion(
                                    f"{bundle.language} ({bundle.language_slug}) - {bundle.total_documents} docs"
                                ).classes("w-full"):
                                    tree = service.output_tree(bundle.language_slug)
                                    for node in _flatten_tree(tree):
                                        if not node["is_dir"]:
                                            ui.button(
                                                node["relative_path"],
                                                on_click=lambda b=bundle.language_slug, p=node["relative_path"]: (
                                                    file_preview.set_value(service.read_output_file(b, p).content)
                                                ),
                                            ).props("flat dense").classes("mono text-xs")

                    ui.button("Refresh output bundles", on_click=refresh_output)

                with ui.tab_panel(checkpoints_tab).classes("dense-panel"):
                    checkpoints_box = ui.column().classes("w-full")

                    def refresh_checkpoints() -> None:
                        checkpoints_box.clear()
                        with checkpoints_box:
                            for item in service.list_checkpoints():

                                def delete_and_refresh(slug: str = item.slug) -> None:
                                    service.delete_checkpoint(slug)
                                    refresh_checkpoints()

                                def rerun_from_checkpoint(summary=item) -> None:
                                    queue.submit_run(
                                        service,
                                        RunLanguageRequest(
                                            language=summary.language,
                                            mode=cast(CrawlMode, summary.mode),
                                            source=source_value(summary.source),
                                        ),
                                    )

                                with ui.expansion(
                                    f"{item.slug} {item.source}/{item.source_slug} {item.mode} "
                                    f"{item.phase} emitted={item.emitted_document_count}"
                                ).classes("w-full"):
                                    ui.label(f"Document position: {item.document_inventory_position}").classes(
                                        "mono text-xs"
                                    )
                                    ui.label(f"Output path: {item.output_path or 'none'}").classes("mono text-xs")
                                    ui.label(f"Failures: {item.failure_count}").classes("mono text-xs")
                                    ui.textarea(
                                        "Checkpoint JSON",
                                        value=json.dumps(service.read_checkpoint(item.slug), indent=2),
                                    ).classes("w-full mono")
                                    with ui.row().classes("items-center gap-2"):
                                        ui.button("Rerun", on_click=rerun_from_checkpoint).props("flat dense")
                                        ui.button(
                                            "Delete",
                                            on_click=delete_and_refresh,
                                        ).props("color=negative flat dense")

                    ui.button("Refresh checkpoints", on_click=refresh_checkpoints)

                with ui.tab_panel(cache_tab).classes("dense-panel"):
                    cache_box = ui.column().classes("w-full")

                    def refresh_cache() -> None:
                        cache_box.clear()
                        with cache_box:
                            rows = [item.model_dump(mode="json") for item in service.list_cache_metadata()]
                            ui.table(
                                columns=[
                                    {"name": "source", "label": "Source", "field": "source"},
                                    {"name": "cache_key", "label": "Key", "field": "cache_key"},
                                    {"name": "policy", "label": "Policy", "field": "policy"},
                                    {"name": "byte_count", "label": "Bytes", "field": "byte_count"},
                                    {"name": "path", "label": "Metadata", "field": "path"},
                                ],
                                rows=rows,
                            ).classes("w-full")

                    ui.button("Refresh cache metadata", on_click=refresh_cache)
                    ui.button("Queue catalog refresh", on_click=lambda: queue.submit_refresh_catalogs(service))

                with ui.tab_panel(settings_tab).classes("dense-panel"):
                    ui.label(f"Project root: {config.paths.root}").classes("mono text-xs")
                    ui.label(f"Output directory: {config.paths.output_dir}").classes("mono text-xs")
                    ui.label("The GUI is local/operator-focused and calls DocumentationService in-process.")
                    ui.label("Install GUI support with: python -m pip install -e .[gui]").classes("mono")

        def refresh_status() -> None:
            active = queue.active
            status.set_text(f"Running: {active.label} {active.progress:.0%}" if active else "Idle")
            render_jobs(job_container)
            render_runtime(runtime_container)

        render_runtime(runtime_container)
        render_jobs(job_container)
        ui.timer(2.0, refresh_status)

    return app


def run_gui(
    config: AppConfig,
    *,
    host: str = "127.0.0.1",
    port: int = 8080,
    reload: bool = False,
    native: bool = False,
) -> None:
    create_gui_app(config)
    _install_nicegui_python314_shim()
    try:
        from nicegui import ui
    except ImportError as exc:  # pragma: no cover - exercised through CLI error handling.
        raise RuntimeError(INSTALL_MESSAGE) from exc
    ui.run(host=host, port=port, reload=reload, native=native, title="DevDocsDownloader")


def _flatten_tree(node: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for child in node.children:
        rows.append(
            {
                "name": child.name,
                "relative_path": child.relative_path,
                "is_dir": child.is_dir,
                "size": child.size,
            }
        )
        rows.extend(_flatten_tree(child))
    return rows


def _install_nicegui_python314_shim() -> None:
    if hasattr(pkgutil, "find_loader"):
        return

    def find_loader(fullname: str) -> Any:
        return importlib.util.find_spec(fullname)

    pkgutil.find_loader = find_loader  # type: ignore[attr-defined]
