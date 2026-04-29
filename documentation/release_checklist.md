# Release Checklist

This checklist applies to every Windows desktop release. Update the version in `version.json` and `pyproject.toml` before starting.

## Bootstrap

```bash
python scripts/setup.py --profile dev
```

Creates `.venv`, installs the full runtime capability set plus developer tools in one step.

## Required Python Checks

```bash
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m mypy doc_ingest
python scripts/check_release_hygiene.py
python scripts/check_version.py
```

PowerShell compile check:

```powershell
Get-ChildItem doc_ingest,tests,scripts -Recurse -Filter *.py | ForEach-Object { python -m py_compile $_.FullName }
```

Package sanity:

```bash
python -m build
```

## Required Desktop Checks

Local Windows release builds require:

- Visual Studio 2022 Build Tools or full Visual Studio with MSBuild
- Windows App SDK packaging components
- .NET 8 SDK
- Inno Setup 6

```bash
python scripts/build_desktop_backend.py --clean
```

```powershell
$publishDir = "desktop\publish\desktop"
Remove-Item -Recurse -Force $publishDir -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $publishDir | Out-Null
msbuild desktop/DevDocsDownloader.Desktop/DevDocsDownloader.Desktop.csproj /restore /t:Publish /p:Configuration=Release /p:Platform=x64 /p:RuntimeIdentifier=win-x64 /p:SelfContained=true /p:WindowsAppSDKSelfContained=true /p:PublishDir="$publishDir\"
```

If the local machine lacks the Windows PRI packaging task assembly required by WinUI build targets, run desktop validation on the GitHub Actions `windows-latest` runner via the CI or release workflow.

## Release Artifact Checks

- Build frozen backend into `dist/DevDocsDownloader.Backend/`
- Publish desktop shell into `desktop/publish/desktop/`
- Copy bundled backend under `desktop/publish/desktop/backend/`
- Verify `DevDocsDownloader.Desktop.pri` was copied to publish dir
- Build installer with `desktop/installer/DevDocsDownloader.iss`
- Build portable zip
- Generate `SHA256SUMS.txt`
- Smoke-check backend startup via `/health` and `/version`
- Smoke-launch desktop exe; confirm it does not exit within 8s
- Confirm startup error dialog shows if backend is missing (rename backend dir, launch, restore)
- Confirm cancel button shows "Cancelling..." immediately on click
- Confirm job history survives a backend restart (start job, let it finish, restart backend, check /jobs)

## Optional Live Checks

Endpoint health without full language downloads:

```powershell
$env:DEVDOCS_LIVE_TESTS='1'; $env:DEVDOCS_LIVE_LIMIT='3'; python -m pytest tests\test_live_endpoints.py -q
```

Bounded extraction sanity:

```powershell
$env:DEVDOCS_LIVE_EXTRACTION_TESTS='1'; python -m pytest -m live tests\test_live_extraction_sanity.py -q
```

## Release Notes

Update `.github/release-notes.md` before tagging. The release workflow reads this file as `body_path` for the GitHub Release.

## Tag and Release

```bash
git tag v<version>
git push origin v<version>
```

The `release.yml` workflow builds the installer and portable zip, writes checksums, and publishes the GitHub Release automatically.

## Known Non-Goals

- No v1 compatibility promise for Python service models.
- No hosted multi-user GUI mode.
- No arbitrary crawler mode.
- No full MDN/Dash live extraction in routine CI checks.
- No PDF/DOCX/browser conversion without a future adapter path and fixture coverage.
- Binary is unsigned — SmartScreen warning expected on first launch.
