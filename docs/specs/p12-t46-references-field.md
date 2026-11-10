---
type: Spec
id: p12-t46-references-field
title: T46 — references First-Class Field on Artifact + write/read/list Surfacing + Filter
description: Promote references to a first-class Artifact field, accept it at write time (dual-store as list[str] in vector metadata; durable annotation added in T47), surface it in write/read/list responses, and add a references list-membership filter with AND semantics. Legacy artifacts return [].
tags: []
status: stable
okf_version: "0.2"
sources:
  - resource: docs/architecture-decisions/adr-2026-07-03-artifact-cross-referencing.md
    title: Artifact Cross-Referencing — First-Class references Field, Migration Rewrite, and referenced_by Warning
    last_modified: 2026-09-29T00:00:00Z
  - resource: docs/architecture-decisions/adr-2026-07-03-annotation-backed-link-storage.md
    title: Annotation-Backed Durable Storage for Mutable Link Fields (commit_refs + references)
    last_modified: 2026-09-29T00:00:00Z
  - resource: docs/specs/p10-t36-commit-refs-metadata-fields.md
    title: T36 — commit_refs and last_edited_ulid Metadata Fields
    last_modified: 2026-07-03T00:00:00Z
  - resource: docs/specs/p12-t45-s3-annotation-client.md
    title: T45 — S3 Object Annotation Client Support + moto Self-Mock Extension
    last_modified: 2026-07-03T00:00:00Z
  - resource: docs/planning-artifacts/requirements.md
    title: Arkeology — Requirements
    last_modified: 2026-09-24T00:00:00Z
generated:
  by: "axians-architect/claude-opus-4.8"
  at: 2026-07-03T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-09T18:25:35Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
---

# T46 — `references` First-Class Field on `Artifact` + write / read / list Surfacing

## TL;DR

Add `references: list[str]` as a first-class `Artifact` field holding resolved full S3 keys (the
operative `artifact_id`), following the exact `commit_refs` /
`source_artifacts` plumbing. It is accepted at
write time, stored as `list[str]` in vector metadata (durable annotation storage is added in T47),
surfaced in `write_artifact`, `read_artifact`, and `list_artifacts` responses, and queryable via a
new `references` list-membership filter with AND semantics. Absent/legacy `references` returns `[]`.
**This spec owns the `references` field across write / read / list — including the bulk write and
migrate surfaces.** (FR-51, AC-56, AC-57.)

## 1. Problem Statement

Arkeology has no first-class way for one artifact to point at another (ADR-012 D2). `source_artifacts`
already establishes the exact dual-storage + `$eq` list-membership pattern needed, and `commit_refs`
(T36) already demonstrates the same field flowing through write/read/list. Promoting `references`
reuses 100% of that plumbing. This field is the data-model foundation the migration rewrite (T51),
`link_metadata` backfill (T49), and the `referenced_by` warning (T50) all build on.

Every behaviour in this spec comes from a P1 story: `references` persisted through write, read, and
list; `references` stored in vector metadata and the `references` filter in `list_artifacts`
(both superseded 2026-08-17 by R6 and R7); bulk write and migrate threading `references`.

**Dependency note (T55):** `references` is a *filterable* vector-metadata list field, so it counts
against the S3 Vectors **2 KB filterable-metadata budget** validated by the write-path size check
specced in `docs/specs/p12-t55-metadata-validation.md` (T55). T55 must land before/with this task so
the enlarged filterable payload is guarded before `references` goes live.

## 2. Rules — The `references` field through write, read and list

### R1 — `references` on the `Artifact` model

When the `Artifact` model is constructed, it accepts `references: list[str]` with
`Field(default_factory=list)`, placed alongside `commit_refs`.

### R2 — `read_artifact` returns `references`

When `read_artifact` runs, it reads `references` from the first section vector's metadata (the same
`list_vectors_by_metadata` + `get_vectors` call already used for `commit_refs`) and returns
`references: list[str]`, defaulting to `[]` when absent or when `vectors is None`.

**Example**

- Given an artifact written with `references=["adr-use-postgres-abc12345"]`, when `read_artifact`
  is called, then `references: ["adr-use-postgres-abc12345"]` appears in the response.

### R3 — `list_artifacts` returns `references` in each entry

When `list_artifacts` returns, it includes `references: list[str]` in each entry, decoded via
`coerce_list_field`.

**Example**

- Given an artifact written with `references=["adr-use-postgres-abc12345"]`, when `list_artifacts`
  is called, then each entry includes `references`.

### R4 — The `write_artifact` response

When `write_artifact` returns, it is not required to add `references` to the success dict beyond
existing keys, but the value is recoverable via `read_artifact` / `list_artifacts`. The write
response echo of `references` — given `write_artifact` succeeds, its response includes the
`references` list it was given — is satisfied by this round-trip through read and list.

### R5 — Absent or legacy `references` is `[]`

When `references` is absent from metadata, the system returns `[]` — never an error, and never an
absent key.

**Example**

- Given an artifact written with no `references`, when read or listed, then `references` is `[]` —
  not absent, not an error.
- Given an artifact written before this feature (no `references` in vector metadata), when read or
  listed, then `references` is `[]`.

Source: AC-56, FR-51

