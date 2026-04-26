# Development Progress

## Current state summary

The repository has a solid curated documentation ingestion pipeline built around three source adapters: DevDocs, MDN, and Dash. The active runtime path now has shared source-runtime ownership, typed adapter events, deterministic output contract tests, dependency/tooling hygiene, streaming compilation, checkpoint resume, conversion cleanup, optional downstream outputs, cache freshness policy, deep validation/observability, and a local NiceGUI operator interface over the service boundary. Historical crawler-oriented utilities are archived outside the active runtime.

In short:

- **Working core:** source resolution, ingestion, active run checkpoints, compilation, validation, reporting
- **Partially complete areas:** plugin expansion, adaptive scaling, advanced output fidelity, packaged desktop distribution
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
- Optional `gui` command launches the local operator interface when `.[gui]` is installed

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

### Local GUI and operator workflows

- NiceGUI-based dashboard is available through `python DevDocsDownloader.py gui`
- Single-language, validation-only, and bulk/preset/all runs expose CLI-equivalent options
- GUI job queue records service events, progress, failures, and completed summaries
- Language listing, preset audit, catalog refresh, report inspection, output browsing, checkpoint controls, and cache metadata views are present
- GUI file reads and checkpoint deletion go through `DocumentationService` path-safety checks

### Tests

- Focused regression tests exist for several error-prone source behaviors
- Concurrency limiting in `run_many()` is tested
- Corrupt cache handling is tested
- Windows-safe slug handling is tested
- Output contract, CLI contracts, fixture-backed integration, live endpoint probes, streaming resume, conversion quality, cache policy, chunk export, service-layer behavior, validation observability, and GUI-safe service behavior are tested

## Partially implemented or shallow areas

The concrete remediation plan for these areas now lives in `documentation/roadmap.md`:

- Phase 8 now covers deeper validation, per-document validation reports, structured source warnings, runtime telemetry, and quality trend reporting.
- Phase 9 delivered the visual GUI and operator workflows over the service layer.
- Phase 10 covers source expansion, cross-document links, assets, tokenizer-aware chunks, and extended conversion backends.
- Phase 11 covers adaptive scaling and test expansion.

### Validation quality

Current validation is layered and pragmatic, not semantic.

- detects missing output
- detects tiny output
- detects unbalanced code fences
- checks for required top-level sections
- checks internal anchors and duplicate section/document heading shapes
- reconciles source inventory counters when diagnostics are available
- emits document-local validation records

It does **not** currently verify:

- semantic source correctness
- Markdown rendering quality beyond static heuristics
- full source completeness beyond discovered/emitted/skipped counter reconciliation

### Resource lifecycle management

- `DocumentationPipeline.close()` releases shared `SourceRuntime` HTTP clients
- source adapters receive the shared runtime from `SourceRegistry`
- HTTP clients are pooled by runtime profile and reused across source calls

Remaining lifecycle work is mostly adding cooperative cancellation inside active pipeline runs and exposing richer real-time progress milestones beyond the post-summary service events.

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

- no pluggable source system beyond editing Python code
- no packaged desktop app or hosted multi-user mode; the GUI is local/operator-focused

### Missing output features

- no cross-document link rewriting
- no deduplicated shared assets or image handling
- chunking is character-bounded, not tokenizer-aware
- no semantic per-document validation reports beyond static issue records
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
| Validator | Working | Layered structural, anchor, inventory, and per-document checks |
| Reporting | Working | Summary artifacts generated |
| State store | Working | Stable final state plus active checkpoint persistence |
| Progress UI | Working | Presentation layer only |
| Local GUI | Working | Optional NiceGUI dashboard over `DocumentationService` |
| Tests | Working | Contract, integration, CLI, resilience, architecture, and opt-in live endpoint coverage |
| Benchmarks | Working | Targets current CLI and reports cold/warm cache throughput |
| Support scripts | Aligned | Setup, benchmark, and state manifest target active runtime; crawler path analyzer is archived |

## Priority improvements

### Highest priority

1. **Improve source expansion and output fidelity**
	- support plugin-ready source registration
	- rewrite known cross-document links to local bundle paths
	- add a first-class asset inventory for diagrams and images

2. **Extend downstream export quality**
	- add tokenizer-aware chunking as an optional mode
	- decide which extended conversion backends are real product features

### Medium priority

3. **Refine GUI operations**
	- add cooperative cancellation for active runs when the pipeline exposes safe cancellation boundaries
	- consider packaged local desktop distribution if operator adoption justifies it

4. **Add adaptive scaling and source-resolution test expansion**
	- benchmark adaptive worker/backpressure policies before changing defaults
	- add deterministic source suggestion quality tests

## Uncertainties that should be kept explicit

- The repository clearly evolved from a larger crawler design, but the current codebase does not include the crawler modules needed to confirm the original architecture fully.
- The benchmark-related scripts cannot be treated as authoritative descriptions of current runtime performance.
- Some declared dependencies may be reserved for future work or removed code; current code inspection cannot prove intent, only current usage.
