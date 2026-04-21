# Project Context Template

## Summary

- Date/time: 2026-04-21-172200
- Agent: GitHub Copilot (GPT-5.4)
- Task: Clarify that `.ai-context/other-documentation/` is optional archival material that agents should not read during normal bootstrap, and refresh `.gitignore` comments to the current repo layout.

## Changed

- Files: `AGENTS.MD`; `.ai-context/other-documentation/README.md`; `.gitignore`
- Behavior: Bootstrap rules now exclude `other-documentation` unless the user asks for it or a task specifically depends on it. The folder README now allows raw/unformatted archives. `.gitignore` comments now reference `DevDocsDownloader.py` and the `source-documents/` files instead of the old root names.

## Why

- Problem/request: The user wanted archived support material to stop burning tokens during normal AI bootstrap.
- Reason this approach was chosen: The rule belongs in `AGENTS.MD`, and the folder README should match so future notes in that folder remain intentionally low-cost.

## Risk

- Side effects: Agents will no longer see potentially useful archival notes unless explicitly directed to them.
- Follow-up: If any file in `other-documentation` becomes frequently needed, move its durable guidance into `main-documentation` instead.

## Validation

- Tests run: N/A
- Not run: Automated checks; markdown/comment-only changes.

## Links

- Related context: `2026-04-21-171500-align-root-launcher-and-source-documents.md`
- Related lesson: `N/A`
