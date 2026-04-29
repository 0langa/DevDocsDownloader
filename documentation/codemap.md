# Code Map

## Repository tree

```text
DevDocsDownloader/
├── DevDocsDownloader.py
├── pyproject.toml
├── README.md
├── requirements.txt
├── benchmarks/
│   └── corpora/
│       └── core_docs_v1.json
├── doc_ingest/
│   ├── __init__.py
│   ├── cache.py
│   ├── adaptive.py
│   ├── cli.py
│   ├── compiler.py
│   ├── config.py
│   ├── conversion.py
│   ├── live_probe.py
│   ├── models.py
│   ├── pipeline.py
│   ├── progress.py
│   ├── runtime.py
│   ├── services.py
│   ├── state.py
│   ├── validator.py
│   ├── gui/
│   │   ├── __init__.py
│   │   ├── app.py
│   │   └── state.py
│   ├── reporting/
│   │   ├── __init__.py
│   │   └── writer.py
│   ├── sources/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── dash.py
│   │   ├── dash_seed.json
│   │   ├── devdocs.py
│   │   ├── devdocs_core.json
│   │   ├── mdn.py
│   │   ├── presets.py
│   │   └── registry.py
│   └── utils/
│       ├── __init__.py
│       ├── filesystem.py
│       ├── text.py
│       └── urls.py
├── documentation/
│   ├── architecture.md
│   ├── codemap.md
│   ├── development_progress.md
│   └── full-project-documentation.md
├── scripts/
│   ├── benchmark_pipeline.py
│   ├── build_skip_manifest.py
│   └── setup.py
├── source-documents/
│   └── requirements.txt
└── tests/
		├── __init__.py
		├── helpers.py
		├── test_cli_contract.py
		├── test_output_contract.py
		├── test_phase4_architecture.py
		├── test_phase5_performance.py
		├── test_phase6_conversion_quality.py
		├── test_phase7_output_consumption.py
		├── test_phase8_validation_observability.py
		├── test_phase9_gui.py
		└── test_source_resilience.py
```

## Navigation notes

- Use this file to find code quickly.
- Use `architecture.md` for subsystem behavior.
- Use `full-project-documentation.md` for detailed workflow explanations.
- Use `development_progress.md` for current-state risks and gaps.

## Entry points

### `DevDocsDownloader.py`

- Main executable entry point
- Imports `app` from `doc_ingest.cli`
- Runs the Typer app when executed directly

### `doc_ingest/cli.py`

- Real operational entry point for the application
- Defines all commands and the interactive wizard
- Starts async work with `asyncio.run()`

## Active package map: `doc_ingest/`

### `doc_ingest/__init__.py`

- Package marker
- Contains only a package docstring

### `doc_ingest/cli.py`

**Purpose**

- User-facing command layer

**Key symbols**

- `app` — Typer application
- `_setup_logging()` — configures file logging
- `_execute_run()` — shared execution path for `run` and `validate`
- `_wizard()` — interactive prompt-based flow
- `run()` — single-language ingestion command
- `bulk()` — preset/all language ingestion command
- `list_presets()`
- `audit_presets()`
- `list_languages()`
- `refresh_catalogs()`
- `validate()`
- `gui()`
- `init()`

**Calls into**

- `load_config()`
- `DocumentationService`
- `CrawlProgressTracker`
- `SourceRegistry`

### `doc_ingest/services.py`

**Purpose**

- Service facade over pipeline, registry, and GUI-safe artifact inspection workflows

**Key symbols**

- `DocumentationService`
- `RunLanguageRequest`
- `BulkRunRequest`
- `ServiceEvent`
- `LanguageEntry`
- `AuditPresetResult`
- `RuntimeSnapshot`
- `OutputBundleSummary`
- `OutputTreeNode`
- `OutputFileContent`
- `ReportBundle`
- `CheckpointSummary`
- `CacheMetadataSummary`

**Used by**

- CLI
- optional local GUI or API layer

### `doc_ingest/gui/app.py`

**Purpose**

- Legacy NiceGUI operator interface over `DocumentationService`, retained as a migration/internal tool

**Key symbols**

- `create_gui_app()`
- `run_gui()`
- `INSTALL_MESSAGE`

**Notable details**

- imported only by the `gui` command or GUI tests
- exposes run, bulk, languages, presets/audit, reports, output browser, checkpoints, cache, and settings/help views
- `SETTINGS_HELP_MARKDOWN` contains the in-app operator tutorial for workflows, cache/resume behavior, validation,
  reports, output browsing, and CLI equivalents
