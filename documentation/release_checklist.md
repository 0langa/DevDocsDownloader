# v0.1.0 Release Checklist

This checklist defines release readiness for the current project state. Version `0.1.0` means the project is usable and tested, not a v1 stable API promise.

## Install

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -e .[dev,gui,tokenizer]
```

If package build tooling is missing:

```bash
python -m pip install build
```

## Required Checks

```bash
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m mypy doc_ingest
```

PowerShell compile check:

```powershell
Get-ChildItem doc_ingest,tests,scripts -Recurse -Filter *.py | ForEach-Object { python -m py_compile $_.FullName }
```

Package build sanity:

```bash
python -m build
```

## Optional Live Checks

Endpoint health without full language downloads:

```powershell
$env:DEVDOCS_LIVE_TESTS='1'; $env:DEVDOCS_LIVE_LIMIT='3'; python -m pytest tests\test_live_endpoints.py -q
```

Bounded extraction sanity:

```powershell
$env:DEVDOCS_LIVE_EXTRACTION_TESTS='1'; python -m pytest -m live tests\test_live_extraction_sanity.py -q
```

## Optional GUI Smoke

```bash
python DevDocsDownloader.py gui --host 127.0.0.1 --port 8080
```

Verify the dashboard loads, bulk/run options are visible, report/output browser views open, and no browser console errors appear during basic navigation.

## Known Non-Goals for v0.1.0

- No v1 compatibility promise for Python service models.
- No hosted multi-user GUI mode.
- No arbitrary crawler mode.
- No full MDN/Dash live extraction in routine checks.
- No PDF/DOCX/browser conversion without a future adapter path and fixture coverage.
