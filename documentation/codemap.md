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
│   ├── cli.py
│   ├── compiler.py
│   ├── config.py
│   ├── models.py
│   ├── pipeline.py
│   ├── progress.py
│   ├── state.py
│   ├── validator.py
│   ├── reporting/
│   │   ├── __init__.py
│   │   └── writer.py
│   ├── sources/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── dash.py
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
│   ├── analyze_doc_paths.py
│   ├── benchmark_pipeline.py
│   ├── build_skip_manifest.py
│   └── setup.py
├── source-documents/
│   └── requirements.txt
└── tests/
		├── __init__.py
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
- `list_languages()`
- `refresh_catalogs()`
- `validate()`
- `init()`

**Calls into**

- `load_config()`
- `DocumentationPipeline`
- `CrawlProgressTracker`
- `SourceRegistry`

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
- `ValidationIssue`
- `ValidationResult`
- `LanguageRunState`
- `LanguageRunReport`
- `RunSummary`

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
- `RunStateStore.save()`
- `write_reports()`

### `doc_ingest/compiler.py`

**Purpose**

- Convert a stream of `Document` objects into on-disk Markdown artifacts

**Key symbols**

- `CompiledOutput`
- `LanguageOutputBuilder`
	- `add()`
	- `finalize()`
- `compile_from_stream()`
- `_render_document()`
- `_render_index()`
- `_render_consolidated()`
- `_normalize_markdown()`
- `_anchor()`

**Calls into**

- `write_text()`
- `slugify()`

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

- Read/write persistence for per-language run state JSON files

**Key symbols**

- `RunStateStore`
	- `load()`
	- `save()`

### `doc_ingest/validator.py`

**Purpose**

- Structural validation of consolidated Markdown output

**Key symbols**

- `validate_output()`

## Reporting package

### `doc_ingest/reporting/__init__.py`

- Re-exports `write_reports`

### `doc_ingest/reporting/writer.py`

**Purpose**

- Write machine-readable and human-readable run summary artifacts

**Key symbols**

- `write_reports()`

**Outputs**

- `output/reports/run_summary.json`
- `output/reports/run_summary.md`

## Sources package

### `doc_ingest/sources/__init__.py`

- Re-exports common source symbols

### `doc_ingest/sources/base.py`

**Purpose**

- Shared source adapter datamodel and protocol

**Key symbols**

- `LanguageCatalog`
- `Document`
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
- does simple frontmatter parsing via regex and line splitting

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

### `doc_ingest/sources/presets.py`

- Defines named bulk language presets such as `webapp`, `backend`, `data`, and `python-stack`

### `doc_ingest/sources/devdocs_core.json`

- Static mapping of DevDocs slugs/families to “important mode” topic names

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

### `scripts/analyze_doc_paths.py`

**Purpose**

- Analyze a list of documentation root URLs and derive allowed path prefixes

**Status relative to active app**

- Standalone utility
- Does not integrate with the current `doc_ingest` execution path
- Belongs to an older crawler/planner workflow

### `scripts/benchmark_pipeline.py`

**Purpose**

- Benchmark ingestion throughput across cold/warm cache modes

**Status relative to active app**

- Stale against the current CLI
- Calls unsupported flags such as `--input-file`, `--page-concurrency`, and `--compile-streaming`
- Expects report fields like `pages_processed` and `performance` that current reports do not generate

### `scripts/build_skip_manifest.py`

**Purpose**

- Build a manifest of processed/failed/discovered URLs from crawler state files

**Status relative to active app**

- Stale against the current config/package layout
- Imports `doc_ingest.parser`, which does not exist
- Uses `config.paths.input_file` and `crawl_cache_dir`, which do not exist

### `scripts/setup.py`

**Purpose**

- Convenience bootstrap script for local environment setup

**Status relative to active app**

- Can still be useful for environment setup
- Installs from `source-documents/requirements.txt`, which includes extra packages not needed by the active pipeline

## Source documents directory

### `source-documents/requirements.txt`

- Alternative dependency file used by `scripts/setup.py`
- Includes several packages not used in the active ingestion flow

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
- `tmp/**`
- `output/markdown/**`
- `output/reports/**`

## Files that appear stale or mismatched

- `scripts/benchmark_pipeline.py`
- `scripts/build_skip_manifest.py`
- local `.claude/settings.local.json` command allowlist entries referencing missing config paths and modules

Treat these files carefully during maintenance because they describe behavior the current runtime package does not implement.
