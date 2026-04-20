# Update Contract

- Keep section order unchanged.
- Prefer flat bullets over prose.
- Replace stale facts; do not append duplicate history.
- Record observed repo state only.

## Project Snapshot

- Name: DevDocsDownloader.
- Purpose: ingest official programming-language documentation and compile one normalized Markdown manual per language.
- Entry points: `documentation_downloader.py` for runtime, `setup.py` for environment bootstrap.

## Implemented Capabilities

- Typer CLI with `run`, `validate`, `init`, and an interactive wizard when launched without a subcommand.
- Language source parsing from `top_50_programming_languages_with_official_docs.txt`.
- Crawl planning with site adapters, per-language overrides, crawl modes, allowed/ignored path rules, sitemap seeding, and locale filtering.
- Async fetch pipeline with HTTP caching, retries, robots checks, per-host delay, browser fallback, and multi-language concurrency.
- Extraction for HTML, Markdown, PDF, DOCX, and plain text.
- Extraction scoring and normalization before compilation.
- Resumable per-language crawl state in `state/` plus fetch cache in `cache/`.
- Duplicate-content suppression by content hash.
- Markdown compilation, validation, reports, and diagnostics output.
- Test coverage for resume flow, extraction/normalization, compiler/validator, and URL/discovery rules.

## Stability

- Current level: beta / usable, with active hardening.
- Core pipeline exists and is test-backed.
- No recent repo evidence of a fresh end-to-end smoke crawl after the latest pipeline and wizard changes.

## Known Limitations

- Browser fallback still creates and closes a Playwright page per browser fetch; this is a visible performance hotspot.
- Wizard answers are not persisted between runs.
- Extracted documents are accumulated in memory until final compilation for a language.
- Recent priority notes indicate retry semantics for failed or thin-content pages still need deeper validation.
- Main AI context system was added after the repo was already active, so older work may be incompletely documented.

## Current Priorities Visible In Repo

- Run a real end-to-end crawl to verify the current pipeline state.
- Reduce Playwright overhead with page reuse.
- Persist wizard configuration.
- Tighten retry/resume handling for failed extraction paths.
- Flatten memory usage during large crawls.

## Working Assumptions For Future Agents

- End-to-end correctness matters more than cleanup refactors.
- `doc_ingest/pipeline.py` is the highest-leverage file.
- Any behavior change requires matching doc updates, including AI-context docs.