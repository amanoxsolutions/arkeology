---
type: spec
title: T48 — reconcile_index Rebuilds commit_refs + references from Annotations
description: When re-indexing an artifact, restore both commit_refs and references into rebuilt vector metadata by reading the object's durable S3 annotations (ListObjectAnnotations / GetObjectAnnotation) instead of standard object metadata. Resolves OQ2 — reconcile is no longer lossy for link data.
tags: []
timestamp: 2026-07-03T00:00:00Z
okf_version: "0.1"
feature: p12-t48-reconcile-from-annotations
status: ready
phase: 12
task: 48
references:
  - docs/architecture-decisions/adr-2026-07-03-annotation-backed-link-storage.md
  - docs/specs/p9-t32-reconcile-phase3-dangling-vectors.md
  - docs/specs/p12-t45-s3-annotation-client.md
  - docs/specs/p12-t47-annotation-dual-write.md
  - docs/planning-artifacts/prd.md
authored:
  by: "architect"
  date: "2026-07-03"
revised:
  by: "tech-writer"
  date: "2026-07-04"
---

# T48 — `reconcile_index` Rebuilds `commit_refs` + `references` from Annotations

<!-- SCOPE BLOCK — frozen after approval -->

## TL;DR

Change `reconcile_index`'s `_reindex_artifact` so that when it rebuilds an artifact's vector
metadata it restores `commit_refs` and `references` by reading the **union of both durable stores**
— the object's S3 annotations (via the T45 client) AND the existing vector metadata, via
`annotations.read_current_link_fields` — instead of the annotations alone or standard object
metadata. Because the write path (T47) and `link_metadata` (T49) now store these fields as
annotations, and because neither store is sole authority (Phase 12 review C5/M6 — see ADR-011's
revised authority model), a reconcile run no longer drops them. This resolves OQ2 and the ADR-009
"reconcile drops commit links" limitation. (FR-17, FR-54, AC-59.)

> **Revised 2026-07-04 (tech-writer, Phase 12 review C5/M6).** The original scope below specified
> reading `commit_refs` / `references` from annotations only. The shipped implementation reads the
> **union of the annotation copy and the existing vector-metadata copy** — a naive annotations-only
> read would erase a value that survives only in vector metadata (e.g. under an annotation-unavailable
> deployment, T52), which is exactly the loss this task exists to prevent. `reconcile.py` also
> re-raises `CredentialError` from that read rather than degrading it (M6) — a credential failure is
> very likely to break the surrounding reconcile call too and must not be silently treated as "no
> link fields". See the corrected Requirements/Boundaries below.

## Problem Statement

`_reindex_artifact` currently reads `commit_refs` from S3 user-defined metadata
(`coerce_list_field(raw_s3_meta, "commit_refs")`). After T47, the write path no longer writes
`commit_refs` (or `references`) into user-defined metadata — the durable copy is an annotation. So
without this change, any reconcile that rebuilds vectors would drop both link fields, silently
losing the append-only link trail on the very operation meant to repair the index. Reading the
fields from annotations closes the gap and makes reconcile lossless for link data.

## User Stories

### Story 1 — Reconcile restores link fields from annotations (P1)

An artifact's vectors were lost (partial write or external deletion). `reconcile_index` rebuilds
them, restoring `commit_refs` and `references` from the object's annotations.

**Acceptance criteria:**
- Given an own-scope artifact whose S3 object carries `commit_refs` and `references` annotations and
  whose vectors are absent from the index, when `reconcile_index` runs then the rebuilt vector
  metadata carries both `commit_refs` and `references` sourced from the union of the annotations and
  any existing vector metadata. (AC-59)
- Given an artifact re-indexed via failure-log replay (Phase 1) or orphan scan (Phase 2), then both
  paths restore the link fields identically (they share `_reindex_artifact`).

### Story 2 — Regression proof: reads the union, not S3 metadata (P1)

**Acceptance criteria:**
- Given an artifact whose S3 user-defined metadata has NO `commit_refs` / `references` keys (the
  post-T47 reality) but whose annotations carry them, when `reconcile_index` rebuilds its vectors
  then the rebuilt metadata carries the link fields — proving the source is the annotation/vector
  union, not S3 metadata. (This is the test written first that fails before implementation.)
- Given an artifact whose annotations are absent (e.g. annotation-unavailable deployment) but whose
  *existing* vector metadata already carries `commit_refs` / `references`, when `reconcile_index`
  rebuilds its vectors then those fields are still present — proving the vector-metadata side of the
  union is not discarded either (Phase 12 review C5/M6).

### Story 3 — Clean state and scope unaffected (P1)

**Acceptance criteria:**
- Given an artifact with no link annotations, when re-indexed then `commit_refs` / `references` are
  simply omitted from the rebuilt vector metadata (no error).
