---
type: feature-spec
feature: p3-t13-purge-archived
status: ready
phase: 3
task: 13
references: []
authored:
  by: "architect"
  date: "2026-05-30"
revised:
  by: ""
  date: ""
---

# T13 — Purge Archived Tool

<!-- SCOPE BLOCK — frozen after approval -->

## Problem Statement

Archive hides inactive artifacts from search and list, but archived content continues to
occupy S3 and vector index space. Over time — months of session summaries, superseded
reviews, old specs — this accumulates. `purge_archived` provides a single-call storage
reclamation operation: it hard-deletes every `status=inactive` artifact in the deployment's
own scope at once. To handle synthesis integrity, any synthesis artifact whose every
`source_artifact` is in the purge set is cascade-deleted and reported. The `confirm=True`
gate prevents accidental bulk erasure.

## User Stories

### Story 1 — Agent purges all archived artifacts in own scope (P1)

After a team archives a batch of stale session summaries over the quarter, they purge in
one call to reclaim storage.

**Acceptance criteria:**
- Given several inactive artifacts in own scope, when `purge_archived` is called with
  `confirm=True`, then all inactive artifacts are removed from S3 and the vector index.
- Given no inactive artifacts in own scope, when `purge_archived` is called, then the
  response reports zero purged — no error.
- Given `confirm` is `False` or absent, when `purge_archived` is called, then a structured
  error is returned and nothing is deleted.

### Story 2 — Synthesis cascade (P1)

A synthesis whose every source artifact is about to be purged is itself cascade-deleted and
reported.

**Acceptance criteria:**
- Given an active synthesis artifact whose `source_artifacts` field lists only artifacts in
  the inactive purge set, when `purge_archived` is called, then the synthesis is also
  deleted and its `artifact_id` appears in the `cascade_deleted` list in the response.
- Given an active synthesis artifact that has at least one `source_artifact` NOT in the
  purge set, when `purge_archived` is called, then the synthesis is NOT cascade-deleted.
- Given no synthesis artifacts in own scope, when `purge_archived` is called, then no
  cascade check is performed and the response returns an empty `cascade_deleted` list.

### Story 3 — Foreign-scope artifacts are never purged (P1)

**Acceptance criteria:**
- Given inactive artifacts in a foreign scope, when `purge_archived` is called, then the
  foreign-scope artifacts are untouched regardless of their status.

### Story 4 — Credential errors return structured responses (P1)

**Acceptance criteria:**
- Given a credential failure during any AWS call, when `purge_archived` returns, then a
  structured error is returned — not a raw exception.

## Requirements

- WHEN `purge_archived` is called without `confirm=True` THE SYSTEM SHALL return a
  structured error and make no AWS write calls.
- WHEN `purge_archived` is called with `confirm=True` THE SYSTEM SHALL list all vectors
  in own scope with `status="inactive"` using `list_vectors_by_metadata`, deduplicate by
  `artifact_id` to obtain the purge set.
- WHEN the purge set is empty THE SYSTEM SHALL return
  `{"purged_count": 0, "purged_ids": [], "cascade_deleted": []}` — no error.
- WHEN the purge set is non-empty THE SYSTEM SHALL check for cascade candidates: active
  synthesis artifacts in own scope whose entire `source_artifacts` list is contained in the
  purge set; add those synthesis `artifact_id`s to the deletion set and report them
  separately.
- WHEN executing deletion THE SYSTEM SHALL, for each artifact in the combined deletion set
  (inactive + cascade syntheses), find all vector keys via `list_vectors_by_metadata`,
  delete vectors first, then delete the S3 object — mirroring the ordering in T12.
- WHEN all deletions succeed THE SYSTEM SHALL return:
  `{"purged_count": int, "purged_ids": list[str], "cascade_deleted": list[str]}`.
- WHEN a CredentialError is raised THE SYSTEM SHALL return a structured error — never a
  raw exception.
