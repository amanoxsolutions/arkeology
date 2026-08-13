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
  by: "developer"
  date: "2026-08-12"
---
# Review Fix 16 — Minor Foundation Improvements

## Verification — 2026-08-12

Re-verified finding-by-finding against current `main`. All seven items were fixed the
same day this spec was authored, by `f642725` (2026-05-31, "production hardening — 20
review-fix specs"), which deliberately implemented this spec alongside fix-01 through
fix-20 in one PR (486 unit tests passing at the time; ruff/mypy clean). This spec's
`status: ready` frontmatter was never flipped to `done` and no closure note was added,
but the code has matched every requirement below since that commit.

- **Resolved:** 7 of 7 — `print()` calls, the `check_required_non_empty` isinstance
  guard, the `date` field validator, the version-lookup fallback, `ArkeologyError`, the
  `startup.py` dimension `try/except`, and the `# type: ignore` boundary (see inline
  markers below for the last one's nuance).
- **Still valid / no longer applicable / changed enough to restate:** none.

See inline `[Verified 2026-08-12 — …]` markers on each requirement below, and the
"Items Resolved Since Last Review" section at the end.

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
- Given the `arkeology` package is not installed (running from source with `uv run`),
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

- WHEN the `arkeology` package is not installed THE SYSTEM SHALL report version as
  `"0.0.0-dev"` instead of raising `PackageNotFoundError`.
  **[Verified 2026-08-12 — ✅ RESOLVED.** `server.py` wraps
  `importlib.metadata.version("arkeology")` in `try/except PackageNotFoundError`,
  falling back to `"0.0.0-dev"`. Fixed by `f642725`, deliberate.]
- WHEN `startup.py` receives a non-numeric dimension value from `describe_index` THE
  SYSTEM SHALL raise `StartupValidationError` with a message including the bad value.
  **[Verified 2026-08-12 — ✅ RESOLVED.** `_check_model_dimension` wraps
  `int(raw_dim)` in `try/except (TypeError, ValueError)`, re-raising a
  `StartupValidationError` that names the bad value, chained with `from exc`. Fixed by
  `f642725`, deliberate.]
- WHEN an `Artifact` is constructed with a date that does not parse as ISO-8601 THE
  SYSTEM SHALL raise `ValidationError` immediately.
  **[Verified 2026-08-12 — ✅ RESOLVED.** `Artifact` has a `@field_validator("date")`
  that calls `_require_valid_date`, which calls `datetime.date.fromisoformat` and
  re-raises `ValueError` (→ pydantic `ValidationError`) on failure. Fixed by `f642725`,
  deliberate.]
- WHEN `__main__.py` needs to emit a critical/error message before the process exits THE
  SYSTEM SHALL use `logger.critical(...)` or `logger.error(...)`, never `print(...,
  file=sys.stderr)`.
  **[Verified 2026-08-12 — ✅ RESOLVED.** No `print()` calls remain in `__main__.py`;
  all exit-path messages use `logger.critical(...)`. Fixed by `f642725`, deliberate.]
- WHEN `check_required_non_empty` receives a non-dict `values` THE SYSTEM SHALL log a
  warning and return `values` unchanged (never raise).
  **[Verified 2026-08-12 — ✅ RESOLVED.** `check_required_non_empty` in `config.py`
  opens with `if not isinstance(values, dict): _config_logger.warning(...); return
  values`, exactly as specified. Fixed by `f642725`, deliberate.]
- WHEN `ArkeologyError` is defined THE SYSTEM SHALL be the base class of `CredentialError`,
  `StartupValidationError`, and `VectorIndexNotFoundError`; existing `except` clauses
  that catch the concrete subclasses SHALL continue to work unchanged.
  **[Verified 2026-08-12 — ✅ RESOLVED.** `errors.py` defines `ArkeologyError(Exception)`
  as the base class of every domain exception (`CredentialError`,
  `StartupValidationError`, `VectorIndexNotFoundError`, and — added since, following the
  same convention — `ConfigurationError`, `AnnotationUnavailableError`,
  `ArtifactCollisionError`, `ArtifactConflictError`, `MetadataTooLargeError`,
  `InvalidFilterValueError`, `FilterEvaluationError`, `NonUtf8PayloadError`,
  `DuplicateManifestPathError`, `VectorDistanceMissingError`). Fixed by `f642725`,
  deliberate; the pattern was carried forward into every exception added since.]

## Boundaries

**Always:**
- `ArkeologyError` must be backward-compatible — no change to any exception's public
  attributes or constructor signature.
- The `isinstance` guard in `check_required_non_empty` must never raise — only warn.
- The `@field_validator("date")` must call `datetime.date.fromisoformat(v)` and re-raise
  as `ValueError` on failure.

**Never:**
- Change the public interface of any exception class.
- Remove the `Any` annotation on the `model_validator(mode="before")` in `config.py` —
  add a suppression comment only.

  **[Verified 2026-08-12 — ✅ RESOLVED, no comment needed.** `check_required_non_empty`
  still types `values: Any` and no `# type: ignore` comment was ever added near it — but
  `uv run mypy --strict src/arkeology/config.py` reports zero issues today. `pyproject.toml`
  has configured `plugins = ["pydantic.mypy"]` since the very first commit
  (`f35cd08`, pre-dating this review), so the mypy boundary this finding warned about
  never actually surfaced under this project's mypy config — the literal "add a
  suppression comment" fix was not applied, but the underlying requirement ("compile
  cleanly under mypy") was already satisfied and remains satisfied. Not a regression risk;
  no action needed unless a future mypy/pydantic upgrade reintroduces the error.]

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_artifact.py` | Modify | Add tests for date validator (Red) before changing `artifact.py` |
| `tests/unit/test_errors.py` | Modify | Add tests asserting `ArkeologyError` base class (Red) before changing `errors.py` |
| `tests/unit/test_startup.py` | Modify | Add test for bad dimension string (Red) before changing `startup.py` |
| `src/arkeology/artifact.py` | Modify | Add `@field_validator("date")` using `datetime.date.fromisoformat` |
| `src/arkeology/errors.py` | Modify | Add `ArkeologyError(Exception)`; make existing exceptions inherit from it |
| `src/arkeology/startup.py` | Modify | Wrap `int(raw_dim)` in try/except; raise `StartupValidationError` |
| `src/arkeology/server.py` | Modify | Wrap `importlib.metadata.version` in `try/except PackageNotFoundError` |
| `src/arkeology/__main__.py` | Modify | Replace three `print(..., file=sys.stderr)` with `logger.critical/error` |
| `src/arkeology/config.py` | Modify | Add `isinstance` guard in `check_required_non_empty`; add `# type: ignore[misc]` comment at line 10 |

## Testing Approach

**TDD cycle:** tests first (Red) → implementation (Green) → `mypy` + `ruff` clean.

**`tests/unit/test_artifact.py` additions (before `artifact.py` change):**
- Valid ISO-8601 date string `"2026-05-31"` → model constructs without error.
- Invalid date string `"not-a-date"` → `ValidationError` raised.
- Invalid date string `"2026-13-01"` (month 13) → `ValidationError` raised.

**`tests/unit/test_errors.py` additions (before `errors.py` change):**
- `isinstance(CredentialError(...), ArkeologyError)` is `True`.
- `isinstance(StartupValidationError(...), ArkeologyError)` is `True`.
- `isinstance(VectorIndexNotFoundError(...), ArkeologyError)` is `True`.
- `except CredentialError` still catches a `CredentialError` instance.

**`tests/unit/test_startup.py` additions (before `startup.py` change):**
- `describe_index` returns `{"dimensions": "nan"}` → `StartupValidationError` raised
  with message containing `"nan"`.
- `describe_index` returns `{"dimensions": None}` → `StartupValidationError` raised.

**`server.py` and `__main__.py` changes:** no new tests; confirm existing unit tests pass
and `uv run arkeology --help` does not raise `PackageNotFoundError`.

## Open Questions

*(none — all behaviour is defined)*

## Items Resolved Since Last Review

<!-- changelog-style: prepend new entries -->
- 2026-08-12 — **Re-verification pass (developer): all 7 items confirmed resolved.**
  This spec sat with `status: ready` and no closure note for ~2.5 months despite the
  code having matched every requirement since the day it was authored. `f642725`
  ("production hardening — 20 review-fix specs", 2026-05-31, same day as this review)
  deliberately implemented `print()` → `logger.critical`, the `check_required_non_empty`
  isinstance guard, the `Artifact.date` ISO-8601 field validator, the
  `importlib.metadata.version` `PackageNotFoundError` fallback, the `ArkeologyError`
  base class, and the `startup.py` dimension `try/except`. The seventh item (a
  `# type: ignore` comment at the `model_validator(mode="before")` boundary) was never
  literally added, but `mypy --strict` has been clean there since the project's first
  commit thanks to the `pydantic.mypy` plugin already being configured — the underlying
  requirement was already met by a different mechanism than the one the spec proposed.
  No code was changed by this re-verification pass.
