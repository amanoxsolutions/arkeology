---
type: Spec
id: p12-t47-annotation-dual-write
title: T47 — Annotation Dual-Write in the Write Path + Tier-3 Overwrite Preservation
description: Write commit_refs and references to S3 object annotations (durable-first, before vectors) in the write path; on an overwriting write read-forward the prior commit_refs from the annotation and re-apply it because PutObject clears annotations, while references is replaced by the supplied value. A failure after the object write is an error whose failure-log entry holds the link values. No re-embed. last_edited_ulid stays in user-defined metadata.
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
  - resource: docs/contracts/modules/arkeology.tools.write.md
    title: arkeology.tools.write
  - resource: docs/contracts/data/s3-annotations.artifact.md
    title: s3-annotations.artifact
  - resource: .docs/reviews/architecture-review-2026-11-15-arkeology-phases-9-10-12.md
    title: "Architecture review — Arkeology, plan phases 9, 10 and 12"
  - resource: docs/contracts/data/s3vectors.artifact.md
    title: s3vectors.artifact
  - resource: docs/contracts/data/s3.artifact.md
    title: s3.artifact
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

# T47 — Annotation Dual-Write in the Write Path + Tier-3 Overwrite Preservation

## TL;DR

Make the write path persist `commit_refs` and `references` to **S3 object annotations** (the durable
copy, ADR-011), written after `PutObject` and before `put_vectors_batch` (durable-first,
recoverable-state ordering). On any overwriting write — a tier-3 living-document update and an
explicit tier-2 replacement alike — read-forward the artifact's existing `commit_refs` and re-apply it to both annotations and vector metadata — required because `PutObject`
clears annotations — while `references` is replaced outright with exactly the value supplied to that
call. No content re-embed is triggered by the annotation write. `last_edited_ulid` stays in
user-defined metadata, set atomically at `PutObject`. (FR-54, FR-55, AC-60.)

## 1. Problem Statement

ADR-011 moves the durable copy of the mutable link fields to S3 object annotations so
`reconcile_index` no longer drops them. Two consequences land on the write path: (1) the write must
now write those annotations (they cannot be set during `PutObject`, only after upload); and (2)
overwriting an object **wipes its annotations**, so any overwriting write — a tier-3
living-document update and an explicit tier-2 replacement alike — would silently lose the
accumulated `commit_refs` trail unless the write reads it forward and re-applies it. Silent loss of
an append-only link trail is exactly what Arkeology exists to prevent. `references` is not read
forward: an overwrite replaces it with exactly the value supplied to that call. For example, an
artifact was written, then had `commit_refs` backfilled; a later tier-3 content update (same type +
title, `overwrite=True`) must not lose those links.

All three stories this spec states are P1: the write persists link fields to annotations; an
overwrite preserves prior `commit_refs`; durable-first ordering enables self-heal.

**Dependency note (T55):** moving `commit_refs`/`references` off S3 user-defined metadata to
annotations *shrinks* the S3 user-metadata size budget consumption. `commit_refs` stays a
*filterable* list field in vector metadata, capped at 20 entries (T58), and so still counts against
the S3 Vectors 2 KB filterable-metadata budget; `references` is in vector metadata nowhere. The
pre-write budget check (representation-driven, so it measures whatever the assembled metadata
holds) is specced in `docs/specs/p12-t55-metadata-validation.md` (T55), which must land before/with
this task.

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

On an overwriting write the `PutObject` is a conditional write guarded by an ETag compare-and-swap
(`IfMatch`); the annotation writes that follow it use the object's new ETag as `ObjectIfMatch`. A
detected concurrent change (HTTP 412) from either call retries the whole cycle — re-read, re-merge,
re-write — up to `CAS_MAX_ATTEMPTS` (3), rather than letting a stale read-forward clobber a newer
merge. Exhausting the cycle returns `conflict` when nothing is durable and `partial_write` when the
final attempt's `PutObject` landed, as `arkeology.tools.write` § write_artifact states.
`put_vectors_batch` stays unconditional (no S3 Vectors CAS surface exists) — it is the recoverable,
derived copy, healed by `reconcile_index` if needed.

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
`apply_link_annotations` always receives the full, uncapped value of both fields, so the annotation
copy stays complete.

