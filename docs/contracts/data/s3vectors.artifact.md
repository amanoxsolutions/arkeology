---
type: Contract
id: s3vectors.artifact
title: s3vectors.artifact
description: The per-artifact S3 Vectors shape — the numbered vector key {artifact_id}#{n} under a 100-vector ceiling, the searchable, filterable metadata projection of an artifact, its three byte budgets, and the deliberate ways it differs from the S3 object-metadata and annotation copies.
tags: []
okf_version: "0.2"
sources:
  - resource: docs/specs/p12-t55-metadata-validation.md
    title: T55 — Write-Path Metadata Size + Charset Validation
    last_modified: 2026-08-17T00:00:00Z
  - resource: docs/specs/p12-t58-commit-refs-cap-references-removal.md
    title: T58 — commit_refs Vector-Metadata Cap (20) + references Vector-Metadata Removal + propose_commit_links Multi-Section Fix
    last_modified: 2026-08-17T00:00:00Z
  - resource: docs/specs/p15-t92-numbered-vector-keys.md
    title: T92 — Numbered Vector Keys and Per-Artifact Vector Access by Key
    last_modified: 2026-11-12T14:38:17Z
  - resource: docs/architecture-decisions/adr-2026-05-29-aws-backend-selection.md
    title: AWS S3 + S3 Vectors + Bedrock as the Storage and Embedding Backend
    last_modified: 2026-11-12T14:38:17Z
  - resource: docs/specs/p10-t35-filter-range-operators.md
    title: T35 — Filter Range Operators ($gte / $lte)
  - resource: docs/learnings.md
    title: Learnings
  - resource: tests/integration/clients/test_vectors_filter_semantics.py
  - resource: .docs/reviews/architecture-review-2026-11-15-arkeology-phases-9-10-12.md
    title: "Architecture review — Arkeology, plan phases 9, 10 and 12"
generated:
  by: "axians-tech-writer/claude-opus-5"
  at: 2026-09-04T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-15T19:18:17Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
  - by: "axians-architect/claude-fable-5-2"
    at: 2026-11-15T21:22:34Z
---

# s3vectors.artifact

## Scope

The metadata dict written alongside each artifact's embedding vector in S3 Vectors, and the
validation layer in front of it. This is the artifact's *searchable* representation: it exists to
be filtered on, not to be authoritative. Artifact content lives only in S3, and the
`commit_refs` / `references` values live only in the S3 object annotation copy — this store's
`commit_refs` is a derived index of that copy, written but never read back.

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

Each vector of an artifact is keyed `{artifact_id}#{n}`, `n` in decimal without padding. An artifact
holds at most 100 vectors, `#0` to `#99` — the maximum of `EMBED_MAX_SECTIONS` and the `GetVectors`
per-call limit — and every indexed artifact holds `#0`. A write numbers the vectors from 0 in the
document order of the artifact's embedded sections, and an artifact with nothing to embed has its
one document vector at `#0`. The order carries no meaning: nothing reads a section from its key, so
an artifact the store migration re-keyed keeps the migration's numbering until its next update or
re-index. No key is derived from a section heading, and no vector is written at the bare
`artifact_id`. Every vector of one artifact carries the same metadata dict below.

The metadata is written as `VectorMetadata = dict[str, str | int | float | list[str]]`.

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
| `commit_refs` | `list[str]` | Capped to the most-recent 20 entries. A **derived filter index**: written so the index can answer "which artifacts carry commit ref X" as a server-side filter clause, never read back as a source of truth. |

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

- The key shape `{artifact_id}#{n}`, `n` from 0 to 99, may not change without a store migration. A
  consumer may rely on reading all of one artifact's vectors with one `GetVectors` over `#0` to
  `#99`, and one artifact's metadata from `#0`. It must never derive the key range from the live
  `EMBED_MAX_SECTIONS`: an artifact written under a higher setting keeps vectors above a lowered one.
- No path writes a vector at an earlier key shape — `{artifact_id}#{heading slug}` or the bare
  `{artifact_id}` — and no per-artifact path reads by one, with two exceptions: the store migration
  reads them to re-key them, and reconcile's orphan-cleanup replay reads the keys an entry recorded,
  which an entry from an old failure log may give in an earlier shape (the replay finds them gone and
  deletes nothing). An enumeration of a scope may still meet
  a vector at an earlier key, from a scope its team has not yet migrated; the store migration moves
  the own scope's to numbered keys, and a repair that meets one at an earlier key leaves it to that
  migration rather than rewriting it in place.
- `artifact_id` may never be removed, renamed, or retyped. It is the join key between this store,
  S3, and the annotation store.
- `tier` stays an `int` here. A consumer may rely on numeric comparison; it must not expect the
  string form used in S3 object metadata.
- `tags` stays a `list[str]` here. A consumer may rely on `$eq` element-in-list filtering; it must
  not expect the comma-joined string form used in S3 object metadata. Both representations are
  correct and intentionally different — neither is being migrated toward the other.
- A reader must tolerate a `references` key on vectors written before its removal shipped, but no
  path reads or writes it. The union-of-both-durable-stores read model that once read it back is
  retired; the annotation copy is the sole source of truth for both link fields.
- A reader must tolerate `tags`, `source_artifacts`, and `commit_refs` being absent rather than
  empty.
- **A range on a string value is evaluated in process, never by the index.** The index accepts the
  range operators on numeric values only and rejects a range on a string value — `last_edited_ulid`,
  `date`, or any other `str` key above — with a `ValidationException`, as the integration suite's
  filter-semantics test pins against the real service. A string range is therefore applied by the
  server after the vectors are fetched and is never placed in a filter expression sent to the
  index; a time bound the index itself must apply needs a numeric field. That the in-process filter
  evaluator accepts a string range proves nothing about the index: the unit suite's query double
  evaluates filters with that same evaluator, so a string range sent to the index passes every unit
  test and fails only against the real service.
- `commit_refs` here is a bounded, most-recent-N **derived** view. A consumer may never treat its
  contents as the complete set, may never derive a count of an artifact's total commit references
  from it, and may never read it back as the current link-field state. Its one job is serving the
  server-side filter clause; the complete value lives in the annotation copy. The cap is therefore
  a property of the index, not a limit on stored data.
- The 20-entry cap is calibrated against real AWS write-rejection behaviour for the current
  filterable-key mix, not derived from the byte budget above — the local approximation
  under-measures what AWS actually rejects. Changing the set of filterable vector-metadata keys
  invalidates the calibration and requires a fresh calibration run before the cap is trusted.
- The index dimension is immutable once created. A change to the configured embedding dimensions
  requires deleting and recreating the index, losing every vector; content in S3 survives and
  `reconcile_index` can rebuild from it.
- Artifact content may never be stored here.
