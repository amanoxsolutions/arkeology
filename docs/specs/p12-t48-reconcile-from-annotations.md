---
type: Spec
id: p12-t48-reconcile-from-annotations
title: T48 — reconcile_index Rebuilds commit_refs + references from Annotations
description: When re-indexing an artifact, rebuild its vector metadata with commit_refs read from the object's durable S3 annotation, by its fixed name (GetObjectAnnotation), instead of standard object metadata; references is read the same way and never written into vector metadata. Resolves OQ2 — reconcile is no longer lossy for link data.
tags: []
status: stable
okf_version: "0.2"
sources:
  - resource: docs/architecture-decisions/adr-2026-07-03-annotation-backed-link-storage.md
    title: Annotation-Backed Durable Storage for Mutable Link Fields (commit_refs + references)
    last_modified: 2026-09-29T00:00:00Z
  - resource: docs/specs/p9-t32-reconcile-phase3-dangling-vectors.md
    title: Reconcile Phase 3 — Dangling Vector Pruning
    last_modified: 2026-07-05T00:00:00Z
  - resource: docs/specs/p12-t45-s3-annotation-client.md
    title: T45 — S3 Object Annotation Client Support + moto Self-Mock Extension
    last_modified: 2026-07-03T00:00:00Z
  - resource: docs/specs/p12-t47-annotation-dual-write.md
    title: T47 — Annotation Dual-Write in the Write Path + Tier-3 Overwrite Preservation
    last_modified: 2026-09-06T00:00:00Z
  - resource: docs/planning-artifacts/requirements.md
    title: Arkeology — Requirements
    last_modified: 2026-09-24T00:00:00Z
  - resource: docs/contracts/modules/arkeology.tools.reconcile.md
    title: arkeology.tools.reconcile
  - resource: docs/contracts/data/s3-annotations.artifact.md
    title: s3-annotations.artifact
  - resource: .docs/reviews/architecture-review-2026-11-15-arkeology-phases-9-10-12.md
    title: "Architecture review — Arkeology, plan phases 9, 10 and 12"
  - resource: docs/contracts/data/s3vectors.artifact.md
    title: s3vectors.artifact
generated:
  by: "axians-architect/claude-opus-4.8"
  at: 2026-07-03T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-15T20:35:38Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
  - by: "axians-architect/claude-fable-5-2"
    at: 2026-11-15T20:45:07Z
---

# T48 — `reconcile_index` Rebuilds `commit_refs` + `references` from Annotations

## TL;DR

`reconcile_index`'s `_reindex_artifact` rebuilds an artifact's vector metadata with `commit_refs`
(capped to the most-recently-appended 20 entries) read from the object's S3 annotation — the sole
source of truth for both link fields — never from standard object metadata and never from the
vector-metadata copy it is replacing; `references` is read the same way and never written into the
rebuilt vector metadata. A failure-log entry's recorded link values are re-applied to the
annotations before the re-index, so a write that failed after its object write loses no links. A
failed annotation read fails that one artifact rather than rebuilding it from an empty value. This
resolves OQ2 and the ADR-009 "reconcile drops commit links" limitation. (FR-17, FR-54, AC-59.)

## 1. Problem Statement

`_reindex_artifact` currently reads `commit_refs` from S3 user-defined metadata
(`coerce_list_field(raw_s3_meta, "commit_refs")`). After T47, the write path no longer writes
`commit_refs` (or `references`) into user-defined metadata — the durable copy is an annotation. So
without this change, any reconcile that rebuilds vectors would drop both link fields, silently
losing the append-only link trail on the very operation meant to repair the index. Reading the
fields from annotations closes the gap and makes reconcile lossless for link data. For example, an
artifact's vectors were lost (partial write or external deletion); `reconcile_index` rebuilds them,
restoring `commit_refs` from the object's annotations.

All three stories this spec states are P1: reconcile restores link fields from annotations; the
regression proof that it reads the annotation, not S3 metadata; clean state and scope unaffected.

This spec depends on the T45 annotation client, the T47 `read_link_annotations` helper, and
annotations actually being written by T47/T49.

## 2. Rules — Where `_reindex_artifact` reads the link fields

### R1 — Both link fields are read from the annotation alone

When `_reindex_artifact` builds vector metadata, it reads `commit_refs` and `references` from the
object's S3 annotations through `annotations.read_link_annotations` — never from S3 user-defined
metadata, and never from the vector-metadata copy being replaced, which is a derived filter index
(capped for `commit_refs`, absent for `references`) and never an authority. An absent annotation
reads as `[]`; a failed read raises (R4), because reconcile writes what it reads straight into the
rebuilt metadata and an empty value caused by a failure would overwrite good link data.
`source_artifacts` and identity fields continue to be read from S3 user-defined metadata (they are
not annotation-backed).

