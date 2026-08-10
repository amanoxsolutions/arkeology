---
type: code_review
title: Review Fix 07 — Bedrock Throttle Retry
description: Adds a single retry with brief sleep to bedrock.py embed() for transient ThrottlingException, ModelTimeoutException, and ServiceUnavailableException so one transient failure does not abort a tool call.
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
# Review Fix 07 — Bedrock Throttle Retry (M6)

## Problem Statement

`bedrock.py` `embed()` only catches credential errors. `ThrottlingException`,
`ModelTimeoutException`, and `ServiceUnavailableException` are transient errors that propagate
unhandled, killing the entire tool call. Bedrock throttling is common under load; a single
transient failure should not abort a write or search operation.

## User Stories

### Story 1 — Transient throttle is retried once and succeeds (P1)

**Acceptance criteria:**
- Given Bedrock raises `ThrottlingException` on the first embed call, when `embed()` is called,
  then the client waits briefly, retries once, and returns the embedding on success.

### Story 2 — Two consecutive throttles surface as a structured error (P1)

**Acceptance criteria:**
- Given Bedrock raises `ThrottlingException` on both the first and retry attempt, when `embed()`
  is called, then a structured error is raised (not an unhandled crash).

### Story 3 — ModelTimeoutException and ServiceUnavailableException follow same retry logic (P1)

**Acceptance criteria:**
- Given Bedrock raises `ModelTimeoutException` or `ServiceUnavailableException` on the first
  attempt and succeeds on retry, when `embed()` is called, then the embedding is returned.

## Requirements

- WHEN `embed()` raises `ThrottlingException` on the first attempt THE SYSTEM SHALL wait briefly
  and retry exactly once.
- WHEN the retry also raises `ThrottlingException` THE SYSTEM SHALL raise a structured error
  (not crash silently).
- WHEN `embed()` raises `ModelTimeoutException` or `ServiceUnavailableException` THE SYSTEM SHALL
  retry once with the same behaviour as `ThrottlingException`.
- WHEN the retry succeeds THE SYSTEM SHALL return the embedding as normal.

## Boundaries

**Always:**
- Exactly one retry — no exponential backoff loop in this spec.
- `CredentialError` and all non-transient errors must NOT be retried.
- The retry sleep default is 2 seconds; this must be a named constant (not a magic number).

**Ask First:**
- Confirm 2-second sleep duration is acceptable for the use case before merging.

**Never:**
- Do not retry on `CredentialError` or any non-transient `ClientError`.
- Do not introduce a retry loop — a single retry is the complete scope.

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/clients/test_fake_bedrock.py` | Modify | Add tests for throttle-retry behaviour (written first — Red) |
| `src/cairn_mcp/clients/fakes/fake_bedrock.py` | Modify | Add `throttle_on_next_call: bool` flag to simulate throttle → retry → success |
| `src/cairn_mcp/clients/bedrock.py` | Modify | Add retry logic for transient errors after `CredentialError` check |

## Testing Approach

**TDD cycle:** update `test_fake_bedrock.py` first (Red) → update `fake_bedrock.py` (fake
supports simulation) → implement retry in `bedrock.py` (Green).

**`tests/unit/clients/test_fake_bedrock.py` — new tests:**
- `test_throttle_on_first_call_succeeds_on_retry` — set `throttle_on_next_call = True`; call
  `embed()`; assert embedding returned and two attempts were made.
- `test_two_consecutive_throttles_raises_error` — configure fake to throttle twice; assert
  `embed()` raises a structured error (not `ThrottlingException` raw crash).
- `test_model_timeout_retried_once` — configure fake to raise `ModelTimeoutException` on first
  call, succeed on second; assert embedding returned.
- `test_non_transient_error_not_retried` — configure fake to raise `CredentialError`; assert
  it propagates immediately without retry.

## Open Questions

- Confirm acceptable sleep duration (default suggestion: 2 s). If lower latency is required, the
  constant can be reduced without changing the spec behaviour.
