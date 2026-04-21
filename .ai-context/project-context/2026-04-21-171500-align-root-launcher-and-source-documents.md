# Project Context Template

## Summary

- Date/time: 2026-04-21-171500
- Agent: GitHub Copilot (GPT-5.4)
- Task: Align the repo with the corrected layout: keep the main launcher at root as `DevDocsDownloader.py`, move setup/helper assets under `scripts/`, move source assets under `source-documents/`, and update active docs/tests.

## Changed

- Files: `DevDocsDownloader.py`; `scripts/setup.py`; `scripts/analyze_doc_paths.py`; `doc_ingest/config.py`; `doc_ingest/parser.py`; `doc_ingest/adapters.py`; `source-documents/renamed-link-source.md`; `README.md`; `doc_ingest/cli.py`; `tests/test_setup_bootstrap.py`; `tests/test_compiler_and_validator.py`; `tests/test_optional_dependencies_and_adapters.py`; `tests/test_pipeline_resume.py`; `tests/test_urls_and_discovery.py`; `.ai-context/main-documentation/TODO.md`; `.ai-context/main-documentation/project_state.md`; `.ai-context/main-documentation/project_architecture.md`
- Behavior: The runtime entry point is now `DevDocsDownloader.py`; setup installs from `source-documents/requirements.txt`; default language input comes from `source-documents/renamed-link-source.md`; overrides load from `source-documents/doc_path_overrides.json`; the parser now accepts markdown bullet entries.

## Why

- Problem/request: The user corrected the earlier script move and required a cleaner root with only the main launcher left there.
- Reason this approach was chosen: It preserves a single obvious runtime command while grouping source/reference assets and setup helpers into purpose-specific folders.

## Risk

- Side effects: External automation still calling `setup.py`, root `requirements.txt`, or `scripts/documentation_downloader.py` must be updated.
- Follow-up: Historical context notes still mention the superseded first script move; leave them as history unless the repo wants rewritten chronology.

## Validation

- Tests run: `"c:/Users/juliu/Documents/AI text stuff/Documentations Coding/.venv/Scripts/python.exe" DevDocsDownloader.py --help`; `"c:/Users/juliu/Documents/AI text stuff/Documentations Coding/.venv/Scripts/python.exe" -m pytest tests/test_setup_bootstrap.py tests/test_compiler_and_validator.py tests/test_optional_dependencies_and_adapters.py tests/test_pipeline_resume.py tests/test_urls_and_discovery.py`
- Not run: Live network crawl after the rename/move.

## Links

- Related context: `2026-04-21-020233-move-root-scripts-into-scripts-folder.md`
- Related lesson: `2026-04-21-bootstrap-helpers-must-track-runtime-layout.md`