**Example**

- Given an artifact whose S3 user-defined metadata has NO `commit_refs` / `references` keys but
  whose annotations carry them, when `reconcile_index` rebuilds its vectors, then the rebuilt
  metadata carries `commit_refs` — proving the source is the annotation, not S3 metadata. (This is
  the test written first that fails before implementation.)
- Given an artifact whose annotations are absent but whose existing vector metadata carries
  `commit_refs`, when `reconcile_index` rebuilds its vectors, then the rebuilt metadata carries no
  `commit_refs` — the old vector copy is never read back.

Source: ADR-011; adr-2026-07-03-annotation-backed-link-storage "Revision — 2026-09-05"; FR-54

### R2 — `_reindex_artifact` receives the S3 client at every call site

When `_reindex_artifact` needs the S3 client, it receives `s3` as a parameter (it does not today) so
it can read annotations; all call sites (Phase 1 replay, Phase 2 orphan scan) pass it.

**Example**

- Given an artifact re-indexed via failure-log replay (Phase 1) or orphan scan (Phase 2), then both
  paths restore the link fields identically (they share `_reindex_artifact`).

## 3. Rules — What the rebuilt vector metadata carries

### R3 — Only `commit_refs` is written back, capped

When `commit_refs` is non-empty, `_reindex_artifact` adds it to the rebuilt vector metadata as
`list[str]`, capped to the most-recently-appended 20 entries (per T58), omitting the key when empty
(the existing S3-Vectors empty-array rule). The rebuilt vector metadata never carries `references`:
`references` is read from the annotation by the same call, and never placed into the
vector-metadata output. The T57 guard-coverage addition (a `check_metadata_budgets` call before
this spec's `put_vector` calls) is layered on top of this rebuild logic and is unaffected by it.

**Example**

- Given an own-scope artifact whose S3 object carries `commit_refs` and `references` annotations and
  whose vectors are absent from the index, when `reconcile_index` runs, then the rebuilt vector
  metadata carries `commit_refs` (capped to the most-recently-appended 20 entries) sourced from the
  annotation, and no `references`.
- Given an artifact with no link annotations, when re-indexed, then `commit_refs` / `references` are
  simply omitted from the rebuilt vector metadata (no error).

Source: AC-59; adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal.md D2 (the `commit_refs`-only narrowing, the 20-entry cap and the T57 note)

## 4. Rules — Failure handling

### R4 — A failed annotation read fails that artifact, not the run

When the annotation read raises anything other than `CredentialError` — `AnnotationUnavailableError`
included — the artifact is reported under `failed` and no vectors are written for it; the run goes
on with the other artifacts and completes. The artifact is never rebuilt with its link fields
omitted.

**Example**

- Given annotations are unavailable for one artifact at reconcile time, when `reconcile_index` runs,
  then that artifact is listed in `failed`, no vector is written for it, and the other artifacts of
  the run are reconciled.

Source: arkeology.tools.reconcile; FR-57

### R5 — A credential error propagates

When the annotation read raises `CredentialError`, the system propagates it to the caller — a
credential failure signals a general authentication problem likely to also break the surrounding
reconcile call, and must never be silently treated as "no link fields".

## 5. Rules — What stays unchanged

### R6 — The reconcile response schema is unchanged

When reconcile completes, it preserves its existing response schema unchanged — this is an internal
source-of-truth change, not a new field.

### R7 — Own-scope gate and phase structure are unchanged

The own-scope gate and the Phase 1/2/3 structure are unchanged — this is a metadata-source swap
inside `_reindex_artifact`. Foreign-scope artifacts are never re-indexed or touched (unchanged from
Phases 1–3).

## 6. Rules — Restoring a failure-log entry's link values

### R8 — A failure-log entry's recorded link values are re-applied before the re-index

When Phase 1 replays a failure-log entry that records `commit_refs` or `references` — written by a
step that failed after the object had been re-PUT, which cleared its annotations
(`p12-t47-annotation-dual-write` R13) — it restores them to the object's annotations before
re-indexing, so the rebuilt vector metadata is derived from the restored values: `commit_refs` as
the union of the entry's copy and the current annotation, `references` only while the entry's
recorded `last_edited_ulid` still equals the artifact's current one. An entry that records neither
field leaves the annotations exactly as they are. Grouping of several entries for one artifact,
the supersession test and the tokenless case are stated in `arkeology.tools.reconcile` §
reconcile_index.

**Example**

- Given an overwrite whose object write landed and whose annotation write failed, leaving a
  failure-log entry with fifteen `commit_refs` and an object with no annotations, when
  `reconcile_index` runs, then the `commit_refs` annotation holds all fifteen again and the rebuilt
  vector metadata carries all fifteen (under the 20-entry cap of R3).
- Given an entry that records no link field, when it is replayed, then the object's annotations are
  unchanged.

Source: FR-54; arkeology.tools.reconcile

## 7. Boundaries

**Always:**
- The sole source of `commit_refs` / `references` during re-index is the object's S3 annotations
  (R1), after any failure-log entry's recorded values have been re-applied (R8).
- Reuse `annotations.read_link_annotations` (T47) — do not re-implement the read or the decode
  logic.

**Ask First:**
- Nothing — behaviour fixed by ADR-011.

**Never:**
- Do not read `commit_refs` / `references` from S3 user-defined metadata (they are no longer there
  after T47).
- Do not read either link field back from vector metadata, and do not fall back to it when the
  annotation read fails.
- Do not rebuild an artifact whose annotation read failed with its link fields omitted (R4); DO let
  a `CredentialError` propagate and abort.
- Do not change the reconcile response schema.

## 8. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_reconcile.py` | Modify | Add the "reads annotations not S3 metadata" regression test (Red) + clean-state + failed-read-fails-the-artifact + failure-log link-restore tests |
| `src/arkeology/tools/reconcile.py` | Modify | Add `s3` param to `_reindex_artifact`; read link fields via `annotations.read_link_annotations` (annotation only, raising on failure); drop the `coerce_list_field(..., "commit_refs")` source; pass `s3` at both call sites; propagate `CredentialError`; in Phase 1, re-apply an entry's recorded `commit_refs` / `references` to the annotations before re-indexing (R8) |
| `tests/integration/test_tools_reconcile.py` | Modify | Real-AWS: write + backfill via `link_metadata` → drop vectors → reconcile → assert both fields restored — Red for integration |

### Contracts

- `docs/contracts/modules/arkeology.tools.reconcile.md` § reconcile_index — the lossless link-field rebuild from the annotation, the capped `commit_refs`, a failed annotation read failing one artifact, `credential_error` abandoning the run, and the restore of a failure-log entry's link values (R1, R3–R5, R8).
- `docs/contracts/data/s3-annotations.artifact.md` § read_link_annotations and § Compatibility Guarantees — the annotation as the sole read source with no fallback to the vector copy, and the raise-never-degrade read (R1, R4).
- `docs/contracts/data/s3vectors.artifact.md` § cap_commit_refs_for_vectors and § Storage Shape — the 20-entry `commit_refs` copy and no `references` in the rebuilt metadata (R3).

### Testing Approach

**TDD cycle — unit test first, then implementation:**

`tests/unit/test_tools_reconcile.py` (Red) → `src/arkeology/tools/reconcile.py` (Green). Requires the
T45 moto annotation self-mock.

New / modified unit tests:
- `test_reindex_restores_link_fields_from_annotations` — object has `commit_refs` / `references`
  annotations and NO corresponding S3 user-metadata keys; delete its vectors; `reconcile_index` →
  rebuilt vector metadata carries the annotation's `commit_refs` and no `references` key (R3) (fails
  before implementation because current code reads S3 metadata → this is the Red proof).
- `test_reindex_clean_state_omits_empty_link_fields` — object with no link annotations → rebuilt
  metadata omits both keys; no error.
- `test_reindex_annotations_unavailable_fails_the_artifact` — patch the annotation read to raise
  `AnnotationUnavailableError` for one artifact → that artifact is in `failed` with no vector
  written for it; another artifact in the same run is reconciled (R4).
- `test_reindex_ignores_vector_copy` — annotations absent, existing vector metadata carries
  `commit_refs` → rebuilt metadata carries no `commit_refs` (R1).
- `test_failure_log_entry_link_values_restored` — failure-log entry carrying `commit_refs` for an
  object with no annotations → after reconcile the annotation holds them and the rebuilt metadata
  carries them; an entry carrying neither field leaves the annotations unchanged (R8).
- `test_failure_log_replay_and_orphan_scan_both_restore` — both `_reindex_artifact` call sites pass
  `s3` and restore link fields.
- Existing scope-gate / Phase-3 dangling tests continue to pass unchanged.

**Integration:** end-to-end reconcile-survival (shared with T49's integration intent): write →
`link_metadata` backfill → force re-index → assert the rebuilt vector metadata carries
`commit_refs` and no `references`, and both annotations still hold their values.
