---
type: feature-spec
feature: p3-t12-delete-artifact
created: 2026-05-30
status: ready
phase: 3
task: 12
---

# T12 — Delete Artifact Tool

<!-- SCOPE BLOCK — frozen after approval -->

## Problem Statement

Archive hides an artifact from search and list but the content remains in S3 and is still
reachable by identifier. For stale or sensitive artifacts — a three-year-old bug report, a
superseded spec, a hidden artifact — permanent removal is the correct remedy. The delete
tool hard-deletes a single artifact (S3 object + all section vectors) from the deployment's
own scope. It requires explicit confirmation to prevent accidental one-liner deletion.
Deletion ordering (vectors first, then S3) ensures the worst-case partial failure leaves an
orphaned S3 object that can be recovered by reconciliation — not orphaned vectors that make
the artifact appear in search results but fail on read.

This task also updates all existing T7–T9 integration tests to use `delete_artifact` in
teardown so every artifact written during integration tests is cleaned up automatically.

Tier 2 immutability is content-only (decisions doc Q1): content cannot be edited, but tier 2
artifacts may be deleted or archived as lifecycle operations.

## User Stories

### Story 1 — Agent hard-deletes an artifact from own scope (P1)

A developer agent removes a three-year-old bug report that is creating confusion.

**Acceptance criteria:**
- Given an active artifact in own scope, when `delete_artifact` is called with its
  `artifact_id` and `confirm=True`, then the artifact is not retrievable by ID, not
  returned by search, and not returned by list.
- Given `confirm` is `False` or absent, when `delete_artifact` is called, then a structured
  error is returned and no deletion occurs.

### Story 2 — Synthesis warning does not block deletion (P1)

An artifact referenced by an active synthesis is still deletable; the caller receives a
warning listing the affected synthesis identifiers but the deletion proceeds.

**Acceptance criteria:**
- Given an artifact that is listed as a `source_artifact` in one or more active synthesis
  artifacts, when `delete_artifact` is called with `confirm=True`, then the artifact is
  deleted AND the response includes a `warnings` field listing the affected synthesis
  `artifact_id`s.
- Given an artifact not referenced by any synthesis, when `delete_artifact` returns, then
  the `warnings` field is absent or empty.

### Story 3 — Foreign-scope artifacts cannot be deleted (P1)

**Acceptance criteria:**
- Given an artifact whose prefix matches a READ_PREFIX but not the WRITE_PREFIX, when
  `delete_artifact` is called, then a structured access-denied error is returned and nothing
  is deleted.

### Story 4 — Partial failure is recoverable (P1)

If vectors are deleted but the S3 delete call fails, reconciliation can recover the orphaned
S3 object. The caller receives a structured partial-failure error.

**Acceptance criteria:**
- Given a simulated S3 delete failure after vectors are successfully deleted, when
  `delete_artifact` returns, then a structured partial-failure error is returned including
  the `artifact_id`; the S3 object still exists and is recoverable via reconciliation.
- Given a simulated vector delete failure, when `delete_artifact` returns, then a structured
  error is returned and the artifact remains fully intact (vectors and S3 both present).

### Story 5 — Credential errors return structured responses (P1)

**Acceptance criteria:**
- Given a credential failure during any AWS call, when `delete_artifact` returns, then a
  structured error is returned — not a raw exception.

## Requirements

- WHEN `delete_artifact` is called without `confirm=True` THE SYSTEM SHALL return a
  structured error and make no AWS write calls.
- WHEN `delete_artifact` is called THE SYSTEM SHALL determine scope using
  `artifact_id.startswith(scope + "/")` against `settings.write_prefix`; if not in own
  scope THE SYSTEM SHALL return a structured access-denied error.
- WHEN the artifact is in own scope THE SYSTEM SHALL check for synthesis references by
  querying the vector index for active synthesis artifacts whose `source_artifacts` metadata
  contains the `artifact_id`.
- WHEN synthesis references are found THE SYSTEM SHALL include their identifiers in a
  `warnings` list in the response but proceed with deletion.
- WHEN deletion proceeds THE SYSTEM SHALL first find all vector keys for the artifact via
  `list_vectors_by_metadata({"artifact_id": {"$eq": s3_key}})`, then call
  `delete_vectors(keys)` before touching S3.
- WHEN `delete_vectors` fails THE SYSTEM SHALL return a structured error; the S3 object
  must remain untouched (artifact fully intact).
- WHEN `delete_vectors` succeeds THE SYSTEM SHALL call `s3.delete_object(s3_key)`; if S3
  delete fails THE SYSTEM SHALL return a structured partial-failure error including the
  `artifact_id` (the S3 orphan is recoverable via reconciliation FR-17).
- WHEN deletion fully succeeds THE SYSTEM SHALL return:
  `{"artifact_id": str, "deleted": True}` (plus optional `warnings` list).
