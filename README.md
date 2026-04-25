# DevDocsDownloader

`DevDocsDownloader` is a Python CLI that downloads official programming-language documentation from curated upstream sources and compiles it into local Markdown bundles. The active implementation resolves a language against catalogs from DevDocs, MDN, and Dash/Kapeli, fetches source data, converts or normalizes content into Markdown, organizes documents by topic, emits a consolidated language file, and writes lightweight validation and run reports.

The runtime path is usable today for those three source families. The repository also contains older helper scripts that reflect a broader crawler-oriented design no longer present in the active execution path. Those mismatches are called out explicitly below.

## What the project does

- Resolves a requested language to one of three documentation sources:
	- `devdocs`
	- `mdn`
	- `dash`
- Downloads source catalogs and caches them locally under `cache/`
- Fetches source content for one language or many languages
- Converts upstream HTML or Markdown content into normalized Markdown
- Groups documents by topic and writes:
	- per-document Markdown files
	- topic section indexes
	- a language index
	- a single consolidated Markdown file per language
	- metadata JSON for each compiled language bundle
- Validates the compiled output with a simple structural scoring pass
- Produces JSON and Markdown run summaries in `output/reports/`

## Current feature set

### Ingestion sources

- **DevDocs**
	- Reads `docs.json` from `https://devdocs.io/docs.json`
	- Downloads `index.json` and `db.json` for a resolved slug from `https://documents.devdocs.io`
	- Filters to configured “core” topic types in `important` mode using `doc_ingest/sources/devdocs_core.json`
- **MDN**
	- Treats supported MDN areas as a fixed catalog: JavaScript, HTML, CSS, Web APIs, HTTP, and WebAssembly
	- Downloads the MDN content repository tarball from GitHub and extracts only the relevant `files/en-us/...` trees into cache
	- Reads frontmatter from `index.md` files and filters by `page-type` in `important` mode
- **Dash / Kapeli**
	- Uses a bundled seed catalog because Dash does not expose a clean JSON catalog in this codebase
	- Downloads `.tgz` docsets, extracts them, reads the SQLite `docSet.dsidx` index, and converts HTML files from the embedded `Documents/` tree

### Output layout

For a language such as Python, the pipeline writes output under:

`output/markdown/python/`

Typical generated files:

- `index.md` — language-level index
- `python.md` — consolidated language documentation file
- `_meta.json` — generation metadata
- `<topic>/_section.md` — topic index
- `<topic>/<document>.md` — one Markdown file per source document

### CLI capabilities

- Interactive wizard when run without a subcommand
- `run` for single-language ingestion
- `bulk` for preset or all-language runs
- `list-presets`
- `list-languages`
- `refresh-catalogs`
- `validate`
- `init`

## High-level architecture

The active architecture is a small async ingestion pipeline:

1. **CLI layer** in `doc_ingest/cli.py`
2. **Source resolution layer** in `doc_ingest/sources/registry.py`
3. **Source adapters** in `doc_ingest/sources/*.py`
4. **Compilation layer** in `doc_ingest/compiler.py`
5. **Validation and reporting** in `doc_ingest/validator.py` and `doc_ingest/reporting/writer.py`
6. **Filesystem/state utilities** in `doc_ingest/config.py`, `doc_ingest/state.py`, and `doc_ingest/utils/`

This is not a generic crawler in its current form. It is a source-adapter pipeline built around source-specific export formats.

```text
CLI
	-> source registry
	-> source adapter
	-> normalized Document stream
	-> compiler
	-> validator + reports
```

## Installation

### Requirements

- Python 3.11+
- Network access to the selected upstream documentation sources
- Enough disk space for cached source datasets, especially for MDN and Dash docsets

### Install with `pip`

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### Optional helper setup

The repository includes `scripts/setup.py`, which creates a virtual environment, installs dependencies from `source-documents/requirements.txt`, and installs the Chromium browser for Playwright. That script appears to belong to an earlier, broader crawler workflow; it is not required by the active `doc_ingest` pipeline.

## Usage

### Show help

```bash
python DevDocsDownloader.py --help
```

### Download one language

```bash
python DevDocsDownloader.py run python
python DevDocsDownloader.py run javascript --source mdn --mode full
python DevDocsDownloader.py run swift --source dash
```

### Run the interactive wizard

```bash
python DevDocsDownloader.py
```

### Download a preset bundle

