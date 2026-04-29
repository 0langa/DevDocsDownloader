# DevDocsDownloader

`DevDocsDownloader` is a documentation ingestion engine with a Windows desktop release path and a Python automation surface. The active implementation resolves a language against catalogs from DevDocs, MDN, and Dash/Kapeli, fetches source data, converts or normalizes content into Markdown, organizes documents by topic, emits a consolidated language file, and writes validation, diagnostics, and run reports.

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
- Optionally emits YAML frontmatter and retrieval-friendly Markdown chunks with JSONL manifests
- Validates the compiled output with a simple structural scoring pass
- Produces JSON and Markdown run summaries in `output/reports/`
- Produces additive per-document validation, report history, and quality trend artifacts
- Writes active per-language checkpoints under `state/checkpoints/` during runs and removes them after successful completion

## Current feature set

### Ingestion sources

- **DevDocs**
	- Reads `docs.json` from `https://devdocs.io/docs.json`
	- Downloads `index.json` and `db.json` for a resolved slug from `https://documents.devdocs.io`
	- Filters to configured “core” topic types in `important` mode using `doc_ingest/sources/devdocs_core.json`
- **MDN**
	- Discovers documentation families by scanning the MDN content tree and writes a generated manifest under `cache/catalogs/mdn.json`
	- Uses live discovery plus cached-manifest fallback; supported families currently include JavaScript, HTML, CSS, Web APIs, HTTP, and WebAssembly, while newly discovered families remain visible as experimental entries in catalog audits
	- Downloads the MDN content repository tarball from GitHub and extracts only the relevant `files/en-us/...` trees into cache, guarded by checksum and area-readiness metadata
	- Reads frontmatter from `index.md` files and filters by `page-type` in `important` mode
- **Dash / Kapeli**
	- Discovers docsets from Kapeli’s official cheat-sheet index and writes a generated manifest under `cache/catalogs/dash.json`
	- Uses live discovery plus cached-manifest fallback instead of a hand-maintained built-in seed catalog
	- Downloads `.tgz` docsets, extracts them, reads the SQLite `docSet.dsidx` index, and converts HTML files from the embedded `Documents/` tree

### Output layout

For a language such as Python, the pipeline writes output under:

`output/markdown/python/`

Typical generated files:

- `index.md` — language-level index
- `python.md` — consolidated language documentation file
- `_meta.json` — generation metadata
- `chunks/manifest.jsonl` and `chunks/*.md` — optional retrieval chunk export
- `<topic>/_section.md` — topic index
- `<topic>/<document>.md` — one Markdown file per source document

The stable generated-output contract is documented in `documentation/output_contract.md`.

### User surfaces

- Interactive wizard when run without a subcommand
- `run` for single-language ingestion
- `bulk` for preset or all-language runs
- `list-presets`
- `audit-presets`
- `list-languages`
- `refresh-catalogs`
- `audit-catalogs`
- `validate`
- `init`
- desktop backend worker for the WinUI 3 shell
- `gui` (legacy NiceGUI operator UI kept for migration/internal use)

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

### Recommended full setup

Run the central setup script before first use:

```bash
python scripts/setup.py
```

This is the primary installation path. By default it:

- creates `.venv`
- installs the editable package with full runtime capability extras: `gui`, `browser`, `benchmark`, and `tokenizer`
- installs Playwright Chromium so browser-backed functionality is actually available
- creates the runtime directories under `output/`, `cache/`, `logs/`, `state/`, and `tmp/`

Useful variants:

```bash
python scripts/setup.py --profile minimal
python scripts/setup.py --profile dev
python scripts/setup.py --skip-playwright-browser
python scripts/setup.py --profile full --extras analysis
```

Profiles:

- `full` — default; installs everything needed for the full user-facing runtime feature set
- `dev` — full runtime plus developer tools (`pytest`, `ruff`, `mypy`)
- `minimal` — base runtime only, without optional GUI/browser/tokenizer/benchmark features

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
- `browser` — Playwright package
- `benchmark` — benchmark helper dependencies
- `gui` — legacy NiceGUI operator interface retained for migration/internal use
- `tokenizer` — optional tiktoken-backed retrieval chunking

### Optional helper setup

The repository includes `scripts/setup.py`, which is the recommended bootstrap entrypoint. It creates `.venv`,
installs the selected capability profile, installs Playwright Chromium by default for full setups, and creates current
runtime directories.

```bash
python scripts/setup.py
python scripts/setup.py --profile dev
python scripts/setup.py --profile minimal
python scripts/setup.py --profile full --extras analysis
```

