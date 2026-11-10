---
type: Spec
id: p1-t4-configuration-model
title: T4 — Configuration Model
description: Feature spec for a validated Pydantic Settings model that reads all environment variables at startup and fails fast with actionable errors on missing or invalid configuration.
tags: []
status: stable
okf_version: "0.2"
generated:
  by: "axians-architect/unknown"
  at: 2026-05-29T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-10T05:48:47Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
---

# T4 — Configuration Model

## TL;DR

A single validated `Settings` model that reads every environment variable once at process start,
applies documented defaults, and fails fast with a clear, actionable message when a required variable
is missing or a value is invalid. It replaces scattered `os.environ` reads, so configuration failures
surface immediately instead of deep in an unrelated call stack.

## 1. Problem Statement

The server is configured entirely by environment variables. Without a single, validated configuration
model, each module reads from `os.environ` independently, type casting errors surface at runtime
during unrelated operations, and missing required variables produce cryptic `KeyError` or `None`
failures deep in the call stack. This task creates a `Settings` dataclass that reads and validates all
configuration at process start, so failures are immediate, clear, and actionable. Both goals — a clear
error for a missing required variable before startup, and optional variables parsing to correct types
with documented defaults — are priority P1.

## 2. Rules — Reading configuration

### R1 — Configuration is read once, at construction

When the `Settings` object is constructed, it reads all environment variables from `os.environ` (or the
system environment) once, at construction time.

### R2 — Environment variables, defaults and constraints

The server reads these environment variables. Optional variables have documented defaults.

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

When an optional variable is not set, its default applies:

| Variable not set | Resulting value |
|------------------|-----------------|
| `WRITE_PREFIX` | an empty string (root of the bucket) |
| `READ_PREFIXES` | an empty list (no additional read scopes) |
| `AWS_PROFILE` | `None` (signal to use the default credential chain) |
| `BEDROCK_EMBEDDING_MODEL` | `"amazon.titan-embed-text-v2:0"` |
| `SEARCH_FETCH_TOP_K` | `search_fetch_top_k` is `25` |

### R3 — `READ_PREFIXES` parsing

When `READ_PREFIXES` is set to a comma-separated string, it is parsed into a `list[str]` with whitespace
and surrounding slashes stripped from each entry and empty entries removed. Internal slashes in
multi-level prefixes (e.g. `"shared/org"`) are preserved. Surrounding slashes are normalized away
(mirroring `WRITE_PREFIX`) so the stored prefix matches the `scope` value persisted in vector metadata
and consumers can append `"/"` to rebuild the scope; a configured `"network/"` therefore becomes
`"network"`, not `"network/"` — which would match nothing at the call site and silently disable
foreign-scope reads.

## 3. Rules — Configuration errors

### R4 — A missing required variable is a clear error before startup

When a required environment variable is absent, a `ConfigurationError` is raised with the variable
name, its purpose, and a remediation hint, before any other processing occurs — the developer sees an
error message identifying exactly which variable is missing and what it is used for, before any AWS
calls are attempted. `AWS_REGION` is never defaulted to any fallback value — it is required and must be
present. When all required variables are set, no configuration error is raised and execution proceeds
to startup validation (T5).

**Example**

- Given `AWS_REGION` is not set in the environment, when the server starts, then it exits immediately
  with a message: `"Missing required configuration: AWS_REGION — AWS region for all API calls"`.
- Given `ARTIFACT_BUCKET` is not set, when the server starts, then it exits with a message identifying
  `ARTIFACT_BUCKET` as missing.

### R5 — An invalid value is an error, never a silent wrong value

A misconfigured optional variable (e.g. a non-integer value where an integer is expected) produces a
clear error, not a silent wrong value. An out-of-range value is never silently coerced to the nearest
boundary — an error is raised instead. When `SEARCH_FETCH_TOP_K` is set to a value above 100, a
`ConfigurationError` is raised identifying the ceiling constraint.

**Example**

- Given `SEARCH_FETCH_TOP_K=150` (above the ceiling of 100), when Settings is constructed, then a
  validation error is raised: `"SEARCH_FETCH_TOP_K must be between 1 and 100 (got 150)"`.
- Given `SEARCH_FETCH_TOP_K=abc`, when Settings is constructed, then a validation error is raised
  indicating the value is not an integer.

### R6 — Configuration failures exit cleanly with every error

When constructing `Settings` fails validation, the server prints a human-readable `ConfigurationError`
message to stderr (not stdout) and exits with code 1 — a raw Pydantic `ValidationError` never
propagates, so the user sees a clean message, not a stack trace. When several variables fail at once,
every field's message is surfaced, joined into the single `ConfigurationError` raised.

**Why:** so one missing variable never hides another.

## 4. Boundaries

**Always:**
- `Settings` is a Pydantic `BaseSettings` model — use `pydantic-settings` for env var parsing. This gives
  automatic type coercion, default handling, and validation error messages for free.
- The `Settings` object is instantiated once, in `__main__.py`, before `server.run()` is called.
- `Settings` is passed into the server and client constructors by dependency injection — never
  re-instantiated or re-read from the environment mid-session.
