## Summary

- Date/time: 2026-04-21 16:00:00
- Agent: GitHub Copilot
- Task: correct `.ai-context` folder roles and upgrade the execution agent sheet

## Changed

- Files: `AGENTS.md`; `devdocsdownloader.agent.md`; `.ai-context/main-documentation/project_state.md`; `.ai-context/main-documentation/project_architecture.md`; `.ai-context/other-documentation/README.md`.
- Behavior: moved core state/architecture docs into `main-documentation`, converted `other-documentation` into a fallback note folder, and upgraded the repo agent file without adding bootstrap logic to it.

## Why

- Problem/request: the folder contract was wrong; `main-documentation` should hold the core knowledge base and `other-documentation` should be the overflow location.
- Reason this approach was chosen: it restores a clean routing model where core docs are always loaded first and miscellaneous AI-facing notes have a single fallback location.

## Risk

- Side effects: historical project-context entries mention the earlier folder layout.
- Follow-up: future agents should treat the newest entries and current `AGENTS.md` as canonical.

## Validation

- Tests run: doc structure review only.
- Not run: code/test execution.

## Links

- Related context: `2026-04-21-151500-ai-context-system-hardening.md`
- Related lesson: N/A