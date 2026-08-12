---
type: spec
title: T47 — Annotation Dual-Write in the Write Path + Tier-3 Overwrite Preservation
description: Write commit_refs and references to S3 object annotations (durable-first, before vectors) in the write path, and on an overwriting tier-3 write read-forward the prior commit_refs/references and re-apply them to both stores because PutObject clears annotations. No re-embed. last_edited_ulid stays in user-defined metadata.
tags: []
timestamp: 2026-07-03T00:00:00Z
okf_version: "0.1"
feature: p12-t47-annotation-dual-write
status: ready
phase: 12
task: 47
references:
  - docs/architecture-decisions/adr-2026-07-03-annotation-backed-link-storage.md
  - docs/architecture-decisions/adr-2026-07-03-artifact-cross-referencing.md
  - docs/specs/p12-t45-s3-annotation-client.md
  - docs/specs/p12-t46-references-field.md
  - docs/planning-artifacts/prd.md
authored:
  by: "architect"
  date: "2026-07-03"
revised:
  by: "tech-writer"
  date: "2026-07-04"
---

# T47 — Annotation Dual-Write in the Write Path + Tier-3 Overwrite Preservation

> **Dependency note (T55):** moving `commit_refs`/`references` off S3 user-defined metadata to
> annotations *shrinks* the S3 user-metadata size budget consumption, but both fields remain
> *filterable* list fields in vector metadata and so still count against the S3 Vectors 2 KB
> filterable-metadata budget. The pre-write budget check that measures both (representation-driven, so
> it stays correct whichever order T46/T47/T55 land in) is specced in
> `docs/specs/p12-t55-metadata-validation.md` (T55), which must land before/with this task.

<!-- SCOPE BLOCK — frozen after approval -->

## TL;DR

Make the write path persist `commit_refs` and `references` to **S3 object annotations** (the durable
copy, ADR-011), written after `PutObject` and before `put_vectors_batch` (durable-first,
recoverable-state ordering). On an overwriting tier-3 write, read-forward the artifact's existing
`commit_refs` / `references` and re-apply them to both annotations and vector metadata — required
because `PutObject` clears annotations. No content re-embed is triggered by the annotation write.
`last_edited_ulid` stays in user-defined metadata, set atomically at `PutObject`. (FR-54, FR-55,
AC-60.)

> **Revised 2026-07-04 (tech-writer).** Two corrections to the shipped
> behaviour vs. the original scope below: (1) the overwrite read-forward reads the **union of both
> durable stores** — the S3 annotation copy AND the current vector-metadata copy (helper
> `annotations.read_current_link_fields`) — not the vector metadata alone, so a value that lives
> only in the annotation (e.g. after a partial `link_metadata` dual-write) is never dropped; (2) the
> T55 metadata budget check (Step 3c) **re-runs a second time** after this read-forward merge
> enlarges `vector_metadata`, before any `put_object` / `put_vectors_batch`, because the merge can
> push the vector filterable/total budgets over their limit even when the supplied values alone did
> not. Both corrections are reflected in the Requirements/Boundaries sections below.
>
> **Revised 2026-07-06 (architect, shipped in `7a697dd`).** A third correction, layered on top of
> the two above: the read-forward-and-union behaviour described throughout this spec — here and in
> the Requirements/Boundaries sections below — now applies to **`commit_refs` only**. `references`
> is no longer read forward or merged on an overwriting write; it is **replaced** outright with
> exactly the value supplied to that call (a call supplying no `references` clears it). This
> supersedes Story 2's "resulting `references` is the union" acceptance criterion below and the
> corresponding Requirements/Boundaries wording — see the notes at each affected location. Full
> semantics: `docs/specs/p12-t46-references-field.md`'s forward-pointer note; rationale: ADR-011
> decision 4.

## Problem Statement

ADR-011 moves the durable copy of the mutable link fields to S3 object annotations so
`reconcile_index` no longer drops them. Two consequences land on the write path: (1) the write must
now write those annotations (they cannot be set during `PutObject`, only after upload); and (2)
overwriting an object **wipes its annotations**, so a tier-3 living-document update would silently
lose the accumulated `commit_refs` / `references` trail unless the write reads them forward and
re-applies them. Silent loss of an append-only link trail is exactly what Arkeology exists to prevent.

## User Stories

### Story 1 — Write persists link fields to annotations (P1)

**Acceptance criteria:**
- Given `write_artifact(commit_refs=["abc1234"], references=["a-1"])`, when it succeeds then the
  S3 object carries a `commit_refs` annotation decoding to `["abc1234"]` and a `references`
  annotation decoding to `["a-1"]`, and vector metadata carries both as `list[str]`.
- Given `commit_refs=[]` and `references=[]`, when the write succeeds then no `commit_refs` /
  `references` annotation is present (empty → annotation absent, mirroring the omit-when-empty rule).
