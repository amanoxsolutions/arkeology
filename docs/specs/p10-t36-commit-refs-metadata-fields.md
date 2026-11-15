---
type: Spec
id: p10-t36-commit-refs-metadata-fields
title: T36 — commit_refs and last_edited_ulid Metadata Fields
description: Spec to add commit_refs and last_edited_ulid as first-class metadata fields flowing through write, read, and list, enabling post-write commit annotation and time-range discovery.
tags: []
status: stable
okf_version: "0.2"
sources:
  - resource: docs/brainstorming/brainstorming-2026-06-06-artifact-commit-refs.md
    title: Artifact Commit References
    last_modified: 2026-07-03T00:00:00Z
  - resource: docs/specs/p10-t35-filter-range-operators.md
    title: T35 — Filter Range Operators ($gte / $lte)
    last_modified: 2026-06-06T00:00:00Z
  - resource: docs/contracts/modules/arkeology.tools.read.md
    title: arkeology.tools.read
  - resource: docs/architecture-decisions/adr-2026-07-03-annotation-backed-link-storage.md
    title: Annotation-Backed Durable Storage for Mutable Link Fields (commit_refs + references)
  - resource: .docs/reviews/architecture-review-2026-11-15-arkeology-phases-9-10-12.md
    title: "Architecture review — Arkeology, plan phases 9, 10 and 12"
  - resource: docs/contracts/data/s3-annotations.artifact.md
    title: s3-annotations.artifact
  - resource: docs/specs/p12-t58-commit-refs-cap-references-removal.md
    title: T58 — commit_refs Vector-Metadata Cap (20) + references Vector-Metadata Removal + propose_commit_links Multi-Section Fix
  - resource: docs/specs/p3-t10-list-artifacts.md
    title: T10 — List Artifacts Tool
  - resource: docs/planning-artifacts/requirements.md
    title: Arkeology — Requirements
  - resource: docs/contracts/modules/arkeology.tools.write.md
    title: arkeology.tools.write
  - resource: docs/contracts/modules/arkeology.tools.list.md
    title: arkeology.tools.list
  - resource: docs/contracts/data/s3.artifact.md
    title: s3.artifact
  - resource: docs/contracts/data/s3vectors.artifact.md
    title: s3vectors.artifact
generated:
  by: "axians-analyst/unknown"
  at: 2026-06-06T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-15T20:19:59Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
  - by: "axians-architect/claude-fable-5-2"
    at: 2026-11-15T20:45:07Z
---

# T36 — `commit_refs` and `last_edited_ulid` Metadata Fields

## TL;DR

Add two new metadata fields — `commit_refs: list[str]` and `last_edited_ulid: str` — to the
artifact storage and retrieval pipeline. `commit_refs` is a caller-supplied list of git
commit references stored alongside existing artifact metadata. `last_edited_ulid` is a
system-generated write-time timestamp (ULID) that enables time-range discovery of artifacts
written during a session. Both fields flow through `artifact.py`, `write.py`, `list.py`,
and `read.py`; `commit_refs` lives in the artifact's S3 object annotation, with a capped copy in
vector metadata for filtering, and `last_edited_ulid` lives in S3 object metadata and vector
metadata.

## 1. Problem Statement

There is currently no way to associate an artifact with a git commit or to discover which
artifacts were written during a given session. Adding `commit_refs` and `last_edited_ulid`
as first-class metadata fields creates the data model that the `propose_commit_links`
(`p10-t37-propose-commit-links`) and `link_metadata` (`p12-t49-link-metadata`) tools depend on.
Without these fields in place, post-write commit annotation is impossible and time-range scans
over the vector index cannot be expressed. The annotation client is specified in
`p12-t45-s3-annotation-client` and the write path's annotation write in
`p12-t47-annotation-dual-write`.

All five user stories this spec covers — `commit_refs` persisted through write, read and list;
`commit_refs` stored correctly in its S3 object annotation and in vector metadata; the `commit_refs` filter in
`list_artifacts`; `last_edited_ulid` generated on every write; and `last_edited_ulid` exposed in
list and read responses — are P1.

## 2. Rules — Storing `commit_refs`

### R1 — `commit_refs` is an optional, caller-supplied field on the `Artifact` model

`commit_refs` IS part of the `Artifact` model — it IS caller-supplied (optional, default empty
list). An agent may write an artifact with `commit_refs=["abc1234", "def5678"]`; on read, and on a
listing that asks for link fields, those refs appear in the response.

**Example**

- Given `Artifact` constructed with `commit_refs=["abc1234"]`, then it stores the value correctly.
- Given `Artifact` constructed without `commit_refs`, then it defaults to `[]`.

### R2 — `commit_refs` lives in the S3 object annotation, with a capped `list[str]` copy in vector metadata

