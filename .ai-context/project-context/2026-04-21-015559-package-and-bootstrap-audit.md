# Project Context Template

## Summary

- Date/time: 2026-04-21-015559
- Agent: GitHub Copilot (GPT-5.4)
- Task: Audit `requirements.txt` and `setup.py` against the current repo runtime and update stale bootstrap behavior.

## Changed

- Files: `setup.py`; `tests/test_setup_bootstrap.py`
- Behavior: `setup.py` now creates `output/diagnostics` and `cache/discovered_links`, and installs requirements via an absolute path. Added a test to lock the bootstrap-created folders to the current runtime layout.

## Why

- Problem/request: The dependency/bootstrap audit showed that `requirements.txt` matched current imports, but `setup.py` no longer created every directory the runtime expects.
- Reason this approach was chosen: A minimal bootstrap fix plus a regression test removes the drift without changing dependency policy or installation flow.

## Risk

- Side effects: None expected beyond creating two additional directories during setup.
- Follow-up: If runtime paths change again, update `setup.py` and the bootstrap test together.

## Validation

- Tests run: `python -m pytest -q tests/test_setup_bootstrap.py tests/test_pipeline_resume.py tests/test_compiler_and_validator.py tests/test_extraction_and_normalization.py` -> 12 passed.
- Not run: Fresh-clone end-to-end `python setup.py` execution.

## Links

- Related context: `2026-04-21-015104-pipeline-live-validation-hardening.md`
- Related lesson: `2026-04-21-bootstrap-helpers-must-track-runtime-layout.md`
