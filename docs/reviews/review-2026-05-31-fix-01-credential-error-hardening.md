---
type: code_review
title: Review Fix 01 — Credential Error Hardening
description: Four gaps in credential error handling leave the server vulnerable to crashes and mis-classified error responses — missing error codes, unhandled NoCredentialsError, unreachable CredentialError branches, and an unguarded list_objects call in reconcile.
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
# Review Fix 01 — Credential Error Hardening

<!-- SCOPE BLOCK — frozen after approval -->

## Problem Statement

Four gaps in credential error handling leave the server vulnerable to crashes and
mis-classified error responses. First, `credentials.py` only recognises 5 error codes —
`ExpiredToken`, `InvalidAccessKeyId`, and `SignatureDoesNotMatch` are missing, so those
errors reach callers as unclassified `ClientError`. Second, `botocore.exceptions.NoCredentialsError`
is not a `ClientError` subclass — no file catches it, so a missing credential crashes
every AWS call with an unhandled exception rather than a structured `CredentialError`.
Third, `delete.py` and `purge.py` use `except (CredentialError, Exception)`, which makes
the `CredentialError` branch unreachable (it IS-A `Exception`), mis-reporting credential
failures as `"partial_delete"`. Fourth, `reconcile.py` has one unguarded `s3.list_objects()`
call with no `CredentialError` catch.

## User Stories

### Story 1 — Missing error codes are classified correctly (P1)

An agent writes an artifact with an expired token. Instead of an unclassified `ClientError`
reaching the MCP caller, the tool returns `{"error": "credential_error", ...}`.

**Acceptance criteria:**
- Given a boto3 call raises `ClientError` with code `ExpiredToken`, when the client method
  handles it, then `CredentialError` is raised.
- Given a boto3 call raises `ClientError` with code `InvalidAccessKeyId`, when the client
  method handles it, then `CredentialError` is raised.
- Given a boto3 call raises `ClientError` with code `SignatureDoesNotMatch`, when the
  client method handles it, then `CredentialError` is raised.

### Story 2 — Missing credentials raise CredentialError (P1)

The server starts with no credentials configured. Every AWS call raises
`botocore.exceptions.NoCredentialsError`.

**Acceptance criteria:**
- Given no credentials are configured, when any client method makes a boto3 call and
  `NoCredentialsError` is raised, then `CredentialError` is raised with a clear message.

### Story 3 — delete_artifact and purge_archived report credential_error correctly (P1)

**Acceptance criteria:**
- Given `delete_artifact` encounters a `CredentialError` during S3 deletion, when the
  tool returns, then the response contains `{"error": "credential_error", ...}`.
- Given `purge_archived` encounters a `CredentialError` during S3 deletion, when the
  tool returns, then the response contains `{"error": "credential_error", ...}`.

### Story 4 — reconcile_index guards list_objects (P1)

**Acceptance criteria:**
- Given `reconcile_index` calls `s3.list_objects()` and a `CredentialError` is raised,
  when the tool returns, then the response contains `{"error": "credential_error", ...}`.

## Requirements

- WHEN a boto3 call raises `botocore.exceptions.NoCredentialsError` THE SYSTEM SHALL
  catch it and raise `CredentialError` with a descriptive message.
- WHEN a boto3 call raises `ClientError` with code `ExpiredToken`, `InvalidAccessKeyId`,
  or `SignatureDoesNotMatch` THE SYSTEM SHALL classify it as a `CredentialError`.
- WHEN `delete_artifact` encounters a `CredentialError` during S3 deletion THE SYSTEM
  SHALL return `{"error": "credential_error", ...}` (not `"partial_delete"`).
- WHEN `purge_archived` encounters a `CredentialError` during S3 deletion THE SYSTEM
  SHALL return `{"error": "credential_error", ...}` (not `"partial_delete"`).
- WHEN `reconcile_index` encounters a `CredentialError` from `s3.list_objects()` THE
  SYSTEM SHALL return `{"error": "credential_error", ...}`.

