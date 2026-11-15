---
type: Spec
id: p9-t32-reconcile-phase3-dangling-vectors
title: Reconcile Phase 3 — Dangling Vector Pruning
description: Spec to add Scenario 3 to reconcile_index — detecting and deleting vector entries whose backing S3 object no longer exists.
tags: []
status: stable
okf_version: "0.2"
sources:
  - resource: docs/contracts/modules/arkeology.tools.reconcile.md
    title: arkeology.tools.reconcile
  - resource: docs/contracts/data/s3vectors.artifact.md
    title: s3vectors.artifact
  - resource: .docs/reviews/architecture-review-2026-11-15-arkeology-phases-9-10-12.md
    title: "Architecture review — Arkeology, plan phases 9, 10 and 12"
generated:
  by: "axians-architect/unknown"
  at: 2026-06-03T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-15T20:19:59Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
  - by: "axians-architect/claude-fable-5-2"
    at: 2026-11-15T20:45:07Z
---

# Reconcile Phase 3 — Dangling Vector Pruning

## TL;DR

Without Scenario 3, `reconcile_index` handles index-S3 inconsistency in one direction only: S3
objects with no vector entries are re-indexed (Scenario 2 — orphan re-indexing). This spec adds
Scenario 3 — dangling vector pruning: vector entries with no backing S3 object are detected and
deleted. Scenario 3 detects candidates from data already collected during Scenario 2, re-confirms
each candidate's S3 absence with one `head_object` call immediately before deleting its vectors,
and always runs automatically — consistent with how Scenarios 1 and 2 operate.

## 1. Problem Statement

Dangling vectors arise when an S3 object is deleted outside Arkeology (manual deletion, lifecycle
rule, bucket migration) while its vector index entries remain. The server's vectors-first deletion
order prevents this from occurring in normal server operation, but external S3 changes are not
controlled by the server. Dangling vectors are not inert: the search path returns metadata from
vector entries directly without fetching S3. An agent sees the artifact in search or list results
with valid-looking metadata, decides it is relevant, calls `read_artifact` — and receives a
not-found error. This is the "the system says it exists but can't deliver" failure mode identified
in vision.md's Product-Value-Failure Pre-Mortem section. No document explicitly descoped the reverse
reconciliation direction; it was silently omitted because the server's own delete path prevents it.
External S3 changes are not so constrained.

| Scenario | Condition | Action taken |
|----------|-----------|--------------|
| Scenario 1 — failure-log replay | Artifact partially written; failure logged | Re-index from log; remove resolved entry |
| Scenario 2 — orphan s3 object | S3 object present; no vector entry | Re-embed and re-index the artifact |
| Scenario 3 — dangling vector pruning | Vector entry present; S3 object absent | Delete the dangling vector entries |

This spec adds Scenario 3. All three stories it was written from are P1: dangling vectors are
pruned automatically (R4, R5), Scenario 2 and Scenario 3 run in the same call (R1), and the scope
gate is enforced (R8).

## 2. Rules — Running and detection

### R1 — Scenario 3 runs automatically after Scenario 2, in the same call

When `reconcile_index` runs, it executes Scenario 3 after Scenario 2, using data already collected
during Scenario 2 (no additional API calls required for detection). Both directions of
inconsistency are resolved in a single `reconcile_index` call with no additional parameters:
Scenario 3 runs automatically, with no new parameters, consistent with Scenario 1 (auto-replay
failure log) and Scenario 2 (auto-reindex orphans).

**Example**

- Given one artifact present in S3 with no vector entries (Scenario 2 — orphan) and one artifact
  with vector entries but no S3 object (Scenario 3 — dangling), when `reconcile_index` is called,
  then `orphans_found` is 1 and `dangling_artifacts_found` is 1 in the same response.

### R2 — Dangling candidates come from Scenario 2's in-memory data

When Scenario 2 collects `indexed_keys_raw` (all vector keys for own scope), the system groups
those keys by `artifact_id` (splitting on `#`) to produce `vectors_by_artifact`. When Scenario 2
collects `own_keys` (all S3 keys in own prefix), the system computes
`dangling_artifact_ids = set(vectors_by_artifact.keys()) − set(own_keys)`.

