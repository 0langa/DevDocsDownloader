# Project Context Template

## Summary

- Date/time: 2026-04-21-020233
- Agent: GitHub Copilot (GPT-5.4)
- Task: Move all root-level scripts except `setup.py` into a dedicated `scripts/` folder and update current-facing documentation.

## Changed

- Files: `scripts/documentation_downloader.py`; `scripts/analyze_doc_paths.py`; `scripts/build_skip_manifest.py`; `README.md`; `doc_ingest/cli.py`; `setup.py`; `.ai-context/main-documentation/TODO.md`; `.ai-context/main-documentation/project_state.md`; `.ai-context/main-documentation/project_architecture.md`
- Behavior: Runtime and helper scripts now live under `scripts/`. The moved scripts bootstrap the repo root onto `sys.path` so direct execution via `python scripts/...` still works. `build_skip_manifest.py` was also updated to understand current `pages`-based state files.

## Why

- Problem/request: Root-level scripts were cluttering the repo root and the user requested a dedicated folder for scripts.
- Reason this approach was chosen: A `scripts/` directory keeps the root cleaner while preserving direct execution with minimal runtime shims and documentation updates.

## Risk

- Side effects: Any external automation that still calls the old root paths will need to switch to `scripts/...`.
- Follow-up: If more repo scripts are added later, keep them under `scripts/` unless they are deliberate root entry points like `setup.py`.

## Validation

- Tests run: `python scripts/documentation_downloader.py --help`; `python scripts/build_skip_manifest.py`
- Not run: `python scripts/analyze_doc_paths.py` live network run.

## Links

- Related context: `2026-04-21-015559-package-and-bootstrap-audit.md`
- Related lesson: `2026-04-21-script-moves-need-runtime-path-shims.md`
