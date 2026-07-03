---
type: spec
title: T36 — commit_refs and last_edited_ulid Metadata Fields
description: Spec to add commit_refs and last_edited_ulid as first-class metadata fields flowing through write, read, and list, enabling post-write commit annotation and time-range discovery.
tags: []
timestamp: 2026-06-06T00:00:00Z
okf_version: "0.1"
feature: p10-t36-commit-refs-metadata-fields
status: ready
phase: 10
task: 36
references:
  - docs/brainstorming/brainstorming-2026-06-06-artifact-commit-refs.md
  - docs/specs/p10-t35-filter-range-operators.md
authored:
  by: "analyst"
  date: "2026-06-06"
revised:
  by: "architect"
  date: "2026-07-03"
---

# T36 — `commit_refs` and `last_edited_ulid` Metadata Fields

> **Alignment note (2026-07-03, ADR-011 — annotation-backed link storage).** This spec predates
> ADR-011. Wherever it states that `commit_refs` is stored **in S3 object metadata** (Story 2, the
> corresponding Requirements bullets, and Boundaries), the **durable copy of `commit_refs` — and,
> going forward, the new `references` field — now lives in an S3 object *annotation*, dual-written
> with vector metadata (durable annotation first, vector second), NOT in user-defined S3 object
> metadata.** The vector-metadata `list[str]` representation and the `$eq` list-membership filter
> (Story 3) are unchanged. The annotation client and its moto self-mock are specced in `p12-t45`;
> the write-path dual-write is specced in `p12-t47`; `link_commit` is generalized into
> `link_metadata` in `p12-t49-link-metadata`.
>
> `last_edited_ulid` is **unaffected**: it remains a write-time system field set atomically in
> user-defined S3 object metadata at `PutObject`. It is never backfilled post-hoc, so it does **not**
> move to annotations. All ULID and `$gte`/`$lte` time-range content in this spec remains valid.

<!-- SCOPE BLOCK — frozen after approval -->

## TL;DR

Add two new metadata fields — `commit_refs: list[str]` and `last_edited_ulid: str` — to the
artifact storage and retrieval pipeline. `commit_refs` is a caller-supplied list of git
commit references stored alongside existing artifact metadata. `last_edited_ulid` is a
system-generated write-time timestamp (ULID) that enables time-range discovery of artifacts
written during a session. Both fields flow through `artifact.py`, `write.py`, `list.py`,
and `read.py` following the identical encoding pattern already used by `tags`.

## Problem Statement

There is currently no way to associate an artifact with a git commit or to discover which
artifacts were written during a given session. Adding `commit_refs` and `last_edited_ulid`
as first-class metadata fields creates the data model that the `propose_commit_links` and
`link_commit` tools (T37, T38) depend on. Without these fields in place, post-write commit
annotation is impossible and time-range scans over the vector index cannot be expressed.

## User Stories

### Story 1 — `commit_refs` persisted through write, read, and list (P1)

An agent writes an artifact with `commit_refs=["abc1234", "def5678"]`. On read and list,
those refs appear in the response.

**Acceptance criteria:**
- Given an artifact written with `commit_refs=["abc1234"]`, when `read_artifact` is called,
  then `commit_refs: ["abc1234"]` appears in the response.
- Given an artifact written with `commit_refs=["abc1234"]`, when `list_artifacts` is
  called, then `commit_refs: ["abc1234"]` appears in each artifact entry.
- Given an artifact written with no `commit_refs`, when read or listed, then `commit_refs`
  is `[]` in the response — not absent.
- Given `link_commit` has been called for an artifact (appending a SHA to vector metadata
  only, without updating S3 object metadata), when `read_artifact` is called, then
  `commit_refs` in the response contains the linked SHA(s).

### Story 2 — `commit_refs` stored correctly in both S3 and vector metadata (P1)

**Acceptance criteria:**
- Given `commit_refs=["abc1234", "def5678"]`, when stored in S3 object metadata, then the
  value is the comma-joined string `"abc1234,def5678"`.
- Given the same artifact, when stored in vector metadata, then `commit_refs` is
  `["abc1234", "def5678"]` (a `list[str]`) — not a comma-joined string.