For manual installs, Playwright Chromium is not installed automatically. Run `python -m playwright install chromium`
if you install the `browser` extra outside the setup script.

## Windows Desktop Release

The `1.0.0` product direction is a native Windows desktop application in `desktop/DevDocsDownloader.Desktop/`.

Release architecture:

- `WinUI 3 + .NET 8` desktop shell
- bundled frozen Python backend worker
- local `127.0.0.1` HTTP API with bearer-token auth
- persistent shell state across navigation, with shared live progress and activity logs
- structured operator views for languages, presets, reports, output bundles, checkpoints, and cache metadata
- GitHub Release artifacts:
  - `DevDocsDownloader-Setup-1.0.6.exe`
  - `DevDocsDownloader-Portable-1.0.6.zip`

The backend API host lives in `doc_ingest/desktop_backend.py`. Release packaging scripts, installer definitions, and workflows live under `scripts/`, `desktop/installer/`, and `.github/workflows/`.

Desktop defaults:

- output root: `%UserProfile%\\Documents\\DevDocsDownloader`
- generated Markdown: `%UserProfile%\\Documents\\DevDocsDownloader\\markdown`
- reports: `%UserProfile%\\Documents\\DevDocsDownloader\\reports`
- cache/state/logs/tmp/settings: `%LocalAppData%\\DevDocsDownloader\\...`

If the desktop shell fails before showing the window, check `%LocalAppData%\DevDocsDownloader\logs\desktop-shell.log` and `%LocalAppData%\DevDocsDownloader\logs\desktop-backend.log`.

## CLI Guide

The CLI is the primary automation interface. It supports one-language runs, preset/all-language bulk runs, validation-only checks, source catalog inspection, cache policy controls, output options, and optional adaptive bulk scheduling.

### Show help and initialize directories

```bash
python DevDocsDownloader.py --help
python DevDocsDownloader.py run --help
python DevDocsDownloader.py bulk --help
python DevDocsDownloader.py gui --help
python DevDocsDownloader.py init
```

The root and sub-command help pages are intended to be usable as an operator reference. They explain source
resolution, modes, cache policy, resume/checkpoint behavior, output files, chunking, adaptive bulk scheduling, and
common examples.

### Run one language

```bash
python DevDocsDownloader.py run python
python DevDocsDownloader.py run javascript --source mdn --mode full
python DevDocsDownloader.py run swift --source dash
```

Common run options:

```bash
python DevDocsDownloader.py run python --include-topic asyncio --include-topic typing
python DevDocsDownloader.py run swift --exclude-topic Guide
python DevDocsDownloader.py run python --document-frontmatter --chunks
python DevDocsDownloader.py run python --chunks --chunk-strategy tokens --chunk-max-tokens 800
python DevDocsDownloader.py run python --cache-policy ttl --cache-ttl-hours 24
```

### Run bulk downloads

```bash
python DevDocsDownloader.py bulk webapp
python DevDocsDownloader.py bulk backend --mode full
python DevDocsDownloader.py bulk all --mode important --yes
```

Bulk runs default to static language concurrency. Adaptive scheduling is opt-in:

```bash
python DevDocsDownloader.py bulk webapp --language-concurrency 3
python DevDocsDownloader.py bulk webapp --concurrency-policy adaptive --adaptive-min-concurrency 1 --adaptive-max-concurrency 6
```

Bulk output options match single-language runs:

```bash
python DevDocsDownloader.py bulk webapp --chunks --chunk-max-chars 6000
python DevDocsDownloader.py bulk webapp --chunks --chunk-strategy tokens --chunk-max-tokens 800
```

### Validate existing output

```bash
python DevDocsDownloader.py validate python
```

### Inspect catalogs and presets

```bash
python DevDocsDownloader.py list-languages
python DevDocsDownloader.py list-languages --source mdn
python DevDocsDownloader.py refresh-catalogs
python DevDocsDownloader.py audit-catalogs
python DevDocsDownloader.py list-presets
python DevDocsDownloader.py audit-presets
python DevDocsDownloader.py audit-presets webapp
```

### Interactive wizard

```bash
python DevDocsDownloader.py
```

## Legacy NiceGUI Guide

The older local NiceGUI surface remains in the repo as a migration and internal operator tool. It is no longer the primary public GUI direction for `1.0.0`, which is the WinUI desktop app.

### Install and launch

```bash
python -m pip install -e .[gui]
python DevDocsDownloader.py gui
python DevDocsDownloader.py gui --host 127.0.0.1 --port 8080
python DevDocsDownloader.py gui --output-dir output
```