- `ConfigurationError` is defined in `errors.py` (alongside `CredentialError`).
- All variable names, types, defaults, and descriptions must be documented in a reference table inside
  `config.py` as module-level docstring or comments — the code is the authoritative reference.

**Ask First:**
- Nothing — all variables and their constraints are defined in requirements.md and design decisions.

**Never:**
- Do not call `os.environ.get(...)` anywhere outside of `config.py` / the `Settings` class.
- Do not silently coerce an out-of-range value to the nearest boundary — raise an error instead.
- Do not default `AWS_REGION` to any fallback value — it is required and must be present.

## 5. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `src/arkeology/errors.py` | Modify | Add `ConfigurationError` |
| `src/arkeology/config.py` | Create | `Settings` model and all env var definitions |
| `src/arkeology/__main__.py` | Modify | Instantiate `Settings` before calling `server.run()` |
| `tests/unit/test_config.py` | Create | All parsing, validation, and default tests |

#### `errors.py` — `ConfigurationError`

Add to the existing `errors.py`:

**`ConfigurationError`**: raised when a required environment variable is missing or a value fails
validation.
- `variable: str` — the environment variable name, e.g. `"AWS_REGION"`
- `message: str` — human-readable description of the problem and how to fix it

#### `config.py` — `Settings` Model

The environment variable reference is the R2 table.

**Parsed properties (derived from raw env vars).** `Settings` must expose these additional computed
properties that downstream code uses directly:

- `read_prefixes_list: list[str]` — `READ_PREFIXES` split on `,`, stripped, empty entries removed (R3)
- `effective_read_scopes: list[str]` — `[write_prefix] + read_prefixes_list` (the full read scope the
  server operates over, including the write prefix which is always in scope)

**Pydantic `BaseSettings` usage.** Use `pydantic-settings` `BaseSettings`. Key configuration:
- Set `model_config = SettingsConfigDict(env_prefix="", case_sensitive=True)` so variable names map
  exactly.
- Use Pydantic `Field(default=..., description=...)` for each field — the description becomes the
  documentation.
- Use a Pydantic `@field_validator` for:
  - `SEARCH_FETCH_TOP_K`: validate range 1–100.
  - `SEARCH_MAX_ITERATIONS`: validate ≥1.
  - `SEARCH_DEFAULT_TOP_K`: validate range 1–100.
  - `LOG_LEVEL`: validate it is one of the four valid values (case-insensitive, store uppercase).
  - `READ_PREFIXES` (raw string): the validator converts the comma-separated string to
    `read_prefixes_list`.

`config.py`'s `load_settings()` iterates `ValidationError.errors()` in full and joins every field's
message into the single `ConfigurationError` raised (R6).

#### How `Settings` is used in `__main__.py`

In `main()`, after configuring logging, construct `Settings()`. If a Pydantic `ValidationError` is
raised, catch it, format all of its errors (R6) as a human-readable `ConfigurationError` message, print it to stderr, and
exit with code 1 (R6).

Pass the constructed `Settings` instance to `server.run(settings)`. The server stores it and passes it
to the startup validator (T5) and eventually to the client factory.

### Contracts

None.

### Testing Approach

`config.py` has pure, side-effect-free validation logic — it is the ideal case for strict TDD. There is
no AWS, no I/O, no concurrency. Every test is fast and deterministic.

1. **Write `tests/unit/test_config.py` in full (Red).** Write all test cases from the table below. Use
   `pytest-monkeypatch` or `os.environ` patching to set/unset env vars per test. Run
   `uv run pytest tests/unit/test_config.py` — every test fails with `ImportError` because `config.py`
   does not exist yet. ✓
2. **Write `config.py` (Green).** Implement the `Settings` model. Run
   `uv run pytest tests/unit/test_config.py` — all tests pass. ✓

   Do not write `config.py` in one shot and then check whether the tests pass. Write enough to make the
   first failing test pass, then the second, and so on. This forces you to think about each validation
   rule individually.
3. **Refactor.** Review the Pydantic validators. Are error messages clear? Are all edge cases (empty
   string, whitespace-only value) handled? Are the computed properties (`read_prefixes_list`,
   `effective_read_scopes`) correct for all combinations? Tests stay green throughout. ✓
4. **Add `ConfigurationError` wrapping in `__main__.py`.** Write a test that constructs `Settings` with a
   missing required variable and asserts that `main()` exits with code 1 and prints to stderr (not
   stdout). Implement the catch in `__main__.py`. This test can live in `test_config.py` or a new
   `test_main.py`.

**Test cases:**

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
| `READ_PREFIXES="network/,shared/ , "` | Parsed to `["network", "shared"]` (empty entries dropped; whitespace and surrounding slashes stripped) |
| `READ_PREFIXES` absent | `read_prefixes_list == []` |
| `WRITE_PREFIX` absent | `write_prefix == ""` |
| `effective_read_scopes` with prefix and read prefixes | `["platform/", "network/", "shared/"]` |
| `effective_read_scopes` with no prefix and no read prefixes | `[""]` |
| `AWS_PROFILE` absent | `aws_profile is None` |
| `BEDROCK_EMBEDDING_MODEL` absent | `bedrock_embedding_model == "amazon.titan-embed-text-v2:0"` |
