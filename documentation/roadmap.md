# DevDocsDownloader Roadmap

This roadmap is forward-looking. Completed work is summarized briefly so the remaining priorities are clear.

## Current Baseline

The project is now a tested source-adapter ingestion system for DevDocs, MDN, and Dash/Kapeli.

Completed foundations:

- Production safety: filesystem-safe slugs, atomic writes, safe archive extraction, retry helpers, local-first validation, and active run checkpoints.
- Core usability: source diagnostics, topic include/exclude filters, preset auditing, maintained Dash seed data, and opt-in live endpoint probes.
- Contracts and tooling: stable output contract docs, golden fixtures, fixture-backed integration tests, CLI contract tests, Ruff, mypy, and canonical `pyproject.toml` dependencies.
- Architecture: shared `SourceRuntime`, pooled HTTP clients, typed adapter events, compiler planning/rendering/writing separation, and archived historical crawler utilities.
- Performance and scalability: streaming compilation, automatic checkpoint resume with artifact manifests, balanced generated-Markdown durability, source-profile throttling, and metadata-driven MDN extraction reuse.
- Extraction quality: source-specific DevDocs/Dash HTML cleanup, source-absolute link rewriting, safe MDN YAML frontmatter parsing, and richer validation warnings for links, HTML leftovers, malformed tables, and definition-list artifacts.
- Output and consumption: collision-safe consolidated anchors, optional per-document YAML frontmatter, optional Markdown+JSONL chunk exports, source-agnostic cache freshness metadata, and a GUI-ready service layer over CLI workflows.

Current guarantees:

- Routine tests do not require live network access.
- Successful runs remove active checkpoints after stable state is saved.
- Failed runs can resume automatically when checkpoint identity and artifact paths are still valid.
- State, checkpoints, reports, and expensive cache/archive writes remain strict; generated Markdown defaults to balanced atomic writes.
- DevDocs, Dash, and MDN normalize relative links toward source-absolute URLs where source context is known.
- Optional downstream outputs are disabled by default, so the baseline output contract remains conservative.
- Future GUI work should call `doc_ingest.services.DocumentationService` instead of shelling out to Typer commands.
- The active product is a curated source-adapter ingester, not a general crawler.

## Phase 7: Output and Downstream Consumption - Completed

### 1. Fix Anchor Collision Handling

- **Problem:** `_anchor()` does not ensure uniqueness, so duplicate titles can create ambiguous table-of-contents links.
- **Implemented:** Consolidated output now uses a shared unique-anchor registry and explicit heading anchors that match TOC links.
- **Impact:** Improves navigation correctness in consolidated manuals, including repeated document titles.
- **Complexity:** Low

### 2. Add Optional Per-Document Metadata Frontmatter

- **Problem:** Per-document Markdown has human-readable metadata but no machine-readable frontmatter.
- **Implemented:** Optional `--document-frontmatter` emits YAML metadata while preserving existing human-readable metadata.
- **Impact:** Makes generated output easier to index, diff, and consume.
- **Complexity:** Medium

### 3. Add Chunked Export for Retrieval Workloads

- **Problem:** Output is either many source documents or one large consolidated file. There is no stable chunk manifest for embeddings or retrieval.
- **Implemented:** Optional `--chunks` writes size-bounded Markdown chunks and `chunks/manifest.jsonl` with stable IDs and source references.
- **Impact:** Makes the project more directly useful for AI/RAG ingestion.
- **Complexity:** Medium

### 4. Add Cache Freshness and Incremental Update Policies

- **Problem:** DevDocs and Dash cache behavior is still mostly "use if present" or `--force-refresh`; MDN now has stronger archive metadata but no shared cache policy model.
- **Implemented:** Source cache artifacts now support source-agnostic metadata and configurable policies: `use-if-present`, `ttl`, `always-refresh`, and `validate-if-possible`.
- **Impact:** Makes recurring documentation updates auditable and predictable across all sources.
- **Complexity:** Medium

## Phase 8: Visual GUI and Advanced Expansion

### 1. Build a Local Visual GUI Over the Service Layer

- **Problem:** The CLI is scriptable and complete, but non-technical users need a visual way to configure languages, sources, modes, cache policy, output options, progress, validation, and reports.
- **Proposed Solution:** Build a local GUI that calls `DocumentationService` for all operations. The first screen should be the operational dashboard, not a marketing page: language/source selection, preset/bulk controls, run queue, live progress, output browser, validation diagnostics, reports, checkpoints, and cache controls.
- **Impact:** Makes the full ingestion system accessible without weakening the CLI contract.
- **Complexity:** High

### 2. Add Plugin-Ready Source Registration

- **Problem:** New sources require editing `SourceRegistry.__init__()` and shipping code inside the package.
- **Proposed Solution:** Support optional entry-point or config-based source registration while keeping DevDocs, MDN, and Dash built in.
- **Impact:** Enables source growth without hard-coding every adapter.
- **Complexity:** High

### 3. Add Extended Conversion Backends Intentionally

- **Problem:** Optional dependencies support PDF, DOCX, browser, and document-conversion ambitions, but those paths are not wired into active adapters.
- **Proposed Solution:** Either wire optional conversion backends under explicit adapters/extras or remove the unused optional capability.
- **Impact:** Converts ambiguous expansion paths into real capability or a cleaner package.
- **Complexity:** High

### 4. Add Quality Dashboards and Trend Reports

- **Problem:** Reports are per-run summaries without long-term trend tracking.
- **Proposed Solution:** Persist timestamped run summaries and generate trend reports for document counts, validation issues, output size, duration, diagnostics, and failures.
- **Impact:** Helps monitor ingestion quality over time.
- **Complexity:** Medium
