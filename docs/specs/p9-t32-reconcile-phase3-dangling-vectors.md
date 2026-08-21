---
type: spec
title: Reconcile Phase 3 — Dangling Vector Pruning
description: Spec to add Scenario 3 to reconcile_index — detecting and deleting vector entries whose backing S3 object no longer exists.
tags: []
timestamp: 2026-06-03T00:00:00Z
okf_version: "0.1"
feature: p9-t32-reconcile-phase3-dangling-vectors
phase: 9
task: 32
status: complete
references: []
authored:
  by: "architect"
  date: "2026-06-03"
revised:
  by: "developer"
  date: "2026-07-05"
---

# Reconcile Phase 3 — Dangling Vector Pruning

<!-- SCOPE BLOCK — frozen after approval -->

> **Revised (2026-07-05).** The "zero additional API cost" design
> below has a race: an artifact fully written between the Scenario 2 S3 listing and the
> vector listing was misclassified dangling and its brand-new vectors were pruned.
> `reconcile_index` now re-confirms S3 absence with one `head_object` call per dangling
> candidate immediately before deleting its vectors — only pruning when the object is
> confirmed absent at prune time. This is a deliberate, narrow exception to the "no
> additional `list_vectors_by_metadata` or `list_objects` calls in Scenario 3" boundary
> below: `head_object` is a different, cheap, per-candidate call, not a repeated bulk
> listing, and it is the only way to close the race without reordering the two listings
> (which narrows but does not eliminate the window). The Requirements and Boundaries
> sections are not rewritten; this note documents the correction.

## TL;DR

`reconcile_index` handles index-S3 inconsistency in one direction only: S3 objects with no
vector entries are re-indexed (Scenario 2 — orphan re-indexing). This spec adds Scenario 3
— dangling vector pruning: vector entries with no backing S3 object are detected and deleted.
Scenario 3 reuses data already collected during Scenario 2 at zero additional API cost and
always runs automatically — consistent with how Scenarios 1 and 2 operate.

## Problem Statement

Dangling vectors arise when an S3 object is deleted outside Arkeology (manual deletion,
lifecycle rule, bucket migration) while its vector index entries remain. The server's
vectors-first deletion order prevents this from occurring in normal server operation, but
external S3 changes are not controlled by the server. Dangling vectors are not inert: the
search path returns metadata from vector entries directly without fetching S3. An agent sees
the artifact in search or list results with valid-looking metadata, decides it is relevant,
calls `read_artifact` — and receives a not-found error. This is the "the system says it
exists but can't deliver" failure mode identified in vision.md's Product-Value-Failure Pre-Mortem section.
No document explicitly descoped the reverse reconciliation direction; it was silently omitted
because the server's own delete path prevents it. External S3 changes are not so constrained.

### Reconcile scenarios

| Scenario | Condition | Action taken |
|----------|-----------|--------------|
| Scenario 1 — failure-log replay | Artifact partially written; failure logged | Re-index from log; remove resolved entry |
| Scenario 2 — orphan s3 object | S3 object present; no vector entry | Re-embed and re-index the artifact |
| Scenario 3 — dangling vector pruning | Vector entry present; S3 object absent | Delete the dangling vector entries |

This spec adds Scenario 3.

## User Stories

### Story 1 — Dangling vectors are pruned automatically (P1)

An S3 object was deleted externally. Its vector entries are still in the index and surface in
search results. An operator calls `reconcile_index`. Scenario 3 detects the dangling entries,
deletes them, and reports the affected artifact IDs and vector count in the response.

**Acceptance criteria:**
- Given an artifact whose S3 object has been deleted while its vector entries remain, when
  `reconcile_index` is called, then all vector entries for that artifact are deleted and the
  artifact no longer appears in search or list results.
- Given the same scenario, when the response is read, then `dangling_artifacts_found` is 1,
  `dangling_vectors_pruned` equals the number of section vectors that were deleted, and
  `dangling_artifacts` contains the artifact's identifier.
- Given no dangling vectors exist, when `reconcile_index` is called, then
  `dangling_artifacts_found` is 0, `dangling_vectors_pruned` is 0, and `dangling_artifacts`
  is an empty list.

### Story 2 — Scenario 2 and Scenario 3 run in the same call (P1)

Both directions of inconsistency are resolved in a single `reconcile_index` call with no
additional parameters.

**Acceptance criteria:**
- Given one artifact present in S3 with no vector entries (Scenario 2 — orphan) and one
  artifact with vector entries but no S3 object (Scenario 3 — dangling), when
  `reconcile_index` is called, then `orphans_found` is 1 and `dangling_artifacts_found` is 1
  in the same response.

### Story 3 — Scope gate enforced (P1)

Scenario 3 never prunes vector entries belonging to foreign scopes.

**Acceptance criteria:**
- Given the vector index contains entries for a foreign-scope artifact that has no S3 object
  in the foreign bucket, when `reconcile_index` is called, then the foreign-scope entries are
  not deleted and do not appear in `dangling_artifacts`.

## Requirements

- WHEN `reconcile_index` runs THE SYSTEM SHALL execute Scenario 3 after Scenario 2, using
  data already collected during Scenario 2 (no additional API calls required for detection).
- WHEN Scenario 2 collects `indexed_keys_raw` (all vector keys for own scope) THE SYSTEM
  SHALL group those keys by `artifact_id` (splitting on `#`) to produce `vectors_by_artifact`.
