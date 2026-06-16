---
type: spec
title: T4 — Configuration Model
description: Feature spec for a validated Pydantic Settings model that reads all environment variables at startup and fails fast with actionable errors on missing or invalid configuration.
tags: []
timestamp: 2026-05-29T00:00:00Z
okf_version: "0.1"
feature: p1-t4-configuration-model
status: ready
phase: 1
task: 4
references: []
authored:
  by: "architect"
  date: "2026-05-29"
revised:
  by: ""
  date: ""
---

# T4 — Configuration Model

<!-- SCOPE BLOCK -->

## Problem Statement

The server is configured entirely by environment variables. Without a single, validated
configuration model, each module reads from `os.environ` independently, type casting errors
surface at runtime during unrelated operations, and missing required variables produce cryptic
`KeyError` or `None` failures deep in the call stack. This task creates a `Settings` dataclass
that reads and validates all configuration at process start, so failures are immediate, clear, and
actionable.

## User Stories

### Story 1 — Missing required variable produces a clear error before startup (P1)

When a required environment variable is absent, the developer sees an error message identifying
exactly which variable is missing and what it is used for — before any AWS calls are attempted.

**Acceptance criteria:**
- Given `AWS_REGION` is not set in the environment, when the server starts, then it exits immediately with a message: `"Missing required configuration: AWS_REGION — AWS region for all API calls"`.
- Given `ARTIFACT_BUCKET` is not set, when the server starts, then it exits with a message identifying `ARTIFACT_BUCKET` as missing.
- Given all required variables are set, when the server starts, then no configuration error is raised and execution proceeds to startup validation (T5).

### Story 2 — Optional variables parse to correct types with documented defaults (P1)

Optional variables have documented defaults. A misconfigured optional variable (e.g. a non-integer
value where an integer is expected) produces a clear error, not a silent wrong value.

**Acceptance criteria:**
- Given `SEARCH_FETCH_TOP_K` is not set, when Settings is constructed, then `search_fetch_top_k` is `25`.
- Given `SEARCH_FETCH_TOP_K=150` (above the ceiling of 100), when Settings is constructed, then a validation error is raised: `"SEARCH_FETCH_TOP_K must be between 1 and 100 (got 150)"`.
- Given `SEARCH_FETCH_TOP_K=abc`, when Settings is constructed, then a validation error is raised indicating the value is not an integer.

## Requirements

- WHEN the `Settings` object is constructed THE SYSTEM SHALL read all environment variables from `os.environ` (or the system environment) once, at construction time.
- WHEN a required variable is absent THE SYSTEM SHALL raise a `ConfigurationError` with the variable name, its purpose, and a remediation hint before any other processing occurs.
- WHEN `SEARCH_FETCH_TOP_K` is set to a value above 100 THE SYSTEM SHALL raise a `ConfigurationError` identifying the ceiling constraint.
- WHEN `READ_PREFIXES` is set to a comma-separated string THE SYSTEM SHALL parse it into a `list[str]` with whitespace stripped from each entry and empty entries removed.
- WHEN `WRITE_PREFIX` is not set THE SYSTEM SHALL default to an empty string (root of the bucket).
- WHEN `READ_PREFIXES` is not set THE SYSTEM SHALL default to an empty list (no additional read scopes).
- WHEN `AWS_PROFILE` is not set THE SYSTEM SHALL store `None` (signal to use the default credential chain).
- WHEN `BEDROCK_EMBEDDING_MODEL` is not set THE SYSTEM SHALL default to `"amazon.titan-embed-text-v2:0"`.

## Boundaries

**Always:**
- `Settings` is a Pydantic `BaseSettings` model — use `pydantic-settings` for env var parsing. This gives automatic type coercion, default handling, and validation error messages for free.
- The `Settings` object is instantiated once, in `__main__.py`, before `server.run()` is called.
- `Settings` is passed into the server and client constructors by dependency injection — never re-instantiated or re-read from the environment mid-session.
- `ConfigurationError` is defined in `errors.py` (alongside `CredentialError`).
- All variable names, types, defaults, and descriptions must be documented in a reference table inside `config.py` as module-level docstring or comments — the code is the authoritative reference.

