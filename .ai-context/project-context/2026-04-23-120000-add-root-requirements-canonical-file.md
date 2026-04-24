## Summary

- Date/time: 2026-04-23-120000
- Agent: GitHub Copilot (GPT-5.4)
- Task: Create a complete root requirements.txt for the repo and remove duplicate dependency maintenance.

## Changed

- Files: `requirements.txt`; `source-documents/requirements.txt`
- Behavior: The repo now has a full dependency list at the root. The existing `source-documents/requirements.txt` install path delegates to the root file, so `scripts/setup.py` and README install commands keep working while dependency updates only need one file.

## Why

- Problem/request: The project had no root `requirements.txt`, and the active dependency list lived only under `source-documents/`.
- Reason this approach was chosen: Making the root file canonical satisfies the request and avoids future drift between two copied requirement lists.

## Risk

- Side effects: Relative `-r ../requirements.txt` resolution now matters for installs through `source-documents/requirements.txt`.
- Follow-up: Consider aligning `[project].dependencies` in `pyproject.toml` with the canonical requirements file.

## Validation

- Tests run: `get_errors` on both requirements files.
- Not run: pip install resolution or networked dependency installation.

## Links

- Related context: `2026-04-21-180000-remote-cleanup-and-pytest-fix.md`
- Related lesson: `2026-04-21-pytest-must-be-in-requirements.md`
