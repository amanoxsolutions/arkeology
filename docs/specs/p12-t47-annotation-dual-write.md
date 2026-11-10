---
type: Spec
id: p12-t47-annotation-dual-write
title: T47 — Annotation Dual-Write in the Write Path + Tier-3 Overwrite Preservation
description: Write commit_refs and references to S3 object annotations (durable-first, before vectors) in the write path, and on an overwriting tier-3 write read-forward the prior commit_refs/references and re-apply them to both stores because PutObject clears annotations. No re-embed. last_edited_ulid stays in user-defined metadata.
tags: []
status: stable
okf_version: "0.2"
sources:
  - resource: docs/architecture-decisions/adr-2026-07-03-annotation-backed-link-storage.md
    title: Annotation-Backed Durable Storage for Mutable Link Fields (commit_refs + references)
    last_modified: 2026-09-29T00:00:00Z
  - resource: docs/architecture-decisions/adr-2026-07-03-artifact-cross-referencing.md
    title: Artifact Cross-Referencing — First-Class references Field, Migration Rewrite, and referenced_by Warning
    last_modified: 2026-09-29T00:00:00Z
  - resource: docs/specs/p12-t45-s3-annotation-client.md
    title: T45 — S3 Object Annotation Client Support + moto Self-Mock Extension
    last_modified: 2026-07-03T00:00:00Z
  - resource: docs/specs/p12-t46-references-field.md
    title: T46 — references First-Class Field on Artifact + write/read/list Surfacing + Filter
    last_modified: 2026-08-17T00:00:00Z
  - resource: docs/planning-artifacts/requirements.md
    title: Arkeology — Requirements
    last_modified: 2026-09-24T00:00:00Z
generated:
  by: "axians-architect/claude-opus-4.8"
  at: 2026-07-03T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-09T18:46:42Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
---

# T47 — Annotation Dual-Write in the Write Path + Tier-3 Overwrite Preservation

## TL;DR

Make the write path persist `commit_refs` and `references` to **S3 object annotations** (the durable
copy, ADR-011), written after `PutObject` and before `put_vectors_batch` (durable-first,
recoverable-state ordering). On an overwriting tier-3 write, read-forward the artifact's existing
`commit_refs` and re-apply it to both annotations and vector metadata — required because `PutObject`
clears annotations — while `references` is replaced outright with exactly the value supplied to that
call. No content re-embed is triggered by the annotation write. `last_edited_ulid` stays in
user-defined metadata, set atomically at `PutObject`. (FR-54, FR-55, AC-60.)

## 1. Problem Statement

ADR-011 moves the durable copy of the mutable link fields to S3 object annotations so
`reconcile_index` no longer drops them. Two consequences land on the write path: (1) the write must
now write those annotations (they cannot be set during `PutObject`, only after upload); and (2)
overwriting an object **wipes its annotations**, so a tier-3 living-document update would silently
lose the accumulated `commit_refs` / `references` trail unless the write reads them forward and
re-applies them. Silent loss of an append-only link trail is exactly what Arkeology exists to prevent.
For example, an artifact was written, then had `commit_refs` backfilled; a later tier-3 content
update (same type + title, `overwrite=True`) must not lose those links.

All three stories this spec states are P1: the write persists link fields to annotations; a tier-3
overwrite preserves prior link fields; durable-first ordering enables self-heal.

**Dependency note (T55):** moving `commit_refs`/`references` off S3 user-defined metadata to
annotations *shrinks* the S3 user-metadata size budget consumption, but both fields remain
*filterable* list fields in vector metadata and so still count against the S3 Vectors 2 KB
filterable-metadata budget. The pre-write budget check that measures both (representation-driven, so
it stays correct whichever order T46/T47/T55 land in) is specced in
`docs/specs/p12-t55-metadata-validation.md` (T55), which must land before/with this task.

## 2. Rules — Writing the link annotations

### R1 — Link fields leave S3 user-defined metadata; `last_edited_ulid` stays

When building `s3_metadata`, the write path does not include `commit_refs` (it moves to an
annotation); it keeps `last_edited_ulid`, `source_artifacts`, and all identity fields in
user-defined metadata unchanged. `last_edited_ulid` remains in S3 user-defined metadata (set at
`PutObject`) and is NOT moved to an annotation.

