# DevDocsDownloader 1.0.4

Bug-fix release.

Changes since 1.0.3:

- Fixed desktop backend startup failure caused by missing `version.json` inside frozen PyInstaller bundles.
- Added frozen-runtime version lookup fallback so backend startup no longer depends on source-tree layout.
- Added backend build step to bundle `version.json` explicitly.
- Added desktop shell logging of bundled backend stdout/stderr for future startup diagnostics.

Included artifacts:

- `DevDocsDownloader-Setup-1.0.4.exe`
- `DevDocsDownloader-Portable-1.0.4.zip`
- `SHA256SUMS.txt`

Notes:

- The release is unsigned. Windows SmartScreen may warn before first launch.
- The desktop app bundles the Python ingestion backend and does not require a separate Python installation.
- Updates are distributed through GitHub Releases for the 1.0.x desktop release line.
