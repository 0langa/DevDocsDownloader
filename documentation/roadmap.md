# DevDocsDownloader Roadmap

This roadmap is intentionally forward-looking. Completed work is summarized only to establish the current baseline; the detailed execution focus is the remaining backlog.

## Current Baseline

The project has moved from a fragile source-downloader prototype into a tested source-adapter ingestion system.

Completed foundations:

- Production safety: filesystem-safe slugs, atomic writes, safe archive extraction, retry helpers, local-first validation, and active run checkpoints.
- Core usability: source diagnostics, topic include/exclude filters, preset auditing, and maintained Dash seed data.
- Test and contract coverage: output contract docs, golden fixtures, fixture-backed end-to-end tests, CLI contract tests, resilience tests, live endpoint probes, Ruff, and mypy.
- Architecture: shared `SourceRuntime`, pooled source HTTP clients, typed adapter events, compiler planning/rendering/writing separation, and archived historical crawler-only utilities.
- Performance baseline: per-document files are written as documents arrive, and consolidated output is streamed from temporary fragments instead of retaining all Markdown bodies in memory.

Current guarantees:

- Routine tests do not require live network access.
- Live endpoint checks are opt-in with `DEVDOCS_LIVE_TESTS=1`.
- `pyproject.toml` is canonical for dependencies.
- The active product is a curated DevDocs, MDN, and Dash source-adapter ingester, not a general crawler.

## Phase 5: Performance and Scalability

### 1. Add Adapter-Level Resume From Checkpoints

- **Problem:** Checkpoints record the last emitted document boundary, but adapters still replay from the beginning after a failed run.
- **Proposed Solution:** Add optional resume support keyed by `Document.order_hint` or source-native inventory IDs. DevDocs and Dash can skip inventory rows before the checkpoint; MDN can skip sorted `index.md` paths. Keep full replay as the safe fallback.
- **Impact:** Reduces wasted network, conversion, and disk work after large-run failures.
- **Complexity:** High

### 2. Reduce Fsync Overhead for Generated Markdown

- **Problem:** Atomic write helpers call `os.fsync()` for every generated Markdown file and fragment. This is robust but expensive for large output trees.
- **Proposed Solution:** Add durability modes: strict for state/checkpoints/reports and balanced for reproducible generated Markdown. Keep atomic replace in both modes.
- **Impact:** Improves throughput while preserving strong guarantees for critical state.
- **Complexity:** Medium

### 3. Add Per-Source Concurrency and Rate Limits

- **Problem:** Bulk concurrency is language-level only. There is no source-aware throttling or rate policy.
- **Proposed Solution:** Add source-level semaphores/rate settings in `SourceRuntime`. Preserve deterministic document ordering by parallelizing only safe independent operations.
- **Impact:** Improves bulk throughput without overloading upstream services.
- **Complexity:** Medium

### 4. Optimize MDN Cache Extraction

- **Problem:** MDN cache extraction is large and all-or-nothing. Freshness is marker-based rather than version-aware.
- **Proposed Solution:** Track archive checksum or ETag, extracted content version, and area-level readiness. Avoid re-extracting unchanged trees.
- **Impact:** Reduces disk churn and makes recurring MDN runs more predictable.
- **Complexity:** Medium

## Phase 6: Extraction and Conversion Quality

### 1. Add Source-Specific HTML Cleanup Before `markdownify`

- **Problem:** DevDocs and Dash rely mostly on direct `markdownify` conversion, so navigation, breadcrumbs, or footer noise can leak into output.
- **Proposed Solution:** Add source-specific cleanup functions that select main content and remove known noisy elements before conversion.
- **Impact:** Improves Markdown quality without changing source acquisition.
- **Complexity:** Medium

### 2. Replace Minimal MDN Frontmatter Parsing With Robust YAML Parsing

- **Problem:** MDN frontmatter parsing ignores nested YAML, indented metadata, list values, and richer status fields.
- **Proposed Solution:** Add a safe YAML/frontmatter parser and preserve fields such as `title`, `slug`, `page-type`, `browser-compat`, and status metadata.
- **Impact:** Makes MDN filtering and metadata more reliable.
- **Complexity:** Low

### 3. Preserve and Rewrite Source Links

- **Problem:** Converted Markdown can contain relative links that do not work in generated output.
- **Proposed Solution:** Normalize links to absolute source URLs or generated local document links where targets are known. Report unresolved links during validation.
- **Impact:** Produces more usable offline manuals and downstream corpora.
- **Complexity:** High

### 4. Improve Code Block and Table Preservation

- **Problem:** Validation only checks triple-backtick balance and does not detect table, definition-list, or code conversion damage.
- **Proposed Solution:** Add representative conversion fixtures and tune conversion/post-processing for code blocks, pre/code pairs, definition lists, and tables.
- **Impact:** Protects the highest-value structures in programming documentation.
- **Complexity:** Medium

## Phase 7: Output and Downstream Consumption

### 1. Fix Anchor Collision Handling

- **Problem:** `_anchor()` does not ensure uniqueness, so duplicate titles can create ambiguous table-of-contents links.
- **Proposed Solution:** Generate anchors through a shared unique-anchor registry and use the same anchors for headings and TOC links.
- **Impact:** Improves navigation correctness in consolidated manuals.
- **Complexity:** Low

### 2. Add Optional Per-Document Metadata Frontmatter

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
- **Impact:** Enables source growth without hard-coding every adapter.
- **Complexity:** High

### 2. Add Extended Conversion Backends Intentionally

- **Problem:** Optional dependencies support PDF, DOCX, browser, and document-conversion ambitions, but those paths are not wired into active adapters.
- **Proposed Solution:** Either wire optional conversion backends under explicit adapters/extras or remove the unused optional capability.
- **Impact:** Converts ambiguous expansion paths into real capability or a cleaner package.
- **Complexity:** High

### 3. Add Quality Dashboards and Trend Reports

- **Problem:** Reports are per-run summaries without long-term trend tracking.
- **Proposed Solution:** Persist timestamped run summaries and generate trend reports for document counts, validation issues, output size, duration, diagnostics, and failures.
- **Impact:** Helps monitor ingestion quality over time.
- **Complexity:** Medium