### R2 — Durable-first ordering

When a write succeeds at `PutObject`, the system writes the `commit_refs` and `references`
annotations (non-empty only) **after** `PutObject` and **before** `put_vectors_batch`. The ordering
is durable-first: `PutObject` → write annotations → `put_vectors_batch`, mirroring
`delete_artifact`'s recoverable-state reasoning — if the vector write fails, the durable annotation
side is already correct and a later `reconcile_index` rebuilds vectors from it (T48).

Source: ADR-011 decision 1/2

### R3 — Compare-and-swap guard on `PutObject` and the annotation writes

Forward-pointer (2026-07-06, shipped in `7a697dd`): the `PutObject` is a conditional write guarded
by an ETag compare-and-swap (`IfMatch`); the annotation writes that follow it use the object's new
ETag as `ObjectIfMatch`. A detected concurrent change (HTTP 412) triggers a bounded retry (~3
attempts: re-read, re-merge, re-write) before returning a structured `conflict` error, rather than
silently letting a stale read-forward clobber a newer merge. `put_vectors_batch` stays unconditional
(no S3 Vectors CAS surface exists) — it is the recoverable, derived copy, healed by
`reconcile_index` if needed. See `docs/specs/p2-t7-write-artifact.md`'s equivalent forward-pointer
note.

Source: ADR-011 decision 6

### R4 — Annotation encoding; empty list means no annotation

Annotation encoding is a comma-joined UTF-8 payload, one annotation per field
(`AnnotationName="commit_refs"`, `AnnotationName="references"`); an empty list deletes the
annotation.

**Example**

- Given `commit_refs=[]` and `references=[]`, when the write succeeds, then no `commit_refs` /
  `references` annotation is present (empty → annotation absent, mirroring the omit-when-empty rule).

### R5 — What a write stores in each store

A write persists `commit_refs` and `references` to S3 object annotations. Vector metadata carries
`commit_refs` only, capped to the most-recently-appended 20 entries, and never carries `references`.
The annotation write behaviour
described throughout this spec (durable-first ordering, CAS-guarded overwrite,
`apply_link_annotations` always receiving the full, uncapped value) is completely unaffected and
remains authoritative: the annotation copy of both fields stays complete and uncapped. See
`docs/specs/p12-t58-commit-refs-cap-references-removal.md`.

**Example**

- Given `write_artifact(commit_refs=["abc1234"], references=["a-1"])`, when it succeeds, then the
  S3 object carries a `commit_refs` annotation decoding to `["abc1234"]` and a `references`
  annotation decoding to `["a-1"]`; vector metadata carries `commit_refs` only and no `references`.

Source: adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal.md D2

### R6 — Merged link values go to both stores

When the merged link values are known, the system uses them for BOTH the vector metadata
(`list[str]`, omitted when empty) and the annotations (comma-joined payload, annotation deleted when
empty).

### R7 — No re-embed

When the annotation write runs, it triggers no embedding and no content mutation — annotations are
metadata-only and never re-embed.

**Example**

- Given a successful write, then Bedrock `embed` is called only for content embedding — the
  annotation write triggers no additional embed call.

## 3. Rules — Overwrite read-forward

### R8 — `commit_refs` is read forward from the annotation and merged on overwrite

When an artifact is being overwritten (`is_existing and overwrite`), the system reads forward the
existing `commit_refs` and merges it with the values supplied to this write: union, dedup,
order-preserving — `list(dict.fromkeys(read_forward + supplied))`, same as the `commit_refs` merge in
`link_commit`.

The read goes through `annotations.read_link_annotations`, which consults the annotation and nothing
else: the S3 object annotation is the **sole** source of truth for both link fields, and the vector
`commit_refs` copy is a derived filter index — still written, never read back. The read-forward does
not source its prior value from a union of both stores, and the vector-metadata copy carries no
authority. The helpers `read_current_link_fields` and its `_read_vector_link_fields` half no longer
exist anywhere in the codebase.

