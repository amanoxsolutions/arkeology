---
type: Spec
id: p1-t1-bootstrap-python-project
title: T1 — Bootstrap Python Project
description: Feature spec for bootstrapping the Arkeology Python project with uv, ruff, mypy, and pre-commit tooling.
tags: []
status: stable
okf_version: "0.2"
generated:
  by: "axians-architect/unknown"
  at: 2026-05-29T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-10T05:53:58Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
---

# T1 — Bootstrap Python Project

## TL;DR

T1 turns the repository into an installable, `src/`-layout Python project managed only by uv, with
pytest wired up and ruff and mypy enforced through pre-commit. Every later task inherits this
tooling, so it is locked in before any Arkeology code is written and the rest of Phase 1 is never
interrupted by tooling setup.

## 1. Problem Statement

Before any Arkeology code can be written, the repository must be a properly structured, installable
Python project. Tooling is locked in upfront so that every subsequent task inherits consistent
formatting, type checking, test running, and pre-commit validation; getting this right in T1 means
the rest of Phase 1 is never interrupted by tooling setup. It delivers two outcomes, both priority
P1: a developer who clones the repository can install the project and run the server from source
using only uv, and any code pushed to the repository is automatically checked for formatting,
linting, and type errors.

## 2. Rules — Install and run from source

### R1 — `uv sync` installs every declared dependency

When a developer with uv installed runs `uv sync` on a fresh clone, all declared dependencies are
installed with no errors. Using only uv, the developer can install the project and launch the server
without any additional setup steps.

### R2 — `uv run arkeology` starts the process through the declared entry point

When a developer runs `uv run arkeology` in an installed project, the process starts through the
entry point declared in `pyproject.toml`, resolving and calling `main()` without import errors, and
starts without error even if it immediately exits because no tools are registered yet. At this
stage `main()` is a stub: it will eventually call the FastMCP server's `run()` method, but for now it
can simply print a startup message and exit — the real server wiring happens in T2. Wiring the entry
point up now is purely to verify that the entry point declaration works.

### R3 — `uv run pytest` runs the suite with zero failures

When a developer runs `uv run pytest` in an installed project, pytest discovers and runs the
(initially empty) test suite with zero failures.

### R4 — The Python version is pinned in two places

The Python version is pinned both in `.python-version` and in `pyproject.toml`'s `requires-python`.
The target (minimum supported) Python version is currently 3.14.

Resolved: the project currently targets Python 3.14 (see `pyproject.toml`'s `requires-python` and
its `[tool.mypy]` `python_version` setting); the default assumption was 3.12 unless instructed
otherwise.

## 3. Rules — Quality gates

### R5 — Pre-commit blocks a commit on a ruff or mypy failure

When a Python file is staged for commit, pre-commit runs exactly these hooks, in this order, on the
staged Python files only:

1. a ruff format check — `ruff format --check`, a formatting check, not an auto-fix;
2. a ruff lint check — `ruff check`;
3. mypy, with `--strict`.

Failing any of them blocks the commit. No hook is configured to auto-fix: the commit must fail
clearly so the developer sees what to fix. These hooks are non-negotiable quality gates.

**Example**

- Given a file with a ruff lint violation, when the developer attempts to commit, then the
  pre-commit hook fails and identifies the file and line.

### R6 — mypy reports a type error with its file and line

When a developer runs `uv run mypy src/` over a file with a type error, the error is reported with
its file and line number.

### R7 — A clean codebase passes every hook

When a developer runs `uv run pre-commit run --all-files` on a clean codebase, all hooks pass.

## 4. Rules — Repository hygiene

### R8 — Ignored files stay untracked, and credentials are never committed

When a file matching the `.gitignore` patterns is created, git does not track it. `.gitignore`
includes: `.docs/`, `failure-log.jsonl`, `.env`, `*.egg-info`, `.venv`, `__pycache__`,
`.mypy_cache`, `.ruff_cache`, `dist/`, `.pytest_cache/`. No `.env` file, and no file containing AWS
credentials, is ever committed.