When `commit_refs` is non-empty, the system stores the full list in the object's `commit_refs` S3
object annotation — its sole durable copy — and a `list[str]` copy of at most the 20
most-recently-appended entries in vector metadata, which serves the `$eq` filter of R6 and is never
read back. `commit_refs` is never written to user-defined S3 object metadata. When `commit_refs` is
empty, the annotation is absent and the key is omitted from vector metadata entirely (S3 Vectors
rejects empty arrays — same rule as `tags`). The annotation's encoding is stated in
`s3-annotations.artifact` § Storage Shape.

**Example**

- Given `commit_refs=["abc1234", "def5678"]`, when the artifact is written, then its
  `commit_refs` annotation carries both entries and its S3 object metadata has no `commit_refs`
  key.
- Given the same artifact, when stored in vector metadata, then `commit_refs` is
  `["abc1234", "def5678"]` (a `list[str]`) — not a comma-joined string.
- Given `commit_refs=[]`, when the artifact is written, then it has no `commit_refs` annotation
  and the `commit_refs` key is omitted from vector metadata.

Source: adr-2026-07-03-annotation-backed-link-storage D1; p12-t58-commit-refs-cap-references-removal R4

## 3. Rules — Surfacing `commit_refs`

### R3 — `read_artifact` always carries `commit_refs: list[str]`; a `list_artifacts` entry carries it when link fields are requested

When `read_artifact` returns, the response includes `commit_refs: list[str]`. A `list_artifacts`
entry carries it only when the caller asks for link fields; an entry listed without that request
has no `commit_refs` key (p3-t10-list-artifacts R11). Wherever the field is returned, an artifact
written with no `commit_refs` shows it as `[]` — not absent.

**Example**

- Given an artifact written with `commit_refs=["abc1234"]`, when `read_artifact` is called,
  then `commit_refs: ["abc1234"]` appears in the response.
- Given an artifact written with `commit_refs=["abc1234"]`, when `list_artifacts` is called
  with `include_links=True`, then `commit_refs: ["abc1234"]` appears in that artifact's entry;
  called without it, the entry has no `commit_refs` key.
- Given an artifact written with no `commit_refs`, when read, or listed with
  `include_links=True`, then `commit_refs` is `[]` in the response — not absent.

Source: FR-28, AC-34; p3-t10-list-artifacts R11

### R4 — `read_artifact` reads `commit_refs` from the S3 object annotation

When `read_artifact` is called, it reads `commit_refs` from the object's S3 annotation
(`annotations.read_link_annotations`), the field's sole source of truth — never from S3 user-defined
metadata and never from vector metadata, whose copy is a capped filter index. When the annotation is
absent it returns `commit_refs: []`. A failed annotation read is an error, never a successful read
reporting `commit_refs: []`: `annotation_unavailable` when annotations are unavailable or access is
denied (`arkeology.tools.read` § read_artifact). The read makes no vector-index call for this field.

**Example**

- Given `link_metadata` has appended a SHA to an artifact's `commit_refs` annotation, when
  `read_artifact` is called, then `commit_refs` in the response contains the linked SHA(s).
- Given an artifact with more than 20 `commit_refs`, when `read_artifact` is called, then the
  response carries all of them, not the 20 its vector metadata holds.

Source: adr-2026-07-03-annotation-backed-link-storage "Revision — 2026-09-05"; FR-54; FR-57

### R5 — A `CredentialError` from the annotation read during `read_artifact` returns `credential_error`

When a `CredentialError` is raised from the `commit_refs` annotation read during `read_artifact`,
the system returns `credential_error` — not a raw exception.

### R6 — `list_artifacts` filters on `commit_refs` with AND semantics

When `list_artifacts` is called with a `commit_refs` filter, the system adds one
`{"commit_refs": {"$eq": ref}}` clause per entry (AND semantics, mirroring `tags`): all refs must
match. When the `commit_refs` filter is omitted, no default filter is applied. An agent uses it to
find all artifacts linked to a specific commit.

**Example**

- Given artifacts with `commit_refs=["abc1234"]` and others without, when `list_artifacts`
  is called with `commit_refs=["abc1234"]`, then only matching artifacts are returned.
- Given `commit_refs` filter is omitted, when `list_artifacts` is called, then artifacts
  with and without `commit_refs` are both returned (no default filter applied).
- Given `commit_refs=["abc1234", "def5678"]`, then all refs must match (AND semantics, same as
  `tags`).

## 4. Rules — `last_edited_ulid`

### R7 — Every `write_artifact` generates and stores a `last_edited_ulid`

When `write_artifact` is called, the system generates a ULID string using `python-ulid` at the
point of writing and stores it as `last_edited_ulid` in both S3 object metadata and vector
metadata. `last_edited_ulid` is a write-time system field — it is NOT part of the `Artifact`
model and is NOT caller-supplied; it is generated inside `_write_artifact_inner` and stored
directly in `s3_metadata` and `vector_metadata`.

