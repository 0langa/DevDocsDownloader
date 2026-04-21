# Lesson Template

## Lesson

- Date: 2026-04-21
- Agent: GitHub Copilot (GPT-5.4)
- Topic: Script moves need runtime path shims
- Category: maintainability

## Insight

- What was learned: Moving executable repo scripts into a subfolder changes Python import resolution and can silently break direct execution unless the repo root is added back to `sys.path` or path handling is rewritten.
- Why it matters: Commands can look correct in documentation but still fail at runtime after a file move if they relied on the old root-level import context.

## Evidence

- Trigger/task: Move all scripts except `setup.py` into `scripts/`.
- Files or components: `scripts/documentation_downloader.py`; `scripts/analyze_doc_paths.py`; `scripts/build_skip_manifest.py`
- Concrete example: After adding a small repo-root shim to the moved scripts, `python scripts/documentation_downloader.py --help` and `python scripts/build_skip_manifest.py` both ran successfully.

## Reuse

- Apply when: Relocating executable Python scripts inside the repo or changing documented command paths.
- Avoid: Assuming a moved script will still import local packages just because it worked from the repo root before the move.
- Related context: `2026-04-21-020233-move-root-scripts-into-scripts-folder.md`
- Tags: scripts,paths,imports,documentation
