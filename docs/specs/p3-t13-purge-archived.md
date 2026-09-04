---
type: spec
title: T13 — Purge Archived Tool
description: Feature spec for the purge_archived MCP tool that bulk hard-deletes all inactive artifacts in own scope with synthesis cascade handling and a confirm gate.
tags: []
timestamp: 2026-05-30T00:00:00Z
okf_version: "0.1"
feature: p3-t13-purge-archived
status: ready
phase: 3
task: 13
references:
  - docs/contracts/modules/arkeology.tools.purge.md
authored:
  by: "architect"
  date: "2026-05-30"
revised:
  by: "pm"
  date: "2026-06-29"
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

Because purge is a *bulk* hard-delete, partial failure must be handled differently from the
single-artifact `delete_artifact` (T12). The deletion phase is **best-effort**: a
non-credential failure on one artifact does not abort the whole operation — the remaining
artifacts are still purged and each failure is reported in an aggregated `failed` list. The
response always reflects what was *actually* deleted, never what was merely intended, so a
caller has an accurate, reconcilable record of irreversible deletions. Per-artifact deletion
ordering and recoverable-orphan semantics are inherited from T12 (vectors-first, S3-second;
an S3 delete that fails after vectors are gone leaves a recoverable orphan, FR-17). A
credential failure is treated as systemic and aborts the remaining deletions, still
reporting what was purged so far.

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
- Given a credential failure during the discovery phase (listing inactive vectors, fetching
  metadata, or the cascade check), when `purge_archived` returns, then a structured error is
  returned — not a raw exception — and no deletions are performed.
- Given a credential failure during the deletion phase, when `purge_archived` returns, then
  the remaining deletions are aborted, a structured credential error is returned, and the
  artifacts purged so far are reported in `purged_ids`.

### Story 5 — Bulk partial failure is best-effort and reported (P1)

A purge of many artifacts must not lose work or hide irreversible deletions when one
artifact fails to delete. Non-credential failures on individual artifacts are collected and
the purge continues; the response reports exactly what was deleted and what failed.

**Acceptance criteria:**
- Given a purge set of several artifacts where one artifact's vector delete fails with a
  non-credential error, when `purge_archived` runs with `confirm=True`, then the remaining
  artifacts are still purged, the failed artifact appears in the `failed` list with its
  `artifact_id` and error, and that artifact remains fully intact (vectors and S3 present).
- Given one artifact's S3 delete fails (non-credential) after its vectors were deleted, when
  `purge_archived` returns, then that artifact appears in the `failed` list (a recoverable
  S3 orphan per T12/FR-17), is excluded from `purged_ids`, and the other artifacts are still
  purged.
- Given every deletion succeeds, when `purge_archived` returns, then `purged_ids` and
  `purged_count` reflect the artifacts actually fully deleted and the `failed` list is empty.
- Given a cascade synthesis fails to delete (non-credential), when `purge_archived` returns,
  then it appears in `failed` and not in `cascade_deleted`, and other deletions still
  proceed.

## Requirements

- WHEN `purge_archived` is called without `confirm=True` THE SYSTEM SHALL return a
  structured error and make no AWS write calls.
- WHEN `purge_archived` is called with `confirm=True` THE SYSTEM SHALL list all vectors
  in own scope with `status="inactive"` using `list_vectors_by_metadata`, deduplicate by
  `artifact_id` to obtain the purge set.
- WHEN the purge set is empty THE SYSTEM SHALL return
  `{"purged_count": 0, "purged_ids": [], "cascade_deleted": [], "failed": []}` — no error.
- WHEN the purge set is non-empty THE SYSTEM SHALL check for cascade candidates: active
  synthesis artifacts in own scope whose entire `source_artifacts` list is contained in the
  purge set; add those synthesis `artifact_id`s to the deletion set and report them
  separately.
- WHEN executing deletion THE SYSTEM SHALL, for each artifact in the combined deletion set
  (inactive + cascade syntheses), find all vector keys via `list_vectors_by_metadata`,
  delete vectors first, then delete the S3 object — mirroring the per-artifact ordering in
  T12.
- WHEN executing the deletion phase THE SYSTEM SHALL be **best-effort**: a non-credential
  failure deleting one artifact (vector delete or S3 delete) SHALL NOT abort the purge; the
  system SHALL record the failure and continue with the remaining artifacts.
