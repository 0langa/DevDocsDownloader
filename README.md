# Documentation Ingestion System

Production-oriented Python pipeline for ingesting official programming language documentation and compiling one normalized Markdown manual per language.

## Features

- Parses `source-documents/renamed-link-source.md`
- Plans crawl strategy per source with site adapters and override-aware boundaries
- Supports asynchronous concurrent fetching, extraction scoring, retries, caching, resumability, and browser fallback
- Uses a bounded two-stage pipeline (`fetch/discover` -> `extract/transform`) to keep CPU-heavy conversions from blocking crawl throughput
- Supports parallel language processing and per-language crawl budget limits for faster large runs
- Uses canonical URL normalization, duplicate suppression, sitemap seeding, and robots-aware filtering
- Prefers a single documentation locale to avoid mixing multiple translated trees in one output
- Shows a live Rich terminal dashboard with crawl totals, language progress, queue depth, and overall completion
- Extracts HTML, Markdown, PDF, DOCX, and plain text into normalized Markdown
- Uses Docling-backed HTML conversion with fallback scoring against alternate extractors
- Persists per-language crawl state, page status, extraction metadata, and normalized page cache for resume/restart
- Batches normalized document cache writes and throttles diagnostics tree persistence to reduce disk churn on large crawls
- Emits per-stage performance metrics (fetch/discover/extract/persist), queue depth high-water marks, extraction latency percentiles, cache hit rates, CPU, and RSS in run reports
- Supports optional streaming compile input and bounded in-memory document retention for large runs
- Supports normalized cache format selection (`json`, `json_compact`, `msgpack`) for serialization tradeoff testing
- Supports adaptive extraction worker scaling and optional process executor mode for non-HTML extraction paths
- Deduplicates and merges documentation into one file per language with source metadata and crawl summary
- Validates output quality and writes JSON/Markdown reports plus per-language diagnostics trees

## Project structure

- `DevDocsDownloader.py` – runtime entry point kept at repo root
- `scripts/` – repository helper scripts
- `scripts/setup.py` – environment/bootstrap helper
- `scripts/analyze_doc_paths.py` – override/discovery analysis helper
- `scripts/build_skip_manifest.py` – skip-manifest helper
- `source-documents/` – source link list, requirements, and crawl override data
- `source-documents/renamed-link-source.md` – language source list consumed by the downloader
- `source-documents/requirements.txt` – Python dependency list
- `source-documents/doc_path_overrides.json` – path override data for planner/adapters
- `doc_ingest/` – application package
- `output/markdown/` – compiled Markdown manuals
- `output/reports/` – run reports
- `output/diagnostics/` – discovered link trees and crawl diagnostics
- `cache/` – fetched content cache
- `logs/` – runtime logs
- `state/` – resumable processing state
- `tmp/` – temporary workspace

## Installation

### Automatic setup

Run:

`python scripts/setup.py`

This will:

- create required folders
- create `.venv` if missing
- upgrade pip tooling
- install `source-documents/requirements.txt`
- install Playwright Chromium

### Manual setup

1. Create a virtual environment.
2. Install dependencies:

   `pip install -r source-documents/requirements.txt`

3. Install Playwright browser runtime:

   `python -m playwright install chromium`

## Usage

Run all languages:

`python DevDocsDownloader.py run`

Important/core docs only:

`python DevDocsDownloader.py run --mode important`

Full documentation crawl:

`python DevDocsDownloader.py run --mode full`

Resume from existing crawl state:

`python DevDocsDownloader.py run --language python --resume`

Faster run with multiple languages and higher page concurrency:

`python DevDocsDownloader.py run --language-concurrency 4 --page-concurrency 12 --max-pages 600 --max-discovered 2000 --per-host-delay 0.05`

Tune extraction throughput and backpressure for heavy HTML-to-Markdown runs:

`python DevDocsDownloader.py run --language python --page-concurrency 12 --extraction-workers 6 --max-pending-extractions 96`

Use compact normalized cache payloads and streaming compile mode:

`python DevDocsDownloader.py run --language python --normalized-cache-format json_compact --compile-streaming`

Evaluate process executor mode for non-HTML extraction:

`python DevDocsDownloader.py run --language python --extract-executor process --extract-process-workers 4`

Disable adaptive extraction scaling for deterministic benchmark runs:

`python DevDocsDownloader.py run --language python --no-adaptive-extraction-workers`

## Benchmark harness

Run benchmark trials with fixed corpus input:

`python scripts/benchmark_pipeline.py run --corpus benchmarks/corpora/core_docs_v1.json --trials 3 --cache-mode both --page-concurrency 8 --extraction-workers 4 --max-pages 400 --max-discovered 1200`

Collect per-trial CPU profiles while benchmarking:

`python scripts/benchmark_pipeline.py run --corpus benchmarks/corpora/core_docs_v1.json --trials 1 --cache-mode cold --profiler cprofile`

Compare latest benchmark with baseline:

`python scripts/benchmark_pipeline.py compare --latest output/reports/benchmarks/latest.json --baseline benchmarks/baselines/core_docs_v1.json --mode cold --fail-on-regression 8`

Use an alternate input file or output directory:

`python DevDocsDownloader.py run --input-file source-documents/renamed-link-source.md --output-dir compiled_docs`

Run one language:

`python DevDocsDownloader.py run --language python`

Force refresh state:

`python DevDocsDownloader.py run --language python --force-refresh`

Dry-run planning:

`python DevDocsDownloader.py run --dry-run`

Validate outputs only:

`python DevDocsDownloader.py validate`

Initialize folder structure:

`python DevDocsDownloader.py init`

## Notes

- Some official sources such as ISO standard pages may expose limited public content or paid assets. The pipeline records failures and suspected incompleteness in reports.
- Browser rendering is used as a fallback for dynamically rendered documentation.
- Runtime logs are written to `logs/run.log` so the terminal can stay focused on the live progress screen.
- The system is resumable through files in `state/`, normalized page cache in `cache/<language>/normalized/`, and fetched asset cache in `cache/`.
- For very large doc sites, use `--max-pages` and `--max-discovered` to stop one domain from expanding indefinitely.
- By default, the crawler prefers English documentation paths and skips common non-English localized URL variants.
- Use `--mode important` for key tutorials/references/manuals only, or `--mode full` for the broadest crawl.
- URLs that finish with an HTTP error are kept in failure state and surfaced in state/report output for later retries.

