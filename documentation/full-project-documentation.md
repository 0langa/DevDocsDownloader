# Full Project Documentation

## 1. Project purpose

`DevDocsDownloader` is a local documentation ingestion tool that compiles official language documentation into Markdown bundles suitable for offline browsing, downstream processing, or AI-oriented consumption. The current implementation is based on curated upstream documentation sources rather than open-ended crawling.

Its core contract is:

1. accept a language name
2. resolve that language to a supported source
3. fetch source content
4. normalize it into `Document` objects
5. write topic-organized Markdown outputs
6. validate and report on the result

## 2. End-to-end workflow

```text
language request
	-> resolve source
	-> fetch source content
	-> normalize to Document objects
	-> compile Markdown outputs
	-> validate
	-> persist state and reports
```

### 2.1 Bootstrap and command dispatch

Execution starts in `DevDocsDownloader.py`, which imports `app` from `doc_ingest.cli`.

The Typer application in `doc_ingest/cli.py` exposes:

- callback entry with interactive wizard fallback
- `run`
- `bulk`
- `list-presets`
- `list-languages`
- `refresh-catalogs`
- `validate`
- `init`

For actual ingestion work, the CLI routes into `_execute_run()` for single-language execution and into a custom async runner inside `bulk()` for multi-language execution.

### 2.2 Configuration and path setup

`load_config()` in `doc_ingest/config.py` derives all runtime paths from the repository root unless an alternate `output_dir` is supplied.

Generated directories:

- `output/`
- `output/markdown/`
- `output/reports/`
- `cache/`
- `logs/`
- `state/`
- `state/checkpoints/`
- `tmp/`

The config object also stores `language_concurrency`, which currently defaults to `3`.

### 2.3 Logging and terminal UI

`_setup_logging()` writes logs to `logs/run.log` and controls verbosity for both local application logs and `httpx`/`httpcore` noise.

`CrawlProgressTracker` renders live Rich panels showing:

- aggregate document count
- per-language progress
- final completion/failure state

The progress tracker is optional and mostly used for user feedback during `run` and `bulk`.

## 3. Core data models

## 3.1 Source-level models

Defined in `doc_ingest/sources/base.py`:

### `LanguageCatalog`

Represents a source-specific language or documentation catalog entry.

Fields:

- `source`
- `slug`
- `display_name`
- `version`
- `core_topics`
- `all_topics`
- `size_hint`
- `homepage`

### `Document`

Normalized unit of content emitted by any source adapter.

Fields:

- `topic`
- `slug`
- `title`
- `markdown`
- `source_url`
- `order_hint`

This object is the key boundary between source adapters and the compiler.

### `DocumentationSource`

Protocol requiring:

- `list_languages()`
- `fetch()`

## 3.2 Run/report models

Defined in `doc_ingest/models.py`.

### `TopicStats`

- topic label plus document count

### `SourceRunDiagnostics`

- discovered source inventory count
- source-emitted document count before pipeline topic filters
- skipped reason-count map for source-level and pipeline-level filtering

### `ValidationIssue`

- severity level, code, and message

### `ValidationResult`

- output file path, score, quality score, and issue list

### `LanguageRunState`

- persisted state snapshot for one language run
- includes final source diagnostics when available

### `LanguageRunCheckpoint`

- active checkpoint for one in-progress or failed language run
- records source slug, mode, phase, emitted document count, last document metadata, document inventory position, output path, and failure records

### `LanguageRunReport`

- final runtime report for one language

### `RunSummary`

- generated timestamp plus all `LanguageRunReport` entries

## 4. Source resolution and selection

## 4.1 Source registry

`SourceRegistry` in `doc_ingest/sources/registry.py` constructs three source adapters:

- `DevDocsSource`
- `MdnContentSource`
- `DashFeedSource`

It provides catalog access and resolution logic.

## 4.2 Resolution algorithm

Given a user-supplied language name:

1. normalize to lowercase
2. load catalogs from all sources
3. if a source override is present, search only that source
4. otherwise select a source priority order
	 - MDN first for web-centric areas: `html`, `css`, `http`, `web-apis`, `webassembly`
	 - DevDocs first for all other languages
	 - Dash as the final fallback
5. search using `_exact_match()` semantics:
	 - exact display-name match
	 - exact slug match
	 - exact slug-family match (`slug.split("~", 1)[0]`)
	 - prefix match
	 - contains match
6. if multiple matches exist inside a bucket, choose the best version via `_version_key()`

If resolution fails, `suggest()` uses `difflib.get_close_matches()` across catalog names to generate hints.

