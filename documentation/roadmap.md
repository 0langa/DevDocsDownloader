# DevDocsDownloader Development Roadmap

Updated after completing Phase 1 stabilization and Phase 2 core functionality work. The project now has safer filesystem behavior, safe archive extraction, HTTP retry helpers, local-first validation, active run checkpoints, source diagnostics, topic filters, preset auditing, and a maintainable Dash seed file.

The next priorities shift from basic stability toward contract hardening, deterministic test coverage, dependency hygiene, and then deeper architecture/performance work.

## Phase 0: Completed Baseline

### 1. Phase 1 Stabilization

- **Problem:** The repository previously had cross-platform filename failures, non-atomic runtime writes, unsafe archive extraction, no shared HTTP retry helper, validate-only dependence on remote catalogs, and broken crawler-era support scripts.
- **Proposed Solution:** Keep the completed stabilization changes as the baseline: sanitized output slugs, atomic writes, safe tar extraction, bounded HTTP retries, local-first validation, modern benchmark/state-manifest scripts, and updated docs.
- **Impact:** Establishes the current production-safe floor for future work.
- **Complexity:** Completed

### 2. Phase 2 Core Functionality

- **Problem:** The pipeline previously lacked active checkpoints, source inventory visibility, topic filters, and preset catalog coverage auditing.
- **Proposed Solution:** Keep the completed core changes as the baseline: `LanguageRunCheckpoint`, `SourceRunDiagnostics`, `--include-topic`, `--exclude-topic`, `audit-presets`, and `doc_ingest/sources/dash_seed.json`.
- **Impact:** Makes failed-run boundaries inspectable, output filtering controllable, and source coverage auditable.
- **Complexity:** Completed

## Phase 3: Contracts, Tests, and Developer Hygiene

### 1. Define and Test the Stable Output Contract

- **Problem:** Output layout and Markdown structure are still implicit in `compiler.py`. Future renderer or streaming changes could break downstream consumers without obvious test failures.
- **Proposed Solution:** Document the generated output contract for per-document files, topic sections, language indexes, consolidated files, `_meta.json`, state, checkpoints, and diagnostics. Add golden-file tests around a synthetic language fixture.
- **Impact:** Creates a stable compatibility target before deeper compiler refactoring.
- **Complexity:** Medium

### 2. Add Fixture-Based End-to-End Integration Tests

- **Problem:** The test suite now covers many risk points, but there is still no deterministic full run that exercises resolution, adapter fetch, compile, validate, state, checkpoints, diagnostics, and reports together.
- **Proposed Solution:** Add fixture-backed source adapters or monkeypatched registry entries for DevDocs-like, MDN-like, and Dash-like flows. Avoid live network in routine tests.
- **Impact:** Prevents regressions across the full ingestion contract without relying on upstream availability.
- **Complexity:** High

### 3. Add CLI Contract Tests

- **Problem:** CLI behavior is still mostly verified manually. Recent additions such as `audit-presets`, topic filters, local validation, and bulk filtering need stable automation coverage.
- **Proposed Solution:** Use Typer's test runner or subprocess tests for `run --help`, `bulk --help`, `validate --output-dir`, `audit-presets`, invalid presets, topic filter wiring, and report writing.
- **Impact:** Protects scripted usage and keeps user-facing commands predictable.
- **Complexity:** Medium

### 4. Reconcile Dependency Manifests

- **Problem:** `pyproject.toml`, `requirements.txt`, and `source-documents/requirements.txt` still diverge. Some packages are unused by the active runtime or only future-facing.
- **Proposed Solution:** Make `pyproject.toml` canonical. Split optional extras such as `dev`, `benchmark`, and `conversion-extended`; regenerate or remove duplicate requirements files.
- **Impact:** Reduces install cost, stale setup behavior, and dependency confusion.
- **Complexity:** Medium

### 5. Modernize Setup and Tooling

- **Problem:** `scripts/setup.py` still reflects older crawler-era assumptions, including broad dependencies and Playwright installation.
- **Proposed Solution:** Update setup to install the active package dependencies, create current runtime directories, and print valid examples. Add Ruff formatting/linting and a pragmatic type-checking gate.
- **Impact:** Improves onboarding and catches simple errors before runtime.
- **Complexity:** Medium

## Phase 4: Architecture and Refactoring

