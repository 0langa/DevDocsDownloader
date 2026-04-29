# Architecture

## Overview

`DevDocsDownloader` is built as a source-adapter ingestion pipeline rather than a generic crawler. The runtime path is centered on resolving a requested language to a known upstream catalog, fetching source-exported documentation artifacts, converting them to Markdown, writing a structured output tree, and validating the result.

The active code path lives entirely under `doc_ingest/` plus the top-level bootstrap file `DevDocsDownloader.py`.

## System sketch

```text
user command
	-> doc_ingest.cli
	-> DocumentationService
	-> DocumentationPipeline
	-> SourceRegistry
	-> {DevDocs | MDN | Dash} adapter
	-> Document stream
	-> LanguageOutputBuilder
	-> output/state/reports
```

Desktop release flow:

```text
WinUI shell
	-> local loopback HTTP API
	-> doc_ingest.desktop_backend
	-> DocumentationService
	-> same pipeline/state/report/output paths as CLI
```

Legacy GUI flow:

```text
local browser
	-> doc_ingest.gui
	-> DocumentationService
	-> same pipeline/state/report/output paths as CLI
```

## Architectural style

### Primary pattern

- **Adapter-based ingestion pipeline**
	- A shared orchestration layer delegates source-specific work to adapter classes
	- All adapters normalize their output into the same `Document` dataclass

### Supporting patterns

- **Registry pattern** via `SourceRegistry`
- **Service facade** via `DocumentationService`
- **Builder pattern** via `LanguageOutputBuilder`
- **State persistence wrapper** via `RunStateStore`
- **Post-run validation/reporting pass** via validator and writer modules

## Runtime subsystems

### 1. CLI and command orchestration

**Files:**

- `DevDocsDownloader.py`
- `doc_ingest/cli.py`

**Responsibilities:**

- expose the Typer application
- parse command-line arguments
- run the interactive wizard when no subcommand is provided
- initialize config, logging, progress tracking, and service requests
- render terminal summaries with Rich
- provide long-form operator help for command behavior, output locations, resume/checkpoint behavior, cache policies,
  chunking, adaptive bulk scheduling, GUI launch, and examples

**Key behavior:**

- `DevDocsDownloader.py` is a thin bootstrap that imports `app` and executes it
- `doc_ingest/cli.py` owns all user-facing commands
- single-language runs and bulk runs call `DocumentationService`, which owns the pipeline lifecycle

The optional `gui` command launches the older local NiceGUI operator interface when the `gui` extra is installed. It remains useful for migration and internal operator flows, but the `1.0.0` desktop release direction is the WinUI 3 shell plus bundled Python backend worker.

### 1.0 Desktop backend host

**Files:**

- `doc_ingest/desktop_backend.py`
- `doc_ingest/desktop_settings.py`

**Responsibilities:**

- expose `DocumentationService` through a local-only HTTP API for the WinUI shell
- enforce bearer-token auth on loopback requests
- own one active desktop job at a time with structured job status and SSE event streaming
- persist desktop defaults through `%LOCALAPPDATA%\DevDocsDownloader\settings.json`
- use desktop-safe output/cache/state/log/tmp roots instead of repo-root defaults when running in desktop mode

**Key behavior:**

- binds to `127.0.0.1` and a caller-selected port
- exposes health/version/shutdown, run/bulk/validate, inspection, reports, checkpoints, cache, and settings endpoints
- reuses existing Pydantic request/response models where practical
- is intended to be frozen and bundled into the desktop release

### 1.1 Local GUI and operator workflow layer

**Files:**

- `doc_ingest/gui/app.py`
- `doc_ingest/gui/state.py`

**Responsibilities:**

- expose the same meaningful run, bulk, validation, catalog, preset, output, report, checkpoint, and cache workflows available from the CLI
- keep a local in-process job queue with one active job by default
- subscribe to `DocumentationService` events for phase, document, warning, validation, telemetry, and failure updates
- browse generated output bundles, report artifacts, checkpoint manifests, and cache metadata through service methods with strict path checks

**Key behavior:**

