---
type: Spec
id: p3-t13-purge-archived
title: T13 — Purge Archived Tool
description: Feature spec for the purge_archived MCP tool that bulk hard-deletes all inactive artifacts in own scope with synthesis cascade handling and a confirm gate.
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

# T13 — Purge Archived Tool

## TL;DR

`purge_archived` reclaims storage in a single call by hard-deleting every `status=inactive` artifact in
the deployment's own scope, cascade-deleting any synthesis whose every source is in the purge set. It
is gated by `confirm=True`, is best-effort across artifacts, and always reports what was actually
deleted and what failed, so a caller has an accurate record of irreversible deletions.

## 1. Problem Statement

Archive hides inactive artifacts from search and list, but archived content continues to occupy S3 and
vector index space. Over time — months of session summaries, superseded reviews, old specs — this
accumulates; for example, after a team archives a batch of stale session summaries over the quarter,
they purge in one call to reclaim storage. `purge_archived` provides a single-call storage reclamation
operation: it hard-deletes every `status=inactive` artifact in the deployment's own scope at once. To
handle synthesis integrity, any synthesis artifact whose every `source_artifact` is in the purge set is
cascade-deleted and reported. The `confirm=True` gate prevents accidental bulk erasure. Per-artifact
deletion ordering and recoverable-orphan semantics are inherited from T12 (vectors-first, S3-second;
an S3 delete that fails after vectors are gone leaves a recoverable orphan, FR-17).

All five stories this spec covers are priority P1.

## 2. Rules — Gates

### R1 — `confirm=True` is a hard gate

When `purge_archived` is called without `confirm=True` — `confirm` is `False` or absent — the system
returns a structured error, makes no AWS write calls, and nothing is deleted.

Source: none

### R2 — Only own-scope artifacts are ever purged

Only artifacts whose `artifact_id` starts with `settings.write_prefix + "/"` are eligible for purging.
The system never touches artifacts outside `settings.write_prefix`, regardless of their status.

**Example**

- Given inactive artifacts in a foreign scope, when `purge_archived` is called, then the foreign-scope
  artifacts are untouched regardless of their status.

Source: none

## 3. Rules — Discovery

### R3 — The purge set is every own-scope inactive artifact

When `purge_archived` is called with `confirm=True`, the system lists all vectors in own scope with
`status="inactive"` using `list_vectors_by_metadata`, and deduplicates by `artifact_id` to obtain the
purge set.

**Example**

- Given several inactive artifacts in own scope, when `purge_archived` is called with `confirm=True`,
  then all inactive artifacts are removed from S3 and the vector index.

Source: none

### R4 — An empty purge set is a valid no-op

When the purge set is empty, the system returns
`{"purged_count": 0, "purged_ids": [], "cascade_deleted": [], "failed": []}` — no error.

**Example**

- Given no inactive artifacts in own scope, when `purge_archived` is called, then the response reports
  zero purged — no error.

Source: none

### R5 — A synthesis is cascade-deleted only when all its sources are in the purge set

When the purge set is non-empty, the system checks for cascade candidates: active synthesis artifacts
in own scope whose entire `source_artifacts` list is contained in the purge set. It adds those
synthesis `artifact_id`s to the deletion set and reports them separately. Cascade logic applies only to
synthesis artifacts whose ALL `source_artifacts` are in the purge set.

**Example**

- Given an active synthesis artifact whose `source_artifacts` field lists only artifacts in the
  inactive purge set, when `purge_archived` is called, then the synthesis is also deleted and its
  `artifact_id` appears in the `cascade_deleted` list in the response.
- Given an active synthesis artifact that has at least one `source_artifact` NOT in the purge set, when
  `purge_archived` is called, then the synthesis is NOT cascade-deleted.
- Given no synthesis artifacts in own scope, when `purge_archived` is called, then no cascade check is
  performed and the response returns an empty `cascade_deleted` list.

Source: decisions doc Q3

## 4. Rules — Deletion

### R6 — Each artifact is deleted vectors-first, S3-second

When executing deletion, the system, for each artifact in the combined deletion set (inactive + cascade
syntheses), finds all vector keys via `list_vectors_by_metadata`, deletes vectors first, then deletes
the S3 object — mirroring the per-artifact ordering in T12.

