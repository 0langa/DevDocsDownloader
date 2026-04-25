# DevDocsDownloader Development Roadmap

This roadmap is based on the current repository state as inspected on 2026-04-25. The active system is a source-adapter ingestion pipeline centered on DevDocs, MDN, and Dash/Kapeli, not the older generic crawler implied by some stale support scripts. Priorities below favor output integrity, restart safety, source reliability, and maintainable growth.

## Phase 1: Critical Fixes and Stabilization

### 1. Fix unsafe compiler filenames from adapter-provided slugs

- **Problem:** `LanguageOutputBuilder.add()` only falls back to `slugify(document.title)` when `document.slug` is empty. Non-empty slugs from adapters can still contain Windows-invalid characters. The current test suite fails on Windows because `std::filesystem::path` is written directly as a filename.
- **Proposed Solution:** Normalize every incoming document slug through `slugify()` before `_unique_slug()`. Keep adapter-specific raw paths only as source metadata, not filesystem names. Add tests covering colon, dot, slash, reserved names, and duplicate post-normalization slugs.
- **Impact:** Restores cross-platform correctness and prevents production runs from failing late during output compilation.
- **Complexity:** Low

### 2. Make all persisted artifacts atomic and consistent

- **Problem:** `RunStateStore` uses atomic JSON writes, but several other persisted artifacts do not. `compiler.py` writes `_meta.json` directly, `reporting/writer.py` writes reports directly, and source adapters write catalog/cache files directly. Interrupted runs can leave corrupt metadata, reports, or catalogs.
- **Proposed Solution:** Route metadata, report, catalog, and cache writes through `write_json()`, `write_text()`, or `write_bytes()`. For downloaded files, write to a temporary sibling and replace after validation when possible.
- **Impact:** Improves restart safety and reduces corruption after cancellation, process termination, or partial downloads.
- **Complexity:** Medium

### 3. Add safe archive extraction for MDN and Dash

- **Problem:** `MdnContentSource._extract_tarball()` and `DashFeedSource._download_docset()` call `tar.extract()` or `extractall()` on remote archives without validating member paths. Even trusted upstream archives should not be extracted with path traversal risk.
- **Proposed Solution:** Add a shared tar extraction helper that rejects absolute paths, parent traversal, drive prefixes, symlinks that escape the destination, and oversized unexpected members. Use it for MDN and Dash.
- **Impact:** Closes a serious filesystem safety gap in the cache population path.
- **Complexity:** Medium

### 4. Add HTTP retry and backoff around source downloads

- **Problem:** DevDocs, MDN, and Dash fetches currently propagate transient HTTP, timeout, and connection failures directly. `tenacity` is declared but unused, and there is no shared retry policy.
- **Proposed Solution:** Implement a small async download helper with bounded retries, exponential backoff, retryable status codes, timeouts, and source-aware error messages. Use it for catalogs, DevDocs datasets, MDN tarball streams, and Dash docsets.
- **Impact:** Improves reliability for long-running bulk jobs where one transient upstream failure currently fails an entire language.
- **Complexity:** Medium

### 5. Decouple validate-only from live source resolution

- **Problem:** `validate` and `run --validate-only` still call `SourceRegistry.resolve()` before validating local output. Local validation can fail or block if source catalogs are unavailable, even when compiled files already exist.
- **Proposed Solution:** Add a validation path that can resolve from `state/<language>.json` or `output/markdown/<slug>/_meta.json` before contacting remote catalogs. Extend `validate` with `--output-dir`, `--source`, and explicit slug fallback where needed.
- **Impact:** Makes validation predictable in offline CI, after upstream outages, and when checking previously generated bundles.
- **Complexity:** Medium

### 6. Resolve broken repository surface area

- **Problem:** `scripts/benchmark_pipeline.py` and `scripts/build_skip_manifest.py` reference old crawler flags, missing modules such as `doc_ingest.parser`, and missing config fields such as `input_file` and `crawl_cache_dir`. `.claude/settings.local.json` contains similar stale command hints.
- **Proposed Solution:** Either modernize these scripts for the current source-adapter pipeline or move them to an archival location with explicit non-runtime status. Prefer modernizing the benchmark harness and removing the skip-manifest script unless crawler state is intentionally restored.
- **Impact:** Prevents engineers and agents from following broken maintenance paths and clarifies the canonical architecture.
- **Complexity:** Medium

