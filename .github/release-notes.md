# DevDocsDownloader 1.0.9.1

Hotfix release — UI state and window icon fixes.

Changes since 1.0.9:

- Fixed sidebar not clearing after job completes: cancel button, progress bar, and job label now reset to idle state when a job finishes (completed, failed, or cancelled).
- Fixed window/taskbar icon missing at runtime: the app now calls AppWindow.SetIcon() on startup so the correct icon appears in the taskbar and title bar (not just the installer).
- Fixed ActiveJobId property change not triggering sidebar refresh: ApplyShellState was not wired to ActiveJobId, so the cancel button stayed visible after ActiveJobId cleared.

Included artifacts:

- `DevDocsDownloader-Setup-1.0.9.1.exe`
- `DevDocsDownloader-Portable-1.0.9.1.zip`
- `SHA256SUMS.txt`

Notes:

- The release is unsigned. Windows SmartScreen may warn before first launch.
- The desktop app bundles the Python ingestion backend and does not require a separate Python installation.
- Updates are distributed through GitHub Releases for the 1.0.x desktop release line.