```bash
python DevDocsDownloader.py bulk webapp
python DevDocsDownloader.py bulk backend --mode full
```

### Download every available language

```bash
python DevDocsDownloader.py bulk all --mode important --yes
```

### Validate an existing compiled bundle

```bash
python DevDocsDownloader.py validate python
```

### List languages and presets

```bash
python DevDocsDownloader.py list-languages
python DevDocsDownloader.py list-presets
```

## Execution behavior

### Resolution rules

- If `--source` is given, the pipeline only checks that source
- Without a source override, the registry prefers:
	- MDN first for `html`, `css`, `http`, `web-apis`, and `webassembly`
	- DevDocs first for everything else
	- Dash as a fallback
- Resolution uses exact, family, prefix, and contains matching against display name and slug

### Mode behavior

- `important`
	- Filters documents by source-specific core topics
	- DevDocs uses `devdocs_core.json`
	- MDN uses selected `page-type` values
	- Dash uses predefined entry types such as `Class`, `Function`, `Guide`, and similar
- `full`
	- Ingests all available entries exposed by the selected source adapter

### Validation behavior

Compiled output is scored by `doc_ingest/validator.py` using simple checks:

- output file exists
- total documents is non-zero
- file size is at least 2000 bytes
- code fences are balanced
- required sections exist:
	- `## Metadata`
	- `## Table of Contents`
	- `## Documentation`

The validation score is heuristic. It does not verify semantic correctness or source completeness.

## Repository layout

```text
DevDocsDownloader.py         # top-level entry point
doc_ingest/                 # active package
documentation/              # project documentation files
scripts/                    # helper and historical support scripts
tests/                      # focused regression tests
benchmarks/                 # benchmark corpora
source-documents/           # legacy support requirements and inputs
```

## Limitations and known issues

### Active pipeline limitations

- Output quality depends entirely on upstream source structure and `markdownify`
- The compiler does not preserve source navigation hierarchy beyond topic grouping
- Validation is shallow and does not inspect broken links, duplicated sections, or malformed converted Markdown beyond unbalanced fences
- `DocumentationPipeline.close()` is effectively a no-op because source adapters open short-lived clients instead of maintaining pooled clients
- Bulk runs gather all language tasks via `asyncio.gather`, with only semaphore-based concurrency limiting at the pipeline layer

### Source-specific limitations

- **DevDocs**
	- Deduplicates by path without fragment, so fragment-level sections are dropped
	- Treats DevDocs entry `type` as the topic label
- **MDN**
	- Only six MDN areas are exposed in the catalog
	- Frontmatter parsing is minimal and ignores indented or complex YAML structures
	- Archive extraction is large and disk-heavy
- **Dash**
	- Catalog coverage is limited to the bundled seed list unless the seed is extended
	- SQLite index structure is assumed to match the expected `searchIndex` schema
	- HTML conversion may include navigation noise depending on docset quality

### Repository consistency issues

- Several scripts reference modules, config fields, and CLI flags that do not exist in the active codebase, including:
	- `doc_ingest.parser`
	- `config.paths.input_file`
	- `config.paths.crawl_cache_dir`
	- CLI flags such as `--input-file`, `--page-concurrency`, and `--compile-streaming`
- `requirements.txt` contains packages such as `mammoth`, `msgpack`, `pypdf`, `playwright`, `psutil`, and `tenacity` that are not used by the active ingestion path
- `pyproject.toml` and `requirements.txt` do not match exactly on dependency versions or package set
- `scripts/benchmark_pipeline.py` targets an older crawler/performance model and is not compatible with the current CLI

## Testing

Run the test suite with:

```bash
pytest
```

The current tests focus on:

- source cache resilience
- concurrency behavior in `run_many`
- slug safety on Windows paths
- docset/tarball failure handling

## Future direction

The most realistic next steps, based on the current repository state, are:

1. Remove or update the stale crawler-era scripts and config references
2. Reconcile dependency manifests
3. Improve Markdown cleanup and validation depth
4. Add deterministic tests for complete source adapter flows
5. Decide whether the project should remain a curated source ingester or return to a general crawler architecture

## Documentation map

- `documentation/architecture.md` — subsystem and pipeline design
- `documentation/codemap.md` — file-by-file navigation guide
- `documentation/development_progress.md` — implementation status and known gaps
- `documentation/full-project-documentation.md` — detailed technical reference