## Phase 2: Core Functionality Gaps

### 1. Add resumable per-language checkpoints

- **Problem:** Current state is saved only after successful compilation. A failed MDN or Dash run may leave large caches and partial output, but there is no document-level checkpoint for resuming compilation or identifying the last safe boundary.
- **Proposed Solution:** Introduce per-language run checkpoints with source slug, mode, document inventory position, emitted document count, failed document records, and output generation phase. Keep final `LanguageRunState` as the stable summary, but add a separate checkpoint file for active runs.
- **Impact:** Improves recovery for large `full` runs and reduces wasted network, conversion, and disk work after failures.
- **Complexity:** High

### 2. Track source inventory and skipped documents explicitly

- **Problem:** Adapters silently skip missing HTML, empty converted content, duplicate base paths, unsupported MDN page types, and missing Dash files. Reports only show final document counts, so source loss is hard to distinguish from intended filtering.
- **Proposed Solution:** Extend the source contract to expose inventory counts and skip reasons, or emit structured diagnostics alongside `Document` objects. Include counts for discovered, emitted, filtered, duplicate, missing-content, conversion-empty, and failed documents.
- **Impact:** Makes output completeness auditable and helps diagnose quality regressions by source.
- **Complexity:** Medium

### 3. Add user-controlled topic include and exclude filters

- **Problem:** The only filtering modes are `important` and `full`, backed by source-specific defaults. Users cannot request a subset such as Python `asyncio` plus `typing`, or exclude noisy Dash entry types.
- **Proposed Solution:** Add CLI options such as `--include-topic`, `--exclude-topic`, and optional config-file support. Apply filters after source normalization so behavior is consistent across adapters.
- **Impact:** Enables practical smaller bundles without requiring code edits to `devdocs_core.json` or source adapters.
- **Complexity:** Medium

### 4. Expand supported source catalogs deliberately

- **Problem:** MDN exposes only six fixed areas, and Dash support is limited to `_DEFAULT_DASH_SEED`. Presets include languages and tools that may not resolve depending on source catalogs.
- **Proposed Solution:** Add a catalog coverage audit command that reports unresolved preset entries. Extend MDN areas where the content tree supports them and add a maintainable Dash seed file with tested entries and metadata.
- **Impact:** Makes bulk presets more trustworthy and reduces surprising "No source provides" outcomes.
- **Complexity:** Medium

## Phase 3: Architecture and Refactoring

### 1. Introduce shared source runtime services

- **Problem:** Each adapter creates short-lived `httpx.AsyncClient` instances and owns its own cache write behavior. `DocumentationPipeline.close()` is currently a no-op because there are no shared resources.
- **Proposed Solution:** Add a `SourceRuntime` or `IngestionContext` that owns shared HTTP clients, retry policy, cache helpers, user agent, and telemetry hooks. Pass it to adapters through the registry and close it from `DocumentationPipeline.close()`.
- **Impact:** Reduces duplicated network/cache logic and makes lifecycle management real instead of aspirational.
- **Complexity:** High

### 2. Formalize adapter outputs beyond `Document`

- **Problem:** The current adapter boundary only streams `Document`. It cannot communicate source inventory, warnings, source-specific metadata, link maps, assets, or recoverable per-document failures without side channels.
- **Proposed Solution:** Introduce a typed stream result such as `DocumentEvent` with variants for document, warning, skipped, source_stats, and asset. Keep a compatibility wrapper for existing adapters during migration.
- **Impact:** Supports better reporting, validation, and future output formats without overloading `Document`.
- **Complexity:** High

### 3. Separate compilation planning from writing

- **Problem:** `LanguageOutputBuilder.finalize()` groups, renders, and writes all outputs in one method. This makes it difficult to test rendered structure, stream large outputs, or add alternate output layouts.
- **Proposed Solution:** Split compilation into planning, rendering, and persistence modules. Keep a pure render model for topics, documents, consolidated output, index, and metadata, then write through a storage layer.
- **Impact:** Improves testability and unlocks streaming or alternate storage without rewriting source adapters.
- **Complexity:** Medium