- Given `commit_refs=[]`, when stored in S3 object metadata, then the value is `""`.
- Given `commit_refs=[]`, when stored in vector metadata, then the `commit_refs` key is
  omitted entirely (S3 Vectors rejects empty arrays — same rule as `tags`).

### Story 3 — `commit_refs` filter in `list_artifacts` (P1)

An agent needs all artifacts linked to a specific commit.

**Acceptance criteria:**
- Given artifacts with `commit_refs=["abc1234"]` and others without, when `list_artifacts`
  is called with `commit_refs=["abc1234"]`, then only matching artifacts are returned.
- Given `commit_refs` filter is omitted, when `list_artifacts` is called, then artifacts
  with and without `commit_refs` are both returned (no default filter applied).
- Given `commit_refs=["abc1234", "def5678"]`, all refs must match (AND semantics, same as
  `tags`).

### Story 4 — `last_edited_ulid` generated on every write (P1)

**Acceptance criteria:**
- Given a `write_artifact` call, when it succeeds, then the response includes
  `last_edited_ulid: str` — a non-empty ULID string.
- Given two successive `write_artifact` calls, the second `last_edited_ulid` is
  lexicographically greater than or equal to the first (ULIDs are monotonically increasing
  within a millisecond resolution; concurrent tests may see equal values).
- Given a `write_artifact` call that overwrites an existing artifact, then the returned
  `last_edited_ulid` reflects the new write — not the original write time.

### Story 5 — `last_edited_ulid` exposed in list and read responses (P1)

**Acceptance criteria:**
- Given an artifact written with a known `last_edited_ulid` stored in its metadata, when
  `list_artifacts` is called, then each artifact entry includes `last_edited_ulid`.
- Given an artifact written with a known `last_edited_ulid` stored in S3 object metadata,
  when `read_artifact` is called, then the response includes `last_edited_ulid`.
- Given an artifact written before this feature was deployed (no `last_edited_ulid` in
  metadata), when read or listed, then `last_edited_ulid` is `None` in the response — not
  an error.

## Requirements

- WHEN `write_artifact` is called THE SYSTEM SHALL generate a ULID string using
  `python-ulid` at the point of writing and store it as `last_edited_ulid` in both S3
  object metadata and vector metadata.
- WHEN `write_artifact` is called THE SYSTEM SHALL include `last_edited_ulid` in the
  success response alongside `artifact_id` and `sections_indexed`.
- WHEN `commit_refs` is non-empty THE SYSTEM SHALL store it as a comma-joined string in S3
  object metadata and as `list[str]` in vector metadata.
- WHEN `commit_refs` is empty THE SYSTEM SHALL store `""` in S3 object metadata and omit
  the key from vector metadata entirely.
- WHEN `list_artifacts` is called with a `commit_refs` filter THE SYSTEM SHALL add one
  `{"commit_refs": {"$eq": ref}}` clause per entry (AND semantics, mirroring `tags`).
- WHEN `list_artifacts` returns THE SYSTEM SHALL include `commit_refs: list[str]` and
  `last_edited_ulid: str | None` in each artifact entry.
- WHEN `read_artifact` is called THE SYSTEM SHALL read `commit_refs` from vector metadata
  (via `vectors.list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}})` then
  `vectors.get_vectors([keys[0]])`) — not from S3 object metadata; this ensures SHAs
  appended by `link_commit` are surfaced without an S3 write.
- WHEN no vector entries exist for the artifact THE SYSTEM SHALL return `commit_refs: []`.
- WHEN `vectors` is `None` THE SYSTEM SHALL return `commit_refs: []`.
- WHEN a CredentialError is raised from `list_vectors_by_metadata` during `read_artifact`
  THE SYSTEM SHALL return a structured error — not a raw exception.
- WHEN `read_artifact` returns THE SYSTEM SHALL include `commit_refs: list[str]` and
  `last_edited_ulid: str | None` in the response.
- WHEN `last_edited_ulid` is absent from metadata (pre-existing artifact) THE SYSTEM SHALL
  return `None` for that field — not raise an error.
- WHEN `pyproject.toml` is updated THE SYSTEM SHALL add `python-ulid` as a runtime
  dependency.

## Boundaries

