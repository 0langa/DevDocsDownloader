# Documentation Ingestion System

Production-oriented Python pipeline for ingesting official programming language documentation and compiling one normalized Markdown manual per language.

## Features

- Parses `top_50_programming_languages_with_official_docs.txt`
- Plans crawl strategy per source
- Supports asynchronous concurrent fetching/extraction with retries, caching, resumability, and browser fallback
- Supports parallel language processing and per-language crawl budget limits for faster large runs
- Prefers a single documentation locale to avoid mixing multiple translated trees in one output
- Shows a live Rich terminal dashboard with crawl totals, language progress, queue depth, and overall completion
- Extracts HTML, Markdown, PDF, DOCX, and plain text into normalized Markdown
- Deduplicates and merges documentation into one file per language
- Validates output quality and writes JSON/Markdown reports
- Persists discovered documentation links under `cache/discovered_links/` for faster reruns

## Project structure

- `documentation_downloader.py` – entry point
- `doc_ingest/` – application package
- `output/markdown/` – compiled Markdown manuals
- `output/reports/` – run reports
- `cache/` – fetched content cache
- `cache/discovered_links/` – saved discovered URL graph per language
- `state/` – resumable processing state
- `logs/` – runtime logs
- `tmp/` – temporary workspace

## Installation

### Automatic setup

Run:

`python setup.py`

This will:

- create required folders
- create `.venv` if missing
- upgrade pip tooling
- install `requirements.txt`
- install Playwright Chromium

### Manual setup

1. Create a virtual environment.
2. Install dependencies:

   `pip install -r requirements.txt`

3. Install Playwright browser runtime:

   `python -m playwright install chromium`

## Usage

Run all languages:

`python documentation_downloader.py run`

Important/core docs only:

`python documentation_downloader.py run --mode important`

Full documentation crawl:

`python documentation_downloader.py run --mode full`

Faster run with multiple languages and higher page concurrency:

`python documentation_downloader.py run --language-concurrency 4 --page-concurrency 12 --max-pages 600 --max-discovered 2000 --per-host-delay 0.05`

Run one language:

`python documentation_downloader.py run --language python`

Force refresh state:

`python documentation_downloader.py run --language python --force-refresh`

Dry-run planning:

`python documentation_downloader.py run --dry-run`

Validate outputs only:

`python documentation_downloader.py validate`

Initialize folder structure:

`python documentation_downloader.py init`

## Notes

- Some official sources such as ISO standard pages may expose limited public content or paid assets. The pipeline records failures and suspected incompleteness in reports.
- Browser rendering is used as a fallback for dynamically rendered documentation.
- Runtime logs are written to `logs/run.log` so the terminal can stay focused on the live progress screen.
- The system is resumable through files in `state/`, fetched asset cache in `cache/`, and discovered-link cache in `cache/discovered_links/`.
- Each language now uses as few discovered-link cache files as practical: one structured JSON file and one human-readable tree text file.
- For very large doc sites, use `--max-pages` and `--max-discovered` to stop one domain from expanding indefinitely.
- By default, the crawler prefers English documentation paths and skips common non-English localized URL variants.
- Use `--mode important` for key tutorials/references/manuals only, or `--mode full` for the broadest crawl.
- URLs that finish with an HTTP error are kept in failure state but are removed from the discovered-link cache.

## Discovered link cache format

For each language, `cache/discovered_links/` contains:

- `<language>.json` – compact structured cache with parent/depth metadata
- `<language>.tree.txt` – readable tree view of discovered paths

The JSON cache is optimized for reuse. The tree file is optimized for inspection.

## Output expectations

Each output file contains:

- top-level title
- source metadata
- generated table of contents
- merged documentation sections in stable order
- validation results in reports