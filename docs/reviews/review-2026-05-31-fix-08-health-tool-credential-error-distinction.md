---
type: code_review
title: Review Fix 08 — Health Tool Credential Error Distinction
description: "Makes health_check distinguishable between credential errors and transient errors by adding a \"cause\": \"credential_error\" field to probe results when CredentialError is raised."
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
# Review Fix 08 — Health Tool Credential Error Distinction (M9)

## Problem Statement

All probes in `health.py` use bare `except Exception`. `CredentialError` is not imported. A
credential expiry is indistinguishable from a connectivity failure in health check output — both
produce `{"status": "error", "message": "..."}`. Callers cannot machine-read the difference
between "re-authenticate" (credential error) and "retry later" (transient error), making
automated alerting and recovery impossible.

## User Stories

### Story 1 — Credential errors are labelled in probe output (P1)

**Acceptance criteria:**
- Given a health probe raises `CredentialError`, when `health_check` is called, then that
  probe's result contains `"cause": "credential_error"`.
- Given a health probe raises a generic `Exception`, when `health_check` is called, then that
  probe's result contains `"status": "error"` and `"message"` but no `"cause"` field.

### Story 2 — One probe's credential error does not affect other probes (P1)

**Acceptance criteria:**
- Given the S3 probe raises `CredentialError` and all other probes succeed, when `health_check`
  is called, then only the S3 probe shows `"cause": "credential_error"`; all other probes show
  their normal results.

## Requirements

- WHEN a health probe raises `CredentialError` THE SYSTEM SHALL include `"cause":
  "credential_error"` in that probe's status dict alongside `"status": "error"` and `"message"`.
- WHEN a health probe raises any other exception THE SYSTEM SHALL return `{"status": "error",
  "message": str(exc)}` without a `"cause"` field (existing behaviour unchanged).
- WHEN any probe raises an exception THE SYSTEM SHALL continue running all remaining probes
  independently.

## Boundaries

**Always:**
- `CredentialError` must be caught before `Exception` in each probe's except chain.
- Each probe runs independently — a failure in one must never skip another.
- `CredentialError` must be imported from `cairn_mcp.errors` at the top of `health.py`.

**Ask First:**
- Nothing — all outcomes are defined.

**Never:**
- Do not change the top-level return shape of `health_check`.
- Do not add `"cause"` to non-credential error responses.

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_health.py` | Modify | Add tests for `CredentialError` cause in each probe (written first — Red) |
| `src/cairn_mcp/tools/health.py` | Modify | Import `CredentialError`; split each probe's except into `CredentialError` then `Exception` |

## Testing Approach

**TDD cycle:** update `test_tools_health.py` first (Red) → implement changes in `health.py` (Green).

**`tests/unit/test_tools_health.py` — new tests (one per probe):**
- `test_s3_probe_credential_error_returns_cause` — configure `FakeS3Client` to raise
  `CredentialError`; assert S3 probe result has `"cause": "credential_error"`.
- `test_vectors_probe_credential_error_returns_cause` — configure `FakeVectorsClient` to raise
  `CredentialError`; assert vectors probe result has `"cause": "credential_error"`.
- `test_bedrock_probe_credential_error_returns_cause` — configure `FakeBedrockClient` to raise
  `CredentialError`; assert bedrock probe result has `"cause": "credential_error"`.
- `test_generic_error_has_no_cause_field` — configure any probe to raise `RuntimeError`; assert
  result has no `"cause"` key.
- `test_credential_error_in_one_probe_does_not_skip_others` — S3 raises `CredentialError`,
  others succeed; assert other probes still return `"status": "ok"`.

## Open Questions

*(none — all behaviour is defined)*