- WHEN Scenario 2 collects `own_keys` (all S3 keys in own prefix) THE SYSTEM SHALL compute
  `dangling_artifact_ids = set(vectors_by_artifact.keys()) − set(own_keys)`.
- WHEN `dangling_artifact_ids` is non-empty THE SYSTEM SHALL call `vectors.delete_vectors`
  for all vector keys belonging to each dangling artifact.
- WHEN vector deletion succeeds THE SYSTEM SHALL include the artifact ID in
  `dangling_artifacts`, increment `dangling_artifacts_found` by 1, and increment
  `dangling_vectors_pruned` by the count of deleted keys for that artifact.
- WHEN a `CredentialError` occurs during vector deletion THE SYSTEM SHALL return
  `{"error": "credential_error", "message": ...}` immediately.
- WHEN any other exception occurs during vector deletion for a single artifact THE SYSTEM
  SHALL add it to `failed` with a reason and continue processing remaining dangling artifacts.
- WHEN Scenario 3 completes THE SYSTEM SHALL include `dangling_artifacts_found` (int),
  `dangling_vectors_pruned` (int), and `dangling_artifacts` (list[str]) in the response.
- WHEN Scenario 2 collects vector keys by scope THE SYSTEM SHALL use
  `{"scope": {"$eq": settings.write_prefix}}` — the existing filter — ensuring Scenario 3
  only considers own-scope entries and never touches foreign-scope vectors.

## Boundaries

**Always:**
- Scenario 3 reuses `own_keys` and `indexed_keys_raw` collected during Scenario 2. No
  additional `list_objects` or `list_vectors_by_metadata` calls are made for Scenario 3.
- Scope is enforced by the existing Scenario 2 filter on `list_vectors_by_metadata`. Scenario
  3 inherits that scope automatically — no additional scope check needed.
- Scenario 3 runs automatically, no new parameters. Consistent with Scenario 1 (auto-replay
  failure log) and Scenario 2 (auto-reindex orphans).
- The response schema change is additive only. The six existing fields are unchanged.
- The `vectors_by_artifact` grouping (splitting vector keys on `#`) is the same logic already
  used in Scenario 2 to extract `indexed_artifact_ids`. Unify into one pass — do not build
  the same map twice.

**Ask First:**
- Nothing — all behaviour is fully defined.

**Never:**
- Do not add a `prune_dangling` parameter. Scenario 3 is always automatic.
- Do not make additional `list_vectors_by_metadata` or `list_objects` calls in Scenario 3 —
  all required data is already in memory from Scenario 2.
- Do not touch foreign-scope vector entries. The scope filter on `list_vectors_by_metadata`
  already ensures only own-scope entries are in `indexed_keys_raw`.
- Do not delete the S3 object for a dangling artifact (it is already gone — this is the
  definition of dangling).

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_reconcile.py` | Modify | Add Phase 3 unit tests — written first (Red) |
| `src/arkeology/tools/reconcile.py` | Modify | Add Phase 3 logic after existing Phase 2 orphan scan; unify `vectors_by_artifact` grouping |
| `tests/integration/test_tools_reconcile.py` | Modify | Add Phase 3 integration test — written first (Red for integration) |

## Testing Approach

**TDD cycle — unit tests first:**
- `tests/unit/test_tools_reconcile.py` (Red) → `src/arkeology/tools/reconcile.py` (Green)

**New unit tests for Phase 3:**
- `test_phase3_dangling_vector_pruned` — fake has one vector entry for `own-scope/artifact-a`
  but no S3 object for it; assert `dangling_artifacts_found == 1`,
  `dangling_vectors_pruned == 1`, `dangling_artifacts == ["own-scope/artifact-a"]`,
  `vectors.delete_vectors` called with the correct key(s).
- `test_phase3_multi_section_artifact_all_keys_pruned` — fake has 3 vector entries for the
  same dangling artifact ID (one per section); assert `dangling_vectors_pruned == 3` and all
  three keys passed to a single `delete_vectors` call.
- `test_phase3_no_dangling_vectors` — all vector entries have matching S3 objects; assert
  `dangling_artifacts_found == 0`, `dangling_vectors_pruned == 0`,
  `dangling_artifacts == []`.
- `test_phase2_and_phase3_both_run` — fake has one S3 orphan (in S3, absent from index) and
  one dangling vector (in index, absent from S3); assert `orphans_found == 1` (Scenario 2)
  and `dangling_artifacts_found == 1` (Scenario 3) in the same response.
- `test_phase3_foreign_scope_not_pruned` — index has a foreign-scope entry with no S3
  backing; assert it does not appear in `dangling_artifacts` (scope filter already excludes
  it from `indexed_keys_raw`).
- `test_phase3_credential_error_on_delete` — patch `vectors.delete_vectors` to raise
  `CredentialError`; assert response is `{"error": "credential_error", ...}`.
- `test_phase3_unexpected_error_on_delete_continues` — patch `delete_vectors` to raise for
  one artifact but not another; assert the failing artifact appears in `failed` and the
  successful one appears in `dangling_artifacts`.
- `test_response_schema_includes_new_fields` — any reconcile call (even with nothing to do)
  returns all three new fields in the response.

**Integration test addition:**
- `test_phase3_dangling_vector_pruned_integration` — write an artifact, manually delete its
  S3 object via `s3.delete_object` (bypassing the MCP tool), call `reconcile_index`, assert
  `dangling_artifacts_found == 1` and the artifact is absent from `search_artifacts`.

## Open Questions

*(none — all behaviour is defined)*