- Given the existing own-scope gate, then foreign-scope artifacts are never re-indexed or touched
  (unchanged from Phases 1–3).
- Given annotations are unavailable at reconcile time, then `_reindex_artifact` degrades to omitting
  the link fields (logged), and the rest of the reconcile completes — it does not raise.

## Requirements

- WHEN `_reindex_artifact` builds vector metadata THE SYSTEM SHALL read `commit_refs` and
  `references` via `annotations.read_current_link_fields(s3, vectors, artifact_id)` — the
  order-preserving dedup union of the S3 annotation copy AND the artifact's existing indexed
  vector-metadata copy (Phase 12 review C5/M6) — rather than `coerce_list_field(raw_s3_meta, ...)`
  or the annotation copy alone.
- WHEN either field is non-empty THE SYSTEM SHALL add it to the rebuilt vector metadata as `list[str]`
  (omitting the key when empty — the existing S3-Vectors empty-array rule).
- WHEN `_reindex_artifact` needs the S3 client THE SYSTEM SHALL receive `s3` as a parameter (it does
  not today) so it can read annotations; all call sites (Phase 1 replay, Phase 2 orphan scan) pass it.
- WHEN the annotation side of the union read is unavailable / access is denied THE SYSTEM SHALL log
  and fall back to the vector-metadata side of the union only — the reconcile SHALL NOT abort.
- WHEN the union read raises `CredentialError` THE SYSTEM SHALL propagate it to the caller (Phase 12
  review M6) — a credential failure signals a general authentication problem likely to also break
  the surrounding reconcile call, and must never be silently treated as "no link fields".
- WHEN reconcile completes THE SYSTEM SHALL preserve its existing response schema unchanged (this is
  an internal source-of-truth change, not a new field).

## Boundaries

**Always:**
- Source of truth for `commit_refs` / `references` during re-index is the **union of both durable
  stores** — S3 annotations and existing vector metadata (Phase 12 review C5/M6, ADR-011's revised
  authority model) — never annotations alone and never S3 user-defined metadata. `source_artifacts`
  and identity fields continue to be read from S3 user-defined metadata (they are not
  annotation-backed).
- Reuse the `annotations.read_current_link_fields` helper (T47/C5) — do not re-implement the union
  read or the decode logic.
- The own-scope gate and Phase 1/2/3 structure are unchanged (this is a metadata-source swap inside
  `_reindex_artifact`).

**Ask First:**
- Nothing — behaviour fixed by ADR-011.

**Never:**
- Do not read `commit_refs` / `references` from S3 user-defined metadata (they are no longer there
  after T47).
- Do not treat the annotation copy as sole authority — a vector-only value must survive re-index.
- Do not change the reconcile response schema.
- Do not let an annotation-read *availability* failure (non-credential) abort an otherwise-successful
  reconcile; DO let a `CredentialError` propagate and abort (M6).

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_reconcile.py` | Modify | Add the "reads annotations not S3 metadata" regression test (Red) + clean-state + unavailable-degrade tests |
| `src/cairn_mcp/tools/reconcile.py` | Modify | Add `s3` param to `_reindex_artifact`; read link fields via `annotations.read_current_link_fields` (union of both stores, C5); drop the `coerce_list_field(..., "commit_refs")` source; pass `s3` at both call sites; propagate `CredentialError` (M6) |
| `tests/integration/test_tools_reconcile.py` | Modify | Real-AWS: write + backfill via `link_metadata` → drop vectors → reconcile → assert both fields restored — Red for integration |

## Testing Approach

**TDD cycle — unit test first, then implementation:**

`tests/unit/test_tools_reconcile.py` (Red) → `src/cairn_mcp/tools/reconcile.py` (Green). Requires the
T45 moto annotation self-mock.

New / modified unit tests:
- `test_reindex_restores_link_fields_from_annotations` — object has `commit_refs` / `references`
  annotations and NO corresponding S3 user-metadata keys; delete its vectors; `reconcile_index` →
  rebuilt vector metadata carries both fields (fails before implementation because current code reads
  S3 metadata → this is the Red proof).
- `test_reindex_clean_state_omits_empty_link_fields` — object with no link annotations → rebuilt
  metadata omits both keys; no error.
- `test_reindex_annotations_unavailable_degrades` — patch the annotation read to raise an
  annotation-unavailable error → re-index still completes, link fields omitted, logged.
- `test_failure_log_replay_and_orphan_scan_both_restore` — both `_reindex_artifact` call sites pass
  `s3` and restore link fields.
- Existing scope-gate / Phase-3 dangling tests continue to pass unchanged.

**Integration:** end-to-end reconcile-survival (shared with T49's integration intent): write →
`link_metadata` backfill → force re-index → assert `commit_refs` + `references` present.

## Open Questions

*(none — depends on T45 annotation client, T47 `read_link_annotations` helper, and annotations
actually being written by T47/T49)*
