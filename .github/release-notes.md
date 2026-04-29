# DevDocsDownloader 1.1.0

Stable 1.1.0 release focused on product-surface cleanup, faster validation cycles, and desktop operator polish.

Highlights:

- Removed the deprecated NiceGUI surface from runtime, setup, tests, and docs.
- Cut local Python test runtime dramatically by avoiding unnecessary catalog loading in source-specific paths.
- `refresh-catalogs` now returns structured per-source status instead of raw counts only.
- WinUI Languages page now surfaces catalog refresh fallback/failure information.
- Output Browser can open the current output folder directly.
- Settings now make it clear that changes apply to the next run and warn when the output root changes.
- Window resizing now uses WinUI `OverlappedPresenter` minimum-size constraints instead of `SizeChanged` clamping.

Included artifacts:

- `DevDocsDownloader-Setup-1.1.0.exe`
- `DevDocsDownloader-Portable-1.1.0.zip`
- `SHA256SUMS.txt`

Notes:

- The release is unsigned. Windows SmartScreen may warn before first launch.
- The desktop app bundles the Python ingestion backend and does not require a separate Python installation.
- Updates are distributed through GitHub Releases.
