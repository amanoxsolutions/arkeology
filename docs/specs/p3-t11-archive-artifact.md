---
type: feature-spec
feature: p3-t11-archive-artifact
created: 2026-05-30
status: ready
phase: 3
task: 11
---

# T11 — Archive Artifact Tool

<!-- SCOPE BLOCK — frozen after approval -->

## Problem Statement

When an artifact becomes stale or superseded it should stop appearing in search and list
results — but hard deletion may be premature. Archiving provides a reversible "hide from
results" lifecycle state: the artifact's status is set to `"inactive"` so it is excluded
from the default active filter applied by search and list, while the content and identifier
remain in S3 and remain reachable by direct `read_artifact` if the caller explicitly targets
it. Archiving is scoped to the deployment's own prefix — an agent cannot archive an artifact
it does not own. Tier 2 content immutability is preserved: archiving changes only the
`status` metadata, never the content.

## User Stories

### Story 1 — Agent archives a stale artifact in own scope (P1)

After a sprint ends, a developer agent archives last sprint's session summary so it no
longer clutters search results.

**Acceptance criteria:**
- Given an active artifact in own scope, when `archive_artifact` is called with its
  `artifact_id`, then the response confirms archival and the artifact is absent from
  subsequent `list_artifacts` calls using the default active filter.
- Given an artifact that is already archived, when `archive_artifact` is called again, then
  the call succeeds idempotently — no error.
- Given an active artifact, after successful archival, when `search_artifacts` is called
  with a matching query, then the archived artifact does not appear in results.

### Story 2 — Foreign-scope artifacts cannot be archived (P1)

A microservices team agent must not be able to archive the platform team's ADRs.

**Acceptance criteria:**
- Given an artifact whose `artifact_id` prefix matches a READ_PREFIX but not the
  `WRITE_PREFIX`, when `archive_artifact` is called, then a structured access-denied error
  is returned and the artifact's status is unchanged.
- Given an `artifact_id` that matches no known scope, when `archive_artifact` is called,
  then a structured access-denied error is returned.

### Story 3 — Non-existent artifact returns a clear error (P1)

**Acceptance criteria:**
- Given an `artifact_id` that does not exist in S3 (own scope), when `archive_artifact` is
  called, then a structured not-found error is returned — not an unhandled exception.

### Story 4 — Credential errors return structured responses (P1)

**Acceptance criteria:**
- Given a credential failure during any AWS call, when `archive_artifact` returns, then a
  structured error is returned — not a raw exception.

## Requirements

- WHEN `archive_artifact` is called THE SYSTEM SHALL determine scope by comparing
  `artifact_id` against `settings.write_prefix` using `startswith(scope + "/")`.
- WHEN the artifact is not in own scope THE SYSTEM SHALL return a structured access-denied
  error without making any AWS write calls.
- WHEN the artifact is in own scope and exists THE SYSTEM SHALL update `status` to
  `"inactive"` in the S3 object metadata and in all corresponding vector metadata entries.
- WHEN updating S3 metadata THE SYSTEM SHALL preserve the artifact's content unchanged;
  only the `status` field in S3 object metadata changes.
- WHEN updating vector metadata THE SYSTEM SHALL find all section vectors via
  `list_vectors_by_metadata({"artifact_id": {"$eq": s3_key}})`, fetch their current data
  and metadata via `get_vectors`, then re-upsert each with updated `status="inactive"`.
- WHEN the S3 key does not exist THE SYSTEM SHALL return a structured not-found error.
- WHEN a CredentialError is raised at any step THE SYSTEM SHALL return a structured error —
  never a raw exception.
- WHEN archiving succeeds THE SYSTEM SHALL return: `{"artifact_id": str, "status": "inactive"}`.

## Boundaries

**Always:**
- Only `status` changes — no other metadata field, no content, is modified.
- The tool operates on own scope only; foreign-scope gate mirrors archive and read.
- Updating S3 object metadata requires reading the current content (`get_object`) and
  writing it back with a new metadata dict (`put_object`) — S3 has no in-place metadata
  patch. The existing S3ClientInterface supports this with `get_object` + `put_object`.
- Updating vector metadata requires fetching the vector data first (`get_vectors`) since
  `put_vector` requires the embedding vector alongside the metadata.
- The tool receives `settings`, `s3`, `vectors`, and `bedrock` (unused) as injected
  dependencies.

**Ask First:**
- Nothing — all constraints are defined.

**Never:**
- Do not modify artifact content during archival.
- Do not skip updating S3 metadata — the authoritative metadata lives in S3 and
  `read_artifact` reads from S3; vector metadata alone being updated is insufficient.
- Do not raise raw exceptions to the caller — all errors must be structured responses.

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_archive.py` | Create | Written first (Red) |
| `src/cairn_mcp/tools/archive.py` | Create | Written after unit tests (Green) |
| `tests/integration/test_tools_archive.py` | Create | Written before integration wiring |
| `src/cairn_mcp/server.py` | Modify | Register `archive_artifact` tool on `_app` |

## Testing Approach

**TDD cycle A (unit):** write `test_tools_archive.py` first → fail → implement
`tools/archive.py` → unit tests pass.

**TDD cycle B (integration):** write integration tests first → fail → wire tool → pass.

---

**`test_tools_archive.py` — unit tests (FakeS3Client + FakeVectorsClient):**

Seed the fake S3 with objects covering: own-scope active artifact (with multiple section
vectors), own-scope already-archived artifact, foreign-scope active artifact.

Happy path:
- Archive an active own-scope artifact → response `{"artifact_id": ..., "status": "inactive"}`.
- S3 object content is unchanged after archival.
- S3 object metadata `status` is `"inactive"` after archival.
- All section vectors for the artifact have `status="inactive"` in their metadata after
  archival.
- Archive an already-archived artifact → same success response (idempotent).

Access control:
- Foreign-scope artifact → structured access-denied error; no S3 or vector writes.
- Artifact_id matching no known scope → structured access-denied error.

Not found:
- Own-scope artifact_id that does not exist in fake S3 → not-found error, no vector calls.

Credential failures:
- `get_object` raises `CredentialError` → structured error; no vector writes.
- `put_object` raises `CredentialError` → structured error; no vector writes (S3 read
  succeeded but write failed — test confirms no partial state in vectors).
- `list_vectors_by_metadata` raises `CredentialError` → structured error.
- `get_vectors` raises `CredentialError` → structured error.
- `put_vector` raises `CredentialError` on first section → structured error.

Fallback (no section vectors found):
- Artifact has a single document-level vector key (no `#` in key) → that vector's metadata
  updated to `status="inactive"`.

**`tests/integration/test_tools_archive.py` — integration tests (`@pytest.mark.integration`):**

Teardown: use `delete_artifact` (T12) to remove all artifacts written during the test.

- Write an artifact; archive it; list with default filter → absent; list with
  `status="inactive"` → present; `read_artifact` by ID still succeeds (content intact).
- Archive a foreign-scope artifact → access-denied error.
- Archive a non-existent artifact → not-found error.

## Open Questions

*(none — all constraints are defined)*
