# Development Progress

## Current state summary

The repository has a solid first working implementation of a curated documentation ingestion pipeline built around three source adapters: DevDocs, MDN, and Dash. The active runtime path is coherent for that scope. The main weakness is repository drift: benchmark/setup/support artifacts from an earlier crawler-oriented design remain in-tree and no longer match the current code.

In short:

- **Working core:** source resolution, ingestion, compilation, validation, reporting
- **Partially complete areas:** lifecycle cleanup, validation depth, test coverage, dependency hygiene
- **Broken/stale areas:** benchmark harness and skip-manifest script relative to the current package API

## What works today

### CLI and orchestration

- Top-level bootstrap works through `DevDocsDownloader.py`
- Typer app is defined and structured in `doc_ingest/cli.py`
- Interactive wizard path exists
- Single-language execution path is complete
- Bulk execution path is complete
- Validation-only command path is complete
- Catalog listing and refresh commands are implemented
- Output directory initialization command is implemented

### Source registry and resolution

- Source registry composes DevDocs, MDN, and Dash adapters
- Language resolution supports source override
- Automatic priority logic exists
- Fuzzy suggestions for missing languages are implemented
- All-language catalog enumeration is implemented with deduplication

### DevDocs adapter

- Catalog fetch and cache implemented
- Dataset fetch and cache implemented
- Corrupt JSON cache detection implemented
- HTML-to-Markdown conversion implemented
- Important/full mode filtering implemented

### MDN adapter

- Static catalog implemented for selected MDN areas
- Archive download implemented
- Selective tar extraction implemented
- Content root discovery implemented
- Markdown body extraction implemented
- Important/full mode filtering implemented through `page-type`

### Dash adapter

- Seeded language catalog implemented
- Docset download and extraction implemented
- SQLite index traversal implemented
- HTML-to-Markdown conversion implemented
- Important/full mode filtering implemented through entry type

### Output generation

- Per-topic directory generation works
- Per-document Markdown generation works
- Topic `_section.md` generation works
- Language `index.md` generation works
- Consolidated language Markdown generation works
- Metadata JSON generation works
- Duplicate slugs within a topic are handled
- Windows-reserved filenames are normalized safely through `slugify()`

### Validation and reporting

- Validation pass runs automatically after compilation
- Validation-only command can assess an existing bundle
- JSON and Markdown run summaries are generated
- Per-language run state is persisted

### Tests

- Focused regression tests exist for several error-prone source behaviors
- Concurrency limiting in `run_many()` is tested
- Corrupt cache handling is tested
- Windows-safe slug handling is tested

## Partially implemented or shallow areas

### Validation quality

Current validation is structural, not semantic.

- detects missing output
- detects tiny output
- detects unbalanced code fences
- checks for required top-level sections

It does **not** currently verify:

- broken internal links
- duplicate topic blocks
- repeated documents
- malformed heading hierarchies beyond simple presence checks
- Markdown rendering quality
- source completeness versus upstream inventory

### Resource lifecycle management

- `DocumentationPipeline.close()` exists but does nothing
- source adapters create short-lived `httpx.AsyncClient` instances on demand
- there is no persistent client pool to close or reuse

This is not a functional bug by itself, but it shows the lifecycle interface is ahead of the implementation.

### Concurrency and throughput controls

- language-level concurrency exists through `run_many()` and `AppConfig.language_concurrency`
- there are no explicit per-source concurrency controls or retry strategies
- there is no adaptive worker model in the active pipeline, despite older scripts referring to one

### Dependency management

- `pyproject.toml` and `requirements.txt` are not fully aligned
- active runtime imports use only a subset of declared dependencies
- `source-documents/requirements.txt` is a second dependency manifest with overlapping but different versions and packages

## Missing features relative to likely next needs

These are not promised by the current code, but they are the most obvious gaps for a production-grade ingestion tool.

### Missing operational features

- no retry/backoff wrapper around HTTP fetches
- no resumable partial language download flow beyond final state persistence
- no cache expiry strategy
- no structured diagnostics around per-document failures inside a successful language run
- no user-configurable include/exclude topic controls
- no pluggable source system beyond editing Python code

### Missing output features

- no cross-document link rewriting
- no deduplicated shared assets or image handling
- no chunking strategy optimized for downstream RAG/embedding ingestion
- no per-document validation reports
- no optional alternate output formats beyond Markdown and metadata JSON

### Missing test coverage

- no real integration tests against cached fixtures for complete runs
- no golden-file tests for compiler output
- no CLI contract tests for command output and error handling
- no tests for suggestion quality in source resolution

## Known bugs, mismatches, and fragile areas

### 1. Historical scripts do not match the current application

### `scripts/benchmark_pipeline.py`

