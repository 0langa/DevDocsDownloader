## Summary

- Date/time: 2026-04-21 15:25:00
- Agent: GitHub Copilot
- Task: keep AI-context bootstrap rules only in `AGENTS.md`

## Changed

- Files: `AGENTS.md`; `devdocsdownloader.agent.md`.
- Behavior: removed context/bootstrap instructions from the execution agent file and made `AGENTS.md` the single routing source.

## Why

- Problem/request: repo-context loading rules were duplicated in `devdocsdownloader.agent.md`.
- Reason this approach was chosen: the system should still bootstrap correctly even when no repo-specific agent file is used.

## Risk

- Side effects: future edits must avoid reintroducing duplicated bootstrap rules.
- Follow-up: if more agent files are added, keep them execution-focused only.

## Validation

- Tests run: doc review only.
- Not run: code/test execution.

## Links

- Related context: `2026-04-21-151500-ai-context-system-hardening.md`
- Related lesson: N/A