- NiceGUI is optional through `.[gui]`
- the GUI calls `DocumentationService` directly and does not shell out to Typer commands
- the GUI is retained as a migration and internal operator surface, not the primary `1.0.0` public GUI
- file reads are constrained to configured output/report/cache/state roots
- destructive checkpoint deletion is limited to `state/checkpoints/*.json`
- the Settings/Help tab embeds the operator tutorial for workflows, expected behavior, validation output, cache/resume
  controls, report interpretation, output browsing, and CLI equivalents

### 2. Configuration and path management

**File:** `doc_ingest/config.py`

**Responsibilities:**

- define repository-relative working directories
- ensure required output/cache/state directories exist
- support an alternate `output_dir` root

**Path model:**

- `output/`
- `output/markdown/`
- `output/reports/`
- `cache/`
- `logs/`
- `state/`
- `state/checkpoints/`
- `tmp/`

The config surface is intentionally small. `AppConfig` controls language concurrency, generated-Markdown durability, optional document frontmatter, optional retrieval chunks, tokenizer chunk settings, and cache freshness policy. `SourceRuntime` accepts conservative environment overrides for source-profile throttling through `DEVDOCS_SOURCE_CONCURRENCY` and `DEVDOCS_SOURCE_MIN_DELAY`. Source plugins are discovered from installed Python entry points in the `devdocsdownloader.sources` group; built-in sources are registered first. In desktop mode, `PathsConfig.from_desktop()` redirects cache, state, logs, tmp, and settings to per-user Windows locations and uses `%UserProfile%\\Documents\\DevDocsDownloader` as the default output root.

### 3. Source resolution layer

**Files:**

- `doc_ingest/sources/base.py`
- `doc_ingest/sources/registry.py`

**Responsibilities:**

- define the common adapter contract
- aggregate source catalogs
- resolve a language name to a specific adapter plus `LanguageCatalog`
- provide suggestions for unmatched names
- deduplicate languages when enumerating all available entries

**Internal model:**

- `LanguageCatalog`
	- source metadata for a language entry
- `Document`
	- normalized document payload emitted by adapters
- `DocumentationSource`
	- protocol that each adapter must implement

**Resolution flow:**

1. normalize input language string
2. fetch cached or remote catalogs for all sources
3. apply source preference ordering
4. run exact / family / prefix / contains matching
5. return `(source_adapter, catalog_entry)` or `None`

### 4. Source adapters

**Files:**

- `doc_ingest/sources/devdocs.py`
- `doc_ingest/sources/mdn.py`
- `doc_ingest/sources/dash.py`
- `doc_ingest/sources/devdocs_core.json`

Each adapter implements the same external contract but uses a different internal fetch and parse strategy.

#### 4.1 DevDocs adapter

**Inputs:**

- `https://devdocs.io/docs.json`
- `https://documents.devdocs.io/<slug>/index.json`
- `https://documents.devdocs.io/<slug>/db.json`

**Pipeline:**

1. list available languages from `docs.json`
2. cache the catalog under `cache/catalogs/devdocs.json`
3. on fetch, ensure `index.json` and `db.json` exist and contain valid JSON
4. iterate DevDocs entries
5. optionally filter by core topic type in `important` mode
6. look up HTML content in `db.json`
7. select the primary content container, remove common navigation noise, rewrite relative links to source-absolute URLs, and convert HTML to Markdown with `markdownify`
8. emit `Document`

**Tradeoffs:**

- fast to ingest because DevDocs already ships structured datasets
- topic semantics are only as good as DevDocs `type` fields
- canonical documents are still deduplicated by base path, but upstream `#fragment` references are now preserved in emitted Markdown instead of being silently discarded

#### 4.2 MDN adapter

**Inputs:**

- GitHub tarball of `mdn/content`
- extracted `files/en-us/.../index.md` files

**Pipeline:**

1. discover MDN families by scanning the extracted `files/en-us/...` tree and persist the generated manifest under `cache/catalogs/mdn.json`
2. ensure the tarball is downloaded to `cache/mdn/mdn-content-main.tar.gz`
3. check `cache/mdn/cache_meta.json` for archive checksum, size, mtime, and ready areas
4. extract only relevant `files/en-us` trees into cache when metadata or area readiness is stale
5. locate each `index.md` file under the selected area
6. parse YAML frontmatter with `yaml.safe_load`
7. optionally filter by `page-type` in `important` mode
8. emit body content directly as Markdown in a `Document`

**Tradeoffs:**