### 1. Introduce Shared Source Runtime Services

- **Problem:** Adapters still create their own `httpx.AsyncClient` instances and lifecycle ownership is fragmented. `DocumentationPipeline.close()` remains mostly ceremonial.
- **Proposed Solution:** Add a `SourceRuntime` or `IngestionContext` that owns HTTP clients, retry policy, cache helpers, user agent, and telemetry hooks. Pass it through `SourceRegistry` and close it from the pipeline.
- **Impact:** Reduces duplicate source logic and enables real pooled-resource lifecycle management.
- **Complexity:** High

### 2. Formalize Adapter Events Beyond `Document`

- **Problem:** `SourceRunDiagnostics` provides aggregate counts, but per-document warnings, source metadata, assets, and recoverable errors still do not have a typed event path.
- **Proposed Solution:** Introduce a typed event stream with variants such as `document`, `warning`, `skipped`, `source_stats`, and `asset`. Keep compatibility wrappers for current adapters during migration.
- **Impact:** Enables richer reporting, semantic metadata, and future asset/link handling without overloading `Document`.
- **Complexity:** High

### 3. Separate Compilation Planning, Rendering, and Writing

- **Problem:** `LanguageOutputBuilder.finalize()` still groups, renders, and persists output in one path, making streaming output and precise renderer tests harder.
- **Proposed Solution:** Split compilation into a planning model, pure render functions, and a persistence layer. Keep atomic writes for state and final artifacts.
- **Impact:** Makes compiler behavior easier to test and prepares for low-memory streaming compilation.
- **Complexity:** Medium

### 4. Decide the Fate of Historical Crawler Utilities

- **Problem:** `scripts/analyze_doc_paths.py`, URL utilities, and local `.claude` settings still reference historical crawler workflows that are not part of the active source-adapter runtime.
- **Proposed Solution:** Either archive crawler-only utilities explicitly or define a separate crawler plugin path with its own tests and config.
- **Impact:** Prevents future architecture drift and keeps maintenance work aligned with the current product.
- **Complexity:** Medium

## Phase 5: Performance and Scalability

### 1. Stream Compilation for Large Languages

- **Problem:** The compiler stores all documents for a language in memory until finalization. Large `full` runs can accumulate substantial Markdown.
- **Proposed Solution:** Write per-document files as documents arrive, record topic manifests, and build consolidated output from manifests or append-safe temporary files while preserving deterministic order.
- **Impact:** Reduces memory pressure for large DevDocs, MDN, and Dash runs.
- **Complexity:** High

### 2. Add Adapter-Level Resume From Checkpoints

- **Problem:** Checkpoints record the last emitted document boundary, but adapters cannot yet seek to a checkpoint position on retry.
- **Proposed Solution:** Extend source adapters with optional resume support keyed by `Document.order_hint` or source-native inventory IDs. Fall back to full replay for adapters that cannot seek safely.
- **Impact:** Converts checkpoints from inspection-only recovery data into real work-saving resume behavior.
- **Complexity:** High

### 3. Reduce Fsync Overhead for Generated Markdown

- **Problem:** Atomic write helpers call `os.fsync()` for every file. That is robust, but expensive for thousands of generated Markdown files.
- **Proposed Solution:** Add durability modes: strict for state/checkpoints/reports, balanced for reproducible generated Markdown where atomic replace is enough.
- **Impact:** Improves large-run throughput while preserving strong guarantees for critical state.
- **Complexity:** Medium

### 4. Add Per-Source Concurrency and Rate Limits

- **Problem:** Bulk concurrency is language-level only. There is no per-source rate limiting or source-aware throttling.
- **Proposed Solution:** Add source-level semaphores/rate settings. Permit safe parallel conversion or independent document processing where ordering can still be preserved.
- **Impact:** Improves bulk throughput without overloading upstream services.
- **Complexity:** Medium

### 5. Optimize MDN Cache Extraction

- **Problem:** MDN cache extraction is large and all-or-nothing. Cache freshness is marker-based rather than version-aware.
- **Proposed Solution:** Track archive checksum or ETag, extracted content version, and area-level readiness. Avoid re-extracting unchanged trees.
- **Impact:** Reduces disk churn and makes recurring MDN runs more predictable.
- **Complexity:** Medium

## Phase 6: Extraction and Conversion Quality

