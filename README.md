# DevDocsDownloader

## Public Version: 1.5.0

DevDocsDownloader is a production-oriented documentation ingestion platform with a Python pipeline and a Windows desktop shell.

It resolves language docs from multiple upstream sources, compiles high-quality Markdown bundles, validates output quality, emits HTML/EPUB variants, and exposes local full-text/cross-reference search.

## Quick Links

- [2-Minute Getting Started](#2-minute-getting-started)
- [Current Feature Set (1.5.0)](#current-feature-set-150)
- [Install](#install)
- [CLI Quickstart](#cli-quickstart)
- [Desktop App](#desktop-app)
- [Developer Checks](#developer-checks)
- [Release](#release)

---

## 2-Minute Getting Started

### Desktop (Windows)

1. Download latest release assets from GitHub Releases (`Setup` or `Portable`).
2. Launch the app.
3. Go to `Languages` and pick a language.
4. Send it to `Run` and start a job.
5. Open `Output Browser` to inspect compiled docs and search them.

Default paths:

- output: `%UserProfile%\Documents\DevDocsDownloader`
- cache/state/logs/settings: `%LocalAppData%\DevDocsDownloader\...`

If startup fails:

- `%LocalAppData%\DevDocsDownloader\logs\desktop-shell.log`
- `%LocalAppData%\DevDocsDownloader\logs\desktop-backend.log`

### CLI (Python)

```bash
python scripts/setup.py
python DevDocsDownloader.py init
python DevDocsDownloader.py list-languages
python DevDocsDownloader.py run python
```

Optional first-run checks:

```bash
python DevDocsDownloader.py validate python
python DevDocsDownloader.py run python --template detailed --output-formats markdown,html,epub
```

---

## Current Feature Set (1.5.0)

### Core Pipeline

- Multi-source ingestion: `devdocs`, `mdn`, `dash`, `web_page`
- Structured compile output:
  - per-document Markdown
  - topic sections
  - consolidated language docs
  - metadata + run/version manifests
- Validation and quality scoring with persisted `validation.json`
- Resume-safe checkpoints and stateful recovery
- Optional semantic chunking for RAG-oriented outputs
- Optional HTML site and EPUB outputs

### Search and Discovery

- SQLite FTS5 index at `output/_search/index.db`
- API endpoints:
  - `GET /search`
  - `GET /search/semantic` (semantic mode if dependency available, otherwise FTS fallback)
  - `GET /xref`
- Cross-reference identifier index (related-doc discovery)
- Favorites and recents persistence:
  - `output/_search/favorites.json`
  - `output/_search/recents.json`

### Desktop UX

- Pages: Run, Bulk, Languages, Presets, Reports, Output Browser, Checkpoints, Cache, Settings
- Global sidebar search with debounce and direct open in Output Browser
- Output Browser:
  - favorites panel
  - related docs panel
  - per-document quality hints
  - website open for generated `_site`
- Job queue and live status tracking with source-health signals

---

## Project Layout

| Area | Path |
|---|---|
| CLI entry | `DevDocsDownloader.py` |
| CLI commands | `doc_ingest/cli.py` |
| Pipeline orchestration | `doc_ingest/pipeline.py` |
| Service layer | `doc_ingest/services.py` |
| Desktop backend API | `doc_ingest/desktop_backend.py` |
| Source adapters | `doc_ingest/sources/` |
| Search/index | `doc_ingest/indexer.py` |
| Desktop app | `desktop/DevDocsDownloader.Desktop/` |
| Docs/roadmap | `documentation/` |

---

## Install

### Requirements

- Python `3.11+`
- Windows (for desktop shell)
- network access for live source fetches

### Recommended

```bash
python scripts/setup.py
```

Useful variants:

```bash
python scripts/setup.py --profile dev
python scripts/setup.py --profile minimal
python scripts/setup.py --skip-playwright-browser
```

### Manual

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -e .[dev,tokenizer,benchmark]
```

Optional semantic search dependency:

```bash
python -m pip install -e .[semantic]
```

---

## CLI Quickstart

```bash
python DevDocsDownloader.py --help
python DevDocsDownloader.py init
python DevDocsDownloader.py list-languages
python DevDocsDownloader.py run python
python DevDocsDownloader.py bulk webapp
python DevDocsDownloader.py validate python
```

Examples:

```bash
python DevDocsDownloader.py run python --source devdocs --mode important
python DevDocsDownloader.py run python --chunks --chunk-strategy semantic
python DevDocsDownloader.py run python --template detailed --output-formats markdown,html,epub
python DevDocsDownloader.py bulk backend --concurrency-policy adaptive
```

---

## Desktop App

Desktop project: `desktop/DevDocsDownloader.Desktop/`

Architecture:

- WinUI 3 (.NET 8) shell
- bundled Python backend worker
- authenticated local FastAPI surface

Key backend endpoint groups:

- `/health`, `/version`, `/sources/health`
- `/languages`, `/presets`, `/refresh-catalogs`
- `/jobs/*`
- `/output/*`, `/reports/*`, `/checkpoints/*`, `/cache/*`
- `/search`, `/search/semantic`, `/xref`
- `/favorites`, `/recents`

---

## Output Contract

Per language (example `python`) under `output/markdown/python/`:

- `_meta.json`
- `manifest.json`
- `validation.json`
- `.history/*.json` (manifest history)
- optional `chunks/manifest.jsonl`, `chunks/*.md`
- optional `_site/**` (HTML)
- optional `*.epub`

Global search artifacts:

- `output/_search/index.db`
- `output/_search/favorites.json`
- `output/_search/recents.json`

Reference: `documentation/output_contract.md`

---

## Developer Checks

```bash
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m mypy doc_ingest
python scripts/check_release_hygiene.py
python scripts/check_version.py
python -m build
```

Desktop build:

```bash
dotnet build desktop/DevDocsDownloader.Desktop/DevDocsDownloader.Desktop.csproj -c Release
```

---

## Release

Releases are tag-driven via `.github/workflows/release.yml`.

For `v1.5.0`, expected assets:

- `DevDocsDownloader-Setup-1.5.0.exe`
- `DevDocsDownloader-Portable-1.5.0.zip`
- `SHA256SUMS.txt`

---

## Roadmap

- Current roadmap: `documentation/roadmap.md`
- Milestone status: `1.5.0` (Search & Discovery) complete
