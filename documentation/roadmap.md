# DevDocsDownloader Roadmap

This roadmap is forward-looking. Completed work is summarized briefly so the remaining priorities are clear.

## Current Baseline

The project is now a tested source-adapter ingestion system for DevDocs, MDN, and Dash/Kapeli.

Completed foundations:

- Production safety: filesystem-safe slugs, atomic writes, safe archive extraction, retry helpers, local-first validation, and active run checkpoints.
- Core usability: source diagnostics, topic include/exclude filters, preset auditing, generated source-discovery manifests with cached fallback, and opt-in live endpoint probes.
- Contracts and tooling: stable output contract docs, golden fixtures, fixture-backed integration tests, CLI contract tests, Ruff, mypy, and canonical `pyproject.toml` dependencies.
- Architecture: shared `SourceRuntime`, pooled HTTP clients, typed adapter events, compiler planning/rendering/writing separation, and archived historical crawler utilities.
- Performance and scalability: streaming compilation, automatic checkpoint resume with artifact manifests, balanced generated-Markdown durability, source-profile throttling, and metadata-driven MDN extraction reuse.
- Extraction quality: source-specific DevDocs/Dash HTML cleanup, source-absolute link rewriting, safe MDN YAML frontmatter parsing, and richer validation warnings for links, HTML leftovers, malformed tables, and definition-list artifacts.
- Output and consumption: collision-safe consolidated anchors, optional per-document YAML frontmatter, optional Markdown+JSONL chunk exports, source-agnostic cache freshness metadata, and service-layer output/report/checkpoint/cache inspection.
- Operator workflows: legacy local NiceGUI dashboard with CLI-equivalent run controls, in-process job queue, output browser, report drill-down, checkpoint controls, and cache metadata views retained as a migration bridge while the WinUI desktop release track is completed.
- Source expansion and fidelity: entry-point source plugins, exact local cross-document link rewriting, event-driven asset inventory, optional tokenizer chunking, and removal of unused extended-conversion extras.
- Release readiness: opt-in adaptive bulk scheduling, deterministic source suggestion tests, bounded live extraction sanity probes, desktop-safe runtime paths/settings, a local desktop backend API, WinUI desktop shell scaffolding, and GitHub Actions release automation for installer/portable artifacts.
- Desktop UX hardening: persistent WinUI tab/view state, shared live progress tracking with activity details, searchable language tree views, structured report/output/checkpoint/cache pages, DPI-aware shell defaults, and a desktop default output root at `Documents/DevDocsDownloader`.

Current guarantees:

- Routine tests do not require live network access.
- Successful runs remove active checkpoints after stable state is saved.
- Failed runs can resume automatically when checkpoint identity and artifact paths are still valid.
- State, checkpoints, reports, and expensive cache/archive writes remain strict; generated Markdown defaults to balanced atomic writes.
- DevDocs, Dash, and MDN normalize relative links toward source-absolute URLs where source context is known.
- Known same-language links are rewritten to generated local Markdown paths when exact targets are available.
- Optional downstream outputs are disabled by default, so the baseline output contract remains conservative.
- Asset handling is inventory-first and does not crawl arbitrary image URLs.
- The GUI calls `doc_ingest.services.DocumentationService` directly instead of shelling out to Typer commands.
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

## Phase 8: Validation, Diagnostics, and Observability - Completed

### 1. Deepen Output Validation Beyond Structural Checks

- **Problem:** Validation is still mostly structural. It checks required sections, size, code fences, relative links, and a few conversion artifacts, but it does not verify broken internal links, duplicate topic blocks, repeated documents, malformed heading hierarchy, Markdown renderability, or source completeness against discovered inventory.
- **Implemented:** `validate_output()` now adds internal-anchor checks, duplicate section/document checks, document heading-count checks, and source-inventory reconciliation using `SourceRunDiagnostics`.
- **Impact:** Makes validation reports more actionable and catches regressions that current golden tests may miss.
- **Complexity:** High

### 2. Add Per-Document Validation Reports

- **Problem:** Validation currently reports language-level issues only. Downstream consumers cannot easily identify which generated document caused a warning, duplicate, broken link, heading issue, or conversion artifact.
- **Implemented:** `output/reports/validation_documents.jsonl` records document-local validation issues with language/source identity, path, topic, slug, source URL, issues, and context.
- **Impact:** Improves debugging, GUI report drill-downs, and quality triage for large languages.
- **Complexity:** Medium