### R8 — `write_artifact`'s success response includes `last_edited_ulid`

When `write_artifact` is called, the system includes `last_edited_ulid` in the success response
alongside `artifact_id` and `sections_indexed`.

**Example**

- Given a `write_artifact` call, when it succeeds, then the response includes
  `last_edited_ulid: str` — a non-empty ULID string.
- Given two successive `write_artifact` calls, then the second `last_edited_ulid` is
  lexicographically greater than or equal to the first (ULIDs are monotonically increasing
  within a millisecond resolution; concurrent tests may see equal values).
- Given a `write_artifact` call that overwrites an existing artifact, then the returned
  `last_edited_ulid` reflects the new write — not the original write time.

### R9 — `read_artifact` and every `list_artifacts` entry carry `last_edited_ulid: str | None`

When `list_artifacts` returns, the system includes `last_edited_ulid: str | None` in each
artifact entry; when `read_artifact` returns, it includes `last_edited_ulid: str | None` in the
response. When `last_edited_ulid` is absent from metadata (pre-existing artifact), the system
returns `None` for that field — not raise an error.

**Example**

- Given an artifact written with a known `last_edited_ulid` stored in its metadata, when
  `list_artifacts` is called, then each artifact entry includes `last_edited_ulid`.
- Given an artifact written with a known `last_edited_ulid` stored in S3 object metadata,
  when `read_artifact` is called, then the response includes `last_edited_ulid`.
- Given an artifact written before this feature was deployed (no `last_edited_ulid` in
  metadata), when read or listed, then `last_edited_ulid` is `None` in the response — not
  an error.

## 5. Rules — Dependency

### R10 — `python-ulid` is a runtime dependency

When `pyproject.toml` is updated, the system adds `python-ulid` as a runtime dependency.

## 6. Boundaries

**Always:**
- `commit_refs` is never written to user-defined S3 object metadata: its full list lives in the
  object's `commit_refs` annotation, and vector metadata carries a `list[str]` copy capped to the
  most-recent 20 entries, with the key omitted when empty — the same omitted-when-empty rule as
  `tags`.
- `last_edited_ulid` is a write-time system field — it is NOT part of the `Artifact` model
  and is NOT caller-supplied. It is generated inside `_write_artifact_inner` and stored
  directly in `s3_metadata` and `vector_metadata`.
- `commit_refs` IS part of the `Artifact` model — it IS caller-supplied (optional, default
  empty list).
- Both fields are present on the `Artifact` model only for `commit_refs`; `last_edited_ulid`
  bypasses the model entirely.
- `python-ulid` is the ULID library; import via `from ulid import ULID`.

**Ask First:**
- Nothing — all constraints are defined.

**Never:**
- Do not store artifact content in metadata (NFR-01 — unchanged).
- Do not add `last_edited_ulid` as a field on `Artifact` — it is a system field, not a
  caller input.
- Do not re-implement the encoding pattern — reuse the exact same `if tags:` / `if sources:`
  guard pattern from `write.py` for `commit_refs` in vector metadata.
- Do not change the `generate_artifact_id` function or the S3 key derivation scheme.

## 7. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `pyproject.toml` | Modify | Add `python-ulid` to runtime dependencies |
| `tests/unit/test_artifact.py` | Modify | Add tests for `commit_refs` field on `Artifact` |
| `src/arkeology/artifact.py` | Modify | Add `commit_refs: list[str]` field |
| `tests/unit/test_tools_write.py` | Modify | Add tests for `last_edited_ulid` in response, S3 metadata, and vector metadata; `commit_refs` round-trip |
| `src/arkeology/tools/write.py` | Modify | Generate ULID; add `last_edited_ulid` to `s3_metadata` and `vector_metadata`; write `commit_refs` to its annotation and its capped copy to `vector_metadata`, never to `s3_metadata`; include `last_edited_ulid` in return dict |
| `tests/unit/test_tools_list.py` | Modify | Add tests for `commit_refs` filter, `last_edited_ulid` in each entry, and `commit_refs` in each entry under `include_links=True` (p3-t10-list-artifacts R11); absence-tolerant for legacy artifacts |
| `src/arkeology/tools/list.py` | Modify | Add `commit_refs` filter parameter; decode both fields in result dict |
| `tests/unit/test_tools_read.py` | Modify | Replace S3-metadata-backed `commit_refs` tests with annotation-backed equivalents; add tests for the absent-annotation, `AnnotationUnavailableError` and `CredentialError` paths; keep `last_edited_ulid` tests unchanged |
| `src/arkeology/tools/read.py` | Modify | Read `commit_refs` with `annotations.read_link_annotations`; remove dead `meta.get("commit_refs", "")` S3 parse; include `commit_refs` and `last_edited_ulid` in return dict |