This file is currently out of sync with the runtime code.

It assumes unsupported CLI flags and unsupported report fields, including:

- `--input-file`
- `--page-concurrency`
- `--extraction-workers`
- `--max-pending-extractions`
- `--normalized-cache-format`
- `--compile-streaming`
- report fields such as `pages_processed` and `performance`

Current status: **not runnable without refactoring**.

### `scripts/build_skip_manifest.py`

This file imports and references code that does not exist in the active package:

- `doc_ingest.parser`
- `config.paths.input_file`
- `config.paths.crawl_cache_dir`

Current status: **broken against current codebase**.

### 2. Repository hints still reference the old architecture

Local settings under `.claude/settings.local.json` reference missing config fields and missing modules, which reinforces that the repository previously supported a broader crawler architecture.

Current status: **stale local developer configuration**.

### 3. MDN frontmatter parsing is intentionally simplistic

The parser in `doc_ingest/sources/mdn.py`:

- uses a single regex to split frontmatter
- ignores nested YAML structure
- ignores indented metadata lines

This is workable for many MDN pages but fragile if frontmatter format changes.

### 4. Source conversion quality depends on `markdownify`

Both DevDocs and Dash ingest rendered HTML and rely on `markdownify`.

Risks:

- noisy navigation remnants
- imperfect code block preservation
- inconsistent list/table formatting
- source-specific HTML quirks leaking into output

### 5. Deduplication strategy may drop useful granularity

- DevDocs and Dash deduplicate by base path before the `#fragment`
- fragment-specific sections are therefore collapsed into one document entry

This reduces duplicates, but it may also lose fine-grained documentation sections.

## Performance observations from code inspection

These observations come from code inspection, not from verified benchmark output, because the included benchmark harness is stale.

### Likely efficient paths

- DevDocs should be the fastest source because it consumes prebuilt JSON datasets
- MDN avoids HTML conversion by using Markdown body content directly
- Atomic writes in utility helpers reduce the chance of partially written output files

### Likely expensive paths

- MDN tarball download and extraction are heavy in both network and disk usage
- Dash docset downloads and extraction may be large and slow depending on the selected language
- Consolidated Markdown files may become very large for `full` mode languages

### Likely bottlenecks

- HTML-to-Markdown conversion in DevDocs and Dash
- disk IO from many small per-document writes
- lack of request retry strategy when upstream endpoints are unstable

## Implementation completeness by subsystem

| Subsystem | Status | Notes |
|---|---|---|
| CLI | Working | Main commands implemented and coherent |
| Config/paths | Working | Minimal but sufficient |
| Registry | Working | Clear resolution behavior |
| DevDocs adapter | Working | Best aligned source adapter |
| MDN adapter | Working with caveats | Heavy cache and simple frontmatter parsing |
| Dash adapter | Working with caveats | Seeded catalog and docset assumptions |
| Compiler | Working | Core output generation complete |
| Validator | Basic | Structural only |
| Reporting | Working | Summary artifacts generated |
| State store | Working | Simple persistence layer |
| Progress UI | Working | Presentation layer only |
| Tests | Partial | Good focused regressions, limited integration coverage |
| Benchmarks | Stale | Not compatible with current CLI |
| Legacy support scripts | Mixed/Broken | Some standalone, some stale |

## Priority improvements

### Highest priority

1. **Resolve stale repository surface area**
	- either remove or modernize `scripts/benchmark_pipeline.py`
	- either remove or modernize `scripts/build_skip_manifest.py`
	- clean up stale local command hints if they are meant to be shared

2. **Reconcile dependency manifests**
	- align `pyproject.toml`, `requirements.txt`, and `source-documents/requirements.txt`
	- remove unused dependencies or document why they remain

3. **Deepen validation**
	- validate link structure, duplicate sections, and heading integrity
	- add checks that compare compiled document count to source inventory

### Medium priority

4. **Improve source robustness**
	- add retry/backoff behavior for HTTP downloads
	- add more explicit source-level error reporting

5. **Expand test coverage**
	- fixture-based integration tests
	- output snapshot tests
	- command behavior tests

6. **Review output ergonomics**
	- better table handling
	- link rewriting
	- optional chunked export for downstream AI ingestion

### Lower priority

7. **Refine lifecycle and performance model**
	- decide whether persistent HTTP clients are desirable
	- decide whether document-level concurrency should be exposed

## Uncertainties that should be kept explicit

- The repository clearly evolved from a larger crawler design, but the current codebase does not include the crawler modules needed to confirm the original architecture fully.
- The benchmark-related scripts cannot be treated as authoritative descriptions of current runtime performance.
- Some declared dependencies may be reserved for future work or removed code; current code inspection cannot prove intent, only current usage.