- WHEN the `artifact_id` does not exist in S3 THE SYSTEM SHALL return a structured
  not-found error.
- WHEN a CredentialError is raised THE SYSTEM SHALL return a structured error — never a
  raw exception.

## Boundaries

**Always:**
- `confirm=True` is a hard gate — no deletion without it.
- Deletion ordering is vectors-first, S3-second (see decisions doc Q4).
- Synthesis reference check is warn-and-proceed (decisions doc Q3).
- Own-scope gate mirrors archive — `startswith(settings.write_prefix + "/")`.
- Tier 2 artifacts are deletable (immutability is content-only — decisions doc Q1).
- The tool receives `settings`, `s3`, `vectors`, and `bedrock` (unused) as injected
  dependencies.

**Ask First:**
- Nothing — all constraints are frozen from the decisions doc.

**Never:**
- Do not delete S3 before deleting vectors.
- Do not block on synthesis references — warn and proceed.
- Do not skip the `confirm=True` check.
- Do not silently swallow a partial failure — return a structured partial-failure error with
  the `artifact_id` so reconciliation can recover the orphan.

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_delete.py` | Create | Written first (Red) |
| `src/cairn_mcp/tools/delete.py` | Create | Written after unit tests (Green) |
| `tests/integration/test_tools_delete.py` | Create | Written before integration wiring |
| `src/cairn_mcp/server.py` | Modify | Register `delete_artifact` tool on `_app` |
| `tests/integration/test_tools_write.py` | Modify | Update teardown to call `delete_artifact` |
| `tests/integration/test_tools_search.py` | Modify | Update teardown to call `delete_artifact` |
| `tests/integration/test_tools_read.py` | Modify | Update teardown to call `delete_artifact` |

## Testing Approach

**TDD cycle A (unit):** write `test_tools_delete.py` first → fail → implement
`tools/delete.py` → unit tests pass.

**TDD cycle B (integration):** write integration tests first → fail → wire tool → pass.

**TDD cycle C (teardown update):** update T7–T9 integration tests to use `delete_artifact`
in teardown — these must pass with the new teardown before the task is done.

---

**`test_tools_delete.py` — unit tests (FakeS3Client + FakeVectorsClient):**

Seed fake S3 with own-scope artifacts (tier 2 and tier 3), foreign-scope artifacts, and
active synthesis artifacts with `source_artifacts` referencing some of the own-scope
artifacts. Seed fake vectors with section vectors for each S3 artifact.

Confirmation gate:
- `confirm=False` → structured error, no AWS writes.
- `confirm` absent → structured error, no AWS writes.

Happy path:
- `confirm=True`, own-scope active artifact → deleted; `{"artifact_id": ..., "deleted": True}`.
- Artifact absent from fake S3 and fake vectors after deletion.
- Tier 2 artifact → deletable (same as tier 3).
- Artifact not referenced by any synthesis → no `warnings` field (or empty list).

Synthesis warning:
- Artifact referenced by one active synthesis → response includes `warnings` with that
  synthesis `artifact_id`; artifact is still deleted.
- Artifact referenced by two syntheses → both identifiers in `warnings`.

Cross-scope gate:
- Foreign-scope artifact → access-denied error; no AWS writes.
- Artifact_id matching no scope → access-denied error.

Not found:
- Own-scope `artifact_id` absent from fake S3 → not-found error; no vector deletes.

Ordering and partial failure:
- Simulate `delete_vectors` raising a non-credential exception → structured error; S3
  object still present in fake S3.
- Simulate `delete_object` failing after `delete_vectors` succeeds → structured
  partial-failure error with `artifact_id`; vectors absent from fake (simulating orphan
  state); S3 object still present.

Credential failures:
- `head_object` raises `CredentialError` → structured error.
- `list_vectors_by_metadata` raises `CredentialError` → structured error; no deletes.
- `delete_vectors` raises `CredentialError` → structured error; S3 intact.
- `delete_object` raises `CredentialError` after vectors deleted → structured
  partial-failure error with `artifact_id`.

**`tests/integration/test_tools_delete.py` — integration tests (`@pytest.mark.integration`):**

- Write an artifact; delete it with `confirm=True` → no longer retrievable by ID; absent
  from list results.
- Delete without `confirm=True` → error; artifact still retrievable.
- Delete foreign-scope artifact → access-denied error.
- Delete non-existent artifact → not-found error.
- Write a synthesis with `source_artifacts`; delete the source → response includes `warnings`.

**Teardown update (T7–T9 integration tests):**

- All existing integration test fixtures that write artifacts must be updated to call
  `delete_artifact(artifact_id=..., confirm=True)` in their teardown/finally block.
- Each updated test file must pass (all existing assertions still green) after the teardown
  change.

## Open Questions

*(none — all decisions resolved in brainstorming-delete-artifact-2026-05-30.md)*
