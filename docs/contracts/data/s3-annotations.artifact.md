---
type: Contract
title: s3-annotations.artifact
description: The S3 object-annotation store holding an artifact's mutable link fields — the complete, authoritative commit_refs and references copies, their comma-joined payload encoding, the union-of-both-stores read authority model, and the compare-and-swap guard on every mutation.
tags: []
timestamp: 2026-09-04T00:00:00Z
okf_version: "0.1"
references:
  - docs/specs/p12-t45-s3-annotation-client.md
  - docs/specs/p12-t47-annotation-dual-write.md
  - docs/specs/p12-t48-reconcile-from-annotations.md
  - docs/specs/p12-t52-annotation-availability-graceful.md
  - docs/specs/p12-t58-commit-refs-cap-references-removal.md
  - docs/architecture-decisions/adr-2026-07-03-annotation-backed-link-storage.md
authored:
  by: "tech-writer"
  date: 2026-09-04
revised:
  by: ""
  date: YYYY-MM-DD
---

# s3-annotations.artifact

## Scope

Annotations attached to an artifact's S3 object, holding the two **mutable** link fields
`commit_refs` and `references`. They exist because these fields change after the artifact is
written — backfilled repeatedly by `link_metadata` — and object metadata cannot be edited in place
while vector metadata is too small to hold them without a cap. This is the complete, uncapped copy;
`s3vectors.artifact` carries a bounded projection of `commit_refs` and none of `references`.

## Symbols

### encode_link_list

```python
def encode_link_list(values: list[str]) -> str: ...
```

**Errors**

None.

**Invariants**

- Comma-joins the values. `[]` encodes to `""`.

**Preconditions**

- No element may itself contain a comma; the payload format has no escaping.

**Postconditions**

- Round-trips through `decode_link_list` for any comma-free element list.

### decode_link_list

```python
def decode_link_list(payload: str) -> list[str]: ...
```

**Errors**

None.

**Invariants**

- An empty payload decodes to `[]`, never `[""]`.
- Empty elements arising from a malformed or hand-edited payload — a double comma, a trailing comma
  — are dropped rather than surfaced as blank entries.

**Preconditions**

- None. Total over its input type, including malformed payloads.

**Postconditions**

- Every element of the result is a non-empty string.

### apply_link_annotations

```python
def apply_link_annotations(
    s3: S3ClientInterface,
    key: str,
    *,
    commit_refs: list[str],
    references: list[str],
    if_match: str | None = None,
) -> None: ...
```

**Errors**

- `ArtifactConflictError` — raised when `if_match` is set and does not match the object's current
  ETag (HTTP 412) on either the put or the delete call.
- `CredentialError` — raised when credentials are invalid or expired.

**Invariants**

- A non-empty list is written as its comma-joined payload; an **empty list deletes** the
  corresponding annotation, mirroring the vector-metadata omit-when-empty rule.
- `delete_object_annotation` is a silent no-op when the annotation is already absent, so this is
  safe to call unconditionally on every write.
- Both fields are always written with their **full, uncapped** values. The 20-entry `commit_refs`
  cap applies to the vector-metadata representation only and must never be applied here.
- Writing an annotation does not change the object's content, its ETag, or require a re-PUT.

**Preconditions**

- The values passed must already be the final, merged values. This symbol does not merge — callers
  resolve the union first, via `read_current_link_fields`.
- The object at `key` must exist.
- On any read-modify-write cycle, `if_match` must carry the ETag captured at read time. Omitting it
  reverts to unconditional behaviour and reopens the lost-update race.

**Postconditions**

- On success both annotations reflect the supplied values exactly — present with the joined payload,
  or absent where the list was empty.
- On `ArtifactConflictError` the caller must retry the whole read-merge-write cycle, bounded by
  `CAS_MAX_ATTEMPTS` (3), before surfacing a structured `conflict` error.

### read_link_annotations

```python
def read_link_annotations(s3: S3ClientInterface, key: str) -> tuple[list[str], list[str]]: ...
```

