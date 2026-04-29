# DevDocsDownloader 1.0.9

Reliability and UX polish release.

Changes since 1.0.8:

- Fixed cancel button: shows "Cancelling..." immediately on click; asyncio cooperative cancellation allows CancelledError to propagate at document boundaries instead of waiting for the entire run.
- Fixed blank window on backend startup failure: a ContentDialog now shows the error message and desktop log path.
- Fixed SSE stream dropping silently: the shell reconnects automatically on unexpected stream disconnect using a from_index cursor (up to 5 retries with exponential backoff).
- Added backend health monitor: polls /health every 30s; marks backend unavailable and shows status text if the backend crashes; recovers automatically if the backend becomes healthy again.
- Added job history persistence: completed, failed, and cancelled job summaries are written to logs/job_history.jsonl and restored on backend startup.
- Fixed ruff format violations in registry.py and generate_icon.py (alignment spaces, long boolean conditions).

Included artifacts:

- `DevDocsDownloader-Setup-1.0.9.exe`
- `DevDocsDownloader-Portable-1.0.9.zip`
- `SHA256SUMS.txt`

Notes:

- The release is unsigned. Windows SmartScreen may warn before first launch.
- The desktop app bundles the Python ingestion backend and does not require a separate Python installation.
- Updates are distributed through GitHub Releases for the 1.0.x desktop release line.