That read **raises** on failure rather than returning empty. Absence of an annotation still returns
a true empty; a failed read never masquerades as one, because an empty value on a read-modify-write
path would be written straight back over good link data.

Because each attempt's own `put_object` clears the object's annotations, the read-forward value
**accumulates across compare-and-swap attempts** rather than being recomputed per attempt. A retry
re-reads the annotations as absent, so replacing rather than accumulating would silently discard
what the earlier attempt had already read forward.

**Example**

- Given a tier-3 artifact whose vector metadata carries `commit_refs=["abc1234"]` and
  `references=["a-1"]`, when `write_artifact` overwrites it (same type + title), then after the write
  both the S3 annotations and the vector metadata carry `["abc1234"]` and `["a-1"]` respectively —
  even though the underlying `PutObject` cleared the annotations.
- Given the overwriting write, then no error is returned and the object body reflects the new
  content.

Source: AC-60, adr-2026-07-03-annotation-backed-link-storage "Revision — 2026-09-05"

### R9 — `references` is replaced, not read forward, on overwrite

Revised 2026-07-06 (shipped in `7a697dd`): the read-forward-and-union behaviour described throughout
this spec applies to **`commit_refs` only**. `references` is not read forward and not merged on an
overwriting write — it is **replaced** outright with exactly the value supplied to that call (which
may be empty, clearing the field). Full semantics: `docs/specs/p12-t46-references-field.md`'s
forward-pointer note.

**Example**

- Given the overwriting write also supplies `references=["b-2"]`, then the resulting `references` is
  exactly `["b-2"]` (replace, not union); `commit_refs` is unaffected by this and still unions to
  `["abc1234"]` unchanged, or accretes normally if also supplied on this call.

Source: ADR-011 decision 4

### R10 — The metadata budget check re-runs after the merge

When the read-forward merge enlarges `vector_metadata`, the system re-runs the T55 metadata budget
check (`check_metadata_budgets`) a second time, after the merge and before any `put_object` /
`put_vectors_batch`, because the union can push the vector filterable/total budgets over their limit
even when the values originally supplied to this write did not.

## 4. Rules — Errors

### R11 — Credential errors are structured

When an annotation call raises `CredentialError`, the system returns a structured
`credential_error` including `artifact_id` — never a raw exception.

### R12 — Annotation-unavailable and access-denied errors defer to T52

When an annotation call raises an annotation-unavailable / access-denied error, the system defers
to the graceful-handling behaviour specified in T52 (structured error / degraded warning; the core
content + vector store still functions). This spec adds the annotation write and the error hook;
the full annotation-unavailable / AccessDenied degrade taxonomy is owned by T52.

### R13 — A failed durable link write is not a success

A failed durable link write is not reported as a success: `write_artifact` returns `partial_write`
and records a failure-log entry.

## 5. Boundaries

**Always:**
- Ordering is durable-first: `PutObject` → write annotations → `put_vectors_batch` (R2).
- Centralise the annotation constants + encode/decode/apply/read helpers in a new
  `src/arkeology/annotations.py`.

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

## 6. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_annotations.py` | Create | Tests for the `annotations.py` encode/decode/apply/read helpers — Red first |
| `src/arkeology/annotations.py` | Create | `COMMIT_REFS_ANNOTATION`, `REFERENCES_ANNOTATION`; `encode_link_list`/`decode_link_list`; `apply_link_annotations(s3, key, *, commit_refs, references)`; `read_link_annotations(s3, key)` |
| `tests/unit/test_tools_write.py` | Modify | Tests: annotations written after PutObject / before put_vectors_batch (call-order spy); overwrite read-forward + merge; empty → annotation absent; no extra embed — Red first |
| `src/arkeology/tools/write.py` | Modify | Remove `commit_refs` from `s3_metadata`; add read-forward on overwrite; write annotations between PutObject and put_vectors_batch using merged values; `references` gets no vector-metadata assignment (T58) — the `vector_metadata["references"] = references` line is removed |
| `tests/integration/test_tools_write.py` | Modify | Real-AWS overwrite-preservation round-trip — Red for integration |

### Contracts

None.

### Testing Approach

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
