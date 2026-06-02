# Issue: AWS Credentials Written to Log File

**Date:** 2026-06-02
**Severity:** Critical
**Status:** Fixed 2026-06-02
**Source:** Live test session — `/home/mlnrt/.local/share/opencode/log/2026-06-02T115606.log`

## Description

When `LOG_LEVEL=DEBUG` is configured, AWS temporary credentials — including `secretAccessKey`
and `sessionToken` — are written verbatim to the stderr log. Full HTTP request headers
containing `X-Amz-Security-Token` and full HTTP response bodies containing credential JSON
are emitted by the botocore, urllib3, boto3, and s3transfer libraries. Any process or person
with read access to the log file can extract live AWS credentials from it.

## Evidence

**Log line 278** — SSO credential refresh response body written at DEBUG:
```
b'{"roleCredentials":{"accessKeyId":"ASIA5HULGU43BP6SWJER","secretAccessKey":"7GRKMgwDaSO+WVAw/...","sessionToken":"IQoJb3JpZ2luX2Vj..."}}'
```
The same pattern appears at lines 805 and 1280 for subsequent credential refreshes.

**Log line 409** — Full HTTP request headers including `X-Amz-Security-Token` on every S3
call:
```
'X-Amz-Security-Token': b'IQoJb3JpZ2luX2VjEFwaDGV1LWNlbnRyYWwtMSJIMEYCIQDGhcNmM3mOs87...'
```
This pattern appears on every S3 and Bedrock API call throughout the log (lines 409, 492,
639, and throughout the full 32 717-line log file).

## Root Cause

`configure_logging()` in `src/cairn_mcp/__main__.py` sets the **root** logger to the
configured level and stops. Python's logging hierarchy means child loggers (`botocore`,
`boto3`, `urllib3`, `s3transfer`) inherit the root level and emit at `DEBUG`. At `DEBUG`,
these libraries log:

- AWS credential provider responses (full JSON bodies with `secretAccessKey` and `sessionToken`)
- All HTTP request headers including `Authorization` and `X-Amz-Security-Token`
- All HTTP response headers and bodies (S3 object content, Bedrock embedding payloads)

There is no per-logger level cap anywhere in the codebase.

## Affected File

`src/cairn_mcp/__main__.py` — `configure_logging()` function only.

## Options

### Option A — Clamp noisy loggers to WARNING in `configure_logging()` (recommended)

After setting the root level, unconditionally call
`logging.getLogger(name).setLevel(logging.WARNING)` for each of
`("botocore", "boto3", "urllib3", "s3transfer")`.

- Minimal code change — a constant tuple and a one-line loop.
- Survives future root-level changes; the cap is always applied.
- Easy to test: verify each logger is at WARNING regardless of root level.
- Trade-off: a developer investigating botocore retries at DEBUG will not see HTTP wire
  output. They would need to temporarily raise the cap in their local environment.

### Option B — Add a `BOTO_LOG_LEVEL` config field (not recommended now)

Expose a separate env var (default `WARNING`) that controls only the third-party logger
level, independent of `LOG_LEVEL`.

- Gives operators an escape hatch to enable botocore DEBUG when needed.
- Adds a config field and complexity; the escape hatch re-opens the credential exposure
  risk if misused.
- Can be added later if a specific debugging need arises. Not needed now.

### Option C — Strip credentials via a custom `logging.Filter` (not recommended)

Write a filter that redacts `secretAccessKey`, `sessionToken`, and `X-Amz-Security-Token`
values in any log record before it reaches the handler.

- Brittle — requires a comprehensive redaction regex maintained as AWS SDK response shapes
  evolve; a missed field is a silent credential leak.

## Recommendation

**Option A.** Simplest, safest, fully testable. Implement the constant tuple `_NOISY_LOGGERS`
and the suppression loop at the end of `configure_logging()`.

## Tests Required

New file `tests/unit/test_main.py`:

- Root logger level is set to the requested level for each valid value.
- Each of `botocore`, `boto3`, `urllib3`, `s3transfer` is at `WARNING` regardless of root level.
- Noisy loggers are still suppressed on an invalid level → INFO fallback.
- Repeated calls to `configure_logging()` do not accumulate duplicate handlers.

## Fix Applied

**File:** `src/cairn_mcp/__main__.py`

Added `_NOISY_LOGGERS: tuple[str, ...] = ("botocore", "boto3", "urllib3", "s3transfer")`
constant and a suppression loop at the end of `configure_logging()`:

```python
for name in _NOISY_LOGGERS:
    logging.getLogger(name).setLevel(logging.WARNING)
```

**Tests:** `tests/unit/test_main.py` created — 20 tests, all passing.
513 unit tests pass; ruff and mypy clean.