### Contracts

- `docs/contracts/modules/arkeology.tools.write.md` § write_artifact — the `commit_refs` input and the `last_edited_ulid` each write stamps and returns (R1, R2, R7, R8).
- `docs/contracts/modules/arkeology.tools.read.md` § read_artifact — `commit_refs` read from the annotation, `last_edited_ulid`, and the annotation-read errors (R3–R5, R9).
- `docs/contracts/modules/arkeology.tools.list.md` § list_artifacts — the `commit_refs` filter, `include_links`, and the fields each entry carries (R3, R6, R9).
- `docs/contracts/data/s3.artifact.md` § Storage Shape — `last_edited_ulid` in object metadata, and no `commit_refs` there (R2, R7).
- `docs/contracts/data/s3vectors.artifact.md` § cap_commit_refs_for_vectors and § Storage Shape — the capped `commit_refs` filter copy and `last_edited_ulid` in vector metadata (R2, R6, R7).
- `docs/contracts/data/s3-annotations.artifact.md` § read_link_annotations, § Storage Shape and § Not-Found Semantics — the annotation as `commit_refs`' sole durable copy, its encoding, and an absent annotation versus a failed read (R2, R4, R5).

### Testing Approach

**TDD cycle — modify tests before modifying each implementation file.**

Process each pair in order; do not skip ahead:

1. **`test_artifact.py` → `artifact.py`**
   - Test: `Artifact` constructed with `commit_refs=["abc1234"]` stores the value correctly.
   - Test: `Artifact` constructed without `commit_refs` defaults to `[]`.
   - Implement: add `commit_refs: list[str] = Field(default_factory=list)` to `Artifact`.

2. **`test_tools_write.py` → `write.py`** (after `pyproject.toml` updated)
   - Test: `write_artifact` response includes `last_edited_ulid` key with a non-empty string.
   - Test: S3 put_object call receives `last_edited_ulid` in metadata dict (spy on `put_object`).
   - Test: vector put_vectors_batch call receives `last_edited_ulid` in vector metadata dict.
   - Test: artifact written with `commit_refs=["abc1234"]` carries `["abc1234"]` in its
     `commit_refs` annotation and in vector metadata, and no `commit_refs` key in S3 metadata.
   - Test: artifact written with `commit_refs=[]` has no `commit_refs` annotation and omits
     the `commit_refs` key from vector metadata.
   - Implement: generate ULID via `from ulid import ULID; ulid_val = str(ULID())`; add
     `last_edited_ulid` to `s3_metadata` and `vector_metadata`; write `commit_refs` as R2
     states; include `last_edited_ulid` in return dict.

3. **`test_tools_list.py` → `list.py`**
   - Test: `list_artifacts` with `commit_refs=["abc1234"]` returns only matching artifacts.
   - Test: `list_artifacts` without `commit_refs` returns all artifacts regardless of their
     `commit_refs` value.
   - Test: with `include_links=True`, each artifact entry includes `commit_refs: list[str]` (may be
     `[]`); without it, no entry has the key (p3-t10-list-artifacts R11).
   - Test: each artifact entry includes `last_edited_ulid` (may be `None` for legacy).
   - Test: artifact with no `last_edited_ulid` in vector metadata → entry has
     `last_edited_ulid: None`.
   - Implement: add `commit_refs` filter parameter with `$eq` clauses; decode both fields
     in result assembly.

4. **`test_tools_read.py` → `read.py`**
   - Delete: the two existing tests that seed `commit_refs` in S3 object metadata and read
     it back — they test the wrong data source.
   - Test: `read_artifact` returns `commit_refs: ["abc1234"]` when the artifact's
     `commit_refs` annotation carries `["abc1234"]` (single SHA, write-time path).
   - Test: `read_artifact` returns `commit_refs: ["prev123", "new456"]` when the annotation
     carries both while the vector metadata carries only `["prev123"]` — the vector copy is
     never read.
   - Test: `read_artifact` returns `commit_refs: []` when the artifact has no `commit_refs`
     annotation.
   - Test: `read_artifact` returns `annotation_unavailable`, not `commit_refs: []`, when the
     annotation read raises `AnnotationUnavailableError`.
   - Test: `read_artifact` returns `credential_error` when the annotation read raises
     `CredentialError`.
   - Keep: `read_artifact` response includes `last_edited_ulid` when S3 metadata has it.
   - Keep: `read_artifact` response includes `last_edited_ulid: None` when S3 metadata
     does not have the field.
   - Implement: read `commit_refs` with `annotations.read_link_annotations(s3, artifact_id)`;
     remove dead `meta.get("commit_refs", "")` S3 parse; include `last_edited_ulid` as
     `meta.get("last_edited_ulid") or None`.