### 4. Decide the fate of crawler-era utilities

- **Problem:** `doc_ingest/utils/urls.py`, `scripts/analyze_doc_paths.py`, benchmark corpus URLs, and stale setup directories point to a previous crawler design that is not wired into the active runtime.
- **Proposed Solution:** Make an explicit architecture decision: either keep the project as a curated source ingester and archive crawler utilities, or create a separate crawler plugin path with its own tests and config.
- **Impact:** Prevents architecture drift and keeps future work aligned with a single maintained runtime model.
- **Complexity:** Medium

## Phase 4: Performance and Scalability

### 1. Stream compilation for large languages

- **Problem:** `LanguageOutputBuilder` stores every `Document` for a language in memory until finalization. Large `full` runs can hold significant Markdown content before any consolidated output is written.
- **Proposed Solution:** Add a streaming compiler mode that writes per-document files as documents arrive, records topic manifests, and builds consolidated output from manifests or append-safe temporary files. Preserve deterministic ordering using `order_hint`.
- **Impact:** Lowers memory pressure and improves scalability for large DevDocs, MDN, and Dash datasets.
- **Complexity:** High

### 2. Reduce fsync overhead for many small files

- **Problem:** `write_text()`, `write_json()`, and `write_bytes()` call `os.fsync()` for every file. This is safest, but per-document writes can become a major bottleneck when generating thousands of small Markdown files.
- **Proposed Solution:** Add configurable durability levels such as `strict` and `balanced`. Keep strict for state/checkpoints, but allow balanced atomic replacement without per-file fsync for reproducible generated Markdown.
- **Impact:** Improves throughput on large compilations while retaining strong guarantees for state files.
- **Complexity:** Medium

### 3. Modernize the benchmark harness

- **Problem:** `scripts/benchmark_pipeline.py` measures an old page-crawler model and reads report fields that current reports do not emit. It cannot provide valid performance data for the active source-adapter system.
- **Proposed Solution:** Rewrite the harness around `run`, `bulk`, source selection, mode, language concurrency, cold/warm cache behavior, wall time, document count, output size, cache size, and peak memory. Use fixture-friendly small corpora plus optional live upstream runs.
- **Impact:** Enables evidence-based performance work instead of code-inspection guesses.
- **Complexity:** Medium

### 4. Add per-source concurrency and rate limits

- **Problem:** Bulk runs have language-level concurrency only. There is no source-aware throttling, and individual source fetches are mostly sequential inside a language.
- **Proposed Solution:** Add source-level semaphores and rate-limit settings. Keep DevDocs dataset fetch simple, but allow safe parallelism for independent conversion or document processing where ordering can be preserved.
- **Impact:** Improves throughput under bulk workloads without overloading upstream services.
- **Complexity:** Medium

### 5. Optimize MDN cache extraction

- **Problem:** MDN uses a large repository tarball and extraction marker. Rebuilds are disk-heavy, and extraction is all-or-nothing for the supported content tree.
- **Proposed Solution:** Track archive checksum or ETag, extracted content version, and area-level readiness. Avoid re-extracting unchanged trees, and allow deleting stale extracted folders before rebuild.
- **Impact:** Reduces disk churn and makes MDN cache behavior easier to reason about.
- **Complexity:** Medium

## Phase 5: Extraction and Conversion Quality

### 1. Add source-specific HTML cleanup before `markdownify`

- **Problem:** DevDocs and Dash rely directly on `markdownify` after stripping only `script` and `style`. Navigation, breadcrumbs, duplicate headings, hidden UI, and footer content can leak into Markdown depending on upstream HTML.
- **Proposed Solution:** Add cleanup functions per source that select main content regions and remove known noisy elements before conversion. Keep fallback conversion for unknown structures and record cleanup warnings.
- **Impact:** Improves Markdown quality without changing the source-adapter contract.
- **Complexity:** Medium

### 2. Replace minimal MDN frontmatter parsing with robust YAML handling