- does not shell out to CLI commands for core operations

### `doc_ingest/desktop_backend.py`

**Purpose**

- Loopback HTTP backend host for the WinUI desktop shell

**Key symbols**

- `create_app()`
- `BackendJobManager`
- `run_backend_server()`

**Notable details**

- exposes health/version/shutdown endpoints plus run, validate, bulk, reports, output, checkpoints, cache, and settings APIs
- enforces bearer-token auth on loopback requests
- supports one active desktop job at a time with SSE event streaming
- uses desktop-safe runtime paths through `load_config(runtime_mode="desktop")`

### `doc_ingest/gui/state.py`

**Purpose**

- In-process GUI job queue and job state models

**Key symbols**

- `GuiJobQueue`
- `GuiJobState`

**Notable details**

- one active job is started by default
- records `ServiceEvent` objects emitted by service runs
- supports queued job cancellation and clearing finished jobs

### `doc_ingest/config.py`

**Purpose**

- Central path configuration and directory creation

**Key symbols**

- `PathsConfig`
- `AppConfig`
- `load_config()`

**Used by**

- CLI
- pipeline
- support scripts that try to reuse repository paths

### `doc_ingest/models.py`

**Purpose**

- Pydantic models for run state, validation, and reports

**Key symbols**

- `CrawlMode`
- `TopicStats`
- `SourceRunDiagnostics`
- `ValidationIssue`
- `ValidationResult`
- `DocumentValidationResult`
- `LanguageRunState`
- `DocumentCheckpoint`
- `CheckpointFailure`
- `LanguageRunCheckpoint`
- `LanguageRunReport`
- `RunSummary`
- `SourceWarningRecord`
- `RuntimeTelemetrySnapshot`
- `CacheEntryMetadata`
- `CacheDecision`
- `CacheFreshnessPolicy`

**Used by**

- pipeline
- validator
- state store
- report writer
- tests

### `doc_ingest/pipeline.py`

**Purpose**

- Core orchestration layer for one-language and many-language runs

**Key symbols**

- `DocumentationPipeline`
	- `run_many()`
	- `run()`
	- `_run_language()`
	- `close()`

**Calls into**

- `SourceRegistry.resolve()`
- `compile_from_stream()`
- `validate_output()`
- `RunCheckpointStore.save()`
- `RunStateStore.save()`
- `write_reports()`

### `doc_ingest/compiler.py`

**Purpose**

- Convert a stream of `Document` objects into on-disk Markdown artifacts

**Key symbols**

- `CompiledOutput`
- `AnchorRegistry`
- `LanguageOutputBuilder`
	- `add()`
	- `finalize()`
- `compile_from_stream()`
- `render_document()`
- `write_chunks()`
- `write_assets()`
- `_render_index()`
- `_render_consolidated()`
- `_build_link_target_map()`
- `_normalize_markdown()`
- `_anchor()`

**Calls into**

- `write_text()`
- `write_bytes()`
- `slugify()`

### `doc_ingest/cache.py`

**Purpose**

- Shared cache freshness decisions and sidecar metadata writing

**Key symbols**

- `decide_cache_refresh()`
- `write_cache_metadata()`
- `write_cache_metadata_for_bytes()`
- `read_cache_metadata()`

### `doc_ingest/adaptive.py`

**Purpose**

- Optional adaptive bulk scheduling controller

**Key symbols**

- `AdaptiveBulkPolicy`
- `AdaptiveBulkController`
- `static_bulk_telemetry()`

### `doc_ingest/progress.py`

**Purpose**

- Rich live progress display

**Key symbols**

- `LanguageProgress`
- `CrawlProgressTracker`
	- `live()`
	- `register_language()`
	- `on_document_completed()`
	- `on_language_complete()`

### `doc_ingest/state.py`

**Purpose**

- Read/write persistence for per-language run state and active checkpoint JSON files

**Key symbols**

- `RunStateStore`
	- `load()`
	- `save()`
- `RunCheckpointStore`
	- `load()`
	- `save()`
	- `update_phase()`
	- `record_document()`
	- `record_failure()`
	- `delete()`

### `doc_ingest/validator.py`

**Purpose**

- Layered validation of consolidated and per-document Markdown output

**Key symbols**

- `validate_output()`
- `validate_documents()`

## Reporting package

### `doc_ingest/reporting/__init__.py`

- Re-exports `write_reports`

### `doc_ingest/reporting/writer.py`

**Purpose**

- Write machine-readable and human-readable run summary, document validation, history, and trend artifacts

**Key symbols**

