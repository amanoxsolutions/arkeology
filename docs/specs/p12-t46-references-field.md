---
type: Spec
id: p12-t46-references-field
title: T46 — references First-Class Field on Artifact + write/read/list Surfacing + Filter
description: Promote references to a first-class Artifact field holding full artifact keys, accept it at write time (stored only as an S3 object annotation, T47; never in vector metadata), return it from read_artifact, and from list_artifacts when link fields are requested, read from the annotation, with no references filter. Legacy artifacts return [].
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
  - resource: docs/contracts/data/s3-annotations.artifact.md
    title: s3-annotations.artifact
  - resource: docs/contracts/modules/arkeology.tools.write.md
    title: arkeology.tools.write
  - resource: docs/contracts/modules/arkeology.tools.read.md
    title: arkeology.tools.read
  - resource: docs/contracts/modules/arkeology.tools.list.md
    title: arkeology.tools.list
  - resource: .docs/reviews/architecture-review-2026-11-15-arkeology-phases-9-10-12.md
    title: "Architecture review — Arkeology, plan phases 9, 10 and 12"
  - resource: docs/specs/p3-t10-list-artifacts.md
    title: T10 — List Artifacts Tool
  - resource: docs/specs/p12-t55-metadata-validation.md
    title: T55 — Write-Path Metadata Size + Charset Validation
  - resource: docs/contracts/modules/arkeology.tools.write_artifacts.md
    title: arkeology.tools.write_artifacts
  - resource: docs/contracts/modules/arkeology.tools.migrate_artifacts.md
    title: arkeology.tools.migrate_artifacts
  - resource: docs/contracts/data/s3vectors.artifact.md
    title: s3vectors.artifact
generated:
  by: "axians-architect/claude-opus-4.8"
  at: 2026-07-03T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-15T20:28:28Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
  - by: "axians-architect/claude-fable-5-2"
    at: 2026-11-15T20:45:07Z
---

# T46 — `references` First-Class Field on `Artifact` + write / read / list Surfacing

## TL;DR

Add `references: list[str]` as a first-class `Artifact` field holding resolved full S3 keys (the
operative `artifact_id`, scope prefix and file extension included). It is accepted at write time,
stored only as an S3 object annotation (written by T47) and never in vector metadata, and returned
by `read_artifact`, and by `list_artifacts` when the caller asks for link fields, both reading it
from that annotation. No tool filters on it.
Absent/legacy `references` returns `[]`. **Among the specs, this one owns the `references` field
across write / read / list — including the bulk write and migrate surfaces;** its stored shape is
the `s3-annotations.artifact` data contract's. (FR-51, AC-56, AC-57.)

## 1. Problem Statement

Arkeology has no first-class way for one artifact to point at another
(adr-2026-07-03-artifact-cross-referencing D2). `commit_refs` (T36) already demonstrates a link
field flowing through write/read/list, and `references` follows the same plumbing on the write and
read side, with its value held in the S3 object annotation. This field is the data-model foundation
the migration rewrite (T51) and the `link_metadata` backfill (T49) build on.

Every behaviour in this spec comes from a P1 story: `references` persisted through write, read, and
list; `references` kept out of vector metadata with no filter on it; bulk write and migrate
threading `references`.

## 2. Rules — The `references` field through write, read and list

### R1 — `references` on the `Artifact` model

When the `Artifact` model is constructed, it accepts `references: list[str]` with
`Field(default_factory=list)`, placed alongside `commit_refs`.

### R2 — `read_artifact` returns `references`

When `read_artifact` runs, it reads `references` from the object's S3 annotation
(`annotations.read_link_annotations`) and returns `references: list[str]`, `[]` when the annotation
is absent. A failed annotation read is an error — `annotation_unavailable` when annotations are
unavailable or access is denied — never a successful read reporting `[]` (`arkeology.tools.read` §
read_artifact).

**Example**

- Given an artifact written with
  `references=["team-a/payments/adr-use-postgres-abc12345.md"]`, when `read_artifact` is called,
  then `references: ["team-a/payments/adr-use-postgres-abc12345.md"]` appears in the response.

### R3 — `list_artifacts` returns `references` in each entry when link fields are requested

When `list_artifacts` is called asking for link fields, it includes `references: list[str]` in each
entry, read from that artifact's S3 annotation, `[]` when absent. Without that request no entry
carries a `references` key (p3-t10-list-artifacts R11).

**Example**