- preserves Markdown source directly from MDN rather than converting rendered HTML
- live discovery is now the steady-state path, with cached-manifest fallback when upstream discovery fails
- extraction and storage cost are significantly larger than simple API-backed sources
- rich frontmatter is preserved for filtering and future metadata work, but only selected fields are used today

#### 4.3 Dash adapter

**Inputs:**

- `https://kapeli.com/feeds/<slug>.tgz`
- extracted `.docset`
- SQLite `docSet.dsidx`
- HTML pages in `Contents/Resources/Documents/`

**Pipeline:**

1. discover docset slugs from Kapeli’s official cheat-sheet index and persist the generated manifest under `cache/catalogs/dash.json`
2. download and extract the docset tarball if not cached
3. open the SQLite search index
4. iterate `(name, type, path)` rows ordered by type and name
5. optionally filter by type in `important` mode
6. read referenced HTML files
7. clean docset navigation noise, rewrite relative links to source URLs, and convert HTML to Markdown with `markdownify`
8. emit `Document`

**Tradeoffs:**

- broad language coverage through existing Dash docsets
- depends on live discovery from Kapeli’s public pages plus cached-manifest fallback
- assumes docset internals follow the standard structure

### 5. Compilation and formatting layer

**File:** `doc_ingest/compiler.py`

**Responsibilities:**

- collect normalized `Document` objects
- maintain lightweight topic/document manifests
- make per-topic directories as documents arrive
- assign unique, filesystem-safe slugs within each topic
- write per-document Markdown files during ingestion
- write temporary consolidated fragments during ingestion
- write topic section indexes
- write a language index
- stream a single consolidated Markdown file from fragments
- write `_meta.json`

**Formatting rules:**

- document headers include language, topic, and optional source URL
- consolidated output includes:
	- metadata
	- table of contents
	- full body content grouped by topic
- headings inside source documents are shifted down by two levels in consolidated output to fit under `####` sections
- repeated blank lines are collapsed

The stable compatibility contract for generated Markdown, `_meta.json`, state, checkpoints, diagnostics, and reports is defined in `documentation/output_contract.md`.

Phase 7 extends the compiler for downstream consumption:

- consolidated topic and document headings receive explicit deterministic anchors
- TOC links are generated from the same unique-anchor registry as emitted headings
- `--document-frontmatter` emits YAML metadata at the top of per-document Markdown files
- `--chunks` emits size-bounded Markdown chunks and `chunks/manifest.jsonl`
- `_meta.json` includes an optional `outputs` object only when optional outputs are enabled

Phase 8 extends validation and observability:

- validation checks internal anchors, duplicate topic/document sections, document heading counts, and source inventory reconciliation
- per-document validation records are emitted to `output/reports/validation_documents.jsonl`
- report history is persisted under `output/reports/history/`
- trend reports summarize validation, diagnostics, runtime telemetry, cache decisions, and failures
- structured document warnings and runtime telemetry are persisted on run reports/state when available

### 6. Validation layer

**File:** `doc_ingest/validator.py`

**Responsibilities:**

- validate that a consolidated file exists
- check minimum output size
- check for balanced code fences
- confirm required top-level sections exist
- report unresolved relative links, unresolved relative images, empty link targets, likely HTML leftovers, malformed table rows, and definition-list artifacts
- report missing internal anchors, duplicate sections/headings, and source-inventory mismatches
- produce document-local validation records for generated per-document Markdown files
- compute a simple heuristic quality score

This subsystem is intentionally lightweight. It validates output structure, not document correctness.

### 7. State and reporting layer

**Files:**

- `doc_ingest/state.py`
- `doc_ingest/reporting/writer.py`
- `doc_ingest/models.py`

**Responsibilities:**

- persist per-language run state to `state/<language>.json`
- persist active per-language checkpoints to `state/checkpoints/<language>.json`
- write run summary artifacts to `output/reports/`
- define the Pydantic models used for validation, state, and reporting
- preserve source diagnostics with discovered, emitted, and skipped document counts

**Persisted state contents:**

- language metadata
- source metadata
- mode
- topics and document counts
- output path
- completion status

**Active checkpoint contents:**