### R3 — Each candidate's S3 absence is re-confirmed immediately before its vectors are deleted

Immediately before deleting a dangling candidate's vectors, `reconcile_index` re-confirms S3
absence with one `head_object` call per dangling candidate, and prunes only when the object is
confirmed absent at prune time.

Detecting candidates from the two listings alone has a race: an artifact fully written between
the Scenario 2 S3 listing and the vector listing is misclassified dangling and its brand-new
vectors are pruned. The per-candidate `head_object` call is the only way to close the race without
reordering the two listings, which narrows but does not eliminate the window. It is a deliberate,
narrow exception to the boundary against additional `list_vectors_by_metadata` or `list_objects`
calls in Scenario 3: `head_object` is a different, cheap, per-candidate call, not a repeated bulk
listing.

### R4 — All vector keys of each dangling artifact are deleted

When `dangling_artifact_ids` is non-empty, the system calls `vectors.delete_vectors` for all vector
keys belonging to each dangling artifact. The artifact then no longer appears in search or list
results. The S3 object of a dangling artifact is not deleted: it is already gone — this is the
definition of dangling.

**Example**

- Given an artifact whose S3 object has been deleted while its vector entries remain, when
  `reconcile_index` is called, then all vector entries for that artifact are deleted and the
  artifact no longer appears in search or list results.

## 3. Rules — Response

### R5 — The response reports dangling artifacts and pruned vectors

When vector deletion succeeds for an artifact, the system includes the artifact ID in
`dangling_artifacts`, increments `dangling_artifacts_found` by 1, and increments
`dangling_vectors_pruned` by the count of deleted keys for that artifact. When Scenario 3
completes, the response includes `dangling_artifacts_found` (int), `dangling_vectors_pruned` (int)
and `dangling_artifacts` (list[str]).

**Example**

- Given an artifact whose S3 object has been deleted while its vector entries remain, when
  `reconcile_index` is called and the response is read, then `dangling_artifacts_found` is 1,
  `dangling_vectors_pruned` equals the number of section vectors that were deleted, and
  `dangling_artifacts` contains the artifact's identifier.
- Given no dangling vectors exist, when `reconcile_index` is called, then
  `dangling_artifacts_found` is 0, `dangling_vectors_pruned` is 0, and `dangling_artifacts` is an
  empty list.

## 4. Rules — Errors

### R6 — A credential error during vector deletion returns immediately

When a `CredentialError` occurs during vector deletion, the system returns
`{"error": "credential_error", "message": ...}` immediately.

### R7 — Any other error during one artifact's vector deletion is recorded and processing continues

When any other exception occurs during vector deletion for a single artifact, the system adds it
to `failed` with a reason and continues processing the remaining dangling artifacts.

## 5. Rules — Scope

### R8 — Scenario 3 only considers own-scope vector entries

When Scenario 2 collects vector keys by scope, the system uses
`{"scope": {"$eq": settings.write_prefix}}` — the existing filter — ensuring Scenario 3 only
considers own-scope entries and never touches foreign-scope vectors. Scenario 3 never prunes vector
entries belonging to foreign scopes.

**Example**

- Given the vector index contains entries for a foreign-scope artifact that has no S3 object in
  the foreign bucket, when `reconcile_index` is called, then the foreign-scope entries are not
  deleted and do not appear in `dangling_artifacts`.

## 6. Boundaries

**Always:**
- Scenario 3 reuses `own_keys` and `indexed_keys_raw` collected during Scenario 2. No additional
  `list_objects` or `list_vectors_by_metadata` calls are made for Scenario 3.
- Scope is enforced by the existing Scenario 2 filter on `list_vectors_by_metadata`. Scenario 3
  inherits that scope automatically — no additional scope check needed.
- Scenario 3 runs automatically, no new parameters. Consistent with Scenario 1 (auto-replay
  failure log) and Scenario 2 (auto-reindex orphans).