The GUI is a local operator interface. It calls `DocumentationService` in-process and does not shell out to CLI commands for core operations. Do not expose it as a public multi-user web service.

### GUI workflows

- **Run:** configure a single language, source, mode, topic filters, cache policy, frontmatter, chunks, and validation-only runs.
- **Bulk:** run presets or all languages with static or adaptive concurrency.
- **Languages:** list available source catalog entries.
- **Presets/Audit:** inspect preset coverage and unresolved languages.
- **Reports:** inspect latest reports, validation records, history, and trends.
- **Output Browser:** browse generated language bundles, per-document Markdown, consolidated manuals, chunks, manifests, and metadata.
- **Checkpoints:** inspect failed/active checkpoints and safely delete selected checkpoint files.
- **Cache:** inspect cache metadata sidecars and refresh catalogs.
- **Settings/Help:** read the built-in operator tutorial covering the full workflow, expected behavior, failure modes, cache/resume semantics, report interpretation, and CLI equivalents.

## WinUI Desktop UX

The WinUI desktop shell is the primary end-user GUI.

- Tabs keep their state when switching between Run, Bulk, Languages, Reports, Output Browser, Checkpoints, Cache, and Settings.
- The left shell shows backend readiness, output root, live job progress, the current activity line, and warning/failure counts.
- Run and Bulk pages reuse the same live job monitor, so progress remains visible while browsing other tabs.
- Languages uses a searchable tree view with `source-first` and `category-first` grouping; selections can prefill Run or Bulk.
- Output Browser loads bundles from the current output root automatically and remembers the last selected bundle/file.
- Settings persists desktop defaults such as output root, cache policy, language-tree mode, last output selection, and selected preset.

## Live Probe Guide

Routine tests do not use the network. To verify that configured upstream source URLs are still reachable without downloading full languages, run the opt-in live probe suite:

```powershell
$env:DEVDOCS_LIVE_TESTS='1'; python -m pytest -m live -q
```

Optional controls:

- `DEVDOCS_LIVE_CONCURRENCY` — concurrent live probes, default `5`
- `DEVDOCS_LIVE_TIMEOUT` — request timeout in seconds, default `20`
- `DEVDOCS_LIVE_LIMIT` — maximum number of probes, useful while debugging

The live probes check one representative endpoint per configured language/source entry. DevDocs probes each language `index.json`, MDN probes a representative discovered family, and Dash probes discovered `.tgz` feeds with capped ranged requests. They validate link health only; they do not compile output or verify extraction quality.

For a bounded extraction sanity tier that checks one representative source-family conversion path without compiling full languages:

```powershell
$env:DEVDOCS_LIVE_EXTRACTION_TESTS='1'; python -m pytest -m live tests\test_live_extraction_sanity.py -q
```

This fetches a DevDocs document payload, one MDN raw `index.md`, and a capped Dash archive probe plus local Dash conversion fixture. It catches upstream shape drift but is not a full extraction correctness check.

GitHub Actions also runs a separate scheduled `live-drift` workflow that writes machine-readable JSON artifacts for endpoint and bounded extraction drift triage.

## Developer Checks

```bash
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m mypy doc_ingest
```

## Execution behavior

### Resolution rules

- If `--source` is given, the pipeline only checks that source
- Without a source override, the registry prefers:
	- MDN first for `html`, `css`, `http`, `web-apis`, and `webassembly`
	- DevDocs first for everything else
	- Dash as a fallback
- Resolution uses exact, family, prefix, and contains matching against display name and slug
- Resolution also considers source-provided aliases from discovery manifests, such as MDN `web-apis` resolving from `api` or `web api`

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
- internal table-of-contents links point to emitted anchors
- duplicate topic/document headings and malformed heading hierarchy are reported
- source diagnostics reconcile discovered, emitted, skipped, and compiled document counts where available
- generated per-document files are scanned for local conversion/link issues

The validation score is heuristic. It does not verify semantic correctness or source completeness.

### Checkpoint behavior

During an active language run, the pipeline writes `state/checkpoints/<language>.json` with the source slug, mode, current phase, emitted document count, last document metadata, emitted artifact manifest, and any failure records. A successful run persists the stable summary to `state/<language>.json` and removes the active checkpoint. A failed run leaves the checkpoint in place so the next matching run can automatically resume after the last safe document boundary when the saved per-document files are still present. Missing temporary consolidated fragments are rebuilt from durable per-document files during resume; missing durable documents still trigger a safe replay from the start.