- Given an artifact written with
  `references=["team-a/payments/adr-use-postgres-abc12345.md"]`, when `list_artifacts` is called
  with `include_links=True`, then that artifact's entry includes the same `references`; called
  without it, the entry has no `references` key.

Source: FR-51, AC-56; p3-t10-list-artifacts R11

### R4 — The `write_artifact` response does not carry `references`

When `write_artifact` succeeds, its response is `artifact_id`, `sections_indexed` and
`last_edited_ulid` and nothing else (`arkeology.tools.write` § write_artifact): it does not echo
`references`, including when the write cleared the field. A caller reads the stored value back with
`read_artifact`, or with `list_artifacts` asking for link fields.

**Example**

- Given an overwriting write that supplies no `references` for an artifact that had two, when it
  succeeds, then the response holds no `references` key, and a following `read_artifact` returns
  `references: []`.

### R5 — Absent or legacy `references` is `[]`

When an artifact has no `references` annotation, every response that carries the field returns
`[]` — never an error, and never an absent key. A listing that did not ask for link fields carries
no `references` key at all, for any artifact (R3).

**Example**

- Given an artifact written with no `references`, when read, or listed with `include_links=True`,
  then `references` is `[]` — not absent, not an error.
- Given an artifact written before this feature (no `references` annotation), when read, or
  listed with `include_links=True`, then `references` is `[]`.

Source: AC-56, FR-51

## 3. Rules — No vector-metadata copy and no `references` filter

### R6 — `references` is never written to vector metadata

`references` is never written to S3 Vectors metadata under any circumstance — the S3 object
annotation copy (`p12-t47-annotation-dual-write.md`) is the field's **sole** durable store and sole
read surface. `write_artifact` accepts it; `read_artifact`, and `list_artifacts` when link fields
are requested, return it from the annotation (R2, R3).

**Why:** a real-AWS calibration showed the local byte-budget measure under-counts AWS's accounting
for this field shape, so a long `references` list overflowed the 2 KB filterable-metadata budget;
the field was kept out of the vector store instead of being capped.

Source: adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal.md D2

### R7 — `list_artifacts` has no `references` filter

`list_artifacts` has no `references=` filter parameter, and no other tool filters on `references`:
with no copy in vector metadata there is nothing for a server-side filter to match. `commit_refs=`
filtering is unaffected.

Source: adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal.md D2; AC-57

## 4. Rules — Bulk write and migrate

### R8 — `write_artifacts` and `migrate_artifacts` thread `references`

When `write_artifacts` / `migrate_artifacts` process a descriptor, they thread a `references` key
through to `_write_artifact_inner`.

**Example**

- Given a `write_artifacts` descriptor carrying
  `references=["team-a/payments/adr-use-postgres-abc12345.md"]`, when the batch is written, then
  the resulting artifact's `references` annotation carries that key and its vector metadata carries
  no `references`.
- Given a `migrate_artifacts(dry_run=False)` descriptor carrying the same `references`, then the
  written artifact carries the same references (threaded through to `write_artifact`).