- `write_reports()`

**Outputs**

- `output/reports/run_summary.json`
- `output/reports/run_summary.md`
- `output/reports/validation_documents.jsonl`
- `output/reports/history/<timestamp>-run_summary.json`
- `output/reports/trends.json`
- `output/reports/trends.md`

## Sources package

### `doc_ingest/sources/__init__.py`

- Re-exports common source symbols

### `doc_ingest/sources/base.py`

**Purpose**

- Shared source adapter datamodel and protocol

**Key symbols**

- `LanguageCatalog`
- `Document`
- `DocumentEvent`
- `WarningEvent`
- `DocumentWarningEvent`
- `DocumentationSource`

### `doc_ingest/sources/registry.py`

**Purpose**

- Source catalog aggregation and language resolution

**Key symbols**

- `SourceRegistry`
	- `get()`
	- `catalog()`
	- `resolve()`
	- `resolve_many()`
	- `all_languages()`
	- `suggest()`
- `_exact_match()`
- `_version_key()`

**Depends on**

- `DevDocsSource`
- `MdnContentSource`
- `DashFeedSource`

### `doc_ingest/sources/devdocs.py`

**Purpose**

- DevDocs adapter

**Key symbols**

- `DevDocsSource`
	- `list_languages()`
	- `fetch()`
	- `_download_dataset()`
	- `_ensure_json_dataset()`
	- `_load_json_cache()`

**Notable details**

- caches catalog and per-language datasets
- uses `markdownify` on HTML blobs
- filters by `entry.type` when `important` mode is active

### `doc_ingest/sources/mdn.py`

**Purpose**

- MDN content adapter

**Key symbols**

- `MdnContentSource`
	- `list_languages()`
	- `fetch()`
	- `_ensure_content()`
	- `_has_expected_tree()`
	- `_find_content_root()`
- `_extract_tarball()`
- `_parse_frontmatter()`

**Notable details**

- exposes a fixed catalog, not a remote-discovered one
- reads source Markdown directly from the MDN repo export
- parses frontmatter with safe YAML and preserves nested/list metadata for filtering and future reporting

### `doc_ingest/sources/dash.py`

**Purpose**

- Dash/Kapeli docset adapter

**Key symbols**

- `DashFeedSource`
	- `list_languages()`
	- `fetch()`
	- `_download_docset()`
- `_convert_html()`
- `_slug()`
- `_DEFAULT_DASH_SEED`

**Notable details**

- depends on `.docset` archive shape and SQLite metadata
- uses a built-in seed list instead of runtime feed discovery

### `doc_ingest/conversion.py`

**Purpose**

- Shared HTML cleanup, source-link rewriting, and Markdown post-processing helpers

**Key symbols**

- `convert_html_to_markdown()`
- `rewrite_markdown_links()`
- `resolve_source_link()`
- `DEVDOCS_PROFILE`
- `DASH_PROFILE`

**Notable details**

- uses BeautifulSoup/lxml before `markdownify`
- removes common navigation, search, header/footer, and hidden elements
- rewrites relative source links outside code spans and fenced blocks

### `doc_ingest/sources/presets.py`

- Defines named bulk language presets such as `webapp`, `backend`, `data`, and `python-stack`

### `doc_ingest/sources/devdocs_core.json`

- Static mapping of DevDocs slugs/families to “important mode” topic names

### `doc_ingest/sources/dash_seed.json`

- Maintained seed catalog for Dash/Kapeli docsets loaded by `SourceRegistry`

## Utilities package

### `doc_ingest/utils/__init__.py`

- Package docstring only

### `doc_ingest/utils/filesystem.py`

**Purpose**

- Atomic file writing helpers and JSON serialization helpers

**Key symbols**

- `read_json()`
- `write_json()`
- `write_text()`
- `write_bytes()`

### `doc_ingest/utils/text.py`

**Purpose**

- Slug and text normalization helpers

**Key symbols**

- `slugify()`
- `normalize_whitespace()`
- `stable_hash()`

### `doc_ingest/utils/urls.py`

**Purpose**

- URL normalization helpers used by legacy support scripts

**Key symbols**

- `normalize_url()`
- `resolve_url()`
- `canonicalize_url_for_content()`
- `is_probably_document_url()`
- `strip_fragment()`
- `same_domain()`

## Documentation directory

### `documentation/architecture.md`

- System design and subsystem-level explanation

### `documentation/codemap.md`

- This file; repository navigation guide

### `documentation/development_progress.md`

- Current implementation status and gaps

### `documentation/full-project-documentation.md`