## Boundaries

**Always:**
- `CredentialError` must be raised from the client layer, never directly from the tool
  layer; tools handle it by returning structured error dicts.
- Each `except (CredentialError, Exception)` block must be split into two separate
  `except` clauses — `CredentialError` first, then `Exception` — so both are reachable.
- `NoCredentialsError` handling must be added at every public entry point in `s3.py`,
  `vectors.py`, and `bedrock.py` that makes a boto3 call.

**Ask First:**
- Nothing — all required changes are defined.

**Never:**
- Change the `CredentialError` exception class definition.
- Change the `is_credential_error` function signature.
- Add credential handling inside tool `_inner` functions beyond the existing `try/except
  CredentialError` pattern already present in well-formed tools.

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/clients/test_fake_s3.py` | Modify | Add tests: `NoCredentialsError` → `CredentialError`; new error codes |
| `tests/unit/clients/test_fake_vectors.py` | Modify | Add tests: `NoCredentialsError` → `CredentialError` |
| `tests/unit/clients/test_fake_bedrock.py` | Modify | Add tests: `NoCredentialsError` → `CredentialError` |
| `tests/unit/test_tools_delete.py` | Modify | Add test: `CredentialError` from S3 → `"credential_error"` response |
| `tests/unit/test_tools_purge.py` | Modify | Add test: `CredentialError` from S3 → `"credential_error"` response |
| `tests/unit/test_tools_reconcile.py` | Modify | Add test: `CredentialError` from `list_objects` → `"credential_error"` response |
| `src/arkeology/clients/credentials.py` | Modify | Add `ExpiredToken`, `InvalidAccessKeyId`, `SignatureDoesNotMatch` to recognised codes |
| `src/arkeology/clients/s3.py` | Modify | Catch `NoCredentialsError` at each public entry point; raise `CredentialError` |
| `src/arkeology/clients/vectors.py` | Modify | Catch `NoCredentialsError` at each public entry point; raise `CredentialError` |
| `src/arkeology/clients/bedrock.py` | Modify | Catch `NoCredentialsError` at each public entry point; raise `CredentialError` |
| `src/arkeology/tools/delete.py` | Modify | Split `except (CredentialError, Exception)` at line 156 into two clauses |
| `src/arkeology/tools/purge.py` | Modify | Split `except (CredentialError, Exception)` at line 169 into two clauses |
| `src/arkeology/tools/reconcile.py` | Modify | Wrap `s3.list_objects()` at line 272 in `try/except CredentialError` |

## Testing Approach

**TDD cycle:** add failing tests first (Red) → implement fixes (Green) → all tests pass.

**`tests/unit/clients/test_fake_s3.py` — new cases:**
- Fake configured to raise `NoCredentialsError` → client raises `CredentialError`.
- Fake configured to raise `ClientError(code="ExpiredToken")` → `CredentialError`.
- Fake configured to raise `ClientError(code="InvalidAccessKeyId")` → `CredentialError`.
- Fake configured to raise `ClientError(code="SignatureDoesNotMatch")` → `CredentialError`.

**`tests/unit/clients/test_fake_vectors.py` — new cases:**
- Same `NoCredentialsError` → `CredentialError` test for vectors client entry points.

**`tests/unit/clients/test_fake_bedrock.py` — new cases:**
- Same `NoCredentialsError` → `CredentialError` test for bedrock client entry points.

**`tests/unit/test_tools_delete.py` — new case:**
- Fake S3 raises `CredentialError` on delete → response is
  `{"error": "credential_error", ...}`, not `"partial_delete"`.

**`tests/unit/test_tools_purge.py` — new case:**
- Fake S3 raises `CredentialError` on delete → response is
  `{"error": "credential_error", ...}`, not `"partial_delete"`.

**`tests/unit/test_tools_reconcile.py` — new case:**
- Fake S3 raises `CredentialError` on `list_objects` → response is
  `{"error": "credential_error", ...}`.

## Open Questions

*(none — all behaviour is defined)*