### 1. Add Source-Specific HTML Cleanup Before `markdownify`

- **Problem:** DevDocs and Dash still rely mostly on direct `markdownify` conversion, so navigation, breadcrumbs, or footer noise can leak into output.
- **Proposed Solution:** Add source-specific cleanup functions that select main content and remove known noisy elements before conversion.
- **Impact:** Improves Markdown quality without changing source acquisition.
- **Complexity:** Medium

### 2. Replace Minimal MDN Frontmatter Parsing With Robust YAML Parsing

- **Problem:** MDN frontmatter parsing ignores nested YAML, indented metadata, and list values.
- **Proposed Solution:** Add a safe YAML/frontmatter parser and preserve fields such as `title`, `slug`, `page-type`, `browser-compat`, and status metadata.
- **Impact:** Makes MDN filtering and metadata more reliable.
- **Complexity:** Low

### 3. Preserve and Rewrite Source Links

- **Problem:** Converted Markdown can contain relative links that do not work in generated output.
- **Proposed Solution:** Normalize links to absolute source URLs or generated local document links where targets are known. Report unresolved links during validation.
- **Impact:** Produces more usable offline manuals and downstream corpora.
- **Complexity:** High

### 4. Improve Code Block and Table Preservation

- **Problem:** Validation only checks triple-backtick balance and does not detect table or code conversion damage.
- **Proposed Solution:** Add representative conversion fixtures and tune conversion/post-processing for code blocks, pre/code pairs, definition lists, and tables.
- **Impact:** Protects the highest-value structures in programming documentation.
- **Complexity:** Medium

## Phase 7: Output and Downstream Consumption

### 1. Fix Anchor Collision Handling

- **Problem:** `_anchor()` does not ensure uniqueness, so duplicate titles can create ambiguous table-of-contents links.
- **Proposed Solution:** Generate anchors through a shared unique-anchor registry and use the same anchors for headings and TOC links.
- **Impact:** Improves navigation correctness in consolidated manuals.
- **Complexity:** Low

### 2. Add Per-Document Metadata Frontmatter

- **Problem:** Per-document Markdown has human-readable metadata but no machine-readable frontmatter.
- **Proposed Solution:** Add optional YAML frontmatter with source, topic, slug, order, mode, diagnostics, and generation metadata.
- **Impact:** Makes generated output easier to index, diff, and consume.
- **Complexity:** Medium

### 3. Add Chunked Export for Retrieval Workloads

- **Problem:** Output is either many source documents or one large consolidated file. There is no stable chunk manifest for embeddings or retrieval.
- **Proposed Solution:** Add optional `chunks/` output with size-bounded Markdown chunks, stable IDs, source references, topic metadata, and JSONL manifests.
- **Impact:** Makes the project more directly useful for AI/RAG ingestion.
- **Complexity:** Medium

### 4. Add Cache Freshness and Incremental Update Policies

- **Problem:** Cache behavior is mostly "use if present" or `--force-refresh`.
- **Proposed Solution:** Add cache metadata with fetched timestamp, source version, ETag/checksum where available, and configurable refresh policies.
- **Impact:** Makes recurring documentation updates auditable and predictable.
- **Complexity:** Medium

## Phase 8: Advanced Expansion

### 1. Add Plugin-Ready Source Registration

- **Problem:** New sources require editing `SourceRegistry.__init__()` and shipping code inside the package.
- **Proposed Solution:** Support optional entry-point or config-based source registration while keeping DevDocs, MDN, and Dash built in.
- **Impact:** Enables growth beyond current sources without hard-coding every adapter.
- **Complexity:** High

### 2. Add Extended Conversion Backends Intentionally

- **Problem:** Dependencies imply PDF, DOCX, browser, and document-conversion ambitions, but those paths are not active.
- **Proposed Solution:** Either wire optional conversion backends under explicit adapters/extras or remove the dependencies.
- **Impact:** Converts ambiguous dependency residue into real capability or a cleaner runtime.
- **Complexity:** High

### 3. Add Quality Dashboards and Trend Reports

- **Problem:** Reports are per-run summaries without long-term trend tracking.
- **Proposed Solution:** Persist timestamped run summaries and generate trend reports for document counts, validation issues, output size, duration, diagnostics, and failures.
- **Impact:** Helps monitor ingestion quality over time.
- **Complexity:** Medium
