---
type: spec
title: T15 — Partial Write Failure Log
description: Feature spec for a structured local failure log that records partial write failures (S3 succeeds but Bedrock or S3 Vectors indexing fails) and a Bedrock throttle retry mechanism.
tags: []
timestamp: 2026-05-30T00:00:00Z
okf_version: "0.1"
feature: p3-t15-partial-write-failure-log
status: ready
phase: 3
task: 15
references: []
authored:
  by: "architect"
  date: "2026-05-30"
revised:
  by: ""
  date: ""
---

# T15 — Partial Write Failure Log

<!-- SCOPE BLOCK — frozen after approval -->

## Problem Statement

A write operation can partially fail: S3 succeeds (the artifact content is stored durably)
but the subsequent Bedrock embedding or S3 Vectors indexing call fails. Without a recovery
mechanism, the artifact is permanently invisible to search — stored in S3 but never indexed.
This is a silent data loss scenario that violates NFR-11 ("never silently discard a write
operation"). This task closes that gap by writing a structured entry to a local tier 1
failure log when a partial write occurs, then surfacing a structured error to the agent that
includes the artifact identifier and a note that a failure log entry was written. The
reconciliation tool (T19, FR-17) will later use this log to re-index orphaned artifacts.

Additionally, Bedrock throttling is a transient error that should be retried once with
back-off before being surfaced as a hard failure.

## User Stories

### Story 1 — A partial write failure is never silent (P1)

The S3 write succeeds but the Bedrock embed call fails. The agent receives a structured
error with the artifact identifier, and a failure log entry is written to disk.

**Acceptance criteria:**
- Given a simulated Bedrock failure after S3 write succeeds, when `write_artifact` returns,
  then the response contains `"error": "partial_write"`, the `artifact_id`, and a message
  indicating the failure log was written.
- Given the partial write occurred, when the failure log file is read, then it contains a
  machine-readable entry with the artifact identifier, title, type, tier, and failure reason.

### Story 2 — A partial write failure on vector index write is also logged (P1)

**Acceptance criteria:**
- Given a simulated S3 Vectors `put_vector` failure after S3 write succeeds, when
  `write_artifact` returns, then the response contains `"error": "partial_write"`, the
  `artifact_id`, and a message indicating the failure log was written.
- The failure log entry includes the failure reason (e.g. which step failed).

### Story 3 — Bedrock throttle triggers one retry (P1)

**Acceptance criteria:**
- Given Bedrock responds with a throttling error on the first embed call, when
  `write_artifact` processes the response, then exactly one retry is attempted after a
  short back-off.
- Given the retry succeeds, when `write_artifact` returns, then the artifact is written
  normally with no error and no failure log entry.
- Given the retry also fails (non-throttle error or throttle again), when `write_artifact`
  returns, then the failure log is written and a partial-write error is returned.

### Story 4 — The failure log is gitignored (P1)

**Acceptance criteria:**
- The failure log path is listed in `.gitignore` so it is never committed to the repository.

## Requirements

- WHEN an S3 write in `write_artifact` succeeds but a subsequent Bedrock embed or
  `put_vector` call fails (for any non-credential reason) THE SYSTEM SHALL write a
  structured JSON entry to the local failure log before returning a structured error.
- THE FAILURE LOG entry SHALL include: `artifact_id` (the full S3 key), `title`, `type`,
  `tier`, `date`, `failure_step` (one of: `"bedrock_embed"`, `"put_vector"`), `reason`
  (exception message), and a timestamp.
- THE FAILURE LOG SHALL be appended to (not overwritten) so multiple failures accumulate.
- WHEN the failure log file does not exist THE SYSTEM SHALL create it.
- WHEN a CredentialError occurs (not a partial write — credential errors are hard failures)
  THE SYSTEM SHALL NOT write a failure log entry; return a credential-error response as
  before.
- WHEN a Bedrock embed call raises a throttling error (HTTP 429 / ThrottlingException)
  THE SYSTEM SHALL wait a short back-off (suggested: 1 second) and retry once before
  treating it as a partial write failure.
- WHEN the retry succeeds THE SYSTEM SHALL proceed normally — no failure log entry, no
  error.
- WHEN the retry also fails (any reason) THE SYSTEM SHALL write the failure log entry and
  return a partial-write error response.
- THE STRUCTURED ERROR RESPONSE on partial write SHALL contain:
  `{"error": "partial_write", "message": str, "artifact_id": str}`.
- THE FAILURE LOG PATH SHALL be a tier 1 artifact: local, ephemeral, and listed in
  `.gitignore`. The path SHALL be configurable via a `FAILURE_LOG_PATH` setting with a
  default of `.arkeology_failures.jsonl`.

## Boundaries

**Always:**
- The failure log is append-only newline-delimited JSON (`.jsonl`); one JSON object per
  line.
- Failure log writes must never raise — if the log write itself fails, log the error to
  stderr (Python logging) and continue to return the partial-write error to the agent.
- The Bedrock retry is a single retry only — no exponential back-off loop.
- Throttling detection identifies the standard AWS ThrottlingException / 429 error code.
- Credential errors remain credential errors and are NOT treated as partial write failures.
- The tool receives failure log path from `settings.failure_log_path`.
- A new optional `FAILURE_LOG_PATH` setting is added to `config.py` with default
  `.arkeology_failures.jsonl`.

**Ask First:**
- Nothing — all constraints are defined.

**Never:**
- Do not write a failure log entry for credential errors.
- Do not overwrite the failure log — always append.
- Do not raise from the failure log write path — log to stderr and continue.
- Do not retry non-throttling errors.

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_failure_log.py` | Create | Written first (Red) — failure_log module |
| `src/arkeology/failure_log.py` | Create | Written after unit tests (Green) |
| `tests/unit/test_tools_write.py` | Modify | Add partial failure + retry test cases (Red) |
| `src/arkeology/tools/write.py` | Modify | Add failure logging + Bedrock retry (Green) |
| `src/arkeology/config.py` | Modify | Add `FAILURE_LOG_PATH` optional setting |
| `.gitignore` | Modify | Add `.arkeology_failures.jsonl` (and pattern for custom paths) |

## Testing Approach

**TDD cycle A (unit — failure log module):** write `test_failure_log.py` first → fail →
implement `failure_log.py` → pass.

**TDD cycle B (unit — write tool changes):** extend `test_tools_write.py` with partial
failure and retry cases → fail → modify `tools/write.py` → pass.

---

**`test_failure_log.py` — unit tests (filesystem, no AWS):**

Use `tmp_path` (pytest fixture) as the log path.

Happy path:
- `append_failure_entry(path, entry_dict)` on a non-existent file → creates file; one line.
- `append_failure_entry` called twice → two lines, each valid JSON.
- Each line is a valid JSON object with all required fields.

Required fields in each entry:
- `artifact_id`, `title`, `type`, `tier`, `date`, `failure_step`, `reason`, `timestamp`.
- `timestamp` is a valid ISO-8601 string.

Resilience:
- `append_failure_entry` on a path in a non-existent directory → logs to stderr, does not
  raise.
- `append_failure_entry` when disk is full (simulate `OSError`) → logs to stderr, does not
  raise.

**`tests/unit/test_tools_write.py` — additional test cases:**

Bedrock retry:
- Bedrock raises throttle error on first call, succeeds on second → artifact written
  normally; no failure log entry; `write_artifact` returns success.
- Bedrock raises throttle error on first call, raises again on second → partial_write error
  returned; `artifact_id` in response; failure log entry written with `failure_step="bedrock_embed"`.
- Bedrock raises non-throttle error → no retry; partial_write error; failure log entry
  written.

Partial write on put_vector failure:
- S3 write succeeds, `put_vector` raises → partial_write error with `artifact_id`; failure
  log entry written with `failure_step="put_vector"`.

Failure log integrity:
- After a partial write failure, failure log contains exactly one entry with all required
  fields.
- After two partial write failures, failure log contains two entries (append behaviour).

Credential errors unchanged:
- Bedrock raises `CredentialError` → credential_error response; no failure log entry.
- `put_vector` raises `CredentialError` → credential_error response; no failure log entry.

**No integration tests for this task** — the failure log is a local tier 1 artifact and
does not interact with real AWS services. The existing integration tests for `write_artifact`
(T7) provide sufficient end-to-end coverage of the non-failure path; they run unchanged.

## Open Questions

*(none — all constraints are defined)*
