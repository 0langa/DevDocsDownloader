# DevDocsDownloader 1.2.0

Stable `1.2.0` foundation release focused on correctness, restart safety, memory efficiency, and desktop operator usability.

Highlights:

- Streaming compilation now writes per-document output and consolidated manuals without holding whole-language content in memory.
- MDN refreshes use commit-SHA delta detection plus archive indexing/on-demand member reads to avoid redundant large downloads.
- Source runtime now applies per-domain circuit breakers to stop repeated upstream failures from consuming all concurrency.
- Desktop backend now queues jobs instead of returning `409 busy`, and the shell shows queued position updates in real time.
- Cache management is fully available in the desktop app: usage summaries, per-entry refresh/delete, source clear, full clear, and cache budget tracking.
- Dry-run preview mode resolves the source and estimates document inventory before a real download.
- Validation now emits weighted component scores and actionable suggestions for common issues.
- Dash acceptance is hardened with a bounded live extraction probe that downloads one real docset, validates SQLite traversal, and converts one indexed document.
- Checkpoint resume is now content-hardened: schema-versioned checkpoints, atomic checkpoint persistence, per-artifact content hashes, rollback to the last verified artifact, stale checkpoint detection, and bulk stale cleanup in the desktop shell.
- Core unit coverage expanded for conversion helpers, cache policy/metadata, adaptive concurrency, backend job lifecycle, and mocked source adapter error cases.

Included artifacts:

- `DevDocsDownloader-Setup-1.2.0.exe`
- `DevDocsDownloader-Portable-1.2.0.zip`
- `SHA256SUMS.txt`

Notes:

- The release is unsigned. Windows SmartScreen may warn before first launch.
- The desktop app bundles the Python ingestion backend and does not require a separate Python installation.
- Updates are distributed through GitHub Releases.