**Ask First:**
- Nothing — all variables and their constraints are defined in the PRD and design decisions.

**Never:**
- Do not call `os.environ.get(...)` anywhere outside of `config.py` / the `Settings` class.
- Do not silently coerce an out-of-range value to the nearest boundary — raise an error instead.
- Do not default `AWS_REGION` to any fallback value — it is required and must be present.

<!-- IMPLEMENTATION BLOCK -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `src/cairn_mcp/errors.py` | Modify | Add `ConfigurationError` |
| `src/cairn_mcp/config.py` | Create | `Settings` model and all env var definitions |
| `src/cairn_mcp/__main__.py` | Modify | Instantiate `Settings` before calling `server.run()` |
| `tests/unit/test_config.py` | Create | All parsing, validation, and default tests |

---

## `errors.py` — `ConfigurationError`

Add to the existing `errors.py`:

**`ConfigurationError`**: raised when a required environment variable is missing or a value fails
validation.
- `variable: str` — the environment variable name, e.g. `"AWS_REGION"`
- `message: str` — human-readable description of the problem and how to fix it

---

## `config.py` — `Settings` Model

### Environment variable reference

| Variable | Type | Required | Default | Constraint | Description |
|----------|------|----------|---------|------------|-------------|
| `AWS_REGION` | `str` | ✅ | — | Non-empty | AWS region for all API calls (e.g. `us-east-1`) |
| `ARTIFACT_BUCKET` | `str` | ✅ | — | Non-empty | S3 bucket name for artifact content storage |
| `VECTORS_BUCKET` | `str` | ✅ | — | Non-empty | S3 Vectors bucket name |
| `VECTORS_INDEX` | `str` | ✅ | — | Non-empty | S3 Vectors index name within the vectors bucket |
| `AWS_PROFILE` | `str \| None` | ❌ | `None` | — | Named AWS profile; if absent, default credential chain is used |
| `WRITE_PREFIX` | `str` | ❌ | `""` | — | S3 key prefix for all writes; may be empty (root) |
| `READ_PREFIXES` | `str` | ❌ | `""` | — | Comma-separated additional read prefixes; empty means no additional scopes |
| `BEDROCK_EMBEDDING_MODEL` | `str` | ❌ | `"amazon.titan-embed-text-v2:0"` | Non-empty if set | Bedrock embedding model ID |
| `SEARCH_FETCH_TOP_K` | `int` | ❌ | `25` | 1–100 inclusive | Section vectors requested per S3 Vectors call in the search re-fetch loop |
| `SEARCH_MAX_ITERATIONS` | `int` | ❌ | `3` | ≥1 | Maximum S3 Vectors calls per search before returning available results |
| `SEARCH_DEFAULT_TOP_K` | `int` | ❌ | `5` | 1–100 inclusive | Default artifacts returned when caller does not specify |
| `LOG_LEVEL` | `str` | ❌ | `"INFO"` | One of: `DEBUG`, `INFO`, `WARNING`, `ERROR` | Controls logging verbosity |

### Parsed properties (derived from raw env vars)

`Settings` must expose these additional computed properties that downstream code uses directly:

- `read_prefixes_list: list[str]` — `READ_PREFIXES` split on `,`, stripped, empty entries removed
- `effective_read_scopes: list[str]` — `[write_prefix] + read_prefixes_list` (the full read scope the server operates over, including the write prefix which is always in scope)

### Pydantic `BaseSettings` usage

Use `pydantic-settings` `BaseSettings`. Key configuration:
- Set `model_config = SettingsConfigDict(env_prefix="", case_sensitive=True)` so variable names map exactly.
- Use Pydantic `Field(default=..., description=...)` for each field — the description becomes the documentation.
- Use a Pydantic `@field_validator` for:
  - `SEARCH_FETCH_TOP_K`: validate range 1–100.
  - `SEARCH_MAX_ITERATIONS`: validate ≥1.
  - `SEARCH_DEFAULT_TOP_K`: validate range 1–100.
  - `LOG_LEVEL`: validate it is one of the four valid values (case-insensitive, store uppercase).
  - `READ_PREFIXES` (raw string): the validator converts the comma-separated string to `read_prefixes_list`.

