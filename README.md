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
- Writes active per-language checkpoints under `state/checkpoints/` during runs and removes them after successful completion

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
	- Uses `doc_ingest/sources/dash_seed.json` because Dash does not expose a clean JSON catalog in this codebase
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

The stable generated-output contract is documented in `documentation/output_contract.md`.

### CLI capabilities

- Interactive wizard when run without a subcommand
- `run` for single-language ingestion
- `bulk` for preset or all-language runs
- `list-presets`
- `audit-presets`
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

`pyproject.toml` is the canonical dependency manifest. The root `requirements.txt` is a compatibility shim for users who expect a requirements file.

For development:

```bash
python -m pip install -e .[dev]
```

Optional extras:

- `analysis` — support for archived crawler path-analysis utilities
- `conversion-extended` — future PDF/DOCX conversion dependencies
- `browser` — Playwright package only
- `benchmark` — benchmark helper dependencies

### Optional helper setup

The repository includes `scripts/setup.py`, which creates `.venv`, installs the editable package with the `dev` extra, and creates current runtime directories.

```bash
python scripts/setup.py
python scripts/setup.py --extras dev,analysis,benchmark
python scripts/setup.py --extras dev,browser --with-playwright-browser
```

Playwright Chromium is not installed by default.

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
python DevDocsDownloader.py run python --include-topic asyncio --include-topic typing
python DevDocsDownloader.py run swift --exclude-topic Guide
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

### Run live endpoint probes

Routine tests do not use the network. To verify that configured upstream source URLs are still reachable without downloading full languages, run the opt-in live probe suite:

```powershell
$env:DEVDOCS_LIVE_TESTS='1'; python -m pytest -m live -q
```

Optional controls:

- `DEVDOCS_LIVE_CONCURRENCY` — concurrent live probes, default `5`
- `DEVDOCS_LIVE_TIMEOUT` — request timeout in seconds, default `20`
- `DEVDOCS_LIVE_LIMIT` — maximum number of probes, useful while debugging

The live probes check one representative endpoint per configured language/source entry. DevDocs probes each language `index.json`, MDN probes one raw `index.md` for each configured area, and Dash probes each configured `.tgz` feed with a capped ranged request. They validate link health only; they do not compile output or verify extraction quality.

### Developer checks

```bash
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m mypy doc_ingest
```

### List languages and presets

```bash
python DevDocsDownloader.py list-languages
python DevDocsDownloader.py list-presets
python DevDocsDownloader.py audit-presets
python DevDocsDownloader.py audit-presets webapp
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

### Topic filter behavior

- `--include-topic` limits output to documents whose normalized topic exactly matches one of the supplied values
- `--exclude-topic` removes documents whose normalized topic exactly matches one of the supplied values
- include filters run before exclude filters
- filtered documents are counted in source diagnostics as `filtered_topic_include` or `filtered_topic_exclude`

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

### Checkpoint behavior

During an active language run, the pipeline writes `state/checkpoints/<language>.json` with the source slug, mode, current phase, emitted document count, last document metadata, and any failure records. A successful run persists the stable summary to `state/<language>.json` and removes the active checkpoint. A failed run leaves the checkpoint in place so the last safe document boundary and failure phase can be inspected before retrying.

### Source diagnostics behavior

Each run records source diagnostics in reports and final state:

- `discovered` — source inventory count observed by the adapter
- `emitted` — documents emitted by the source before pipeline topic filters
- `skipped` — reason-count map for source-level and pipeline-level skips

Common skip reasons include mode filtering, duplicate paths, missing content, empty converted Markdown, and topic include/exclude filtering.

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
- `DocumentationPipeline.close()` releases shared source-runtime HTTP clients
- Bulk runs gather all language tasks via `asyncio.gather`, with only semaphore-based concurrency limiting at the pipeline layer
- Checkpoints expose the last emitted document boundary, but adapters do not yet support seeking directly to that position on retry

### Source-specific limitations

- **DevDocs**
	- Deduplicates by path without fragment, so fragment-level sections are dropped
	- Treats DevDocs entry `type` as the topic label
- **MDN**
	- Only six MDN areas are exposed in the catalog
	- Frontmatter parsing is minimal and ignores indented or complex YAML structures
	- Archive extraction is large and disk-heavy
- **Dash**
	- Catalog coverage is limited to `doc_ingest/sources/dash_seed.json` unless the seed is extended
	- SQLite index structure is assumed to match the expected `searchIndex` schema
	- HTML conversion may include navigation noise depending on docset quality

### Repository consistency notes

- `scripts/benchmark_pipeline.py` now targets the active source-adapter CLI and reports document throughput for cold and warm cache trials.
- `scripts/build_skip_manifest.py` now writes a current state and checkpoint manifest from `state/*.json` and `state/checkpoints/*.json`; URL-level crawler skip manifests are not part of the active pipeline.
- `pyproject.toml` is the canonical dependency manifest; `requirements.txt` and `source-documents/requirements.txt` are compatibility shims.
- Extended conversion, browser, analysis, benchmark, and developer packages are optional extras instead of baseline runtime dependencies.

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

1. Add adapter-level resume from checkpoints
2. Reduce generated-Markdown fsync overhead with durability modes
3. Add per-source concurrency and rate limits
4. Improve Markdown cleanup and validation depth

## Documentation map

- `documentation/architecture.md` — subsystem and pipeline design
- `documentation/codemap.md` — file-by-file navigation guide
- `documentation/development_progress.md` — implementation status and known gaps
- `documentation/full-project-documentation.md` — detailed technical reference