- Deep technical reference

## Benchmarks and support assets

### `benchmarks/corpora/core_docs_v1.json`

- Tiny benchmark corpus containing Python and TypeScript source URLs
- Used by the historical benchmark harness, not by the active CLI directly

## Support scripts

These scripts matter mostly because they show repository history; they are not equally aligned with the active package.

### `documentation/archive/analyze_doc_paths.py.txt`

**Purpose**

- Analyze a list of documentation root URLs and derive allowed path prefixes

**Status relative to active app**

- Archived historical utility
- Does not integrate with the current `doc_ingest` execution path
- Belongs to an older crawler/planner workflow and is no longer part of active tooling gates

### `scripts/benchmark_pipeline.py`

**Purpose**

- Benchmark current source-adapter CLI throughput across cold/warm cache modes

**Status relative to active app**

- Compatible with the current CLI
- Runs configured corpus languages through `DevDocsDownloader.py run`
- Reports document count, document throughput, duration, and output size

### `scripts/build_skip_manifest.py`

**Purpose**

- Build a manifest of current per-language run state and active checkpoints

**Status relative to active app**

- Compatible with the current source-adapter state model
- Writes `cache/state_manifest.json`
- Includes `state/checkpoints/*.json` when failed or active runs leave checkpoint files
- Does not produce URL-level crawler skip data because the active pipeline does not persist URL crawl state

### `scripts/setup.py`

**Purpose**

- Convenience bootstrap script for local environment setup

**Status relative to active app**

- Current local bootstrap helper
- Primary recommended setup entrypoint before running the downloader
- Creates `.venv`, installs a selected setup profile, creates runtime directories, and prints current CLI/test/tooling commands
- Defaults to the `full` profile, which installs runtime extras for GUI, browser fallback, benchmark telemetry, and tokenizer chunking
- Installs Playwright Chromium by default whenever browser support is included unless `--skip-playwright-browser` is passed

## Source documents directory

### `source-documents/requirements.txt`

- Legacy compatibility shim for support scripts
- Points to the canonical project metadata through the `analysis` extra instead of duplicating dependency pins

## Tests

### `tests/__init__.py`

- Package marker

### `tests/test_source_resilience.py`

**Purpose**

- Regression tests for:
	- bulk-run concurrency propagation
	- cache corruption handling
	- tarball/docset failure behavior
	- Windows-safe slug generation

**Notable coverage gaps**

- no end-to-end integration test for a real single-language run
- no snapshot tests for generated Markdown
- no direct validation of CLI tables or report format stability

## Cross-file execution paths

### Path: `run` command

```text
DevDocsDownloader.py
	-> doc_ingest.cli.app
	-> doc_ingest.cli.run()
	-> doc_ingest.cli._execute_run()
	-> doc_ingest.pipeline.DocumentationPipeline.run()
	-> doc_ingest.sources.registry.SourceRegistry.resolve()
	-> chosen source adapter.fetch()
	-> doc_ingest.compiler.compile_from_stream()
	-> doc_ingest.validator.validate_output()
	-> doc_ingest.state.RunStateStore.save()
	-> doc_ingest.reporting.write_reports()
```

### Path: `bulk` command

```text
doc_ingest.cli.bulk()
	-> SourceRegistry.all_languages() or presets lookup
	-> DocumentationPipeline.run_many()
	-> many DocumentationPipeline.run() calls
	-> aggregated RunSummary
	-> write_reports()
```

### Path: `validate` command

```text
doc_ingest.cli.validate()
	-> _execute_run(validate_only=True)
	-> DocumentationPipeline.run()
	-> _run_language(validate_only=True)
	-> existing state load + validate_output()
```

### Path: `gui` command

```text
doc_ingest.cli.gui()
	-> doc_ingest.gui.app.run_gui()
	-> doc_ingest.gui.state.GuiJobQueue
	-> DocumentationService
	-> same pipeline/report/state/output paths as CLI
```

## Generated vs source files

### Source-controlled files

- everything under `doc_ingest/`
- support scripts under `scripts/`
- tests
- documentation files
- dependency manifests

### Runtime-generated files

- `cache/**`
- `logs/**`
- `state/**`
- `state/checkpoints/**`
- `tmp/**`
- `output/markdown/**`
- `output/reports/**`

## Files that appear historical or partially mismatched

- `documentation/archive/analyze_doc_paths.py.txt`
- local `.claude/settings.local.json` command allowlist entries referencing missing config paths and modules

Treat these files carefully during maintenance because they describe behavior the current runtime package does not implement.
