# Architecture

## Overview

`DevDocsDownloader` is built as a source-adapter ingestion pipeline rather than a generic crawler. The runtime path is centered on resolving a requested language to a known upstream catalog, fetching source-exported documentation artifacts, converting them to Markdown, writing a structured output tree, and validating the result.

The active code path lives entirely under `doc_ingest/` plus the top-level bootstrap file `DevDocsDownloader.py`.

## System sketch

```text
user command
	-> doc_ingest.cli
	-> DocumentationPipeline
	-> SourceRegistry
	-> {DevDocs | MDN | Dash} adapter
	-> Document stream
	-> LanguageOutputBuilder
	-> output/state/reports
```

## Architectural style

### Primary pattern

- **Adapter-based ingestion pipeline**
	- A shared orchestration layer delegates source-specific work to adapter classes
	- All adapters normalize their output into the same `Document` dataclass

### Supporting patterns

- **Registry pattern** via `SourceRegistry`
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
- initialize config, logging, progress tracking, and the pipeline
- render terminal summaries with Rich

**Key behavior:**

- `DevDocsDownloader.py` is a thin bootstrap that imports `app` and executes it
- `doc_ingest/cli.py` owns all user-facing commands
- single-language runs and bulk runs both eventually call into `DocumentationPipeline`

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

The config surface is intentionally small. There is no environment-variable config layer, no settings file, and no runtime plugin system in the current code.

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
7. convert HTML to Markdown with `markdownify`
8. emit `Document`

**Tradeoffs:**

- fast to ingest because DevDocs already ships structured datasets
- topic semantics are only as good as DevDocs `type` fields
- fragment-level granularity is discarded by deduplicating on path without `#fragment`

#### 4.2 MDN adapter

**Inputs:**

- GitHub tarball of `mdn/content`
- extracted `files/en-us/.../index.md` files

**Pipeline:**

1. expose a static catalog for selected MDN areas
2. ensure the tarball is downloaded to `cache/mdn/mdn-content-main.tar.gz`
3. extract only relevant `files/en-us` trees into cache
4. locate each `index.md` file under the selected area
5. parse simple YAML-like frontmatter
6. optionally filter by `page-type` in `important` mode
7. emit body content directly as Markdown in a `Document`

**Tradeoffs:**

- preserves Markdown source directly from MDN rather than converting rendered HTML
- extraction and storage cost are significantly larger than simple API-backed sources
- frontmatter parsing is intentionally shallow and may miss complex metadata

#### 4.3 Dash adapter

**Inputs:**

- `https://kapeli.com/feeds/<slug>.tgz`
- extracted `.docset`
- SQLite `docSet.dsidx`
- HTML pages in `Contents/Resources/Documents/`

**Pipeline:**

1. expose a seeded catalog of docset slugs
2. download and extract the docset tarball if not cached
3. open the SQLite search index
4. iterate `(name, type, path)` rows ordered by type and name
5. optionally filter by type in `important` mode
6. read referenced HTML files
7. convert HTML to Markdown with `markdownify`
8. emit `Document`

**Tradeoffs:**

- broad language coverage through existing Dash docsets
- depends on a seeded catalog rather than discovery
- assumes docset internals follow the standard structure

### 5. Compilation and formatting layer

**File:** `doc_ingest/compiler.py`

**Responsibilities:**

- collect normalized `Document` objects
- group them by topic
- make per-topic directories
- assign unique, filesystem-safe slugs within each topic
- write per-document Markdown files
- write topic section indexes
- write a language index
- write a single consolidated Markdown file
- write `_meta.json`

**Formatting rules:**

- document headers include language, topic, and optional source URL
- consolidated output includes:
	- metadata
	- table of contents
	- full body content grouped by topic
- headings inside source documents are shifted down by two levels in consolidated output to fit under `####` sections
- repeated blank lines are collapsed

### 6. Validation layer

**File:** `doc_ingest/validator.py`

**Responsibilities:**

- validate that a consolidated file exists
- check minimum output size
- check for balanced code fences
- confirm required top-level sections exist
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
- failure records with phase, error type, message, and document position

Successful runs remove the active checkpoint after the stable `LanguageRunState` is saved. Failed runs leave the checkpoint in place for inspection before retrying.

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
4. `DocumentationPipeline.run()` resolves the requested language
5. selected source adapter fetches source documents
6. `RunCheckpointStore` records active phase and per-document progress
7. pipeline-level topic include/exclude filters are applied if configured
8. `compile_from_stream()` consumes documents and writes output files
9. `validate_output()` scores the consolidated file
10. `RunStateStore.save()` persists language state and source diagnostics
11. the active checkpoint is removed after successful state save
12. `write_reports()` writes JSON and Markdown summaries
13. CLI prints a Rich summary table

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
	-> doc_ingest.pipeline
	-> doc_ingest.progress
	-> doc_ingest.sources.presets
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
- `orjson` — optional fast JSON serialization
- `lxml` / `beautifulsoup4` — not in active runtime path, but used by support scripts
- `pytest` — test runner

Dependencies present in manifests but not used by the active pipeline include `docling`, `playwright`, `psutil`, `tenacity`, `mammoth`, `msgpack`, and `pypdf`.

## Concurrency model

### Active concurrency

- CLI uses `asyncio.run()` to enter async execution
- bulk processing uses `asyncio.gather()` plus a semaphore in `run_many()`
- document fetch within each source adapter is async at the adapter boundary
- CPU-bound conversion steps are offloaded with `asyncio.to_thread()` where used

### Concurrency limits

- only language-level concurrency is configurable through `AppConfig.language_concurrency`
- there is no explicit per-source HTTP rate limiting, retry policy, or backoff logic in the active adapters

## Design decisions and tradeoffs

### Why source adapters instead of a crawler

The code favors deterministic, source-specific data paths over broad site crawling. That reduces link-discovery complexity and yields more consistent output when a source already exposes structured exports.

### Why compile both per-document and consolidated outputs

- per-document files preserve smaller reusable chunks
- consolidated files are easier to feed into downstream tooling or language-level review workflows

### Why validation is lightweight

The validator is intended as a quick sanity pass, not a correctness proof. It is fast and simple, but it cannot detect semantic breakage or source incompleteness.

## Architectural uncertainties and incomplete areas

- Some local settings and historical utilities still refer to a previous crawler architecture with inputs such as `input_file`, crawl caches, and per-page throughput metrics. Those components are not implemented in the active `doc_ingest` package.
- `DocumentationPipeline.close()` does not release any shared adapter resources because no long-lived clients are retained.
- The codebase mixes a coherent ingestion runtime with historical benchmarking/setup artifacts. Any future cleanup should explicitly choose which architecture is canonical.