**Example**

- Given `write_artifact(commit_refs=["abc1234"], references=["a-1"])`, when it succeeds, then the
  S3 object carries a `commit_refs` annotation decoding to `["abc1234"]` and a `references`
  annotation decoding to `["a-1"]`; vector metadata carries `commit_refs` only and no `references`.

Source: adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal.md D2; p12-t58-commit-refs-cap-references-removal R1, R4

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
`link_metadata`.

The read goes through `annotations.read_link_annotations`, which consults the annotation and nothing
else: the S3 object annotation is the **sole** source of truth for both link fields, and the vector
`commit_refs` copy is a derived filter index — still written, never read back and never an
authority.

That read **raises** on failure rather than returning empty (R12). Absence of an annotation returns
a true empty; a failed read never masquerades as one, because an empty value on a read-modify-write
path would be written straight back over good link data.

Because each attempt's own `put_object` clears the object's annotations, the read-forward value
**accumulates across compare-and-swap attempts** rather than being recomputed per attempt. A retry
re-reads the annotations as absent, so replacing rather than accumulating would silently discard
what the earlier attempt had already read forward.

**Example**

- Given a tier-3 artifact whose `commit_refs` annotation carries `["abc1234"]`, when
  `write_artifact` overwrites it (same type + title) without supplying `commit_refs`, then after the
  write both the `commit_refs` annotation and the vector metadata carry `["abc1234"]` — even though
  the underlying `PutObject` cleared the annotations.
- Given the same artifact whose annotation read fails with `AnnotationUnavailableError`, when
  `write_artifact` overwrites it, then the write returns `annotation_unavailable` before any
  `PutObject` and writes nothing.
- Given the overwriting write, then no error is returned and the object body reflects the new
  content.

Source: AC-60, adr-2026-07-03-annotation-backed-link-storage "Revision — 2026-09-05"

### R9 — `references` is replaced, not read forward, on overwrite

The read-forward and merge of R8 apply to **`commit_refs` only**. `references` is not read forward
and not merged on an overwriting write — it is **replaced** outright with exactly the value supplied
to that call (which may be empty, clearing the field), as `p12-t46-references-field` R9 states.

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

### R12 — Annotation-unavailable and access-denied errors return `annotation_unavailable`

When an annotation call raises `AnnotationUnavailableError` (annotations unavailable, or access
denied), `write_artifact` returns `annotation_unavailable` — the one code every tool returns for
that condition (`s3-annotations.artifact` § Compatibility Guarantees) — never a success and never a
warning. Raised by the read-forward of an overwriting write (R8), it returns before anything is
written and appends no failure-log entry; raised by the annotation write after `PutObject`, it
carries the durability facts of R13.

Source: FR-57

### R13 — Every failure after the object write is an error, and its failure-log entry holds the links