### How `Settings` is used in `__main__.py`

In `main()`, after configuring logging, construct `Settings()`. If a Pydantic `ValidationError` is
raised, catch it, format the first error (or all errors) as a human-readable `ConfigurationError`
message, print it to stderr, and exit with code 1. Do not let a raw Pydantic `ValidationError`
propagate — the user should see a clean message, not a stack trace.

Pass the constructed `Settings` instance to `server.run(settings)`. The server stores it and passes
it to the startup validator (T5) and eventually to the client factory.

---

## TDD Workflow

`config.py` has pure, side-effect-free validation logic — it is the ideal case for strict TDD.
There is no AWS, no I/O, no concurrency. Every test is fast and deterministic.

**Step 1 — Write `tests/unit/test_config.py` in full (Red).**
Write all test cases from the Test Cases section below. Use `pytest-monkeypatch` or
`os.environ` patching to set/unset env vars per test. Run `uv run pytest tests/unit/test_config.py`
— every test fails with `ImportError` because `config.py` does not exist yet. ✓

**Step 2 — Write `config.py` (Green).**
Implement the `Settings` model. Run `uv run pytest tests/unit/test_config.py` — all tests pass. ✓

Do not write `config.py` in one shot and then check whether the tests pass.
Write enough to make the first failing test pass, then the second, and so on.
This forces you to think about each validation rule individually.

**Step 3 — Refactor.**
Review the Pydantic validators. Are error messages clear? Are all edge cases (empty string,
whitespace-only value) handled? Are the computed properties (`read_prefixes_list`,
`effective_read_scopes`) correct for all combinations? Tests stay green throughout. ✓

**Step 4 — Add `ConfigurationError` wrapping in `__main__.py`.**
Write a test that constructs `Settings` with a missing required variable and asserts that
`main()` exits with code 1 and prints to stderr (not stdout). Implement the catch in `__main__.py`.
This test can live in `test_config.py` or a new `test_main.py`.

---

## Test Cases

| Scenario | Test |
|----------|------|
| All required vars present, all optionals absent | `Settings()` constructs without error; optional fields have expected defaults |
| `AWS_REGION` absent | `ValidationError` / `ConfigurationError` raised; message references `AWS_REGION` |
| `ARTIFACT_BUCKET` absent | Same pattern |
| `VECTORS_BUCKET` absent | Same pattern |
| `VECTORS_INDEX` absent | Same pattern |
| `SEARCH_FETCH_TOP_K=0` | Validation error; message references constraint (1–100) |
| `SEARCH_FETCH_TOP_K=101` | Validation error; message references constraint (1–100) |
| `SEARCH_FETCH_TOP_K=50` | Accepted; `settings.search_fetch_top_k == 50` |
| `SEARCH_MAX_ITERATIONS=0` | Validation error |
| `LOG_LEVEL=TRACE` (invalid) | Validation error; message lists valid values |
| `LOG_LEVEL=debug` (lowercase) | Accepted; stored as `"DEBUG"` |
| `READ_PREFIXES="network/,shared/ , "` | Parsed to `["network/", "shared/"]` (no empty entries, stripped whitespace) |
| `READ_PREFIXES` absent | `read_prefixes_list == []` |
| `WRITE_PREFIX` absent | `write_prefix == ""` |
| `effective_read_scopes` with prefix and read prefixes | `["platform/", "network/", "shared/"]` |
| `effective_read_scopes` with no prefix and no read prefixes | `[""]` |
| `AWS_PROFILE` absent | `aws_profile is None` |
| `BEDROCK_EMBEDDING_MODEL` absent | `bedrock_embedding_model == "amazon.titan-embed-text-v2:0"` |

## Open Questions

- [ ] Pydantic `ValidationError` exposes errors as a structured list. Decide how many errors to surface in the human-readable output when multiple vars are missing simultaneously — first error only, or all errors at once. Recommendation: all errors at once (one missing variable should not hide another).