- **Problem:** `_parse_frontmatter()` ignores nested YAML, indented metadata, lists, and more complex values. This can misclassify pages or lose metadata as MDN evolves.
- **Proposed Solution:** Add `PyYAML` or a small safe frontmatter parser dependency, parse only the frontmatter block, and preserve selected fields such as `title`, `slug`, `page-type`, `browser-compat`, and `status`.
- **Impact:** Makes MDN filtering and metadata more reliable.
- **Complexity:** Low

### 3. Preserve and rewrite source links

- **Problem:** Converted Markdown can contain relative links that point nowhere in the generated output, and consolidated output anchors are generated independently from source links.
- **Proposed Solution:** Build a link normalization pass that converts external relative links to absolute source URLs and local generated-document links where a target is known. Report unresolved links during validation.
- **Impact:** Produces more usable offline Markdown and improves downstream consumption.
- **Complexity:** High

### 4. Improve code block and table preservation

- **Problem:** Current validation only counts triple backticks. It does not detect indented code loss, malformed fenced blocks, broken Markdown tables, or conversion artifacts from HTML tables.
- **Proposed Solution:** Add conversion tests with representative DevDocs and Dash snippets. Tune `markdownify` options and post-processing for code blocks, pre/code pairs, definition lists, and tables.
- **Impact:** Protects the most valuable documentation structures from silent degradation.
- **Complexity:** Medium

## Phase 6: Output and Markdown Standardization

### 1. Define a stable Markdown output contract

- **Problem:** Per-document files, section files, indexes, consolidated files, and `_meta.json` are generated, but the exact schema is implicit in renderer code and shallow tests.
- **Proposed Solution:** Document an output contract covering file layout, metadata fields, heading levels, source links, topic ordering, slug rules, and compatibility expectations. Add golden-file tests for a small synthetic language.
- **Impact:** Gives downstream tools and future maintainers a stable target.
- **Complexity:** Medium

### 2. Fix anchor collision handling in consolidated output

- **Problem:** `_anchor()` does not ensure uniqueness. Duplicate topic names or duplicate document titles under similar topics can produce ambiguous table-of-contents links.
- **Proposed Solution:** Generate anchors through a shared unique-anchor registry during consolidated rendering. Use the same generated anchors for headings and table-of-contents links.
- **Impact:** Improves navigation correctness in large compiled manuals.
- **Complexity:** Low

### 3. Add per-document metadata frontmatter

- **Problem:** Per-document Markdown currently has human-readable header lines but no machine-readable metadata block. Downstream indexing cannot reliably extract source, topic, slug, order, mode, or generation details.
- **Proposed Solution:** Add optional YAML frontmatter to per-document files and consolidated section boundaries, controlled by a compatibility flag if needed.
- **Impact:** Makes generated output easier to index, diff, and consume in RAG or offline tooling.
- **Complexity:** Medium

### 4. Add chunked export for downstream AI ingestion

- **Problem:** The project describes AI-friendly Markdown, but output is either many source documents or one very large consolidated file. There is no chunk manifest optimized for embeddings or retrieval.
- **Proposed Solution:** Add an optional `chunks/` output with size-bounded Markdown chunks, stable IDs, source references, topic metadata, and a JSONL manifest.
- **Impact:** Expands the practical value of generated documentation without changing source ingestion.
- **Complexity:** Medium

## Phase 7: Developer Experience and Tooling

### 1. Reconcile dependency manifests

- **Problem:** `pyproject.toml`, `requirements.txt`, and `source-documents/requirements.txt` diverge. Several packages are unused by the active runtime, including `docling`, `mammoth`, `msgpack`, `playwright`, `pypdf`, `psutil`, and `tenacity` unless future work intentionally wires them in.
- **Proposed Solution:** Make `pyproject.toml` the canonical dependency source. Split optional extras such as `dev`, `benchmark`, `crawler-legacy`, and `conversion-extended`. Regenerate or remove duplicate requirements files.
- **Impact:** Reduces install cost, dependency confusion, and stale setup behavior.
- **Complexity:** Medium

### 2. Bring setup and CLI examples in line with current commands