### Source diagnostics behavior

Each run records source diagnostics in reports and final state:

- `discovered` — source inventory count observed by the adapter
- `emitted` — documents emitted by the source before pipeline topic filters
- `skipped` — reason-count map for source-level and pipeline-level skips

Common skip reasons include mode filtering, duplicate paths, missing content, empty converted Markdown, and topic include/exclude filtering.

### Performance and durability behavior

Generated Markdown files are still written through atomic temp-file replacement, but they use balanced durability by default to avoid an `fsync()` on every per-document file and fragment. State files, active checkpoints, reports, downloaded archives, and cache payloads keep strict durability.

`SourceRuntime` applies conservative source-profile throttling around HTTP requests and archive downloads. Operational overrides are available through `DEVDOCS_SOURCE_CONCURRENCY` and `DEVDOCS_SOURCE_MIN_DELAY`.

Bulk runs default to static language concurrency. `--concurrency-policy adaptive` enables conservative adaptive scheduling that reduces new language starts after failures, retry pressure, or local resource pressure, and increases slowly after successful windows. Adaptive mode remains opt-in.

### Output and downstream consumption behavior

Consolidated manuals include explicit stable anchors before topic and document headings. The table of contents uses the same anchor registry, so repeated headings receive deterministic suffixes such as `repeat` and `repeat-2`.

Optional per-document YAML frontmatter is enabled with `--document-frontmatter`. It records language/source identity, topic, slug, title, order hint, mode, source URL, and generation timestamp while preserving the existing human-readable metadata lines.

Optional retrieval chunks are enabled with `--chunks`. The compiler writes size-bounded Markdown chunks under `output/markdown/<language>/chunks/` and a `manifest.jsonl` file with stable chunk IDs, source references, topic metadata, document metadata, text paths, and character offsets.

Character chunking is the default. Token chunking is opt-in and requires:

```bash
python -m pip install -e .[tokenizer]
python DevDocsDownloader.py run python --chunks --chunk-strategy tokens
```

Known same-language document links are rewritten to local generated Markdown paths when the compiler can match the target exactly from source URLs or known source paths. Unknown links keep the existing source-absolute behavior.

When adapters emit `AssetEvent` records with bytes or safe local files, the compiler writes deduplicated assets under `output/markdown/<language>/assets/`, writes `assets/manifest.json`, and rewrites matching Markdown references to local asset paths. Asset records without local payload are inventoried but are not fetched by the compiler.

### Cache freshness behavior

`--cache-policy` controls source cache reuse:

- `use-if-present` keeps the historical default behavior
- `ttl` refreshes cache entries older than `--cache-ttl-hours`
- `always-refresh` refreshes source cache artifacts each run
- `validate-if-possible` records the intent and falls back to local cache when a source-specific validator is unavailable

`--force-refresh` remains the strongest override. Source cache artifacts write sidecar `*.meta.json` files with fetched timestamp, URL, ETag/Last-Modified when available, checksum, byte count, and policy.

### Desktop and service boundary

`doc_ingest.services.DocumentationService` exposes typed request and response models for run, bulk run, list, audit, refresh, validation-only, runtime inspection, output bundle browsing, report reading, checkpoint inspection/deletion, and cache metadata workflows. The new desktop backend host in `doc_ingest.desktop_backend` exposes these workflows over a local loopback HTTP API for the WinUI shell, while the older NiceGUI surface remains a migration-only interface.

The service layer also accepts an optional event sink for phase, document, warning, validation, runtime telemetry, and failure events. The desktop backend uses that signal path for SSE job streams. Existing CLI rendering continues to use Rich progress.

### Report history and trends

`output/reports/run_summary.json` and `run_summary.md` remain the latest report files. Each report write also stores a timestamped JSON copy under `output/reports/history/`, writes document-level validation records to `validation_documents.jsonl`, and updates `trends.json` / `trends.md` with historical counts, issue codes, runtime telemetry, cache decisions, and failures.

## Repository layout

```text
DevDocsDownloader.py         # top-level entry point
doc_ingest/                 # active package
doc_ingest/gui/             # optional NiceGUI operator interface
desktop/                    # WinUI 3 desktop shell and installer assets
documentation/              # project documentation files
scripts/                    # helper and historical support scripts
tests/                      # focused regression tests
benchmarks/                 # benchmark corpora
source-documents/           # legacy support requirements and inputs
```

## Limitations and known issues

### Active pipeline limitations