When any step after `PutObject` has landed fails — the annotation write, a compare-and-swap retry's
budget re-check, the vector write — `write_artifact` returns an error code, never success:
`credential_error` or `annotation_unavailable` where the cause is diagnosable, `partial_write`
otherwise (`arkeology.tools.write` § write_artifact gives each code's terms). It appends a
failure-log entry, and the response carries `failure_logged`, `true` when that append succeeded and
`false` when it failed. The entry records the full, uncapped `commit_refs` and `references` the
write was applying — each omitted when empty, where absence means "nothing to restore", never
"clear the field" — and the `last_edited_ulid` this write generated, because `PutObject` has
already cleared the object's annotations and the entry is the only place left to restore them from
(`p12-t48-reconcile-from-annotations` R8).

**Example**

- Given an overwrite of a tier-3 artifact whose annotations hold fifteen `commit_refs`, when
  `PutObject` lands and the annotation write then fails with `AnnotationUnavailableError`, then the
  response is `annotation_unavailable` with `failure_logged: true`, and the appended entry's
  `commit_refs` holds all fifteen plus any supplied on this call.
- Given the same failure where the failure-log append itself also fails, then the response carries
  `failure_logged: false` and its message does not claim an entry was recorded.

Source: FR-57; arkeology.tools.write

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
- Do not report a write whose durable link write failed as a success, with or without a warning,
  and do not fall back to any other store for the link fields (R12, R13).

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

- `docs/contracts/modules/arkeology.tools.write.md` § write_artifact — the store ordering, the overwrite read-forward and compare-and-swap cycle, the accrete/replace split, and every error code with its failure-log terms (R2, R3, R8–R13).
- `docs/contracts/data/s3-annotations.artifact.md` § apply_link_annotations, § read_link_annotations and § Compatibility Guarantees — the payload encoding with an empty list deleting the annotation, the `if_match` guard, the raise-never-degrade read, and the overwrite wipe the read-forward answers (R2–R6, R8, R12).
- `docs/contracts/data/s3vectors.artifact.md` § cap_commit_refs_for_vectors and § Storage Shape — the capped `commit_refs` copy and no `references` in vector metadata (R5, R6).
- `docs/contracts/data/s3.artifact.md` § Storage Shape and § check_metadata_budgets — `last_edited_ulid` kept in object metadata with no link field there, and the budget re-run after the merge (R1, R10).

### Testing Approach

**TDD cycle — test file before implementation file in each pair:**

1. **`test_annotations.py` → `annotations.py`** — `encode_link_list(["a","b"]) == "a,b"`;
   `decode_link_list("a,b") == ["a","b"]`; `decode_link_list("") == []`;
   `apply_link_annotations` puts non-empty fields and deletes empty ones (spy on the
   `put_object_annotation` / `delete_object_annotation` client calls); `read_link_annotations`
   returns `([], [])` when annotations are absent.

2. **`test_tools_write.py` → `write.py`** (moto self-mock from T45 must model overwrite-wipe):
   - Fresh write with `commit_refs=["abc1234"], references=["a-1"]` → both annotations present and
     decode correctly; vector metadata carries `commit_refs` as a list and no `references` key.
   - Call-order assertion: `put_object` is called before the annotation writes, which are called
     before `put_vectors_batch` (use `mocker.spy` + a recorded call sequence).
   - Empty lists → no annotation written for that field.
   - Overwrite: seed an existing tier-3 artifact whose annotations carry `commit_refs=["abc1234"]`
     and `references=["a-1"]`; overwrite it (same type+title, `overwrite=True`, supplying
     `references=["b-2"]`); assert the post-write `commit_refs` annotation and vector metadata carry
     `["abc1234"]` and the `references` annotation carries exactly `["b-2"]` (R9). This is the core
     AC-60 test and depends on the T45 moto overwrite-wipe model.
   - Bedrock `embed` call count is unchanged by the annotation write (spy).
   - `CredentialError` from `put_object_annotation` → structured `credential_error` with `artifact_id`.
   - `AnnotationUnavailableError` from the read-forward → `annotation_unavailable`, no `put_object`
     call and no failure-log entry (R12).
   - `AnnotationUnavailableError` from the annotation write after `put_object` →
     `annotation_unavailable` with `failure_logged: true`, and the failure-log entry carries the full
     `commit_refs`, `references` and `last_edited_ulid` the write was applying (R13); with the append
     patched to fail → `failure_logged: false`.

3. **Integration** — write → backfill via `link_metadata` (or direct annotation) → overwrite the
   tier-3 artifact → assert, against real AWS, that `commit_refs` survives in both the annotation
   and the vector metadata, and that `references` holds exactly the value the overwrite supplied.