- Given a successful write, then Bedrock `embed` is called only for content embedding — the
  annotation write triggers no additional embed call.
- Given `last_edited_ulid`, then it remains in S3 user-defined metadata (set at `PutObject`) and is
  NOT moved to an annotation.

### Story 2 — Tier-3 overwrite preserves prior link fields (P1)

An artifact was written, then had `commit_refs` backfilled. A later tier-3 content update
(same type + title, `overwrite=True`) must not lose those links.

**Acceptance criteria:**
- Given a tier-3 artifact whose vector metadata carries `commit_refs=["abc1234"]` and
  `references=["a-1"]`, when `write_artifact` overwrites it (same type + title) then after the write
  both the S3 annotations and the vector metadata carry `["abc1234"]` and `["a-1"]` respectively —
  even though the underlying `PutObject` cleared the annotations. (AC-60)
- Given the overwriting write also supplies `references=["b-2"]`, then the resulting `references` is
  the union `["a-1", "b-2"]` (input merged with read-forward, deduplicated, order-preserving).
  **Superseded 2026-07-06 (not yet shipped) — see the note above:** the resulting `references` is
  now exactly `["b-2"]` (replace, not union); `commit_refs` is unaffected by this change and still
  unions to `["abc1234"]` unchanged, or accretes normally if also supplied on this call.
- Given the overwriting write, then no error is returned and the object body reflects the new content.

### Story 3 — Durable-first ordering enables self-heal (P1)

**Acceptance criteria:**
- Given the write path, then the `commit_refs` / `references` annotations are written **before**
  `put_vectors_batch`, so that if the vector write fails the durable annotation side is already
  correct and a later `reconcile_index` rebuilds vectors from it (T48).

## Requirements

- WHEN building `s3_metadata` THE SYSTEM SHALL NOT include `commit_refs` (it moves to an annotation);
  it SHALL keep `last_edited_ulid`, `source_artifacts`, and all identity fields in user-defined
  metadata unchanged.
- WHEN a write succeeds at `PutObject` THE SYSTEM SHALL write the `commit_refs` and `references`
  annotations (non-empty only) **after** `PutObject` and **before** `put_vectors_batch`.
- WHEN an artifact is being overwritten (`is_existing and overwrite`) THE SYSTEM SHALL read-forward
  the existing `commit_refs` and `references` as the **union of both durable stores** — the S3
  annotation copy and the current vector metadata (via `annotations.read_current_link_fields`:
  neither store is sole authority) — and merge them (union, dedup,
  order-preserving) with the values supplied to this write.

  > **Shipped in `7a697dd`:** this union read-forward applies to **`commit_refs` only**.
  > `references` is not read forward and not merged — it is replaced outright with exactly the
  > value supplied to this call (which may be empty, clearing the field). See
  > `docs/specs/p12-t46-references-field.md`'s forward-pointer note.
- WHEN the read-forward merge above enlarges `vector_metadata` THE SYSTEM SHALL re-run the T55
  metadata budget check (`check_metadata_budgets`) a second time, after the merge and before any
  `put_object` / `put_vectors_batch`, because the union can push the vector filterable/total budgets
  over their limit even when the values originally supplied to this write did not.
- WHEN the merged link values are known THE SYSTEM SHALL use them for BOTH the vector metadata
  (`list[str]`, omitted when empty) and the annotations (comma-joined payload, annotation deleted
  when empty).
- WHEN the annotation write triggers embedding or content mutation THE SYSTEM SHALL NOT — annotations
  are metadata-only and never re-embed.
- WHEN an annotation call raises `CredentialError` THE SYSTEM SHALL return a structured
  `credential_error` including `artifact_id` — never a raw exception.
- WHEN an annotation call raises an annotation-unavailable / access-denied error THE SYSTEM SHALL
  defer to the graceful-handling behaviour specified in T52 (structured error / degraded warning;
  the core content + vector store still functions) — this task adds the annotation write and the
  error hook; the full taxonomy is T52.

## Boundaries

**Always:**
- Ordering is durable-first: `PutObject` → write annotations → `put_vectors_batch`. This mirrors
  `delete_artifact`'s recoverable-state reasoning (ADR-011 decision 1/2).

> **Forward-pointer note (2026-07-06, shipped in `7a697dd`).** The `PutObject` above is now a
> conditional write guarded by an ETag compare-and-swap (`IfMatch`); the annotation writes that
> follow it use the object's new ETag as `ObjectIfMatch`. A detected concurrent change (HTTP 412)
> triggers a bounded retry (~3 attempts: re-read, re-merge, re-write) before returning a structured
> `conflict` error, rather than silently letting a stale read-forward clobber a newer merge.
> `put_vectors_batch` stays unconditional (no S3 Vectors CAS surface exists) — it is the
> recoverable, derived copy, healed by `reconcile_index` if needed. See
> `docs/specs/p2-t7-write-artifact.md`'s equivalent forward-pointer note; rationale: ADR-011
> decision 6.