Source: none

### R7 — The deletion phase is best-effort for non-credential failures

The deletion phase is **best-effort**: a non-credential failure deleting one artifact (vector delete or
S3 delete) does not abort the purge; the system records the failure and continues with the remaining
artifacts. When an individual artifact deletion fails with a non-credential error, the system records
an entry in a `failed` list containing the `artifact_id`, the error code, and a message. An artifact
recorded in `failed` does not appear in `purged_ids` or `cascade_deleted`.

Rationale: because purge is a *bulk* hard-delete, partial failure must be handled differently from
the single-artifact `delete_artifact` (T12) — a purge of many artifacts must not lose work or hide
irreversible deletions when one artifact fails to delete.

**Example**

- Given a purge set of several artifacts where one artifact's vector delete fails with a
  non-credential error, when `purge_archived` runs with `confirm=True`, then the remaining artifacts are
  still purged, the failed artifact appears in the `failed` list with its `artifact_id` and error, and
  that artifact remains fully intact (vectors and S3 present).
- Given one artifact's S3 delete fails (non-credential) after its vectors were deleted, when
  `purge_archived` returns, then that artifact appears in the `failed` list (a recoverable S3 orphan per
  T12/FR-17), is excluded from `purged_ids`, and the other artifacts are still purged.
- Given a cascade synthesis fails to delete (non-credential), when `purge_archived` returns, then it
  appears in `failed` and not in `cascade_deleted`, and other deletions still proceed.

Source: none

### R8 — A failed artifact is left intact or as a recoverable orphan

When a vector delete fails for an artifact, the system leaves that artifact fully intact (vectors and
S3 both present) before continuing. When an S3 delete fails after the artifact's vectors were deleted,
the system leaves a recoverable S3 orphan (per T12 / FR-17) before continuing.

Source: FR-17 (the S3-orphan clause)

## 5. Rules — Credential errors

### R9 — A credential failure during deletion aborts the remaining deletions

When a `CredentialError` is raised during the deletion phase, the system aborts the remaining deletions
(credential failures are systemic), and returns a structured credential error together with the
artifacts purged so far in `purged_ids` — never a raw exception.

**Example**

- Given a credential failure during the deletion phase, when `purge_archived` returns, then the
  remaining deletions are aborted, a structured credential error is returned, and the artifacts purged
  so far are reported in `purged_ids`.

Source: none

### R10 — A credential failure during discovery deletes nothing

When a `CredentialError` is raised during the discovery phase (listing inactive vectors, fetching their
metadata, or the cascade check), the system returns a structured error and performs no deletions —
never a raw exception.

Source: none

## 6. Rules — Response

### R11 — The response reports what was actually deleted

When the purge completes, the system returns
`{"purged_count": int, "purged_ids": list[str], "cascade_deleted": list[str], "failed": list[dict]}`
where `purged_ids` / `purged_count` reflect the artifacts **actually fully deleted** (S3 object
removed), `cascade_deleted` reflects cascade syntheses **actually deleted**, and `failed` lists the
artifacts that could not be deleted. The response always includes a `failed` list, which is an empty
list when all deletions succeed.

Rationale: the response always reflects what was *actually* deleted, never what was merely intended,
so a caller has an accurate, reconcilable record of irreversible deletions.

**Example**

- Given every deletion succeeds, when `purge_archived` returns, then `purged_ids` and `purged_count`
  reflect the artifacts actually fully deleted and the `failed` list is empty.

Source: none

## 7. Boundaries

**Always:**
- The tool receives `settings`, `s3`, `vectors`, and `bedrock` (unused) as injected dependencies.

**Ask First:**
- Nothing — all constraints are defined.

**Never:**
- Do not purge artifacts from foreign scopes.
- Do not cascade-delete a synthesis that still has at least one source artifact outside the purge set.
- Do not skip the `confirm=True` gate.
- Do not return an error for an empty purge set — an empty set is a valid no-op.
- Do not abort the entire purge on a single non-credential artifact failure — only a credential
  failure (systemic) aborts the deletion phase.
- Do not report an artifact in `purged_ids` / `cascade_deleted` unless it was actually deleted; a
  failed or merely-intended artifact must never appear there.