### 3. Formalize Per-Document Source Warnings

- **Problem:** Typed adapter events support warnings, but diagnostics still mostly aggregate skip counts and report-level warning strings. Recoverable per-document warnings do not have a stable persisted path.
- **Implemented:** `DocumentWarningEvent` and `SourceWarningRecord` persist structured document warnings on run reports/state while preserving human-readable warnings.
- **Impact:** Enables better quality reporting, GUI inspection, and source-specific remediation without overloading `Document`.
- **Complexity:** Medium

### 4. Add Runtime Telemetry and GUI Progress Events

- **Problem:** `SourceRuntime` has basic counters, and Rich progress shows live terminal state, but there is no stable event stream for GUI progress, throughput, retries, cache hits, bytes, or current phase transitions.
- **Implemented:** `DocumentationService` accepts an optional event sink and emits phase, document, warning, validation, runtime telemetry, and failure events. Runtime telemetry now includes requests, retries, bytes, failures, cache hits, and cache refreshes.
- **Impact:** Turns lifecycle and telemetry gaps into a reusable observability surface for both CLI and GUI.
- **Complexity:** Medium

### 5. Add Quality Trend Reports

- **Problem:** Reports are per-run summaries without long-term trend tracking.
- **Implemented:** Report writes now keep latest summaries, timestamped history files, document validation JSONL, and `trends.json` / `trends.md` summaries.
- **Impact:** Helps monitor ingestion quality and upstream drift over time.
- **Complexity:** Medium

## Phase 9: Visual GUI and Operator Workflows - Completed

### 1. Build a Local Visual GUI Over the Service Layer

- **Problem:** The CLI is scriptable and complete, but non-technical users need a visual way to configure languages, sources, modes, cache policy, output options, progress, validation, and reports.
- **Implemented:** Added an optional NiceGUI dashboard launched with `python DevDocsDownloader.py gui`. It calls `DocumentationService`, exposes run/bulk/validate/catalog/preset/output/report/checkpoint/cache workflows, and uses a local in-process job queue over service events. It now serves as a migration and internal operator surface while the supported `1.0.0` GUI direction is the WinUI shell plus bundled backend.
- **Impact:** Makes the full ingestion system accessible without weakening the CLI contract.
- **Complexity:** High

### 2. Add Output Browser and Report Drill-Down

- **Problem:** Users can generate per-document files, chunks, manifests, diagnostics, and reports, but there is no visual way to inspect them together.
- **Implemented:** Added service readers and GUI views for language bundles, output trees, Markdown preview, latest reports, document validation JSONL, history/trends, checkpoints, and cache metadata sidecars.
- **Impact:** Makes shallow validation and conversion issues easier to investigate without manually navigating output trees.
- **Complexity:** Medium

### 3. Add GUI Cache and Resume Controls

- **Problem:** Cache policy, force refresh, checkpoints, and resume fallback are production-critical but currently controlled through CLI flags and filesystem inspection.
- **Implemented:** Added GUI controls for cache policy, TTL, force refresh, catalog refresh, checkpoint listing, checkpoint manifest inspection through service APIs, and safe checkpoint deletion constrained to `state/checkpoints`.
- **Impact:** Gives operators safe visibility and control over recurring documentation updates.
- **Complexity:** Medium

## Phase 10: Source Expansion and Output Fidelity - Completed

### 1. Add Plugin-Ready Source Registration

- **Problem:** New sources require editing `SourceRegistry.__init__()` and shipping code inside the package.
- **Implemented:** `SourceRegistry` registers DevDocs, MDN, and Dash first, then loads optional source factories from the `devdocsdownloader.sources` entry-point group. Built-ins win name collisions and plugin failures are isolated as warnings.
- **Impact:** Enables source growth without hard-coding every adapter.
- **Complexity:** High

### 2. Improve Cross-Document Link Rewriting

- **Problem:** Phase 6 rewrites relative links to source-absolute URLs, but generated bundles still do not rewrite known same-language links to local generated documents.
- **Implemented:** The compiler builds an exact source-target map from source URLs, normalized source URLs, source paths, slugs, and generated document paths. Known same-bundle links are rewritten to local relative Markdown paths while external, unknown, and fenced-code links are preserved.
- **Impact:** Produces more useful offline manuals and downstream corpora.
- **Complexity:** High