## 5. Detailed source adapter behavior

## 5.1 DevDocs adapter

### Catalog loading

`list_languages()`:

- reads `cache/catalogs/devdocs.json` if possible
- otherwise downloads `https://devdocs.io/docs.json`
- stores raw entries to cache
- maps each entry into `LanguageCatalog`

### Core topic handling

`devdocs_core.json` maps source slugs or source families to topic names. In `important` mode, only entries whose `type` matches those topic names are emitted.

### Dataset retrieval

For a given source slug, `_download_dataset()` ensures:

- `cache/devdocs/<slug>/index.json`
- `cache/devdocs/<slug>/db.json`

Files are redownloaded if missing or if cached JSON is invalid.

### Document emission

During `fetch()`:

- iterate `index["entries"]`
- skip entries outside `core_topics` in `important` mode
- normalize a document key by removing any URL fragment
- avoid duplicate base paths with `seen_doc_keys`
- load HTML content from `db[doc_key]`
- convert HTML to Markdown via `markdownify`
- emit `Document`

### Implications

- good structural consistency
- coarse deduplication by base path
- dependent on DevDocs export quality

## 5.2 MDN adapter

### Catalog model

Unlike DevDocs and Dash, MDN does not discover languages dynamically here. `AREAS` is a fixed mapping:

- `javascript`
- `html`
- `css`
- `web-apis`
- `http`
- `webassembly`

### Archive retrieval

`_ensure_content()`:

- checks for `.ready` marker under `cache/mdn/content/`
- verifies that extracted trees still contain expected area directories
- downloads the GitHub tarball if missing
- extracts only the relevant documentation subtree
- writes `.ready` after a successful extraction

### Frontmatter parsing

`_parse_frontmatter()` uses:

- a regex split on leading `--- ... ---`
- flat line-by-line parsing of `key: value`
- no nested YAML support

### Document emission

For each `index.md` under the selected area:

- parse frontmatter and body
- inspect `page-type`
- in `important` mode, allow only selected page types from `CORE_PAGE_TYPES`
- derive `topic` from the first relative path segment
- derive `title` from frontmatter or the directory name
- use the Markdown body directly without HTML conversion

### Implications

- avoids HTML cleanup for MDN
- sensitive to content-tree and frontmatter format changes
- narrower language coverage by design

## 5.3 Dash adapter

### Catalog seeding

Dash catalog entries come from `_DEFAULT_DASH_SEED` unless an optional seed file is supplied. This means available Dash languages are limited to the embedded list in the current repository.

### Docset retrieval

`_download_docset()`:

- looks for an extracted `.docset` under `cache/dash/<slug>/`
- otherwise downloads `https://kapeli.com/feeds/<slug>.tgz`
- writes to a temporary tarball file
- extracts to the cache directory
- raises a `RuntimeError` if the archive is invalid or no `.docset` appears after extraction

### Document emission

`fetch()`:

- opens `docSet.dsidx` via `sqlite3`
- queries `SELECT name, type, path FROM searchIndex ORDER BY type, name`
- filters by `type` in `important` mode
- skips duplicates based on `path` without fragment
- reads HTML files from `Contents/Resources/Documents/`
- converts HTML to Markdown
- emits `Document`

### Implications

- depends on docset schema stability
- broad language reach through docsets
- HTML conversion quality varies with each docset

## 6. Compilation pipeline

## 6.1 Builder state

`LanguageOutputBuilder` writes per-document Markdown files and consolidated document fragments as documents arrive. It keeps lightweight topic/document manifests in memory for final indexes, metadata, and deterministic consolidated ordering.

Internal structures:

- `_topic_docs: dict[str, list[CompilationDocument]]`
- `_topic_order: list[str]`
- `_used_slugs: dict[str, set[str]]`
- `total_documents`

## 6.2 Document ingestion

`add()`:

- normalizes empty topics to `Reference`
- creates per-topic buckets lazily
- ensures slug uniqueness within a topic via `_unique_slug()`
- writes the per-document Markdown file immediately
- writes a temporary consolidated fragment for the document body
- mutates `document.slug` to the chosen unique slug
- appends the document to the topic bucket

## 6.3 Finalization

`finalize()` writes multiple output layers.

### Topic layer

For each topic:

- create `output/markdown/<language>/<topic-slug>/`
- write one Markdown file per document
- write `_section.md` containing a topic title and contents list

### Language index layer

Writes `index.md` containing:

- metadata
- consolidated file link
- topic list and topic document counts

### Consolidated layer

Writes `<language-slug>.md` containing:

- metadata
- table of contents
- all topics and documents inline

### Metadata layer

Writes `_meta.json` with:

- language metadata
- source metadata
- mode
- total document count
- per-topic counts
- generation timestamp

## 6.4 Markdown normalization heuristics

`_normalize_markdown()`:

- converts CRLF/CR to LF
- demotes all headings by two levels, capped at `######`
- collapses runs of 3+ blank lines into 2
- strips leading/trailing whitespace

This heuristic exists so compiled document content nests cleanly inside the consolidated file’s heading structure.

## 7. Validation and scoring

`validate_output()` in `doc_ingest/validator.py` performs a shallow structural pass.

Checks:

1. output file exists
2. `total_documents > 0`
3. file size is at least 2000 bytes
4. code fence count is even
5. required sections exist
6. topic list is non-empty

Score calculation:

- start from `1.0`
- subtract `0.3` for each error
- subtract `0.1` for each warning
- clamp to `[0.0, 1.0]`

This is best understood as a smoke test, not a quality guarantee.

## 8. State persistence and reporting

## 8.1 State store

`RunStateStore` reads and writes per-language state files under `state/`.

Behavior:

- `load()` returns a default if the file is missing or invalid
- `save()` updates `updated_at`, ensures parent directories exist, and writes atomically

`RunCheckpointStore` reads and writes active checkpoint files under `state/checkpoints/`.

Behavior:

- a checkpoint is created when a non-validation language run starts
- phase is updated before fetching, during per-document compilation, before validation, and on failure
- each emitted document increments `emitted_document_count` and records `Document.order_hint` as `document_inventory_position`
- failures are recorded with phase, error type, message, emitted document count, and document position
- successful runs save the stable `LanguageRunState` and remove the active checkpoint
- failed runs leave the checkpoint on disk for inspection before retrying

Source diagnostics are saved in final language state and reports. Adapters record source-level inventory and skip reasons, while the pipeline records topic include/exclude skips after documents are normalized.

## 8.2 Report generation

`write_reports()` writes two summary artifacts:

- `run_summary.json`
- `run_summary.md`

Each report includes:

- language
- source
- source URL
- mode
- output path
- document count
- duration
- validation score and issues
- source diagnostics
- topic counts
- failures

## 9. Error handling model

## 9.1 Source-level failures

Each source adapter uses normal exception propagation.

Examples:

- HTTP failures from `httpx.raise_for_status()` bubble up
- invalid JSON caches are converted into runtime failures in DevDocs loading paths
- invalid Dash archives raise `RuntimeError`
- missing expected MDN extraction trees raise `RuntimeError`

## 9.2 Pipeline-level handling

`DocumentationPipeline._run_language()` wraps compilation in a `try/except Exception` block.

On failure:

- the exception type and message are added to `report.failures`
- the active checkpoint is marked `failed` and records the failure phase plus last emitted document boundary
- progress is marked complete/failure if a tracker exists
- duration is recorded
- processing returns a failed `LanguageRunReport` instead of crashing the whole CLI process

## 9.3 Validate-only handling

In `validate_only` mode:

- if the consolidated file is absent, the report records a failure
- otherwise the pipeline loads prior run state and validates the existing file

## 9.4 Retry logic

HTTP downloads use bounded retry helpers in `doc_ingest/utils/http.py`.

Current behavior:

- retries transient network, timeout, and remote protocol failures
- retries selected transient HTTP statuses such as 408, 429, 500, 502, 503, and 504
- writes streamed downloads through temporary files before replacing the final cache artifact
- does not retry non-retryable HTTP statuses such as 404

## 10. Storage and filesystem behavior

## 10.1 Atomic writes

`doc_ingest/utils/filesystem.py` writes text, bytes, and JSON to temporary sibling files before replacing the destination. This reduces the risk of partially written outputs if a process terminates mid-write.

## 10.2 Cache layout

Current cache usage:

- `cache/catalogs/devdocs.json`
- `cache/catalogs/mdn.json`
- `cache/catalogs/dash.json`
- `cache/devdocs/<slug>/...`
- `cache/mdn/...`
- `cache/dash/<slug>/...`

## 10.3 Output layout example

The stable generated-output contract for these files, runtime state, checkpoints, diagnostics, and reports is defined in `documentation/output_contract.md`.

Example for Python:

```text
output/
└── markdown/
		└── python/
				├── _meta.json
				├── index.md
				├── python.md
				├── built-in-functions/
				│   ├── _section.md
				│   └── abs.md
				└── language-reference/
						├── _section.md
						└── lexical-analysis.md
```

