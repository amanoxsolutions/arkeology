---
type: spec
title: T1 — Bootstrap Python Project
description: Feature spec for bootstrapping the Arkeology Python project with uv, ruff, mypy, and pre-commit tooling.
tags: []
timestamp: 2026-05-29T00:00:00Z
okf_version: "0.1"
feature: p1-t1-bootstrap-python-project
status: ready
phase: 1
task: 1
references: []
authored:
  by: "architect"
  date: "2026-05-29"
revised:
  by: ""
  date: ""
---

# T1 — Bootstrap Python Project

<!-- SCOPE BLOCK -->

## Problem Statement

Before any Arkeology code can be written, the repository must be a properly structured, installable
Python project. Tooling must be locked in upfront so that every subsequent task inherits consistent
formatting, type checking, test running, and pre-commit validation. Getting this right in task 1
means the rest of Phase 1 is never interrupted by tooling setup.

## User Stories

### Story 1 — Developer can install and run the server from source (P1)

A developer clones the repository and, using only `uv`, can install the project and launch the
server without any additional setup steps.

**Acceptance criteria:**
- Given a fresh clone with uv installed, when the developer runs `uv sync`, then all dependencies are installed with no errors.
- Given a installed project, when the developer runs `uv run arkeology`, then the process starts without error (even if it immediately exits because no tools are registered yet).
- Given a installed project, when the developer runs `uv run pytest`, then pytest discovers and runs the (initially empty) test suite with zero failures.

### Story 2 — Code quality is enforced automatically (P1)

Any code pushed to the repository is automatically checked for formatting, linting, and type errors.

**Acceptance criteria:**
- Given a file with a ruff lint violation, when the developer attempts to commit, then the pre-commit hook fails and identifies the file and line.
- Given a file with a mypy type error, when the developer runs `uv run mypy src/`, then the error is reported with file and line number.
- Given a clean codebase, when the developer runs `uv run pre-commit run --all-files`, then all hooks pass.

## Requirements

- WHEN the developer runs `uv sync` THE SYSTEM SHALL install all declared dependencies without errors.
- WHEN the developer runs `uv run arkeology` THE SYSTEM SHALL start the process using the entry point defined in `pyproject.toml`.
- WHEN a Python file is staged for commit THE SYSTEM SHALL run ruff format check and ruff lint check via pre-commit; failing either check blocks the commit.
- WHEN a Python file is staged for commit THE SYSTEM SHALL run mypy via pre-commit; a type error blocks the commit.
- WHEN a file matching the gitignore patterns is created THE SYSTEM SHALL not track it in git.

## Boundaries

**Always:**
- Use `uv` for all dependency management and script execution — no `pip`, no `poetry`, no `venv` direct usage.
- Python version must be pinned in `.python-version` and in `pyproject.toml` `requires-python`.
- Source layout must follow `src/` layout: package lives at `src/arkeology/`.
- Pre-commit hooks run ruff and mypy — these are non-negotiable quality gates.
- `.gitignore` must include: `.docs/`, `failure-log.jsonl`, `.env`, `*.egg-info`, `.venv`, `__pycache__`, `.mypy_cache`, `.ruff_cache`, `dist/`, `.pytest_cache/`.

**Ask First:**
- Python version to target (minimum supported version). Default assumption: 3.12 unless instructed otherwise.

**Never:**
- Do not commit `.env` files or any file containing AWS credentials.
- Do not add a `setup.py` — pyproject.toml is the sole build config.
- Do not configure ruff to ignore errors globally — all rule violations must be addressed, not suppressed.

<!-- IMPLEMENTATION BLOCK -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `pyproject.toml` | Create | Full project config: see details below |
| `.python-version` | Create | Single line: `3.12` (or target version) |
| `.pre-commit-config.yaml` | Create | Hooks: ruff-pre-commit (format + check), mypy |
| `.gitignore` | Modify | Extend existing with patterns listed in Boundaries |
| `src/arkeology/__init__.py` | Create | Package marker — empty or version string only |
| `src/arkeology/__main__.py` | Create | Thin entry point stub — imports and calls server run (stub only at this stage) |
| `tests/__init__.py` | Create | Empty — makes tests a package |
| `tests/unit/__init__.py` | Create | Empty |
| `tests/integration/__init__.py` | Create | Empty |

### `pyproject.toml` required content

The file must declare:

**Build system:** `hatchling` (uv's preferred build backend).

**Project metadata:** name `arkeology`, version `0.1.0`, description, `requires-python = ">=3.12"`.

**Runtime dependencies** (the full list the server needs for all phases — declare them all now so
subsequent tasks can import without modifying this file):
- `fastmcp` — MCP server framework
- `boto3` — AWS SDK
- `pydantic` — settings validation and data models
- `pydantic-settings` — env var → settings parsing

**Optional dev dependencies** (declared under `[project.optional-dependencies]` or
`[dependency-groups]`):
- `pytest`, `pytest-asyncio`, `pytest-mock` — test runner and utilities
- `mypy`, `boto3-stubs[s3,bedrock-runtime,sts]` — type checking
- `pre-commit` — hook runner

**Entry point:** `[project.scripts]` → `arkeology = "arkeology.__main__:main"`. This is what makes
`uv run arkeology` work.

**Tool settings:**
- `[tool.ruff]` — enable at minimum: `E`, `F`, `I` (isort), `UP` (pyupgrade); line length 100.
- `[tool.mypy]` — `strict = true`, `python_version = "3.12"`.
- `[tool.pytest.ini_options]` — `testpaths = ["tests"]`, `asyncio_mode = "auto"` (for future async tests).

### `__main__.py` entry point

The entry point at this stage is a stub. It must:
1. Define a `main()` function that will eventually call the FastMCP server's `run()` method.
2. At this stage, `main()` can simply print a startup message and exit — the real server wiring
   happens in T2.
3. The `if __name__ == "__main__": main()` guard must be present.

The point of wiring this up in T1 is purely to verify the entry point declaration works — `uv run arkeology` must resolve and call `main()` without import errors.

### Pre-commit hooks configuration

`.pre-commit-config.yaml` must include exactly these hooks in order:
1. `ruff-pre-commit` → `ruff format --check` (formatting check, not auto-fix)
2. `ruff-pre-commit` → `ruff check` (lint check)
3. `mirrors-mypy` → `mypy` with `--strict` and `additional_dependencies` listing the boto3-stubs packages

The hooks run on staged Python files only. Do not configure them to auto-fix — the commit must fail
clearly so the developer sees what to fix.

## TDD Note

T1 has no business logic — there is nothing to test-drive. The test suite is deliberately empty
after this task. The TDD discipline starts in T3 (client layer) and T4 (configuration model).

The done condition for T1 is tooling health, not test coverage:
- `uv run pytest` → exit 0, `no tests ran` is acceptable
- `uv run arkeology` → exits 0 (stub), prints a line to stdout
- `uv run mypy src/` → exit 0, zero errors
- `uv run ruff check src/ tests/` → exit 0
- `uv run pre-commit run --all-files` → all hooks pass

## Open Questions

- [x] Python version: confirm 3.12 is the target, or specify otherwise before starting.
  **Resolved** — the project currently targets Python 3.14 (see `pyproject.toml`'s
  `requires-python` and its `[tool.mypy]` `python_version` setting).
