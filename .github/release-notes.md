# DevDocsDownloader 1.0.8

Desktop UX and reliability release.

Changes since 1.0.4:

- Reworked the WinUI shell into a stateful operator UI with persistent tab/page state across navigation.
- Added shared live progress tracking, activity history, warning/failure counts, and cancel controls across the shell.
- Replaced raw JSON-heavy desktop views with structured pages for Languages, Run/Bulk, Presets, Reports, Output Browser, Checkpoints, Cache, and Settings/Help.
- Added searchable source-first and category-first language tree views with cross-tab prefill actions.
- Changed the desktop default output root to `%UserProfile%\\Documents\\DevDocsDownloader` while keeping `markdown/` and `reports/` under that root.
- Extended backend service events and desktop settings persistence to support the richer shell behavior.

Included artifacts:

- `DevDocsDownloader-Setup-1.0.8.exe`
- `DevDocsDownloader-Portable-1.0.8.zip`
- `SHA256SUMS.txt`

Notes:

- The release is unsigned. Windows SmartScreen may warn before first launch.
- The desktop app bundles the Python ingestion backend and does not require a separate Python installation.
- Updates are distributed through GitHub Releases for the 1.0.x desktop release line.
