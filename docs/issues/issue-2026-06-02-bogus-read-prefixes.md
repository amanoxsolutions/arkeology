---
status: closed
references: []
authored:
  by: "developer"
  date: "2026-06-02"
revised:
  by: ""
  date: ""
---

# Issue: `.env` Template Placeholder Text Accepted as S3 Prefixes

**Date:** 2026-06-02
**Severity:** High
**Status:** Fixed 2026-06-02
**Source:** Live test session — `/home/mlnrt/.local/share/opencode/log/2026-06-02T115606.log`

## Description

The user's `.env` file contained `READ_PREFIXES=# comma-separated, or leave blank` — the
verbatim help text from a `.env` template. The server accepted both comma-split tokens
(`"# comma-separated"` and `"or leave blank"`) as valid S3 key prefixes, issued real
`ListObjectsV2` calls against them at startup and on every `health_check` invocation, and
reported no error. The misconfiguration is invisible to the operator.

## Evidence

**Log line 580:**
```
DEBUG cairn_mcp.clients.s3 S3 list_objects prefix=# comma-separated
```

**Log line 604:** Real `ListObjectsV2` request:
```
'query_string': {'prefix': '# comma-separated', 'encoding-type': 'url'}
'url': 'https://...s3.eu-west-1.amazonaws.com/?list-type=2&prefix=%23%20comma-separated&encoding-type=url'
```

**Log line 659:**
```
DEBUG cairn_mcp.clients.s3 S3 list_objects prefix=or leave blank
```

**Log line 675:** Real `ListObjectsV2` request with `prefix=or%20leave%20blank`.

**Log line 1562:** Same pair of bogus calls repeated during `health_check`.

Each spurious call adds latency and consumes an AWS API request. The calls succeed with
an empty result (`KeyCount=0`), so no error is surfaced.

## Root Cause

**In `config.py`:** `READ_PREFIXES` has no `@field_validator`. The `read_prefixes_list`
property only strips surrounding whitespace and drops empty entries. Tokens that start with
`#` or contain internal whitespace reach `startup.py` and `health.py` unchanged.

**In python-dotenv:** python-dotenv treats a `#` as a full-line comment only when it
appears at the start of a line. An inline `#` in a value (e.g.
`READ_PREFIXES=# comma-separated, or leave blank`) is treated as part of the value, not
as a comment. The entire string is passed to `Settings` verbatim.

**In the `.env` template:** The repo's README references `.env.example`
(`cp .env.example .env`) but the file does not exist in the repository. The operator
constructed their `.env` manually and wrote help text directly into the value instead
of as a separate comment line.

Valid S3 key prefixes never contain whitespace and are never intended to begin with `#`.

## Affected Files

- `src/cairn_mcp/config.py` — no validator for `READ_PREFIXES`.
- `.env.example` — does not exist in the repo; README references it.

## Options

### Option A — `@field_validator("READ_PREFIXES")` with filtering and rejection (recommended)

Parse the comma-separated value. For each token:
1. Strip surrounding whitespace.
2. Silently drop empty tokens and tokens starting with `#` (common comment accident).
3. Raise `ValueError` for any token containing internal whitespace (e.g. `"or leave blank"`).
   Message: `"READ_PREFIXES contains an invalid prefix '<token>': S3 prefixes must not
   contain whitespace. Check your .env file for template placeholder text."`
4. Return the cleaned, comma-rejoined string.

The `read_prefixes_list` property continues to work unchanged.

- Fails fast at startup for unambiguously invalid input.
- Silently heals the `#` comment accident (common; silent drop is appropriate).
- Surfacing the whitespace error forces the operator to fix their `.env` — desirable.
- Fully testable via `test_config.py`.

### Option B — Silent filtering for all invalid tokens (no error)

Same as A but also drop whitespace-containing tokens silently instead of raising.

- Server starts without errors even with template text.
- Operator never learns their `.env` is misconfigured. Not recommended.

### Option C — Fix `.env.example` only

Change the template so help text appears as a full-line comment:
```ini
# READ_PREFIXES — comma-separated foreign read scopes; leave blank if none
READ_PREFIXES=
```
python-dotenv ignores lines starting with `#`, so this would produce `READ_PREFIXES=""`.

- No code change needed.
- Does not fix existing `.env` files already copied from the old (or manually authored)
  template.
- Does not prevent future misconfiguration from other sources.

## Recommendation

**Option A + Option C together.** The validator fixes existing misconfigured installs; the
`.env.example` (which must be created) prevents the mistake for new installs.

## Tests Required

Additions to `tests/unit/test_config.py`:

- `READ_PREFIXES="# comma-separated"` → `read_prefixes_list == []` (comment token silently dropped).
- `READ_PREFIXES="platform/, # a comment"` → `read_prefixes_list == ["platform/"]`.
- `READ_PREFIXES="or leave blank"` → `ValidationError` (internal whitespace).
- `READ_PREFIXES="# comma-separated, or leave blank"` → `ValidationError` (whitespace token
  detected even when preceded by a comment token).

## Fix Applied

**File:** `src/cairn_mcp/config.py`

Added `@field_validator("READ_PREFIXES")` that splits on commas, silently drops empty and
`#`-prefixed tokens, and raises `ValueError` for any token containing internal whitespace.
Returns the cleaned comma-joined string so `read_prefixes_list` continues to work unchanged.

**File:** `.env.example` (created)

All optional variables are commented out with help text on separate lines, preventing
python-dotenv from capturing help text as a variable value.

**Tests:** 4 new test cases added to `tests/unit/test_config.py`, all passing.
513 unit tests pass; ruff and mypy clean.
