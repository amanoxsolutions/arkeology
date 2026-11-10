---
type: Spec
id: p3-t11-archive-artifact
title: T11 — Archive Artifact Tool
description: Feature spec for the archive_artifact MCP tool that sets artifact status to inactive to hide it from search and list results while preserving content in S3.
tags: []
status: stable
okf_version: "0.2"
generated:
  by: "axians-architect/unknown"
  at: 2026-05-30T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-09T12:01:40Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
---

# T11 — Archive Artifact Tool

## TL;DR

`archive_artifact` lets an agent hide a stale or superseded artifact from search and list results
without deleting it, by setting its `status` to `"inactive"` in S3 object metadata and in every
corresponding vector. It is a reversible lifecycle state limited to the deployment's own scope, and it
never touches the artifact's content.

## 1. Problem Statement

When an artifact becomes stale or superseded it should stop appearing in search and list results — but
hard deletion may be premature; for example, after a sprint ends, a developer agent archives last
sprint's session summary so it no longer clutters search results. Archiving provides a reversible
"hide from results" lifecycle state: the artifact's status is set to `"inactive"` so it is excluded
from the default active filter applied by search and list, while the content and identifier remain in
S3 and remain reachable by direct `read_artifact` if the caller explicitly targets it. Archiving is
scoped to the deployment's own prefix — an agent cannot archive an artifact it does not own; a
microservices team agent must not be able to archive the platform team's ADRs. Tier 2 content
immutability is preserved: archiving changes only the `status` metadata, never the content.

All four stories this spec covers are priority P1.

## 2. Rules — Scope

### R1 — Only own-scope artifacts can be archived

When `archive_artifact` is called, the system determines scope by comparing `artifact_id` against
`settings.write_prefix` using `startswith(scope + "/")`. When the artifact is not in own scope, the
system returns a structured access-denied error without making any AWS write calls, and the artifact's
status is unchanged. The tool operates on own scope only; foreign-scope gate mirrors archive and read.

**Example**

- Given an artifact whose `artifact_id` prefix matches a READ_PREFIX but not the `WRITE_PREFIX`, when
  `archive_artifact` is called, then a structured access-denied error is returned and the artifact's
  status is unchanged.
- Given an `artifact_id` that matches no known scope, when `archive_artifact` is called, then a
  structured access-denied error is returned.

Source: none

## 3. Rules — Archival

### R2 — Archiving sets `status` to `"inactive"` and changes nothing else

When the artifact is in own scope and exists, the system updates `status` to `"inactive"` in the S3
object metadata and in all corresponding vector metadata entries. Only `status` changes — no other
metadata field, no content, is modified.

**Example**

- Given an active artifact in own scope, when `archive_artifact` is called with its `artifact_id`,
  then the response confirms archival and the artifact is absent from subsequent `list_artifacts`
  calls using the default active filter.
- Given an active artifact, after successful archival, when `search_artifacts` is called with a
  matching query, then the archived artifact does not appear in results.

Source: none

### R3 — The S3 metadata update re-writes the content unchanged

When updating S3 metadata, the system preserves the artifact's content unchanged; only the `status`
field in S3 object metadata changes. Updating S3 object metadata requires reading the current content
(`get_object`) and writing it back with a new metadata dict (`put_object`) — S3 has no in-place
metadata patch. The existing S3ClientInterface supports this with `get_object` + `put_object`. The S3
metadata update is never skipped: the authoritative metadata lives in S3 and `read_artifact` reads
from S3; vector metadata alone being updated is insufficient.

Source: none

### R4 — The status-flip re-PUT is guarded by an ETag compare-and-swap

The status-flip re-PUT (and, once `commit_refs`/`references` durable-link storage lands — see
`p12-t47` — the annotation re-apply that must accompany it) is guarded by an ETag compare-and-swap:
the object's ETag is captured before the re-PUT and the write is conditional (`IfMatch`); a detected
concurrent change triggers a bounded retry (~3 attempts: re-read status and link fields, re-flip)
before returning a structured `conflict` error, rather than silently racing another concurrent writer
of the same artifact. See `docs/specs/p2-t7-write-artifact.md`'s equivalent forward-pointer note for
the same mechanism on the write path.

Rationale: ADR-011 decision 6.