## 3. Rules — No vector-metadata copy and no `references` filter

### R6 — `references` is never written to vector metadata

`references` is never written to S3 Vectors metadata under any circumstance — the S3 object
annotation copy (`p12-t47-annotation-dual-write.md`) is the field's **sole** durable store and sole
read surface. This was a deliberate, operator-approved capability narrowing (a real-AWS calibration
proved the local byte-budget approximation this task originally relied on under-measures AWS's real
accounting for this exact field shape), not a defect in this spec's original design. What is
unaffected: `references: list[str]` remains a first-class `Artifact` field; `write_artifact` still
accepts it; `read_artifact` and `list_artifacts` still return it (both already source it via
`read_current_link_fields`, the annotation-backed union helper — see the T47 forward-pointer note
below — so the *returned* value round-trips exactly as originally specified, unaffected by the
vector-metadata removal). See `docs/specs/p12-t58-commit-refs-cap-references-removal.md` for the
current, authoritative contract.

Source: adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal.md D2

### R7 — `list_artifacts` has no `references` filter

`list_artifacts` has no `references=` filter parameter: it was removed outright rather than left
silently unable to match anything (it can no longer match anything once `references` is no longer
in vector metadata). `commit_refs=` filtering is unaffected. See
`docs/specs/p12-t59-remove-references-filter-param.md` for the current, authoritative contract.

Source: adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal.md D2

## 4. Rules — Bulk write and migrate

### R8 — `write_artifacts` and `migrate_artifacts` thread `references`

When `write_artifacts` / `migrate_artifacts` process a descriptor, they thread a `references` key
through to `_write_artifact_inner`.

**Example**

- Given a `write_artifacts` descriptor carrying `references=["a-1"]`, when the batch is written,
  then the resulting artifact's vector metadata carries `references: ["a-1"]`.
- Given a `migrate_artifacts(dry_run=False)` descriptor carrying `references=["a-1"]`, then the
  written artifact carries the same references (threaded through to `write_artifact`).

## 5. Rules — Overwrite and cross-scope behaviour

These two behaviours (forward-pointer, 2026-07-06, shipped — replace semantics in `7a697dd`,
cross-scope filtering in `2aa1633`) layer on top of this field's plumbing without changing anything
else in this spec; neither changes the field's write-time acceptance or vector-metadata encoding.

### R9 — Replace, not accrete, on overwrite

On an ordinary overwriting write, `references` is **replaced** outright with exactly the value
supplied to that call — no read-forward, no merge against the prior stored value, and a call
supplying no `references` clears the field. This is asymmetric with `commit_refs`, which stays
accretive (union of read-forward and supplied values) — `commit_refs` is a git-derived audit trail
with no frontmatter counterpart, backfilled by `link_metadata`; `references` mirrors the artifact's
*current* frontmatter and must be able to shrink. `link_metadata`'s own backfill merge is unaffected
by this — a value it adds can later be superseded by an ordinary overwriting write that doesn't also
supply it, which is expected. `archive_artifact`'s status-flip re-PUT is also unaffected — it has no
caller-supplied `references` to replace *from*, so it continues to re-apply the stored value
unconditionally across both fields.

Source: ADR-011 decision 4, FR-51, FR-54, FR-55, FR-10

### R10 — Cross-scope filtering of returned `references`

When `references` is returned to a **foreign-scope** reader (via `read_artifact` /
`list_artifacts`), any entry the reader could not independently read (i.e. not itself a tier 3
shared artifact, or unresolvable — fail safe) is dropped from the response first, via a shared
`resolve_readable_targets` helper that reuses `read_artifact`'s own readability predicate.
**Own-scope reads bypass this filter entirely** — `references` is returned exactly as stored.
`list_artifacts` batches this into a single additional query across the whole result page's
distinct foreign-scope reference ids, rather than one lookup per artifact per reference, to avoid
an N×M cost.

Source: ADR-012 "Cross-scope reference visibility", FR-51, FR-54, FR-55, FR-10

## 6. Boundaries

**Always:**
- `references` holds **only resolved full S3 keys (the operative `artifact_id`)** — no `arkeology://`
  prefix, no path text (ADR-012 D2). Validation of resolvability is out of scope (a `references`
  entry can only ever be a real Arkeology artifact — no write-time cross-scope validation, ADR-012
  "Cross-scope reference visibility"; a *separate*, later decision filters what a foreign-scope
  reader is shown, see R10).
- Encoding mirrors `commit_refs` exactly: `list[str]` in vector metadata, key omitted when empty.
- `references` is read from **vector metadata** in `read_artifact` / `list_artifacts` (consistent
  with how `commit_refs` is surfaced today) — NOT from S3 user-defined metadata.

**Ask First:**
- Nothing — all constraints are defined.

**Never:**
- Do not write `references` into S3 user-defined object metadata — the durable copy is an S3 object
  annotation, added in T47 (ADR-011). This spec only covers the `Artifact` field + vector metadata +
  read/list surfacing + filter. The annotation dual-write is T47's responsibility.
- Do not store artifact content in vector metadata (NFR-01).
- Do not add cross-scope validation for reference targets (ADR-012 closed this as not applicable).

## 7. For the developer agent

### Files to Touch

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

### Contracts

None.

### Testing Approach

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