## 8. For the developer agent

### Files to Touch

The tool already exists and is registered. The best-effort bulk partial-failure contract (`failed`
list, actually-deleted reporting) is a **modification** of the existing files, not a fresh creation.

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_purge.py` | Modify | Update/add partial-failure tests first (Red) |
| `src/arkeology/tools/purge.py` | Modify | Implement best-effort loop + `failed` reporting (Green) |
| `tests/integration/test_tools_purge.py` | Modify | Update if needed for the new response shape |

### Contracts

None.

### Testing Approach

**TDD cycle A (unit):** update `test_tools_purge.py` for the new contract first → fail → modify
`tools/purge.py` → unit tests pass.

**TDD cycle B (integration):** update integration tests for the response shape if needed → fail →
verify against live AWS → pass.

**`test_tools_purge.py` — unit tests (FakeS3Client + FakeVectorsClient):**

Seed: own-scope inactive artifacts (some tier 2, some tier 3), own-scope active artifacts, a synthesis
artifact whose all `source_artifacts` are in the inactive set, a synthesis artifact with at least one
source outside the inactive set, a foreign-scope inactive artifact.

Confirmation gate:
- `confirm=False` → structured error, no AWS writes.
- `confirm` absent → structured error, no AWS writes.

Empty purge set:
- No inactive artifacts in own scope →
  `{"purged_count": 0, "purged_ids": [], "cascade_deleted": [], "failed": []}`.

Happy path:
- Multiple inactive artifacts → all absent from S3 and vectors after purge; `purged_ids` lists all
  deleted `artifact_id`s; `purged_count` matches list length.
- Active artifacts in own scope → untouched.
- Foreign-scope inactive artifact → untouched.

Cascade:
- Synthesis whose all sources are in purge set → cascade-deleted; its `artifact_id` in
  `cascade_deleted` field; absent from fake S3 and vectors after purge.
- Synthesis with at least one source outside purge set → NOT in `cascade_deleted`; still present in
  fake S3 and vectors after purge.
- No synthesis artifacts → `cascade_deleted` is empty list; no error.

All-success reporting:
- Multiple inactive artifacts, all deletes succeed → `purged_ids`/`purged_count` reflect the
  actually-deleted set; `failed` is an empty list.

Best-effort partial failure (non-credential):
- Simulate `delete_vectors` raising a non-credential exception for ONE artifact in a multi-artifact
  purge → that artifact appears in `failed` (with `artifact_id` + error code) and is absent from
  `purged_ids`; it remains fully intact (vectors and S3 present in fakes); the other artifacts are
  deleted and listed in `purged_ids`.
- Simulate `delete_object` failure on ONE artifact after its vectors were deleted → that artifact
  appears in `failed` and is excluded from `purged_ids`; its vectors are absent (orphan state), S3
  object still present; the other artifacts are purged.
- Simulate a cascade synthesis delete failing (non-credential) → it appears in `failed` and not in
  `cascade_deleted`; other deletions still proceed.
- Multiple failures in one purge → all appear in `failed`; all successful deletions appear in
  `purged_ids`/`cascade_deleted`.

Credential failures:
- `list_vectors_by_metadata` (discovery) raises `CredentialError` → structured error; no deletes.
- `get_vectors` (cascade discovery) raises `CredentialError` → structured error; no deletes.
- `delete_vectors` raises `CredentialError` mid-loop → deletion phase aborts; structured credential
  error returned; artifacts purged before the failure appear in `purged_ids`.
- `delete_object` raises `CredentialError` mid-loop → deletion phase aborts; structured credential
  error returned; artifacts purged before the failure appear in `purged_ids`.

**`tests/integration/test_tools_purge.py` — integration tests (`@pytest.mark.integration`):**

Teardown: any artifacts NOT purged (e.g. active artifacts, partially-failed cases) must be cleaned up
via `delete_artifact`.

- Write and archive two artifacts; purge → both absent from list; `purged_count=2`.
- Write an active artifact; purge → active artifact untouched; `purged_count=0`.
- Write a synthesis with sources all archived; purge → synthesis cascade-deleted and reported in
  `cascade_deleted`.
- Purge with no inactive artifacts → `purged_count=0`, no error.