- The response schema change is additive only. The six existing fields are unchanged.
- The `vectors_by_artifact` grouping (splitting vector keys on `#`) is the same logic already used
  in Scenario 2 to extract `indexed_artifact_ids`. Unify into one pass — do not build the same map
  twice.

**Ask First:**
- Nothing — all behaviour is fully defined.

**Never:**
- Do not add a `prune_dangling` parameter. Scenario 3 is always automatic.
- Do not make additional `list_vectors_by_metadata` or `list_objects` calls in Scenario 3 — all
  required data is already in memory from Scenario 2. The one `head_object` call per dangling
  candidate (R3) is a deliberate, narrow exception: a different, cheap, per-candidate call, not a
  repeated bulk listing.
- Do not touch foreign-scope vector entries. The scope filter on `list_vectors_by_metadata` already
  ensures only own-scope entries are in `indexed_keys_raw`.
- Do not delete the S3 object for a dangling artifact (it is already gone — this is the definition
  of dangling).

## 7. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_reconcile.py` | Modify | Add Phase 3 unit tests — written first (Red) |
| `src/arkeology/tools/reconcile.py` | Modify | Add Phase 3 logic after existing Phase 2 orphan scan; unify `vectors_by_artifact` grouping |
| `tests/integration/test_tools_reconcile.py` | Modify | Add Phase 3 integration test — written first (Red for integration) |

### Contracts

- `docs/contracts/modules/arkeology.tools.reconcile.md` § reconcile_index — the dangling-vector prune, its response keys and its error paths (R1–R8).
- `docs/contracts/data/s3vectors.artifact.md` § Storage Shape — the `{artifact_id}#{n}` vector key by which an artifact's vectors are grouped and deleted (R2, R4).

### Testing Approach

**TDD cycle — unit tests first:**
- `tests/unit/test_tools_reconcile.py` (Red) → `src/arkeology/tools/reconcile.py` (Green)

**New unit tests for Phase 3:**
- `test_phase3_dangling_vector_pruned` — fake has one vector entry for `own-scope/artifact-a` but
  no S3 object for it; assert `dangling_artifacts_found == 1`, `dangling_vectors_pruned == 1`,
  `dangling_artifacts == ["own-scope/artifact-a"]`, `vectors.delete_vectors` called with the
  correct key(s).
- `test_phase3_multi_section_artifact_all_keys_pruned` — fake has 3 vector entries for the same
  dangling artifact ID (one per section); assert `dangling_vectors_pruned == 3` and all three keys
  passed to a single `delete_vectors` call.
- `test_phase3_no_dangling_vectors` — all vector entries have matching S3 objects; assert
  `dangling_artifacts_found == 0`, `dangling_vectors_pruned == 0`, `dangling_artifacts == []`.
- `test_phase2_and_phase3_both_run` — fake has one S3 orphan (in S3, absent from index) and one
  dangling vector (in index, absent from S3); assert `orphans_found == 1` (Scenario 2) and
  `dangling_artifacts_found == 1` (Scenario 3) in the same response.
- `test_phase3_foreign_scope_not_pruned` — index has a foreign-scope entry with no S3 backing;
  assert it does not appear in `dangling_artifacts` (scope filter already excludes it from
  `indexed_keys_raw`).
- `test_phase3_credential_error_on_delete` — patch `vectors.delete_vectors` to raise
  `CredentialError`; assert response is `{"error": "credential_error", ...}`.
- `test_phase3_unexpected_error_on_delete_continues` — patch `delete_vectors` to raise for one
  artifact but not another; assert the failing artifact appears in `failed` and the successful one
  appears in `dangling_artifacts`.
- `test_response_schema_includes_new_fields` — any reconcile call (even with nothing to do) returns
  all three new fields in the response.

**Integration test addition:**
- `test_phase3_dangling_vector_pruned_integration` — write an artifact, manually delete its S3
  object via `s3.delete_object` (bypassing the MCP tool), call `reconcile_index`, assert
  `dangling_artifacts_found == 1` and the artifact is absent from `search_artifacts`.