- WHEN an individual artifact deletion fails with a non-credential error THE SYSTEM SHALL
  record an entry in a `failed` list containing the `artifact_id`, the error code, and a
  message. An artifact recorded in `failed` SHALL NOT appear in `purged_ids` or
  `cascade_deleted`.
- WHEN a vector delete fails for an artifact THE SYSTEM SHALL leave that artifact fully
  intact (vectors and S3 both present) before continuing. WHEN an S3 delete fails after the
  artifact's vectors were deleted THE SYSTEM SHALL leave a recoverable S3 orphan (per T12 /
  FR-17) before continuing.
- WHEN a CredentialError is raised during the deletion phase THE SYSTEM SHALL abort the
  remaining deletions (credential failures are systemic), and return a structured credential
  error together with the artifacts purged so far in `purged_ids` — never a raw exception.
- WHEN a CredentialError is raised during the discovery phase (listing inactive vectors,
  fetching their metadata, or the cascade check) THE SYSTEM SHALL return a structured error
  and perform no deletions — never a raw exception.
- WHEN the purge completes THE SYSTEM SHALL return
  `{"purged_count": int, "purged_ids": list[str], "cascade_deleted": list[str], "failed": list[dict]}`
  where `purged_ids` / `purged_count` reflect the artifacts **actually fully deleted** (S3
  object removed), `cascade_deleted` reflects cascade syntheses **actually deleted**, and
  `failed` lists the artifacts that could not be deleted. `failed` is an empty list when all
  deletions succeed.
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
- The deletion phase is best-effort for non-credential failures: collect each failure in
  `failed` and continue with the remaining artifacts.
- The response reports the artifacts **actually deleted** (`purged_ids` / `purged_count` /
  `cascade_deleted`) and always includes a `failed` list (empty when all succeed).
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
- Do not abort the entire purge on a single non-credential artifact failure — only a
  credential failure (systemic) aborts the deletion phase.
- Do not report an artifact in `purged_ids` / `cascade_deleted` unless it was actually
  deleted; a failed or merely-intended artifact must never appear there.

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

> Note (2026-06-29 revision): the tool already exists and is registered. This revision adds
> the best-effort bulk partial-failure contract (`failed` list, actually-deleted reporting).
> The work is now a **modification** of the existing files, not a fresh creation.

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_purge.py` | Modify | Update/add partial-failure tests first (Red) |
| `src/arkeology/tools/purge.py` | Modify | Implement best-effort loop + `failed` reporting (Green) |
| `tests/integration/test_tools_purge.py` | Modify | Update if needed for the new response shape |

## Testing Approach

**TDD cycle A (unit):** update `test_tools_purge.py` for the new contract first → fail →
modify `tools/purge.py` → unit tests pass.

**TDD cycle B (integration):** update integration tests for the response shape if needed →
fail → verify against live AWS → pass.

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
- No inactive artifacts in own scope → `{"purged_count": 0, "purged_ids": [], "cascade_deleted": [], "failed": []}`.

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

All-success reporting:
- Multiple inactive artifacts, all deletes succeed → `purged_ids`/`purged_count` reflect the
  actually-deleted set; `failed` is an empty list.

Best-effort partial failure (non-credential):
- Simulate `delete_vectors` raising a non-credential exception for ONE artifact in a
  multi-artifact purge → that artifact appears in `failed` (with `artifact_id` + error code)
  and is absent from `purged_ids`; it remains fully intact (vectors and S3 present in fakes);
  the other artifacts are deleted and listed in `purged_ids`.
- Simulate `delete_object` failure on ONE artifact after its vectors were deleted → that
  artifact appears in `failed` and is excluded from `purged_ids`; its vectors are absent
  (orphan state), S3 object still present; the other artifacts are purged.
- Simulate a cascade synthesis delete failing (non-credential) → it appears in `failed` and
  not in `cascade_deleted`; other deletions still proceed.
- Multiple failures in one purge → all appear in `failed`; all successful deletions appear in
  `purged_ids`/`cascade_deleted`.

Credential failures:
- `list_vectors_by_metadata` (discovery) raises `CredentialError` → structured error; no
  deletes.
- `get_vectors` (cascade discovery) raises `CredentialError` → structured error; no deletes.
- `delete_vectors` raises `CredentialError` mid-loop → deletion phase aborts; structured
  credential error returned; artifacts purged before the failure appear in `purged_ids`.
- `delete_object` raises `CredentialError` mid-loop → deletion phase aborts; structured
  credential error returned; artifacts purged before the failure appear in `purged_ids`.

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