- THE SYSTEM SHALL never touch artifacts outside `settings.write_prefix` regardless of
  their status.

## Boundaries

**Always:**
- `confirm=True` is a hard gate.
- Own-scope gate: only artifacts whose `artifact_id` starts with
  `settings.write_prefix + "/"` are eligible for purging.
- Cascade logic applies only to synthesis artifacts whose ALL `source_artifacts` are in the
  purge set (decisions doc Q3).
- Deletion ordering per artifact is vectors-first, S3-second (same as T12).
- The tool receives `settings`, `s3`, `vectors`, and `bedrock` (unused) as injected
  dependencies.

**Ask First:**
- Nothing — all constraints are defined.

**Never:**
- Do not purge artifacts from foreign scopes.
- Do not cascade-delete a synthesis that still has at least one source artifact outside the
  purge set.
- Do not skip the `confirm=True` gate.
- Do not return an error for an empty purge set — an empty set is a valid no-op.

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_purge.py` | Create | Written first (Red) |
| `src/cairn_mcp/tools/purge.py` | Create | Written after unit tests (Green) |
| `tests/integration/test_tools_purge.py` | Create | Written before integration wiring |
| `src/cairn_mcp/server.py` | Modify | Register `purge_archived` tool on `_app` |

## Testing Approach

**TDD cycle A (unit):** write `test_tools_purge.py` first → fail → implement `tools/purge.py`
→ unit tests pass.

**TDD cycle B (integration):** write integration tests first → fail → wire tool → pass.

---

**`test_tools_purge.py` — unit tests (FakeS3Client + FakeVectorsClient):**

Seed: own-scope inactive artifacts (some tier 2, some tier 3), own-scope active artifacts,
a synthesis artifact whose all `source_artifacts` are in the inactive set, a synthesis
artifact with at least one source outside the inactive set, a foreign-scope inactive
artifact.

Confirmation gate:
- `confirm=False` → structured error, no AWS writes.
- `confirm` absent → structured error, no AWS writes.

Empty purge set:
- No inactive artifacts in own scope → `{"purged_count": 0, "purged_ids": [], "cascade_deleted": []}`.

Happy path:
- Multiple inactive artifacts → all absent from S3 and vectors after purge; `purged_ids`
  lists all deleted `artifact_id`s; `purged_count` matches list length.
- Active artifacts in own scope → untouched.
- Foreign-scope inactive artifact → untouched.

Cascade:
- Synthesis whose all sources are in purge set → cascade-deleted; its `artifact_id` in
  `cascade_deleted` field; absent from fake S3 and vectors after purge.
- Synthesis with at least one source outside purge set → NOT in `cascade_deleted`; still
  present in fake S3 and vectors after purge.
- No synthesis artifacts → `cascade_deleted` is empty list; no error.

Deletion ordering (per artifact):
- Simulate `delete_object` failure on one artifact after vectors deleted → structured
  partial-failure error with affected `artifact_id`; successfully deleted artifacts are
  still gone.

Credential failures:
- `list_vectors_by_metadata` raises `CredentialError` → structured error; no deletes.
- `delete_vectors` raises `CredentialError` → structured error.
- `delete_object` raises `CredentialError` → structured partial-failure error with
  `artifact_id`.

**`tests/integration/test_tools_purge.py` — integration tests (`@pytest.mark.integration`):**

Teardown: any artifacts NOT purged (e.g. active artifacts, partially-failed cases) must be
cleaned up via `delete_artifact`.

- Write and archive two artifacts; purge → both absent from list; `purged_count=2`.
- Write an active artifact; purge → active artifact untouched; `purged_count=0`.
- Write a synthesis with sources all archived; purge → synthesis cascade-deleted and
  reported in `cascade_deleted`.
- Purge with no inactive artifacts → `purged_count=0`, no error.

## Open Questions

*(none — all constraints are defined)*