### 3. Add Asset Inventory and Deduplicated Asset Handling

- **Problem:** Image and asset references are currently rewritten or stripped rather than represented as first-class output artifacts.
- **Implemented:** `AssetEvent` can carry bytes or a safe local path. The compiler writes `assets/manifest.json`, deduplicates copied assets by checksum, rewrites matching Markdown asset references to local paths, and records remote-only assets as references without fetching arbitrary URLs.
- **Impact:** Improves offline fidelity for documentation that relies on diagrams, screenshots, or local assets.
- **Complexity:** Medium

### 4. Add Tokenizer-Aware Chunking

- **Problem:** Chunk export is character-bounded, which is deterministic and dependency-free but not ideal for embedding model limits.
- **Implemented:** Character chunking remains the default. Optional `--chunk-strategy tokens` uses the `tokenizer` extra (`tiktoken`) and adds token offsets/counts to chunk manifest records.
- **Impact:** Makes RAG exports more predictable for embedding and retrieval workloads.
- **Complexity:** Medium

### 5. Remove Unused Extended Conversion Extras

- **Problem:** Optional dependencies support PDF, DOCX, browser, and document-conversion ambitions, but those paths are not wired into active adapters.
- **Implemented:** Removed the unused `conversion-extended` extra and stale `docling`, `mammoth`, and `pypdf` references from active setup guidance. PDF/DOCX/browser conversion should return only with a real adapter path and fixture coverage.
- **Impact:** Keeps install cost and dependency claims aligned with the active runtime.
- **Complexity:** High

## Phase 11: Scalability Intelligence and Test Expansion - Completed

### 1. Add Adaptive Worker and Backpressure Policy

- **Problem:** Bulk concurrency is static and there is no adaptive worker model, despite historical references to adaptive runtime behavior.
- **Implemented:** Added opt-in adaptive bulk scheduling with static as the default. Adaptive mode adjusts new language starts based on failures, retry/source failure pressure, and optional local resource pressure while preserving report order.
- **Impact:** Improves large bulk runs without sacrificing deterministic defaults.
- **Complexity:** High

### 2. Test Source Suggestion Quality

- **Problem:** Source resolution has fuzzy suggestions for missing languages, but suggestion quality is not directly tested.
- **Implemented:** Added deterministic registry fixtures for exact/family/prefix/contains resolution, source priority, Dash fallback, and deduplicated suggestion ordering across built-in and plugin-like catalogs.
- **Impact:** Prevents CLI and GUI resolution regressions.
- **Complexity:** Low

### 3. Extend Live Probes Toward Extraction Sanity

- **Problem:** Live endpoint probes validate representative link health but intentionally do not validate extraction or conversion correctness.
- **Implemented:** Added a separate `DEVDOCS_LIVE_EXTRACTION_TESTS=1` tier for bounded DevDocs conversion, MDN frontmatter/body parsing, and Dash archive-shape plus fixture conversion sanity.
- **Impact:** Catches upstream shape changes earlier while preserving deterministic routine tests.
- **Complexity:** Medium

## Desktop Release Track - In Progress

- Windows-native desktop shell under `desktop/DevDocsDownloader.Desktop/`
- loopback desktop backend host in `doc_ingest/desktop_backend.py`
- desktop-safe settings and storage roots
- persistent shell viewmodels and cached page instances so navigation does not reset forms or loaded data
- live SSE job progress, shared activity history, and richer phase/document payloads for the WinUI shell
- structured operator views replacing raw JSON dumps for Languages, Run/Bulk, Presets, Reports, Output Browser, Checkpoints, Cache, and Settings/Help
- backend freeze, installer, and GitHub Release workflow scaffolding
- release-facing docs now point to the WinUI desktop path as the supported GUI direction for `1.0.0`
- remaining practical blocker for full local verification on this machine: missing WinUI PRI packaging task assembly required by the Windows App SDK build targets

## Post-v1.0.0 Future Work

- Remove the legacy NiceGUI path completely once WinUI parity and release validation are complete.
- Add cooperative cancellation inside active source runs when safe cancellation boundaries are available.
- Add deeper semantic validation only where source-specific truth data exists.
- Reintroduce PDF/DOCX/browser conversion only with a real adapter path and fixture coverage.