**Errors**

- `CredentialError` — raised when credentials are invalid or expired.

**Invariants**

- Returns `(commit_refs, references)`, each `[]` when its annotation is absent. An absent annotation
  is indistinguishable from a cleared one by design — both mean "no values".

**Preconditions**

- None beyond the object existing.

**Postconditions**

- Reads this store only. A caller needing current truth must use `read_current_link_fields`
  instead; this symbol alone is not authoritative.

### read_current_link_fields

```python
def read_current_link_fields(
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    artifact_id: str,
) -> tuple[list[str], list[str]]: ...
```

**Errors**

- `CredentialError` — re-raised, never swallowed, from either store. It signals a general
  authentication failure very likely to break the surrounding operation, so treating it as "no link
  fields" would be a silent data-loss path.

**Invariants**

- Returns the **order-preserving dedup union of both stores**, annotation values first, vector
  values second. Neither store is sole authority.
- The annotation side degrades gracefully on any non-`CredentialError` failure — an unsupported
  region or bucket type, `AccessDenied` — falling back to the vector copy for that store rather than
  aborting the caller.
- The vector side unions across **all** of the artifact's section vectors, not just the first key.

**Preconditions**

- None beyond the artifact existing in at least one store.

**Postconditions**

- Each returned list is `[]` only when the field is absent from **both** stores.
- This is the only correct input to a link-field merge. It exists to close two real data-loss paths:
  an annotation-unavailable deployment holding values in vector metadata only (where an
  annotation-only read reports them absent and a `reconcile_index` rebuild would erase the sole
  durable copy), and a partial dual-write leaving the annotation copy ahead of the vector copy
  (where a vector-only read misses the newer value and the next overwrite drops it).

## Storage Shape

Two named annotations per object, both optional:

| Annotation name | Payload | Absent when |
|---|---|---|
| `commit_refs` | Comma-joined `list[str]` — full SHA, short SHA, PR URL, or tag; format is opaque | The list is empty |
| `references` | Comma-joined `list[str]` of resolved `artifact_id` values | The list is empty |

Annotations are mutable in place, do not require re-PUTting the object, leave the ETag stable, and
carry a far larger ceiling than either object metadata (2 KB) or vector filterable metadata (2 KB).

`CAS_MAX_ATTEMPTS` = 3 bounds the compare-and-swap retry cycle for every mutation.

## Compatibility Guarantees

- This store is the **sole authoritative and only complete** copy of `commit_refs`, and the sole
  durable store and sole read surface for `references`. A consumer needing either field in full must
  read here, never the vector projection.
- `references` may never be written back to vector metadata. Native `$eq`/`$in` filtering on
  `references` was deliberately given up rather than forced into a 2 KB budget; restoring it is a
  graph-technology decision, not a storage tweak.
- **Overwriting the object wipes its annotations.** This is real S3 semantics, not a bug, and the
  write path must always read-forward and re-apply the link fields after an overwriting
  `put_object`. Any refactor that drops that read-forward silently loses link data on every tier-3
  living-document update.
- Durable-first write ordering must be preserved: annotations are written before vector metadata, so
  a failed vector write self-heals on the next `reconcile_index` rather than losing the value. The
  reverse order makes the loss permanent.
- The payload format has no escaping, so no element may contain a comma. A future value shape that
  needs commas requires a payload format change, not a workaround at a call site.
- A reader must tolerate both annotations being absent on any artifact written before the annotation
  split shipped, and must treat absence as `[]` rather than as an error.
- Annotations are unavailable on directory buckets and Outposts buckets. Every path touching them
  must degrade gracefully rather than fail, except `link_metadata`, whose entire purpose is the
  durable write and which therefore surfaces `annotation_unavailable` instead of absorbing it.
- `reconcile_index` reads both fields from here to rebuild vector metadata losslessly. It must keep
  reading a `references` key from vector metadata too, for backward-read compatibility with vectors
  written before that field's removal.