- language and source identifiers
- mode
- current phase: initialized, fetching, compiling, validating, completed, or failed
- last emitted document metadata
- current document inventory position from `Document.order_hint`
- emitted document count
- emitted document artifact manifest with per-document path and consolidated fragment path
- failure records with phase, error type, message, and document position

Successful runs remove the active checkpoint after the stable `LanguageRunState` is saved. Failed runs leave the checkpoint in place for inspection and automatic resume. A matching rerun resumes only when the checkpoint identity matches the current language/source/mode/output path and the durable per-document artifact files still exist. Missing temporary consolidated fragments are rebuilt from those durable document files; missing durable artifacts still force a safe replay from the start.

**Source diagnostics contents:**

- `discovered`: source inventory count observed by the adapter
- `emitted`: documents emitted by the source before pipeline topic filters
- `skipped`: reason-count map for source-level and pipeline-level skips

Pipeline topic filters add `filtered_topic_include` and `filtered_topic_exclude` skip reasons. Source adapters add reasons such as mode filtering, duplicate paths, missing files, missing content, and empty Markdown.

### 8. Progress and terminal presentation

**File:** `doc_ingest/progress.py`

**Responsibilities:**

- manage Rich `Live` display state
- track per-language progress counts
- render a progress panel plus language status table

This is presentation-only and does not affect the core pipeline.

## End-to-end execution pipeline

### Single-language run

1. CLI parses `run` arguments
2. `load_config()` resolves paths and creates directories
3. logging is configured to `logs/run.log`
4. `DocumentationService.run_language()` applies output/cache options and owns pipeline shutdown
5. `DocumentationPipeline.run()` resolves the requested language
6. selected source adapter fetches source documents, optionally with a resume boundary loaded from a valid checkpoint
7. `RunCheckpointStore` records active phase, per-document progress, and emitted artifact paths
8. pipeline-level topic include/exclude filters are applied if configured
9. `compile_from_stream()` consumes documents and writes output files
10. `validate_output()` scores the consolidated file
11. `RunStateStore.save()` persists language state and source diagnostics
12. the active checkpoint is removed after successful state save
13. `write_reports()` writes JSON and Markdown summaries
14. CLI prints a Rich summary table

### Bulk run

1. CLI expands a preset or enumerates all languages
2. `DocumentationPipeline.run_many()` wraps `run()` with a semaphore-limited task fan-out
3. each language is processed independently
4. all partial summaries are merged into a single `RunSummary`
5. final reports are written once after the gather completes

## Data-flow diagrams

### Single run data flow

```text
CLI request
	-> SourceRegistry.resolve()
	-> Source adapter fetch()
	-> Async stream of Document objects
	-> LanguageOutputBuilder.add()
	-> output/markdown/<language>/...
	-> validate_output()
	-> state/<language>.json
	-> output/reports/run_summary.{json,md}
```

### DevDocs flow

```text
docs.json
	-> language catalog entry
	-> index.json + db.json
	-> HTML blobs keyed by path
	-> markdownify
	-> Document(topic, slug, title, markdown, source_url)
```

### MDN flow

```text
GitHub tarball
	-> extracted content tree
	-> files/en-us/<area>/**/index.md
	-> frontmatter parse + page-type filter
	-> Document(..., markdown=body)
```

### Dash flow

```text
Kapeli .tgz
	-> extracted .docset
	-> docSet.dsidx searchIndex rows
	-> HTML file path lookup
	-> markdownify
	-> Document(...)
```

## Internal dependency graph

```text
DevDocsDownloader.py
	-> doc_ingest.cli

doc_ingest.cli
	-> doc_ingest.config
	-> doc_ingest.models
	-> doc_ingest.progress
	-> doc_ingest.services
	-> doc_ingest.sources.presets
	-> doc_ingest.sources.registry

doc_ingest.gui
	-> doc_ingest.services
	-> doc_ingest.gui.state

doc_ingest.services
	-> doc_ingest.pipeline
	-> doc_ingest.sources.registry

doc_ingest.pipeline
	-> doc_ingest.compiler
	-> doc_ingest.reporting
	-> doc_ingest.state
	-> doc_ingest.validator
	-> doc_ingest.sources.registry
	-> doc_ingest.utils.text

doc_ingest.sources.registry
	-> doc_ingest.sources.devdocs
	-> doc_ingest.sources.mdn
	-> doc_ingest.sources.dash
	-> installed devdocsdownloader.sources entry points

doc_ingest.compiler
	-> doc_ingest.utils.filesystem
	-> doc_ingest.utils.text
```