- **Problem:** `scripts/setup.py` installs `source-documents/requirements.txt`, installs Playwright Chromium, creates crawler-era directories, and prints an invalid example command shape.
- **Proposed Solution:** Update setup to install current package dependencies, create only active runtime directories, and print valid examples such as `python DevDocsDownloader.py run python`.
- **Impact:** Makes fresh clone onboarding reliable.
- **Complexity:** Low

### 3. Add CLI contract tests

- **Problem:** Tests focus on source resilience and compiler path safety. There are no tests for Typer command behavior, `--output-dir`, bulk errors, list commands, validation-only behavior, or no-argument wizard bypass.
- **Proposed Solution:** Use Typer's test runner or subprocess-based tests for command help, invalid language handling, list commands with monkeypatched registries, validate-only local output, and bulk preset expansion.
- **Impact:** Prevents user-facing regressions and keeps scripted automation stable.
- **Complexity:** Medium

### 4. Add linting, formatting, and type-checking gates

- **Problem:** The repository has no visible Ruff, Black, mypy, pyright, or CI configuration. Type hints exist, but they are not enforced.
- **Proposed Solution:** Add Ruff for lint and format, plus a pragmatic type checker configuration. Start with package and tests, excluding archival scripts until they are modernized or removed.
- **Impact:** Catches simple errors earlier and keeps future refactors lower risk.
- **Complexity:** Low

### 5. Add fixture-based integration tests

- **Problem:** There is no complete deterministic run test for DevDocs, MDN, or Dash using local fixtures. Live upstream behavior is too variable for routine CI.
- **Proposed Solution:** Add fixture adapters or monkeypatched HTTP/archive inputs that exercise source resolution, fetch, compile, validate, state save, and report generation end to end.
- **Impact:** Protects the core ingestion contract without relying on network availability.
- **Complexity:** High

## Phase 8: Advanced Features and Future Expansion

### 1. Add a plugin-ready source registration model

- **Problem:** Adding a new source currently requires editing `SourceRegistry.__init__()` and shipping Python code inside the package.
- **Proposed Solution:** Support optional entry-point or config-based source registration while keeping built-in DevDocs, MDN, and Dash as first-class adapters. Require plugin adapters to implement the same typed source contract and tests.
- **Impact:** Enables growth beyond current sources without turning the core registry into a large hard-coded list.
- **Complexity:** High

### 2. Add extended conversion backends intentionally

- **Problem:** Dependencies imply future PDF, DOCX, browser, and document-conversion support, but none of that is wired into the active pipeline.
- **Proposed Solution:** If non-HTML sources are a product goal, add explicit optional conversion backends using tools such as `docling`, `pypdf`, `mammoth`, or Playwright under source-specific adapters. If not, remove the dependencies.
- **Impact:** Converts ambiguous dependency residue into either real capability or a cleaner runtime.
- **Complexity:** High

### 3. Add cache freshness and incremental update policies

- **Problem:** Cache behavior is mostly "use if present" or `--force-refresh`. There is no TTL, ETag, checksum, version pinning, or stale-cache report.
- **Proposed Solution:** Add cache metadata files with fetched timestamp, source version, ETag/checksum where available, and user-configurable refresh policies. Surface cache age in reports.
- **Impact:** Makes recurring documentation updates predictable and auditable.
- **Complexity:** Medium

### 4. Add quality dashboards and trend reports

- **Problem:** Reports are per-run summaries with shallow validation scores. There is no trend view for document counts, validation issues, output size, duration, or source failures across runs.
- **Proposed Solution:** Persist historical run summaries under timestamped report directories and generate a compact trend report. Include regression thresholds for document count drops, validation score drops, and duration increases.
- **Impact:** Helps maintain production ingestion quality over time.
- **Complexity:** Medium

### 5. Add source-specific semantic enrichment

- **Problem:** All sources collapse into generic topic/document Markdown. Rich source metadata such as MDN page type, browser compatibility, DevDocs entry type, Dash symbol type, and API kind is mostly discarded.
- **Proposed Solution:** Extend `Document` or the future event model with structured metadata and render it into `_meta.json`, per-document frontmatter, and chunk manifests.
- **Impact:** Improves search, filtering, retrieval, and downstream automation without changing the human-readable output.
- **Complexity:** Medium

