# v1.0.2 Release Checklist

This checklist defines the current Windows desktop release line. Version `1.0.2` means the WinUI 3 shell, bundled Python backend, packaging, and GitHub Release automation are all present and validated together.

## Bootstrap

```bash
python scripts/setup.py --profile dev
```

This is the preferred repo bootstrap for release validation because it creates `.venv`, installs the full runtime capability set, installs Playwright Chromium, and adds developer tools in one step.

If package build tooling is missing:

```bash
python -m pip install build
```

## Required Python Checks

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

Package and version sanity:

```bash
python -m build
python scripts/check_version.py
```

## Required Desktop Checks

```bash
dotnet build DevDocsDownloader.Desktop.sln -c Release -p:Platform=x64
python scripts/build_desktop_backend.py --clean
```

If the local machine lacks the Windows PRI packaging task assembly required by WinUI build targets, run the desktop and installer validation on a Windows image with Visual Studio packaging components available, such as the GitHub Actions `windows-latest` runner used by the CI/release workflows.

## Release Artifact Checks

- Build the frozen backend into `dist/DevDocsDownloader.Backend/`
- Publish the desktop shell into `desktop/publish/desktop/`
- Copy the bundled backend under `desktop/publish/desktop/backend/`
- Build the installer with `desktop/installer/DevDocsDownloader.iss`
- Build `DevDocsDownloader-Portable-1.0.2.zip`
- Generate `SHA256SUMS.txt`
- Smoke-check backend startup via `/health` and `/version`
- Smoke-check first desktop launch against the bundled backend

## Optional Live Checks

Endpoint health without full language downloads:

```powershell
$env:DEVDOCS_LIVE_TESTS='1'; $env:DEVDOCS_LIVE_LIMIT='3'; python -m pytest tests\test_live_endpoints.py -q
```

Bounded extraction sanity:

```powershell
$env:DEVDOCS_LIVE_EXTRACTION_TESTS='1'; python -m pytest -m live tests\test_live_extraction_sanity.py -q
```

## Legacy NiceGUI Smoke

```bash
python DevDocsDownloader.py gui --host 127.0.0.1 --port 8080
```

Verify the dashboard loads, bulk/run options are visible, report/output browser views open, and no browser console errors appear during basic navigation.

## Known Non-Goals for v1.0.0

- No v1 compatibility promise for Python service models.
- No hosted multi-user GUI mode.
- No arbitrary crawler mode.
- No full MDN/Dash live extraction in routine checks.
- No PDF/DOCX/browser conversion without a future adapter path and fixture coverage.