- Read-forward source is the **union of both durable stores** — the S3 annotation copy and the
  vector metadata (`get_vectors`, which `PutObject` does not touch) — via
  `annotations.read_current_link_fields`. Neither store is sole authority:
  an annotation-unavailable deployment can hold values in vector metadata only, and a partial
  dual-write can leave the annotation copy ahead of the vector copy.
  **Shipped in `7a697dd`:** this union read-forward now applies to `commit_refs` only —
  `references` is replaced outright from the supplied value instead (see the Requirements section
  above and `docs/specs/p12-t46-references-field.md`'s forward-pointer note).
- Merge semantics: `list(dict.fromkeys(read_forward + supplied))` — order-preserving dedup, same as
  `commit_refs` merge in `link_commit`. (Applies to `commit_refs` only as of 2026-07-06 — see above.)
- Annotation encoding is comma-joined UTF-8 payload, one annotation per field
  (`AnnotationName="commit_refs"`, `AnnotationName="references"`); empty list → delete the annotation.
  Centralise the constants + encode/decode/apply/read helpers in a new `src/arkeology/annotations.py`.

**Ask First:**
- Nothing — mechanics are fixed by ADR-011.

**Never:**
- Do not set annotations during `PutObject` (the API does not allow it — annotations are set only
  after upload).
- Do not write `commit_refs` / `references` into S3 user-defined metadata (they are annotations now).
- Do not re-embed on the annotation write or on read-forward.
- Do not shift `last_edited_ulid` — it is set once per write at `PutObject`.
- Do not invert a durably-written object + successfully-indexed vectors into a hard failure over a
  best-effort annotation problem beyond the CredentialError / T52-taxonomy cases.

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_annotations.py` | Create | Tests for the `annotations.py` encode/decode/apply/read helpers — Red first |
| `src/arkeology/annotations.py` | Create | `COMMIT_REFS_ANNOTATION`, `REFERENCES_ANNOTATION`; `encode_link_list`/`decode_link_list`; `apply_link_annotations(s3, key, *, commit_refs, references)`; `read_link_annotations(s3, key)` |
| `tests/unit/test_tools_write.py` | Modify | Tests: annotations written after PutObject / before put_vectors_batch (call-order spy); overwrite read-forward + merge; empty → annotation absent; no extra embed — Red first |
| `src/arkeology/tools/write.py` | Modify | Remove `commit_refs` from `s3_metadata`; add read-forward on overwrite; write annotations between PutObject and put_vectors_batch using merged values |
| `tests/integration/test_tools_write.py` | Modify | Real-AWS overwrite-preservation round-trip — Red for integration |

## Testing Approach

**TDD cycle — test file before implementation file in each pair:**

1. **`test_annotations.py` → `annotations.py`** — `encode_link_list(["a","b"]) == "a,b"`;
   `decode_link_list("a,b") == ["a","b"]`; `decode_link_list("") == []`;
   `apply_link_annotations` puts non-empty fields and deletes empty ones (spy on the
   `put_object_annotation` / `delete_object_annotation` client calls); `read_link_annotations`
   returns `([], [])` when annotations are absent.

2. **`test_tools_write.py` → `write.py`** (moto self-mock from T45 must model overwrite-wipe):
   - Fresh write with `commit_refs=["abc1234"], references=["a-1"]` → both annotations present and
     decode correctly; vector metadata carries both as lists.
   - Call-order assertion: `put_object` is called before the annotation writes, which are called
     before `put_vectors_batch` (use `mocker.spy` + a recorded call sequence).
   - Empty lists → no annotation written for that field.
   - Overwrite: seed an existing tier-3 artifact whose vectors carry `commit_refs=["abc1234"]` and
     `references=["a-1"]`; overwrite it (same type+title, `overwrite=True`, supplying
     `references=["b-2"]`); assert post-write annotations + vector metadata carry `["abc1234"]` and
     `["a-1","b-2"]`. This is the core AC-60 test and depends on the T45 moto overwrite-wipe model.
   - Bedrock `embed` call count is unchanged by the annotation write (spy).
   - `CredentialError` from `put_object_annotation` → structured `credential_error` with `artifact_id`.

3. **Integration** — write → backfill via `link_metadata` (or direct annotation) → overwrite the
   tier-3 artifact → assert link fields survive in both stores against real AWS.

## Open Questions

*(none — annotation-unavailable / AccessDenied degrade taxonomy is owned by T52 and cross-referenced
here; this task provides the annotation write and the error hook)*
