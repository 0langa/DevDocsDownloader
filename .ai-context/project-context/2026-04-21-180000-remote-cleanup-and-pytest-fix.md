# Project Context Template

## Summary

- Date/time: 2026-04-21-180000
- Agent: Claude Sonnet 4.6
- Task: Clean remote of local-only files, ensure fresh-clone test runs work on Linux.

## Changed

- Files: `.gitignore`; `source-documents/requirements.txt`; `pyproject.toml` (new); `AGENTS.MD`
- Behavior: `.claude/` is now gitignored. `pytest` is installed as part of the normal venv setup. Running `python -m pytest` works on a fresh clone after `pip install -r source-documents/requirements.txt`. pytest config (testpaths) lives in `pyproject.toml` at root.

## Why

- Problem/request: Fresh Linux clone failed all tests with `ModuleNotFoundError: No module named 'pydantic'` because system pytest (not venv pytest) was resolving. Root cause: pytest was not in `requirements.txt` so the venv had no pytest binary.
- Reason this approach was chosen: Adding pytest to requirements is the correct fix. `pyproject.toml` is the standard single-file location for pytest config and keeps root clean.

## Risk

- Side effects: None. pytest is a dev dependency and does not affect runtime.
- Follow-up: N/A

## Validation

- Tests run: `python -m pytest` on Linux after `pip install -r source-documents/requirements.txt` — 18 passed.
- Not run: Live crawl.

## Links

- Related context: `2026-04-21-171500-align-root-launcher-and-source-documents.md`
- Related lesson: `2026-04-21-pytest-must-be-in-requirements.md`
