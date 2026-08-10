---
type: code_review
title: Review Fix 16 — Minor Foundation Improvements
description: Code review spec for seven low-risk foundation defects — print() calls, config validator silent fallback, non-ISO-8601 date acceptance, version lookup crash, missing error base class, unhandled ValueError in startup, and missing type ignore comment.
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
# Review Fix 16 — Minor Foundation Improvements

## Problem Statement

Seven small defects in the foundation layer accumulate risk: `print()` calls in
`__main__.py` corrupt the MCP stdio transport; a silent fallback in the config validator
is misleading; `artifact.py` accepts non-ISO-8601 dates; the version lookup crashes when
the package is not installed; `errors.py` lacks a shared base class; `startup.py` can
crash with an unhandled `ValueError`; and a `# type: ignore` comment is missing at a
known Pydantic boundary. All are low-risk, non-breaking, and safe to ship as one PR.

## User Stories

### Story 1 — Server starts from source without crashing (P2)

**Acceptance criteria:**
- Given the `cairn-mcp` package is not installed (running from source with `uv run`),
  when the server starts, then `server_info.version` is `"0.0.0-dev"` and no exception
  is raised.

### Story 2 — Bad dimension value produces a clear error (P2)

**Acceptance criteria:**
- Given `describe_index` returns a non-numeric string for the dimension field, when
  `startup.py` processes the response, then a `StartupValidationError` is raised with a
  message that names the bad value and tells the operator what was expected.

### Story 3 — Non-ISO-8601 date is rejected at write time (P2)

**Acceptance criteria:**
- Given an artifact is constructed with `date="not-a-date"`, when Pydantic validates the
  model, then a `ValidationError` is raised before any S3 or vector operation is called.

## Requirements

- WHEN the `cairn-mcp` package is not installed THE SYSTEM SHALL report version as
  `"0.0.0-dev"` instead of raising `PackageNotFoundError`.
- WHEN `startup.py` receives a non-numeric dimension value from `describe_index` THE
  SYSTEM SHALL raise `StartupValidationError` with a message including the bad value.
- WHEN an `Artifact` is constructed with a date that does not parse as ISO-8601 THE
  SYSTEM SHALL raise `ValidationError` immediately.
- WHEN `__main__.py` needs to emit a critical/error message before the process exits THE
  SYSTEM SHALL use `logger.critical(...)` or `logger.error(...)`, never `print(...,
  file=sys.stderr)`.
- WHEN `check_required_non_empty` receives a non-dict `values` THE SYSTEM SHALL log a
  warning and return `values` unchanged (never raise).
- WHEN `CairnError` is defined THE SYSTEM SHALL be the base class of `CredentialError`,
  `StartupValidationError`, and `VectorIndexNotFoundError`; existing `except` clauses
  that catch the concrete subclasses SHALL continue to work unchanged.

## Boundaries

**Always:**
- `CairnError` must be backward-compatible — no change to any exception's public
  attributes or constructor signature.
- The `isinstance` guard in `check_required_non_empty` must never raise — only warn.
- The `@field_validator("date")` must call `datetime.date.fromisoformat(v)` and re-raise
  as `ValueError` on failure.

**Never:**
- Change the public interface of any exception class.
- Remove the `Any` annotation on the `model_validator(mode="before")` in `config.py` —
  add a suppression comment only.

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_artifact.py` | Modify | Add tests for date validator (Red) before changing `artifact.py` |
| `tests/unit/test_errors.py` | Modify | Add tests asserting `CairnError` base class (Red) before changing `errors.py` |
| `tests/unit/test_startup.py` | Modify | Add test for bad dimension string (Red) before changing `startup.py` |
| `src/cairn_mcp/artifact.py` | Modify | Add `@field_validator("date")` using `datetime.date.fromisoformat` |
| `src/cairn_mcp/errors.py` | Modify | Add `CairnError(Exception)`; make existing exceptions inherit from it |
| `src/cairn_mcp/startup.py` | Modify | Wrap `int(raw_dim)` in try/except; raise `StartupValidationError` |
| `src/cairn_mcp/server.py` | Modify | Wrap `importlib.metadata.version` in `try/except PackageNotFoundError` |
| `src/cairn_mcp/__main__.py` | Modify | Replace three `print(..., file=sys.stderr)` with `logger.critical/error` |
| `src/cairn_mcp/config.py` | Modify | Add `isinstance` guard in `check_required_non_empty`; add `# type: ignore[misc]` comment at line 10 |

## Testing Approach

**TDD cycle:** tests first (Red) → implementation (Green) → `mypy` + `ruff` clean.

**`tests/unit/test_artifact.py` additions (before `artifact.py` change):**
- Valid ISO-8601 date string `"2026-05-31"` → model constructs without error.
- Invalid date string `"not-a-date"` → `ValidationError` raised.
- Invalid date string `"2026-13-01"` (month 13) → `ValidationError` raised.

**`tests/unit/test_errors.py` additions (before `errors.py` change):**
- `isinstance(CredentialError(...), CairnError)` is `True`.
- `isinstance(StartupValidationError(...), CairnError)` is `True`.
- `isinstance(VectorIndexNotFoundError(...), CairnError)` is `True`.
- `except CredentialError` still catches a `CredentialError` instance.

**`tests/unit/test_startup.py` additions (before `startup.py` change):**
- `describe_index` returns `{"dimensions": "nan"}` → `StartupValidationError` raised
  with message containing `"nan"`.
- `describe_index` returns `{"dimensions": None}` → `StartupValidationError` raised.

**`server.py` and `__main__.py` changes:** no new tests; confirm existing unit tests pass
and `uv run cairn-mcp --help` does not raise `PackageNotFoundError`.

## Open Questions

*(none — all behaviour is defined)*
