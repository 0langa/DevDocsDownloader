# DevDocsDownloader 1.0.3

Bug-fix release.

Changes since 1.0.2:

- Fixed sidebar rendering: hardcoded light-grey sidebar background made nav buttons invisible in dark mode.
- Increased backend startup timeout from 20 s to 60 s to accommodate antivirus scanning on first launch.
- Switched PyInstaller bundling to `--collect-all uvicorn` to ensure all protocol modules are included.

Included artifacts:

- `DevDocsDownloader-Setup-1.0.3.exe`
- `DevDocsDownloader-Portable-1.0.3.zip`
- `SHA256SUMS.txt`

Notes:

- The release is unsigned. Windows SmartScreen may warn before first launch.
- The desktop app bundles the Python ingestion backend and does not require a separate Python installation.
- Updates are distributed through GitHub Releases for the 1.0.x desktop release line.