- Output quality still depends on upstream source structure, but DevDocs and Dash now use source-specific HTML cleanup before `markdownify`
- The compiler does not preserve source navigation hierarchy beyond topic grouping
- Validation is heuristic and now reports unresolved relative links, internal anchor issues, duplicate sections/headings, source-inventory mismatches, likely HTML leftovers, malformed table shapes, and definition-list artifacts, but it is not a semantic correctness proof
- `DocumentationPipeline.close()` releases shared source-runtime HTTP clients
- Bulk runs gather language tasks via `asyncio.gather`, with language-level concurrency in the pipeline and source-profile throttling in `SourceRuntime`
- Checkpoint resume depends on the saved artifact manifest; runs with missing fragments fall back to full replay
- Optional frontmatter and chunk exports are off by default to preserve conservative output behavior
- Tokenizer-aware chunks are opt-in through the `tokenizer` extra; character chunks remain the default
- Asset inventory is event-driven only; the compiler does not crawl arbitrary image or asset URLs

### Source-specific limitations

- **DevDocs**
	- Deduplicates by base path, but now preserves upstream fragment references in the emitted canonical document instead of silently dropping them
	- Treats DevDocs entry `type` as the topic label
- **MDN**
	- Discovery is dynamic, but only the stable quality-set families are treated as fully supported by default
	- Frontmatter is parsed with safe YAML, but downstream metadata usage is still limited
	- Archive extraction is still large, but unchanged archives with ready area trees are not re-extracted
- **Dash**
	- Discovery comes from Kapeli’s public cheat-sheet index and assumes the matching `/feeds/<slug>.tgz` archives remain valid
	- SQLite index structure is assumed to match the expected `searchIndex` schema
	- HTML conversion removes common navigation noise but still depends on docset HTML quality
	- Fragment-level references are preserved as notes on the canonical emitted document; section-precise extraction is still conservative

### Repository consistency notes

- `scripts/benchmark_pipeline.py` now targets the active source-adapter CLI and reports document throughput for cold and warm cache trials.
- `scripts/build_skip_manifest.py` now writes a current state and checkpoint manifest from `state/*.json` and `state/checkpoints/*.json`; URL-level crawler skip manifests are not part of the active pipeline.
- `pyproject.toml` is the canonical dependency manifest; `requirements.txt` and `source-documents/requirements.txt` are compatibility shims.
- BeautifulSoup, lxml, and PyYAML are runtime dependencies for source cleanup and frontmatter parsing. Browser, benchmark, GUI, tokenizer, and developer packages remain optional extras.
- Plugin source adapters can be installed as Python packages exposing entry points in the `devdocsdownloader.sources` group. Built-in DevDocs, MDN, and Dash adapters are registered first and keep priority on name collisions.

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
- source-specific HTML cleanup, MDN YAML frontmatter parsing, link rewriting, and conversion-quality validation
- collision-safe consolidated anchors, optional document frontmatter, optional chunk exports, cache freshness policy, and service-layer wiring
- GUI-safe service artifact readers, checkpoint/cache inspection, job queue transitions, CLI GUI launcher wiring, and optional NiceGUI app-factory smoke coverage
- source plugin registration, exact cross-document link rewriting, asset inventory, and optional tokenizer chunking
- adaptive bulk scheduling, deterministic source suggestions, and opt-in live extraction sanity hooks
- dynamic DevDocs/MDN/Dash catalog discovery manifests, alias-aware resolution, cached-manifest fallback, and fragment-reference preservation

## Future direction

The most realistic next steps, based on the current repository state, are:

1. Finish validating the WinUI release build on a Windows image with the required packaging components available
2. Remove the legacy NiceGUI surface once WinUI parity and release validation are complete
3. Reintroduce PDF/DOCX/browser conversion only when a real source adapter path and fixture coverage justify the dependency

## Release readiness

The project now includes the backend host, WinUI shell scaffold, installer definition, and GitHub Actions release automation for the `1.0.0` desktop release track. Use `documentation/release_checklist.md` for the required Python checks, desktop build/package validation, and release artifact smoke tests.

## Documentation map

- `documentation/architecture.md` — subsystem and pipeline design
- `documentation/codemap.md` — file-by-file navigation guide
- `documentation/development_progress.md` — implementation status and known gaps
- `documentation/full-project-documentation.md` — detailed technical reference
- `documentation/output_contract.md` — generated output, state, checkpoint, and report contract
- `documentation/release_checklist.md` — v1.0.0 desktop release validation checklist
- `documentation/roadmap.md` — completed roadmap and post-v1.0.0 future work
