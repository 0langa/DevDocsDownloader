# Lesson Template

## Lesson

- Date: 2026-04-21
- Agent: Claude Sonnet 4.6
- Topic: pytest must be in requirements for cross-machine test runs
- Category: reliability

## Insight

- What was learned: If pytest is not in `requirements.txt`, a fresh venv will not have it. The system pytest resolves instead and fails with import errors for venv-only packages.
- Why it matters: Tests appear to pass on the dev machine (where pytest was manually installed) but fail on every other machine including CI and Linux validation clones.

## Evidence

- Trigger/task: Fresh Linux clone failed all 5 test collection steps with `ModuleNotFoundError: No module named 'pydantic'` despite pydantic being installed in the venv.
- Files or components: `source-documents/requirements.txt`; `pyproject.toml`
- Concrete example: `pip install pydantic` showed "already satisfied" but `pytest` still failed — because the running pytest was the system one, outside the venv.

## Reuse

- Apply when: Adding or auditing test infrastructure, setting up CI, or onboarding a new machine.
- Avoid: Assuming pytest is available just because it works locally.
- Related context: `2026-04-21-180000-remote-cleanup-and-pytest-fix.md`
- Tags: pytest,requirements,venv,cross-platform,ci