## External dependencies and roles

- `typer` — CLI definition
- `rich` — terminal UI and tables
- `pydantic` — run state and result models
- `httpx` — async HTTP downloads
- `markdownify` — HTML to Markdown conversion
- `beautifulsoup4` / `lxml` — source-specific HTML cleanup before conversion
- `PyYAML` — safe MDN frontmatter parsing
- `orjson` — optional fast JSON serialization
- `pytest` — test runner in the `dev` extra
- `ruff` — lint and format check in the `dev` extra
- `mypy` — pragmatic type-checking gate in the `dev` extra
- `nicegui` — optional local operator GUI in the `gui` extra
- `tiktoken` — optional tokenizer-aware chunking in the `tokenizer` extra
- `playwright` — optional browser package in the `browser` extra
- `psutil` — benchmark support in the `benchmark` extra

`pyproject.toml` is the canonical dependency manifest. The root `requirements.txt` and `source-documents/requirements.txt` files are compatibility shims only.

For local installation, `scripts/setup.py` is the recommended bootstrap entrypoint. Its default `full` profile creates
`.venv`, installs the runtime extras needed for GUI/browser/tokenizer/benchmark capabilities, installs Playwright
Chromium, and creates the runtime directory tree before first use.

## Concurrency model

### Active concurrency

- CLI uses `asyncio.run()` to enter async execution
- bulk processing uses `asyncio.gather()` plus a semaphore in `run_many()`
- document fetch within each source adapter is async at the adapter boundary
- CPU-bound conversion steps are offloaded with `asyncio.to_thread()` where used

### Concurrency limits

- language-level concurrency is configurable through `AppConfig.language_concurrency`
- bulk runs default to static language concurrency; opt-in adaptive mode adjusts new language starts from recent failures, retry pressure, and optional local resource pressure
- `SourceRuntime` applies per-profile semaphores and minimum request spacing around shared HTTP clients
- generated Markdown uses balanced atomic writes by default; state, checkpoints, reports, and cache/archive payloads retain strict fsync-backed writes
- source cache artifacts write `*.meta.json` sidecars where practical
- cache freshness policies are `use-if-present`, `ttl`, `always-refresh`, and `validate-if-possible`; `--force-refresh` remains the strongest override

## Design decisions and tradeoffs

### Why source adapters instead of a crawler

The code favors deterministic, source-specific data paths over broad site crawling. That reduces link-discovery complexity and yields more consistent output when a source already exposes structured exports.

### Why compile both per-document and consolidated outputs

- per-document files preserve smaller reusable chunks
- consolidated files are easier to feed into downstream tooling or language-level review workflows

### Why validation is lightweight

The validator is intended as a quick sanity pass, not a correctness proof. It is fast and simple, but it cannot detect semantic breakage or source incompleteness.

## Current architectural boundaries

- `DocumentationPipeline` owns a shared `SourceRuntime` and closes pooled HTTP clients at shutdown.
- `DocumentationService` exposes typed request/response models for CLI and GUI workflows. The GUI calls this service layer directly instead of shelling out to Typer.
- `DocumentationService` accepts an optional event sink for phase, document, warning, validation, telemetry, and failure events.
- GUI-safe service readers expose output bundles, report artifacts, checkpoints, and cache metadata with strict root-bound path resolution.
- `SourceRegistry` loads built-in DevDocs, MDN, and Dash adapters first, then discovers optional plugin adapters through Python entry points. Plugin load failures and duplicate built-in names are warnings, not hard failures.
- `SourceRuntime` owns retry policy, telemetry, and conservative source-profile throttling.
- Source adapters expose typed events through a compatibility-first event stream while retaining document-fetch compatibility.
- Compilation is split into planning, pure rendering, and writing behind the existing public compile API.
- The compiler builds an exact same-language target map for local cross-document links, writes optional asset inventories from adapter events, and supports optional token-bounded chunks when `tiktoken` is installed.
- Compilation can preload checkpointed artifact manifests, then append newly emitted documents after a resume boundary.
- Historical crawler path-analysis code is archived under `documentation/archive/`; the active product is the curated source-adapter ingester.