**Always:**
- `commit_refs` encoding follows the exact pattern of `tags` and `source_artifacts`:
  comma-joined in S3 metadata, `list[str]` in vector metadata, key omitted when empty in
  vector metadata.
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

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `pyproject.toml` | Modify | Add `python-ulid` to runtime dependencies |
| `tests/unit/test_artifact.py` | Modify | Add tests for `commit_refs` field on `Artifact` |
| `src/cairn_mcp/artifact.py` | Modify | Add `commit_refs: list[str]` field |
| `tests/unit/test_tools_write.py` | Modify | Add tests for `last_edited_ulid` in response, S3 metadata, and vector metadata; `commit_refs` round-trip |
| `src/cairn_mcp/tools/write.py` | Modify | Generate ULID; add both fields to `s3_metadata` and `vector_metadata`; include `last_edited_ulid` in return dict |
| `tests/unit/test_tools_list.py` | Modify | Add tests for `commit_refs` filter and `last_edited_ulid` / `commit_refs` in response; absence-tolerant for legacy artifacts |
| `src/cairn_mcp/tools/list.py` | Modify | Add `commit_refs` filter parameter; decode both fields in result dict |
| `tests/unit/test_tools_read.py` | Modify | Replace S3-backed `commit_refs` tests with vector-backed equivalents; add tests for no-vectors and CredentialError paths; keep `last_edited_ulid` tests unchanged |
| `src/cairn_mcp/tools/read.py` | Modify | Read `commit_refs` from first section vector's metadata via `list_vectors_by_metadata` + `get_vectors`; remove dead `meta.get("commit_refs", "")` S3 parse; `vectors` parameter is no longer discarded; include `commit_refs` and `last_edited_ulid` in return dict |

## Testing Approach

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
   - Test: artifact written with `commit_refs=["abc1234"]` stores `"abc1234"` in S3 metadata
     and `["abc1234"]` in vector metadata.
   - Test: artifact written with `commit_refs=[]` stores `""` in S3 metadata and omits
     `commit_refs` key from vector metadata.
   - Implement: generate ULID via `from ulid import ULID; ulid_val = str(ULID())`; add
     both fields to `s3_metadata` and `vector_metadata`; include `last_edited_ulid` in
     return dict.

3. **`test_tools_list.py` → `list.py`**
   - Test: `list_artifacts` with `commit_refs=["abc1234"]` returns only matching artifacts.
   - Test: `list_artifacts` without `commit_refs` returns all artifacts regardless of their
     `commit_refs` value.
   - Test: each artifact entry includes `commit_refs: list[str]` (may be `[]`).
   - Test: each artifact entry includes `last_edited_ulid` (may be `None` for legacy).
   - Test: artifact with no `last_edited_ulid` in vector metadata → entry has
     `last_edited_ulid: None`.
   - Implement: add `commit_refs` filter parameter with `$eq` clauses; decode both fields
     in result assembly.

4. **`test_tools_read.py` → `read.py`**
   - Delete: the two existing tests that seed `commit_refs` in S3 object metadata and read
     it back — they test the wrong data source (S3 is never updated by `link_commit`).
   - Test: `read_artifact` returns `commit_refs: ["abc1234"]` when vector metadata for
     the artifact carries `commit_refs: ["abc1234"]` (single SHA, write-time path).
   - Test: `read_artifact` returns `commit_refs: ["prev123", "new456"]` when vector
     metadata carries `commit_refs: ["prev123", "new456"]` (multiple SHAs — simulates
     post-`link_commit` state where S3 object metadata has no `commit_refs` at all).
   - Test: `read_artifact` returns `commit_refs: []` when `vectors=None`.
   - Test: `read_artifact` returns `commit_refs: []` when `list_vectors_by_metadata`
     returns no entries for the artifact.
   - Test: `read_artifact` returns a structured error when `list_vectors_by_metadata`
     raises `CredentialError`.
   - Keep: `read_artifact` response includes `last_edited_ulid` when S3 metadata has it.
   - Keep: `read_artifact` response includes `last_edited_ulid: None` when S3 metadata
     does not have the field.
   - Implement: call `vectors.list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}})`;
     if entries found, call `vectors.get_vectors([keys[0]])` and extract `commit_refs`
     from that section's metadata; return `[]` when no vectors found or when `vectors` is
     `None`; remove dead `meta.get("commit_refs", "")` S3 parse; include
     `last_edited_ulid` as `meta.get("last_edited_ulid") or None`.

## Open Questions

*(none — all constraints are defined)*
