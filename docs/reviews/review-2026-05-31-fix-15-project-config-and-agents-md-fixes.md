---
type: code_review
title: Review Fix 15 — Project Config and AGENTS.md Fixes
description: Code review spec addressing housekeeping gaps — ruff dev dependency, missing AGENTS.md file inventory, placeholder sections, undocumented env var, and CI command discrepancy.
tags: []
timestamp: 2026-05-31T00:00:00Z
okf_version: "0.1"
status: ready
references: []
authored:
  by: "developer"
  date: "2026-05-31"
revised:
  by: ""
  date: ""
---
# Review Fix 15 — Project Config and AGENTS.md Fixes

## Problem Statement

Five housekeeping gaps degrade developer experience and agent accuracy. (M4) `ruff` is absent
from `[dependency-groups] dev` in `pyproject.toml`; `uv sync` does not install it. (M24)
`AGENTS.md` Repository Structure table is missing 9 source files. (M25) Two AGENTS.md sections
contain only irrelevant `<!-- TODO -->` placeholder text. (M26) `.env.example` does not document
`FAILURE_LOG_PATH`. (M27) `AGENTS.md` CI section omits `ruff format --check`, which runs in
pre-commit, so developers push code that fails the hook.

## User Stories

### Story 1 — `ruff` is a declared dev dependency

**Acceptance criteria:**
- Given a developer runs `uv sync` on a fresh checkout, when sync completes, then `ruff` is
  available without any global installation.

### Story 2 — AGENTS.md has an accurate file inventory

**Acceptance criteria:**
- Given an agent reads the Repository Structure table in AGENTS.md, when it scans the table,
  then all 9 previously missing source files are present with accurate descriptions.

### Story 3 — AGENTS.md placeholder sections contain real content

**Acceptance criteria:**
- Given a developer reads the Component Dependencies section, when they finish, then they
  understand which AWS services this project depends on and what a loss of each means.
- Given a developer reads the High-Friction Areas section, when they finish, then they see at
  least the vector index immutability constraint and the `startswith(prefix + "/")` scope-check
  pattern documented.

### Story 4 — `.env.example` documents all env vars

**Acceptance criteria:**
- Given a developer copies `.env.example` to `.env`, when they read it, then `FAILURE_LOG_PATH`
  is listed with its default value and a note on when to override.

### Story 5 — AGENTS.md CI section matches pre-commit hooks

**Acceptance criteria:**
- Given a developer follows the AGENTS.md "Run before pushing" block verbatim, when all
  commands pass, then the pre-commit hooks also pass (including `ruff format --check`).

## Requirements

- WHEN a developer runs `uv sync` THE SYSTEM SHALL install `ruff` as a dev dependency because
  it is declared in `[dependency-groups] dev`.
- WHEN an agent reads AGENTS.md THE SYSTEM SHALL see all source files listed in the Repository
  Structure table.
- WHEN a developer follows AGENTS.md quality gates THE SYSTEM SHALL catch formatting violations
  because `uv run ruff format --check src/ tests/` is listed.
- WHEN a developer copies `.env.example` THE SYSTEM SHALL see `FAILURE_LOG_PATH` with its
  default and guidance.

## Boundaries

**Never:**
- Change the ruff configuration itself (line length, enabled rules, etc.).
- Fill in Component Dependencies or High-Friction Areas with speculative content — only document
  what is verifiably true of this codebase (inspect actual source files before writing).
- Alter any CI workflow files or pre-commit hook definitions — only update AGENTS.md prose.

**Always:**
- Verify each of the 9 missing files exists in `src/cairn_mcp/` before adding it to the table.
- Keep AGENTS.md under its existing style and heading structure.

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `pyproject.toml` | Modify | Add `"ruff>=0.11"` to `[dependency-groups] dev` |
| `AGENTS.md` | Modify | Add 9 missing files to Repository Structure; fill Component Dependencies and High-Friction Areas; add `ruff format --check` to CI block |
| `.env.example` | Modify | Add `# FAILURE_LOG_PATH=.cairn_failures.jsonl` with a note on when to override |

## Testing Approach

No automated tests gate documentation and config changes. Verify manually:

| Order | Step | Verification |
|-------|------|-------------|
| 1 | Add `ruff` to `pyproject.toml` | Run `uv sync && uv run ruff --version` — must succeed |
| 2 | Update AGENTS.md Repository Structure | Cross-check each added file with `ls src/cairn_mcp/` |
| 3 | Fill AGENTS.md placeholder sections | Read `src/cairn_mcp/` source to confirm only true facts |
| 4 | Add `ruff format --check` to AGENTS.md CI block | Run the updated block end-to-end; all commands pass |
| 5 | Update `.env.example` | Confirm `FAILURE_LOG_PATH` default matches `config.py` |

Run the full CI quality gate after all edits:

```bash
uv run pytest tests/unit/ -q -m 'not integration'
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/
```

## Open Questions

*(none — scope is fully defined)*