Source: ADR-011 decision 6

### R5 — Every section vector is re-upserted with `status="inactive"`

When updating vector metadata, the system finds all section vectors via
`list_vectors_by_metadata({"artifact_id": {"$eq": s3_key}})`, fetches their current data and metadata
via `get_vectors`, then re-upserts each with updated `status="inactive"`. The vector data is fetched
first (`get_vectors`) since `put_vector` requires the embedding vector alongside the metadata.

Source: none

### R6 — Archiving an already-archived artifact succeeds

Given an artifact that is already archived, when `archive_artifact` is called again, the call succeeds
idempotently — no error.

Source: none

## 4. Rules — Response and errors

### R7 — A successful archival returns the id and the new status

When archiving succeeds, the system returns `{"artifact_id": str, "status": "inactive"}`.

Source: none

### R8 — A non-existent own-scope artifact returns a not-found error

When the S3 key does not exist, the system returns a structured not-found error — not an unhandled
exception.

**Example**

- Given an `artifact_id` that does not exist in S3 (own scope), when `archive_artifact` is called, then
  a structured not-found error is returned.

Source: none

### R9 — Credential errors at any step return a structured error

When a `CredentialError` is raised at any step — a credential failure during any AWS call — the system
returns a structured error, never a raw exception. All errors are structured responses.

Source: none

## 5. Boundaries

**Always:**
- The tool receives `settings`, `s3`, `vectors`, and `bedrock` (unused) as injected dependencies.

**Ask First:**
- Nothing — all constraints are defined.

**Never:**
- Do not modify artifact content during archival.
- Do not skip updating S3 metadata — the authoritative metadata lives in S3 and `read_artifact` reads
  from S3; vector metadata alone being updated is insufficient.
- Do not raise raw exceptions to the caller — all errors must be structured responses.

## 6. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_archive.py` | Create | Written first (Red) |
| `src/arkeology/tools/archive.py` | Create | Written after unit tests (Green) |
| `tests/integration/test_tools_archive.py` | Create | Written before integration wiring |
| `src/arkeology/server.py` | Modify | Register `archive_artifact` tool on `_app` |

### Contracts

None.

### Testing Approach

**TDD cycle A (unit):** write `test_tools_archive.py` first → fail → implement `tools/archive.py` →
unit tests pass.

**TDD cycle B (integration):** write integration tests first → fail → wire tool → pass.

**`test_tools_archive.py` — unit tests (FakeS3Client + FakeVectorsClient):**

Seed the fake S3 with objects covering: own-scope active artifact (with multiple section vectors),
own-scope already-archived artifact, foreign-scope active artifact.

Happy path:
- Archive an active own-scope artifact → response `{"artifact_id": ..., "status": "inactive"}`.
- S3 object content is unchanged after archival.
- S3 object metadata `status` is `"inactive"` after archival.
- All section vectors for the artifact have `status="inactive"` in their metadata after archival.
- Archive an already-archived artifact → same success response (idempotent).

Access control:
- Foreign-scope artifact → structured access-denied error; no S3 or vector writes.
- Artifact_id matching no known scope → structured access-denied error.

Not found:
- Own-scope artifact_id that does not exist in fake S3 → not-found error, no vector calls.

Credential failures:
- `get_object` raises `CredentialError` → structured error; no vector writes.
- `put_object` raises `CredentialError` → structured error; no vector writes (S3 read succeeded but
  write failed — test confirms no partial state in vectors).
- `list_vectors_by_metadata` raises `CredentialError` → structured error.
- `get_vectors` raises `CredentialError` → structured error.
- `put_vector` raises `CredentialError` on first section → structured error.

Fallback (no section vectors found):
- Artifact has a single document-level vector key (no `#` in key) → that vector's metadata updated to
  `status="inactive"`.

**`tests/integration/test_tools_archive.py` — integration tests (`@pytest.mark.integration`):**

Teardown: use `delete_artifact` (T12) to remove all artifacts written during the test.

- Write an artifact; archive it; list with default filter → absent; list with `status="inactive"` →
  present; `read_artifact` by ID still succeeds (content intact).
- Archive a foreign-scope artifact → access-denied error.
- Archive a non-existent artifact → not-found error.
