---
type: Contract
title: s3vectors.artifact
description: The per-artifact S3 Vectors metadata shape — the searchable, filterable projection of an artifact, its three byte budgets, and the deliberate ways it differs from the S3 object-metadata and annotation copies.
tags: []
timestamp: 2026-09-04T00:00:00Z
okf_version: "0.1"
references:
  - docs/specs/p12-t55-metadata-validation.md
  - docs/specs/p12-t58-commit-refs-cap-references-removal.md
authored:
  by: "tech-writer"
  date: 2026-09-04
revised:
  by: ""
  date: YYYY-MM-DD
---

# s3vectors.artifact

## Scope

The metadata dict written alongside each artifact's embedding vector in S3 Vectors, and the
validation layer in front of it. This is the artifact's *searchable* representation: it exists to
be filtered on, not to be authoritative. Artifact content lives only in S3, and the complete
`commit_refs` / `references` values live only in the S3 object annotation copy.

## Symbols

### cap_commit_refs_for_vectors

```python
def cap_commit_refs_for_vectors(commit_refs: list[str]) -> list[str]: ...
```

**Errors**

None. Total over its input type.

**Invariants**

- Returns the **last** `COMMIT_REFS_VECTOR_METADATA_MAX_ENTRIES` (20) elements — the
  most-recently-appended window, never the first 20, never the full list.
- Never returns fewer than `min(len(commit_refs), 20)` entries.
- The cap applies to the vector-metadata representation only. It is never applied to a value on
  its way to the annotation store.
- It is the single shared helper for this cap. The three write paths (`write.py`,
  `link_metadata.py`, `reconcile.py`) all call it rather than each slicing independently.

**Preconditions**

- None beyond the argument type.

**Postconditions**

- The returned list is a suffix of the input, in the input's order.
- The result is **not** a completeness guarantee. A consumer that needs the complete
  `commit_refs` list must read the annotation-backed copy.

## Storage Shape

Written as `VectorMetadata = dict[str, str | int | float | list[str]]`.

Always present:

| Key | Type | Notes |
|---|---|---|
| `artifact_id` | `str` | The full S3 key. Identifies the artifact across both stores. |
| `scope` | `str` | The writing server's `write_prefix`. |
| `type` | `str` | One of `ARTIFACT_TYPES`. |
| `team` | `str` | |
| `project` | `str` | |
| `tier` | `int` | Stored as an integer, not a string, for filter compatibility. |
| `date` | `str` | |
| `status` | `str` | `active` or `inactive`. |
| `title` | `str` | Raw UTF-8. Non-filterable. |
| `visibility` | `str` | |
| `author_role` | `str` | Empty string when unset, never absent. Non-filterable. |
| `description` | `str` | Non-filterable. |
| `last_edited_ulid` | `str` | |

Present only when non-empty — S3 Vectors rejects empty arrays, so an empty list means the key is
omitted rather than written as `[]`:

| Key | Type | Notes |
|---|---|---|
| `tags` | `list[str]` | Stored as a list so `$eq` matches an individual element. |
| `source_artifacts` | `list[str]` | Non-filterable. |
| `commit_refs` | `list[str]` | Capped to the most-recent 20 entries. |

Never present: `references`. The field was removed from this representation entirely; the
annotation copy is its sole durable store and sole read surface.

Non-filterable keys are exactly `NON_FILTERABLE_METADATA_KEYS` — `description`,
`source_artifacts`, `title`, `author_role`. This tuple must match the externally-created S3
Vectors index's declared non-filterable slots exactly. Every other key counts against the
filterable budget.

Three byte budgets apply, all validated by `check_metadata_budgets` against the actual serialized
dicts about to be written, before any `head_object` / `put_object` / `put_vectors_batch` call and
before any failure-log append:

| Budget | Limit | Measured over |
|---|---|---|
| `S3_USER_METADATA_MAX_BYTES` | 2048 | Sum of UTF-8 key + transport-encoded value bytes in the S3 user-metadata dict |
| `VECTOR_FILTERABLE_METADATA_MAX_BYTES` | 2048 | JSON serialization of the keys *not* in `NON_FILTERABLE_METADATA_KEYS` |
| `VECTOR_TOTAL_METADATA_MAX_BYTES` | 40960 | JSON serialization of the full dict |

## Compatibility Guarantees

- `artifact_id` may never be removed, renamed, or retyped. It is the join key between this store,
  S3, and the annotation store.
- `tier` stays an `int` here. A consumer may rely on numeric comparison; it must not expect the
  string form used in S3 object metadata.
- `tags` stays a `list[str]` here. A consumer may rely on `$eq` element-in-list filtering; it must
  not expect the comma-joined string form used in S3 object metadata. Both representations are
  correct and intentionally different — neither is being migrated toward the other.
- A reader must tolerate a `references` key on vectors written before its removal shipped. No path
  writes it going forward, but the union-of-both-stores read helper keeps reading it for
  backward-read compatibility.
- A reader must tolerate `tags`, `source_artifacts`, and `commit_refs` being absent rather than
  empty.
- `commit_refs` here is a bounded, most-recent-N view. A consumer may never treat its contents as
  the complete set, and may never derive a count of an artifact's total commit references from it.
- The 20-entry cap is calibrated against real AWS write-rejection behaviour for the current
  filterable-key mix, not derived from the byte budget above — the local approximation
  under-measures what AWS actually rejects. Changing the set of filterable vector-metadata keys
  invalidates the calibration and requires a fresh calibration run before the cap is trusted.
- The index dimension is immutable once created. A change to the configured embedding dimensions
  requires deleting and recreating the index, losing every vector; content in S3 survives and
  `reconcile_index` can rebuild from it.
- Artifact content may never be stored here.
