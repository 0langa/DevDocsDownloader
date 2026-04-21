# Update Contract

- Keep section order unchanged.
- Prefer module-to-responsibility bullets.
- Describe current mechanics, not aspirational design.
- Update this file whenever control flow, storage layout, or component boundaries change.

## Runtime Entry Points

- `DevDocsDownloader.py`: thin launcher at repo root; imports `doc_ingest.cli.app` and executes it.
- `scripts/setup.py`: bootstraps local environment, installs requirements from `source-documents/requirements.txt`, installs Playwright Chromium, and creates runtime folders.

## Core Modules

- `doc_ingest/cli.py`: CLI commands, interactive wizard, logging setup, run orchestration.
- `doc_ingest/config.py`: path, crawl, and planner configuration models; resolves workspace directories.
- `doc_ingest/parser.py`: parses the language input file into `LanguageEntry` records.
- `doc_ingest/planner/planner.py`: builds a `PlannedSource` per language.
- `doc_ingest/adapters.py`: site-specific crawl constraints and override application.
- `doc_ingest/discovery.py`: sitemap loading, robots handling, discovery filtering, and `UrlRecord` creation.
- `doc_ingest/fetchers/http.py`: async HTTP client, retry logic, cache read/write, host throttling.
- `doc_ingest/fetchers/browser.py`: Playwright fallback fetch path.
- `doc_ingest/extractors/`: asset-type detection plus HTML/PDF/DOCX/text extraction.
- `doc_ingest/normalizers/markdown.py`: cleanup and post-extraction normalization.
- `doc_ingest/pipeline.py`: end-to-end run orchestration, queues, state transitions, caching, compilation trigger.
- `doc_ingest/state.py`: load/save per-language crawl state.
- `doc_ingest/mergers/compiler.py`: orders extracted documents and compiles final Markdown.
- `doc_ingest/validators/markdown_validator.py`: quality checks for compiled output.
- `doc_ingest/reporting/writer.py`: writes run summaries and reports.
- `doc_ingest/progress.py`: Rich live progress dashboard.
- `doc_ingest/adaptive.py`: runtime tuning signals for concurrency and crawl limits.

## End-to-End Flow

1. CLI loads config and starts `DocumentationPipeline`.
2. Pipeline parses language entries and filters by requested language.
3. For each language, planner + adapter build crawl boundaries and starting URLs.
4. Pipeline loads saved state, cached normalized documents, and pending/discovered URLs.
5. Initial queue is seeded from planned start URLs, sitemap URLs, and resumable pending pages.
6. Worker tasks fetch pages with `HttpFetcher`; browser fallback is used for unsupported or weak HTML fetch results.
7. Extractors convert content to `ExtractedDocument`; normalization runs before persistence.
8. Discovery logic extracts follow-up links and enqueues allowed URLs.
9. State and diagnostics trees are persisted periodically.
10. After queue drain, compiled Markdown is written, validated, and reported.

## Data Flow

- Input source: `source-documents/renamed-link-source.md`.
- Crawl plan: `LanguageEntry` -> `PlannedSource`.
- Queue unit: `UrlRecord`.
- Fetch output: `FetchResult`.
- Extraction output: `ExtractedDocument`.
- Persistent state: `CrawlState` + `PageState` in `state/<slug>.json`.
- Raw fetch cache: `cache/`.
- Final artifacts: `output/markdown/`, `output/reports/`, `output/diagnostics/`.

## State And Persistence Rules

- State is per language, not global.
- Queue deduplication uses normalized/canonical URLs.
- Content deduplication uses content hashes from extracted documents.
- Periodic persistence writes both crawl state and a discovered-link tree.
- Resume behavior relies on page status in state plus cached normalized documents.

## Visible Design Decisions

- Planner/adapters are separated from runtime execution so crawl rules can vary by site.
- Extraction uses multiple extractors and a scorer instead of a single hard-coded HTML path.
- Browser rendering is a fallback, not the default fetch path.
- Validation is post-compilation, not inline during page processing.
- Progress tracking is decoupled from crawl logic through `CrawlProgressTracker` callbacks.