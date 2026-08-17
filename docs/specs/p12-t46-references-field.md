---
type: spec
title: T46 — references First-Class Field on Artifact + write/read/list Surfacing + Filter
description: Promote references to a first-class Artifact field, accept it at write time (dual-store as list[str] in vector metadata; durable annotation added in T47), surface it in write/read/list responses, and add a references list-membership filter with AND semantics. Legacy artifacts return [].
tags: []
timestamp: 2026-07-03T00:00:00Z
okf_version: "0.1"
feature: p12-t46-references-field
status: ready
phase: 12
task: 46
references:
  - docs/architecture-decisions/adr-2026-07-03-artifact-cross-referencing.md
  - docs/architecture-decisions/adr-2026-07-03-annotation-backed-link-storage.md
  - docs/specs/p10-t36-commit-refs-metadata-fields.md
  - docs/specs/p12-t45-s3-annotation-client.md
  - docs/planning-artifacts/prd.md
authored:
  by: "architect"
  date: "2026-07-03"
revised:
  by: "architect"
  date: "2026-08-17"
---

# T46 — `references` First-Class Field on `Artifact` + write / read / list Surfacing

> **Superseded 2026-08-17 (architect, `adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal.md`
> D2, implemented in T58/T59).** This spec's original scope stored `references` as a filterable
> `list[str]` in S3 Vectors metadata and exposed a `list_artifacts(references=[...])` server-side
> `$eq` filter (Story 2, Story 3, and the corresponding Requirements bullets below). Both are now
> **superseded**: T58 removed `references` from S3 Vectors metadata entirely — the S3 object
> annotation copy (`p12-t47-annotation-dual-write.md`) is now the field's **sole** durable store and
> sole read surface — and T59 removed the `references=` filter parameter from `list_artifacts`
> outright rather than leaving it silently unable to match anything. This was a deliberate,
> operator-approved capability narrowing (a real-AWS calibration proved the local byte-budget
> approximation this task originally relied on under-measures AWS's real accounting for this exact
> field shape), not a defect in this spec's original design. What is **unaffected**: `references:
> list[str]` remains a first-class `Artifact` field; `write_artifact` still accepts it;
> `read_artifact` and `list_artifacts` still return it (both already source it via
> `read_current_link_fields`, the annotation-backed union helper — see the T47 forward-pointer note
> below — so the *returned* value round-trips exactly as originally specified, unaffected by the
> vector-metadata removal). Only the vector-metadata storage and the filter parameter are gone. See
> `docs/specs/p12-t58-commit-refs-cap-references-removal.md` and
> `docs/specs/p12-t59-remove-references-filter-param.md` for the current, authoritative contract.

> **Dependency note (T55):** `references` is a *filterable* vector-metadata list field, so it counts
> against the S3 Vectors **2 KB filterable-metadata budget** validated by the write-path size check
> specced in `docs/specs/p12-t55-metadata-validation.md` (T55). T55 must land before/with this task so
> the enlarged filterable payload is guarded before `references` goes live.

<!-- SCOPE BLOCK — frozen after approval -->

## TL;DR

Add `references: list[str]` as a first-class `Artifact` field holding resolved full S3 keys (the
operative `artifact_id`), following the exact `commit_refs` /
`source_artifacts` plumbing. It is accepted at
write time, stored as `list[str]` in vector metadata (durable annotation storage is added in T47),
surfaced in `write_artifact`, `read_artifact`, and `list_artifacts` responses, and queryable via a
new `references` list-membership filter with AND semantics. Absent/legacy `references` returns `[]`.
**This spec owns the `references` field across write / read / list — including the bulk write and
migrate surfaces.** (FR-51, AC-56, AC-57.)

## Problem Statement

Arkeology has no first-class way for one artifact to point at another (ADR-012 D2). `source_artifacts`
already establishes the exact dual-storage + `$eq` list-membership pattern needed, and `commit_refs`
(T36) already demonstrates the same field flowing through write/read/list. Promoting `references`
reuses 100% of that plumbing. This field is the data-model foundation the migration rewrite (T51),
`link_metadata` backfill (T49), and the `referenced_by` warning (T50) all build on.

## User Stories

### Story 1 — `references` persisted through write, read, and list (P1)

An agent writes an artifact with `references=["adr-use-postgres-abc12345"]`; read and list return it.

**Acceptance criteria:**
- Given an artifact written with `references=["adr-use-postgres-abc12345"]`, when `read_artifact`
  is called then `references: ["adr-use-postgres-abc12345"]` appears in the response.
- Given the same artifact, when `list_artifacts` is called then each entry includes `references`.
- Given `write_artifact` succeeds, then its response includes the `references` list it was given.
- Given an artifact written with no `references`, when read or listed then `references` is `[]` —
  not absent, not an error. (AC-56)
- Given an artifact written before this feature (no `references` in vector metadata), when read or
  listed then `references` is `[]`.

### Story 2 — `references` stored correctly in vector metadata (P1)

> **Superseded 2026-08-17 (T58).** This story's acceptance criteria describe the pre-T58 contract.
> As of T58, `references` is never written to vector metadata under any circumstance — the S3
> object annotation (T47) is its sole store. See `docs/specs/p12-t58-commit-refs-cap-references-removal.md`.

**Acceptance criteria (pre-T58, superseded — retained for decision history):**
- Given `references=["a-1", "b-2"]`, when stored in vector metadata then `references` is the
  `list[str]` `["a-1", "b-2"]` (enables `$eq` element-in-list filtering).
- Given `references=[]`, when stored in vector metadata then the `references` key is omitted
  entirely (S3 Vectors rejects empty arrays — same rule as `tags` / `commit_refs`).

### Story 3 — `references` filter in `list_artifacts` (AND semantics) (P1)

> **Superseded 2026-08-17 (T59).** The `references=` filter parameter described in this story was
> removed from `list_artifacts` outright (it can no longer match anything once T58 removed
> `references` from vector metadata). See `docs/specs/p12-t59-remove-references-filter-param.md`.
> `commit_refs=` filtering is unaffected and is not part of this supersession.

**Acceptance criteria (pre-T59, superseded — retained for decision history):**
- Given artifacts with `references=["a-1"]` and others without, when `list_artifacts` is called with
  `references=["a-1"]` then only matching artifacts are returned. (AC-57)
- Given the `references` filter is omitted, when `list_artifacts` is called then artifacts are
  returned regardless of their `references` value.
- Given `references=["a-1", "b-2"]`, then all supplied identifiers must be present (AND semantics,
  mirroring `tags` / `commit_refs`). (AC-57)

### Story 4 — bulk write and migrate thread `references` (P1)

**Acceptance criteria:**
- Given a `write_artifacts` descriptor carrying `references=["a-1"]`, when the batch is written then
  the resulting artifact's vector metadata carries `references: ["a-1"]`.
- Given a `migrate_artifacts(dry_run=False)` descriptor carrying `references=["a-1"]`, then the
  written artifact carries the same references (threaded through to `write_artifact`).

## Requirements

> **Superseded 2026-08-17 (T58/T59).** The two Requirements bullets below marked `[SUPERSEDED]`
> describe the pre-T58/T59 vector-metadata storage and filter contract; see the note at the top of
> this document and `docs/specs/p12-t58-commit-refs-cap-references-removal.md` /
> `docs/specs/p12-t59-remove-references-filter-param.md` for the current, authoritative behaviour.

- WHEN the `Artifact` model is constructed THE SYSTEM SHALL accept `references: list[str]` with
  `Field(default_factory=list)`, placed alongside `commit_refs`.
- `[SUPERSEDED by T58]` WHEN `write_artifact` is called with `references` THE SYSTEM SHALL store it as `list[str]` in
  vector metadata, omitting the key when the list is empty (same guard as `tags` / `commit_refs`).
- WHEN `write_artifact` returns THE SYSTEM SHALL NOT be required to add `references` to the success
  dict beyond existing keys, but the value SHALL be recoverable via `read_artifact` / `list_artifacts`.
  (The write response echo of `references` is satisfied by the round-trip in Story 1.)
- WHEN `read_artifact` runs THE SYSTEM SHALL read `references` from the first section vector's
  metadata (the same `list_vectors_by_metadata` + `get_vectors` call already used for `commit_refs`)
  and return `references: list[str]`, defaulting to `[]` when absent or when `vectors is None`.
- WHEN `list_artifacts` returns THE SYSTEM SHALL include `references: list[str]` in each entry,
  decoded via `coerce_list_field`.
- `[SUPERSEDED by T59]` WHEN `list_artifacts` is called with a `references` filter THE SYSTEM SHALL add one
  `{"references": {"$eq": ref}}` clause per supplied identifier (AND semantics, mirroring `commit_refs`).
- WHEN `references` is absent from metadata THE SYSTEM SHALL return `[]` — never an error. (FR-51)
- WHEN `write_artifacts` / `migrate_artifacts` process a descriptor THE SYSTEM SHALL thread a
  `references` key through to `_write_artifact_inner`.

## Boundaries

**Always:**
- `references` holds **only resolved full S3 keys (the operative `artifact_id`)** — no `arkeology://`
  prefix, no path text (ADR-012 D2). Validation of resolvability is out of scope (a `references`
  entry can only ever be a real Arkeology artifact — no write-time cross-scope validation, ADR-012
  "Cross-scope reference visibility"; a *separate*, later decision filters what a foreign-scope
  reader is shown, see the forward-pointer note below).