## 5. Rules — Overwrite and cross-scope behaviour

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
- `references` holds **only resolved full S3 keys (the operative `artifact_id`, scope prefix and
  file extension included)** — no `arkeology://` prefix, no path text
  (adr-2026-07-03-artifact-cross-referencing D2). The form is checked at write: an element with no
  scope separator is rejected with `validation_error` (`p12-t55-metadata-validation` R10).
  Resolvability is not checked (no write-time cross-scope validation, ADR-012 "Cross-scope
  reference visibility"; what a foreign-scope reader is shown is filtered by R10).
- Stored as the comma-joined `references` annotation, absent when empty
  (`s3-annotations.artifact` § Storage Shape); never in vector metadata (R6).
- `references` is read from the **S3 object annotation** in `read_artifact` / `list_artifacts` —
  never from vector metadata and never from S3 user-defined metadata.

**Ask First:**
- Nothing — all constraints are defined.

**Never:**
- Do not write `references` into S3 user-defined object metadata or into vector metadata — the only
  copy is the S3 object annotation, whose write is T47's responsibility (ADR-011).
- Do not store artifact content in vector metadata (NFR-01).
- Do not add cross-scope validation for reference targets (ADR-012 closed this as not applicable).

## 7. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_artifact.py` | Modify | Tests for `references` field on `Artifact` — Red first |
| `src/arkeology/artifact.py` | Modify | Add `references: list[str] = Field(default_factory=list)`; update docstring |
| `tests/unit/test_tools_write.py` | Modify | Tests: `references` passed to the annotation write, absent from vector metadata and from `s3_metadata`; success response carries no `references` key — Red first |
| `src/arkeology/tools/write.py` | Modify | Accept `references` param; add to `Artifact(...)` and pass it to the T47 annotation write; do NOT add it to `s3_metadata` or `vector_metadata` |
| `tests/unit/test_tools_read.py` | Modify | Tests: `references` from the annotation; `[]` when the annotation is absent; `AnnotationUnavailableError` → `annotation_unavailable` — Red first |
| `src/arkeology/tools/read.py` | Modify | Read `references` with `read_link_annotations`; add to return dict |
| `tests/unit/test_tools_list.py` | Modify | Tests: under `include_links=True`, `references` in each entry, read from the annotation; no `references` filter parameter — Red first |
| `src/arkeology/tools/list.py` | Modify | Under `include_links=True`, read `references` per entry from the annotation; no `references` filter parameter |
| `tests/unit/test_tools_write_artifacts.py` | Modify | Test descriptor `references` threading — Red first |
| `src/arkeology/tools/write_artifacts.py` | Modify | Thread `references` from descriptor to `_write_artifact_inner` |
| `src/arkeology/tools/migrate_artifacts.py` | Modify | Thread `references` through descriptor (dry_run=False path) |
| `src/arkeology/server.py` | Modify | Add `references` param to the `write_artifact` tool wrapper |
| `src/arkeology/resources.py` | Modify | Add `references` to the artifact-schema resource field catalogue |

### Contracts

- `docs/contracts/modules/arkeology.tools.write.md` § write_artifact — the `references` input, its replace semantics on overwrite, and the success response that does not echo it (R4, R9).
- `docs/contracts/modules/arkeology.tools.read.md` § read_artifact — `references` read from the annotation, filtered for a foreign-scope reader, and the annotation-read errors (R2, R5, R10).
- `docs/contracts/modules/arkeology.tools.list.md` § list_artifacts — `references` in each entry only under `include_links`, its foreign-scope filtering, and no `references` filter (R3, R5, R7, R10).
- `docs/contracts/modules/arkeology.tools.write_artifacts.md` § write_artifacts — the descriptor that carries `references` into the single write (R8).
- `docs/contracts/modules/arkeology.tools.migrate_artifacts.md` § migrate_artifacts — the `references` descriptor key passed through to the write (R8).
- `docs/contracts/data/s3-annotations.artifact.md` § Storage Shape, § read_link_annotations and § Compatibility Guarantees — the annotation as the field's sole store and read surface, its encoding and full-key form, and an absent annotation read as `[]` (R2, R5, R6).
- `docs/contracts/data/s3vectors.artifact.md` § Storage Shape — `references` never present in vector metadata (R6, R8).

### Testing Approach

**TDD cycle — modify the test file before the implementation file in each pair; do not skip ahead:**

Examples use full keys, e.g. `team-a/payments/adr-use-postgres-abc12345.md` (`A`) and
`team-a/payments/spec-billing-export-1f2e3d4c.md` (`B`).

1. **`test_artifact.py` → `artifact.py`** — `Artifact(references=[A])` stores the value; default
   is `[]`.
2. **`test_tools_write.py` → `write.py`** — `write_artifact(references=[A, B])` writes the
   `references` annotation with both keys and puts no `references` key in vector metadata (spy on
   `put_vectors_batch`); the success response has no `references` key (R4); `references=[]` writes
   no `references` annotation.
3. **`test_tools_read.py` → `read.py`** — read returns `references` from the annotation; returns
   `[]` when the annotation is absent; an `AnnotationUnavailableError` from the read returns
   `annotation_unavailable`, never `references: []`.
4. **`test_tools_list.py` → `list.py`** — with `include_links=True`, each entry carries
   `references` read from its annotation (may be `[]`); without it, no entry has the key (R3);
   calling with a `references` argument is rejected (R7).
5. **`test_tools_write_artifacts.py` → `write_artifacts.py` / `migrate_artifacts.py`** — a
   descriptor with `references` round-trips into the written artifact's `references` annotation,
   with no `references` key in its vector metadata.

Use `aws_mock`, `s3_client`, `vectors_client` fixtures. `FakeBedrockClient` for embeddings.