## 5. Boundaries

**Always:**

- Use `uv` for all dependency management and script execution — no `pip`, no `poetry`, no `venv`
  direct usage.
- Source layout follows the `src/` layout: the package lives at `src/arkeology/`.

**Ask First:** None.

**Never:**

- Do not commit `.env` files or any file containing AWS credentials.
- Do not add a `setup.py` — `pyproject.toml` is the sole build config.
- Do not configure ruff to ignore errors globally — all rule violations must be addressed, not
  suppressed.

## 6. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `pyproject.toml` | Create | Full project config: see `pyproject.toml` required content below |
| `.python-version` | Create | Single line: `3.12` (or target version) |
| `.pre-commit-config.yaml` | Create | Hooks: ruff-pre-commit (format + check), mypy — see Pre-commit hook sources below |
| `.gitignore` | Modify | Extend existing with the patterns R8 lists |
| `src/arkeology/__init__.py` | Create | Package marker — empty or version string only |
| `src/arkeology/__main__.py` | Create | Thin entry point stub — imports and calls server run (stub only at this stage); see `__main__.py` entry point below |
| `tests/__init__.py` | Create | Empty — makes tests a package |
| `tests/unit/__init__.py` | Create | Empty |
| `tests/integration/__init__.py` | Create | Empty |

#### `pyproject.toml` required content

The file must declare:

- **Build system:** `hatchling` (uv's preferred build backend).
- **Project metadata:** name `arkeology`, version `0.1.0`, description,
  `requires-python = ">=3.12"`.
- **Runtime dependencies** — the full list the server needs for all phases, declared now so
  subsequent tasks can import without modifying this file:
  - `fastmcp` — MCP server framework
  - `boto3` — AWS SDK
  - `pydantic` — settings validation and data models
  - `pydantic-settings` — env var → settings parsing
- **Optional dev dependencies** (declared under `[project.optional-dependencies]` or
  `[dependency-groups]`):
  - `pytest`, `pytest-asyncio`, `pytest-mock` — test runner and utilities
  - `mypy`, `boto3-stubs[s3,bedrock-runtime,sts]` — type checking
  - `pre-commit` — hook runner
- **Entry point:** `[project.scripts]` → `arkeology = "arkeology.__main__:main"`. This is what makes
  `uv run arkeology` work.
- **Tool settings:**
  - `[tool.ruff]` — enable at minimum: `E`, `F`, `I` (isort), `UP` (pyupgrade); line length 100.
  - `[tool.mypy]` — `strict = true`, `python_version = "3.12"`.
  - `[tool.pytest.ini_options]` — `testpaths = ["tests"]`, `asyncio_mode = "auto"` (for future
    async tests).

#### `__main__.py` entry point

It must define the `main()` function R2 describes, and the `if __name__ == "__main__": main()` guard
must be present.

#### Pre-commit hook sources

`.pre-commit-config.yaml` takes R5's three hooks, in R5's order, from these sources:

1. `ruff-pre-commit` → `ruff format --check`
2. `ruff-pre-commit` → `ruff check`
3. `mirrors-mypy` → `mypy` with `--strict` and `additional_dependencies` listing the boto3-stubs
   packages

### Contracts

None.

### Testing Approach

T1 has no business logic — there is nothing to test-drive. The test suite is deliberately empty
after T1. The TDD discipline starts in T3 (client layer) and T4 (configuration model).

The done condition for T1 is tooling health, not test coverage:

- `uv run pytest` → exit 0, `no tests ran` is acceptable (R3)
- `uv run arkeology` → exits 0 (stub), prints a line to stdout (R2)
- `uv run mypy src/` → exit 0, zero errors (R6)
- `uv run ruff check src/ tests/` → exit 0 (R5)
- `uv run pre-commit run --all-files` → all hooks pass (R7)