- Encoding mirrors `commit_refs` exactly: `list[str]` in vector metadata, key omitted when empty.
- `references` is read from **vector metadata** in `read_artifact` / `list_artifacts` (consistent
  with how `commit_refs` is surfaced today) — NOT from S3 user-defined metadata.

> **Forward-pointer note (2026-07-06, shipped — replace semantics in `7a697dd`, cross-scope
> filtering in `2aa1633`).** Two behaviours layer on top of this field's plumbing without changing
> anything above:
>
> 1. **Replace, not accrete, on overwrite.** On an ordinary overwriting write, `references` is
>    **replaced** outright with exactly the value supplied to that call — no read-forward, no merge
>    against the prior stored value, and a call supplying no `references` clears the field. This is
>    asymmetric with `commit_refs`, which stays accretive (union of read-forward and supplied
>    values) — `commit_refs` is a git-derived audit trail with no frontmatter counterpart, backfilled
>    by `link_metadata`; `references` mirrors the artifact's *current* frontmatter and must be able
>    to shrink. `link_metadata`'s own backfill merge is unaffected by this — a value it adds can
>    later be superseded by an ordinary overwriting write that doesn't also supply it, which is
>    expected. `archive_artifact`'s status-flip re-PUT is also unaffected — it has no caller-supplied
>    `references` to replace *from*, so it continues to re-apply the stored value unconditionally
>    across both fields. Rationale: ADR-011 decision 4.
> 2. **Cross-scope filtering.** When `references` is returned to a **foreign-scope** reader (via
>    `read_artifact` / `list_artifacts`), any entry the reader could not independently read (i.e.
>    not itself a tier 3 shared artifact, or unresolvable — fail safe) is dropped from the response
>    first, via a shared `resolve_readable_targets` helper that reuses `read_artifact`'s own
>    readability predicate. **Own-scope reads bypass this filter entirely** — `references` is
>    returned exactly as stored. `list_artifacts` batches this into a single additional query across
>    the whole result page's distinct foreign-scope reference ids, rather than one lookup per
>    artifact per reference, to avoid an N×M cost. Rationale: ADR-012's "Cross-scope reference
>    visibility" section.
>
> Neither behaviour changes the field's write-time acceptance or vector-metadata encoding described
> above. PRD: FR-51/FR-54/FR-55/FR-10.

