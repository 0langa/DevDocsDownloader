# DevDocsDownloader Roadmap

## Audit Baseline

Audit date: `2026-04-30`

Verified current state:
- Package version in `pyproject.toml`: `1.1.1`
- Full test suite: `113 passed, 3 skipped` in about 6 seconds
- Active product path: Python ingestion engine + FastAPI desktop backend + WinUI 3 shell
- Active built-in sources: `devdocs`, `mdn`, `dash`
- Legacy NiceGUI surface removed from runtime, setup, and tests

This roadmap replaces older items that are already fixed on `main`.

## What 1.1.1 Shipped

`1.1.1` ended up as a consolidation release instead of a narrow patch. It includes:

- language resolution hardening for shorthand aliases, punctuation variants, and version-shaped inputs
- weighted validation scoring with additive component scores
- bounded live Dash acceptance probing against one real docset archive
- desktop output storage management with bundle sizing, safe bundle deletion, and report-history pruning

## Current Project Shape

Project is past the "make desktop usable" stage. Core ingestion, reporting, resume, desktop backend, WinUI shell, output contract, and broad regression coverage all exist and are working.

Most valuable next work is now focused on product boundaries rather than architecture churn:

- improve repeated-use desktop ergonomics beyond basic storage cleanup
- deepen source confidence where bounded probes still stop short of full-language coverage
- reduce packaging and release friction for the Windows app
- keep trust signals accurate as output and cache volume grow

## Main Findings

### 1. Dash confidence improved, but still stops short of full-language assurance

`1.1.1` added a meaningful bounded live Dash acceptance probe. That closes the biggest blind spot, but it still validates only one real docset per run and does not prove broad docset coverage across families.

### 2. Desktop storage management now exists, but is still intentionally narrow

The desktop shell can now:

- show bundle sizes and managed-storage totals
- delete generated output bundles safely
- prune old report-history snapshots

Still missing:

- cache cleanup from the desktop shell
- retention policies for bundles or reports
- richer “last used” / “last generated” operational views

### 3. Desktop job model still favors simplicity over throughput

Current behavior is still acceptable for single-user desktop use, but limits remain:

- single active backend job
- no queued-job UX
- job event history retained in memory per backend lifetime

### 4. Packaging friction remains outside the Python runtime itself

The Python path is fast and well-covered now. Remaining release risk is concentrated in the Windows desktop packaging flow:

- unsigned binaries
- fragile PRI packaging path
- no in-product update flow

## Development Direction

Recommended order of work after `1.1.1`:

1. better single-user job management
2. broader Dash acceptance depth
3. packaging/distribution polish
4. deeper desktop cleanup controls if user demand justifies them

Reason:

- storage cleanup basics now exist, so the next most visible desktop gap is job handling
- Dash now has a real bounded acceptance signal, but it still needs broader coverage more than new adapter surface
- release packaging remains a recurrent operational tax

## Release Plan

### v1.2.0 — Desktop Flow Hardening

Goal: make the desktop path easier to use repeatedly without expanding scope.

#### P1. Better single-user job management

Scope:

- explicit queued/pending UX in shell
- clearer 409 handling and recovery hints
- consider bounded event retention for long backend lifetimes

Validation:

- backend job tests
- shell interaction smoke tests

#### P2. Broader output lifecycle controls

Scope:

- optional cache cleanup from desktop shell
- safer retention-oriented cleanup actions
- better surfaced “last generated” and “managed size” signals

Validation:

- service path-safety tests
- backend cleanup endpoint tests
- manual desktop smoke test

### v1.3.0 — Source Confidence And Distribution

Goal: improve confidence and reduce release friction.

#### P3. Broaden Dash acceptance confidence

Scope:

- extend bounded live acceptance beyond one representative small docset
- cover more docset shapes, encoding edges, and index/path variants
- document exactly what “supported” means for Dash

Validation:

- opt-in live extraction tests
- stable CI path for bounded Dash verification

#### P4. Distribution polish

Scope:

- code signing
- release packaging cleanup around PRI handling
- optional update notification

Validation:

- release workflow
- release checklist
- artifact smoke tests

## What Should Not Be Prioritized Now

Avoid spending the next cycle on:

- broad architectural rewrites
- multi-platform GUI strategy
- speculative new source adapters
- deeper browser automation features without adapter demand

Reason: current leverage sits in consolidation and operator usability, not expansion.

## Success Criteria For Next Phase

Roadmap is on track when these are true:

- desktop job handling feels intentional instead of conflict-driven
- Dash support has broader acceptance evidence than one representative live docset
- release packaging is less brittle and less warning-prone
- storage management remains safe while covering more than the bundle/report-history basics

## Maintainer Notes

If only one milestone can ship next, ship better single-user job management. It is now the most obvious day-to-day usability gap on the desktop path.
