# Development Progress

## Current state summary

The repository has a solid curated documentation ingestion pipeline built around three source adapters: DevDocs, MDN, and Dash. The active runtime path now has shared source-runtime ownership, typed adapter events, deterministic output contract tests, dependency/tooling hygiene, streaming compilation, checkpoint resume, conversion cleanup, optional downstream outputs, cache freshness policy, and a GUI-ready service boundary. Historical crawler-oriented utilities are archived outside the active runtime.

In short:

- **Working core:** source resolution, ingestion, active run checkpoints, compilation, validation, reporting
- **Partially complete areas:** validation depth, plugin expansion, visual GUI, long-term quality trend reporting
- **Recently stabilized areas:** benchmark harness and state manifest script now target the current package API

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
- Consolidated anchors are collision-safe through a shared unique-anchor registry
- Optional per-document YAML frontmatter is implemented
- Optional retrieval chunk export writes Markdown chunks and JSONL manifests
- Windows-reserved filenames are normalized safely through `slugify()`

### Validation and reporting

- Validation pass runs automatically after compilation
- Validation-only command can assess an existing bundle
- JSON and Markdown run summaries are generated
- Per-language run state is persisted
- Active checkpoints are persisted under `state/checkpoints/` during runs and removed after successful completion
- Source diagnostics are persisted with discovered, emitted, and skipped document counts
- Topic include/exclude filters are available through the CLI and are recorded in diagnostics

### Tests

- Focused regression tests exist for several error-prone source behaviors
- Concurrency limiting in `run_many()` is tested
- Corrupt cache handling is tested
- Windows-safe slug handling is tested
- Output contract, CLI contracts, fixture-backed integration, live endpoint probes, streaming resume, conversion quality, cache policy, chunk export, and service-layer behavior are tested

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

- `DocumentationPipeline.close()` releases shared `SourceRuntime` HTTP clients
- source adapters receive the shared runtime from `SourceRegistry`
- HTTP clients are pooled by runtime profile and reused across source calls

Remaining lifecycle work is mostly richer telemetry and GUI-facing progress/event exposure.

### Resume and checkpoint depth

The pipeline records per-language active checkpoints with phase, emitted document count, document inventory position, last document metadata, emitted artifact manifests, and failure records. Matching reruns automatically resume after the saved safe boundary when artifacts still exist; stale or missing artifacts fall back to full replay.

### Concurrency and throughput controls

- language-level concurrency exists through `run_many()` and `AppConfig.language_concurrency`
- `SourceRuntime` applies per-profile source throttling and retry helpers
- there is no adaptive worker model in the active pipeline, despite older scripts referring to one

### Dependency management

- `pyproject.toml` is the canonical dependency manifest
- runtime dependencies are limited to active package imports
- developer, analysis, conversion, browser, and benchmark packages are split into optional extras
- `requirements.txt` and `source-documents/requirements.txt` are compatibility shims, not independent manifests

## Missing features relative to likely next needs

These are not promised by the current code, but they are the most obvious gaps for a production-grade ingestion tool.

### Remaining operational gaps

- no visual GUI yet, although `DocumentationService` is ready for one
- no per-document structured warning stream beyond aggregate skip diagnostics
- no pluggable source system beyond editing Python code

### Missing output features

- no cross-document link rewriting
- no deduplicated shared assets or image handling
- chunking is character-bounded, not tokenizer-aware
- no per-document validation reports
- no optional alternate output formats beyond Markdown and metadata JSON

### Remaining test coverage gaps

- no tests for suggestion quality in source resolution
- live endpoint probes are opt-in and intentionally do not validate extraction quality

## Known bugs, mismatches, and fragile areas

### 1. Historical crawler hints are archived outside the active application

The crawler path analyzer now lives under `documentation/archive/analyze_doc_paths.py.txt`. The active application does not consume URL root input files or crawler path override files.

### `scripts/benchmark_pipeline.py`

This file now benchmarks the active CLI by running corpus languages through `DevDocsDownloader.py run` and measuring document throughput, duration, and output size across cold and warm cache trials.

### `scripts/build_skip_manifest.py`

This file now writes `cache/state_manifest.json` from current `LanguageRunState` files. It no longer attempts to build URL-level skip manifests because the active source-adapter pipeline does not persist crawler URL state.

### 2. Repository hints now target current commands

Local settings under `.claude/settings.local.json` now reference current CLI, test, lint, and type-check commands.

### 3. MDN frontmatter parsing is YAML-based but still source-specific

The parser in `doc_ingest/sources/mdn.py` uses `yaml.safe_load()` and preserves nested/list metadata for filtering and future reporting. Malformed frontmatter is recoverable and counted in diagnostics.

### 4. Source conversion quality depends on cleanup plus `markdownify`

Both DevDocs and Dash ingest rendered HTML and rely on `markdownify`.

Risks:

- noisy navigation remnants when a source changes markup significantly
- imperfect code block preservation
- inconsistent list/table formatting
- source-specific HTML quirks leaking into output

### 5. Deduplication strategy may drop useful granularity

- DevDocs and Dash deduplicate by base path before the `#fragment`
- fragment-specific sections are therefore collapsed into one document entry

This reduces duplicates, but it may also lose fine-grained documentation sections.

## Performance observations from code inspection

These observations come from code inspection; the benchmark harness now supports measuring the active CLI, but benchmark data has not been checked into this documentation.

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
| State store | Working | Stable final state plus active checkpoint persistence |
| Progress UI | Working | Presentation layer only |
| Tests | Working | Contract, integration, CLI, resilience, architecture, and opt-in live endpoint coverage |
| Benchmarks | Working | Targets current CLI and reports cold/warm cache throughput |
| Support scripts | Aligned | Setup, benchmark, and state manifest target active runtime; crawler path analyzer is archived |

## Priority improvements

### Highest priority

1. **Add adapter-level resume from checkpoints**
	- let adapters skip safely to the last persisted document boundary where source inventory order is stable
	- keep full replay fallback for sources that cannot seek safely

2. **Deepen validation**
	- validate link structure, duplicate sections, and heading integrity
	- add checks that compare compiled document count to source inventory

### Medium priority

4. **Improve source robustness**
	- add more explicit source-level error reporting
	- extend diagnostics from aggregate skip counts to per-document warning records

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