**Ask First:**
- Nothing — all constraints are defined.

**Never:**
- Do not write `references` into S3 user-defined object metadata — the durable copy is an S3 object
  annotation, added in T47 (ADR-011). This spec only covers the `Artifact` field + vector metadata +
  read/list surfacing + filter. The annotation dual-write is T47's responsibility.
- Do not store artifact content in vector metadata (NFR-01).
- Do not add cross-scope validation for reference targets (ADR-012 closed this as not applicable).

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_artifact.py` | Modify | Tests for `references` field on `Artifact` — Red first |
| `src/arkeology/artifact.py` | Modify | Add `references: list[str] = Field(default_factory=list)`; update docstring |
| `tests/unit/test_tools_write.py` | Modify | Tests: `references` in vector metadata (list, omitted when empty) — Red first |
| `src/arkeology/tools/write.py` | Modify | Accept `references` param; add to `Artifact(...)` + vector metadata (`if refs2:`); do NOT add to `s3_metadata` |
| `tests/unit/test_tools_read.py` | Modify | Tests: `references` from vector metadata; `[]` when absent / `vectors=None` — Red first |
| `src/arkeology/tools/read.py` | Modify | Extend Step 4 to also extract `references` from the fetched section vector metadata; add to return dict |
| `tests/unit/test_tools_list.py` | Modify | Tests: `references` filter + `references` in each entry — Red first |
| `src/arkeology/tools/list.py` | Modify | Add `references` filter parameter (`$eq` clauses); decode `references` into each result |
| `tests/unit/test_tools_write_artifacts.py` | Modify | Test descriptor `references` threading — Red first |
| `src/arkeology/tools/write_artifacts.py` | Modify | Thread `references` from descriptor to `_write_artifact_inner` |
| `src/arkeology/tools/migrate_artifacts.py` | Modify | Thread `references` through descriptor (dry_run=False path) |
| `src/arkeology/server.py` | Modify | Add `references` param to `write_artifact` and `list_artifacts` tool wrappers |
| `src/arkeology/resources.py` | Modify | Add `references` to the artifact-schema resource field catalogue |

## Testing Approach

**TDD cycle — modify the test file before the implementation file in each pair; do not skip ahead:**

1. **`test_artifact.py` → `artifact.py`** — `Artifact(references=["a-1"])` stores the value;
   default is `[]`.
2. **`test_tools_write.py` → `write.py`** — `write_artifact(references=["a-1","b-2"])` puts
   `references: ["a-1","b-2"]` in vector metadata (spy on `put_vectors_batch`); `references=[]`
   omits the key from vector metadata.
3. **`test_tools_read.py` → `read.py`** — read returns `references` from the section vector
   metadata; returns `[]` when the key is absent, when no vectors exist, and when `vectors=None`.
4. **`test_tools_list.py` → `list.py`** — filter `references=["a-1"]` returns only matches;
   filter omitted returns all; two-identifier filter is AND; each entry carries `references`
   (may be `[]`).
5. **`test_tools_write_artifacts.py` → `write_artifacts.py` / `migrate_artifacts.py`** — a
   descriptor with `references` round-trips into the written artifact's vector metadata.

Use `aws_mock`, `s3_client`, `vectors_client` fixtures. `FakeBedrockClient` for embeddings.

## Open Questions

*(none — all constraints are defined; durable annotation storage is deferred to T47)*