Exact topic directories depend on source-emitted topic names and slug normalization.

## 11. Supported inputs and outputs

## 11.1 Supported inputs in active runtime

- language names typed interactively or passed to CLI commands
- optional source override values:
	- `devdocs`
	- `mdn`
	- `dash`
- bulk targets:
	- named presets from `presets.py`
	- `all`

## 11.2 Supported source content formats

- DevDocs JSON datasets containing HTML content blobs
- MDN repository Markdown pages with frontmatter
- Dash docset SQLite metadata plus HTML files

## 11.3 Output formats

- Markdown per document
- Markdown topic index files
- Markdown language index files
- Markdown consolidated language bundle
- JSON metadata per language bundle
- JSON and Markdown run summary reports

### Not supported in the active runtime

Despite optional extras supporting broader ambitions, the active pipeline does **not** process arbitrary:

- PDF input files
- DOCX input files
- user-specified local HTML files
- free-form URL crawl lists

Packages like `pypdf`, `mammoth`, and `docling` are isolated in the `conversion-extended` extra because they are not wired into the active code path.

## 12. Performance characteristics

## 12.1 Work decomposition

- single-language runs are mostly sequential within one adapter stream
- bulk runs add language-level parallelism only
- some blocking conversions are offloaded via `asyncio.to_thread()`

## 12.2 Likely memory behavior

The compiler stores all fetched `Document` objects for a language in memory until `finalize()` completes. This is simple and deterministic, but it means very large `full` mode runs may have substantial per-language memory usage.

## 12.3 Likely disk behavior

- many small atomic writes for per-document outputs
- one large write for the consolidated file
- potentially large cache footprints for MDN and Dash

## 12.4 Benchmarking

The repository includes `scripts/benchmark_pipeline.py` for the active source-adapter CLI. It runs corpus languages through `DevDocsDownloader.py run` and reports document throughput, duration, and output size for cold and warm cache trials.

## 13. Extension points

## 13.1 Adding a new source adapter

To add a new source:

1. implement the `DocumentationSource` protocol
2. emit `LanguageCatalog` entries from `list_languages()`
3. emit normalized `Document` objects from `fetch()`
4. register the adapter in `SourceRegistry.__init__()`
5. define source-preference behavior if needed

Because the compiler and report layers only depend on normalized `Document` objects, the adapter boundary is the main extensibility seam.

## 13.2 Improving validation

The validator can be expanded without changing source adapters if it continues to accept:

- `language`
- `output_path`
- `total_documents`
- `topics`

Potential additions:

- heading tree validation
- broken local-link detection
- duplicate heading/document detection
- source count reconciliation

## 13.3 Alternative output strategies

The compiler is another natural extension point. Possible enhancements:

- chunked exports for embedding pipelines
- source-preserving frontmatter on per-document files
- optional HTML/plain-text output
- TOC depth controls

## 14. Repository inconsistencies and explicit uncertainties

## 14.1 Historical architecture residue

Several files indicate the repository once supported or planned a crawler that accepted input files of documentation roots, discovered URLs, and measured per-page throughput. The active code does not contain the modules, CLI flags, state fields, or report schema required for that design.

Evidence includes:

- `.claude/settings.local.json`
- `documentation/archive/analyze_doc_paths.py.txt`

The benchmark and state-manifest scripts have been updated for the active runtime. The crawler path analyzer has been archived and is not part of active tooling gates.

## 14.2 Dependency management

`pyproject.toml` is the canonical dependency manifest. Current runtime imports use:

- `httpx`
- `markdownify`
- `typer`
- `rich`
- `pydantic`
- optional `orjson`

Developer tooling lives in the `dev` extra. Support-script, extended-conversion, browser, and benchmark dependencies live in explicit optional extras. `requirements.txt` and `source-documents/requirements.txt` are compatibility shims only.

## 14.3 Incomplete cleanup boundaries

- richer source-runtime policies such as per-source rate limits are not implemented yet
- benchmark corpus assets are small live-run inputs for the current benchmark runner

These are not runtime blockers for the active ingestion path, but they matter for maintainability.

## 15. Practical maintenance guidance

For a new engineer extending the current codebase, the safest sequence is:

1. treat `doc_ingest/` as the canonical runtime system
2. verify whether historical support scripts apply to the active adapter pipeline before relying on them
3. keep new work aligned with the adapter-based ingestion architecture unless the project is intentionally pivoting back to crawling
4. add tests around any new source adapter or compiler behavior
5. reconcile stale repository artifacts early if broader maintenance is planned
