---
type: Contract
title: arkeology.tools.write
description: The write_artifact MCP tool — stores one artifact to S3 and indexes its section vectors, with a deterministic key, a reject-by-default collision guard, pre-write budget validation, and durable-first link-field ordering.
tags: []
timestamp: 2026-09-04T00:00:00Z
okf_version: "0.1"
references:
  - docs/specs/p2-t7-write-artifact.md
  - docs/specs/p8-t26-concurrent-embedding.md
  - docs/specs/p8-t28-section-caps.md
  - docs/specs/p12-t46-references-field.md
  - docs/specs/p12-t47-annotation-dual-write.md
  - docs/specs/p12-t55-metadata-validation.md
  - docs/specs/p12-t58-commit-refs-cap-references-removal.md
authored:
  by: "tech-writer"
  date: 2026-09-04
revised:
  by: "architect"
  date: 2026-09-04
---

# arkeology.tools.write

## Scope

The single-artifact write boundary and the origin of every durable shape in the system. It writes
three stores in one call — the S3 object, the object's annotations, and the vector index — and the
ordering and failure semantics between them are the contract.

## Symbols

### write_artifact

```python
async def write_artifact(
    *,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface,
    type: str,
    team: str,
    project: str,
    tier: int,
    date: str,
    title: str,
    description: str,
    content: str,
    visibility: str,
    tags: list[str] | None = None,
    author_role: str | None = None,
    source_artifacts: list[str] | None = None,
    commit_refs: list[str] | None = None,
    references: list[str] | None = None,
    status: str = "active",
    file_extension: str = ".md",
    overwrite: bool = False,
) -> dict[str, Any]: ...
```

**Errors**

Never raises. Every failure is a returned dict carrying an `"error"` key.

- `validation_error` — an invalid field value, a `type` outside `ARTIFACT_TYPES`, an invalid or
  wrong-typed `tier`, a title over length or containing a control character, a metadata budget
  breach, or a generated key that already exists while `overwrite` is `False`.
- `conflict` — the bounded compare-and-swap retry cycle was exhausted on an overwriting write.
- `partial_write` — the S3 object was written but indexing failed. A failure-log entry is appended
  so `reconcile_index` can complete the write later.
- `credential_error` — an AWS call raised `CredentialError`.
- `internal_error` — any otherwise unhandled exception.

**Invariants**

- The key is fully deterministic from artifact attributes — never random, never a UUID. See
  `s3.artifact` for the scheme.
- **A generated key that already exists is rejected by default.** `overwrite=True` is required to
  replace an existing artifact. The guard is atomic via a conditional `put_object`
  (`IfNoneMatch: "*"`) when `overwrite=False`, so two concurrent creates cannot both succeed and
  there is no check-then-act window.
- Metadata budgets are validated against the **actual serialized representations about to be
  written**, before any `head_object` / `put_object` / `put_vectors_batch` and before any
  failure-log append. A rejected write touches neither store nor the log.
- On a tier-3 overwriting write, existing link fields are read forward from the union of both
  durable stores and merged, then the budget check is **re-run** against the enlarged metadata
  before any write.
- `commit_refs` is accretive on overwrite — a union-merge, because it is a git-derived audit trail.
  `references` has **plain replace semantics** — it mirrors the supplied value exactly, and omitting
  it clears the field. The two are deliberately different and must not be unified.
- Vector metadata never receives `references`, and receives at most the most-recent 20 `commit_refs`
  entries. The annotation write always receives both in full.
- Store ordering is S3 object, then annotations, then vectors — durable before searchable, so a
  failed vector write leaves a recoverable orphan that `reconcile_index` repairs, never lost content.
- Section embedding goes through the shared `_section_pipeline`, applying the minimum-length filter,
  the maximum-sections cap, and per-section truncation. `reconcile_index` uses the same pipeline, so
  a section truncated at write time is not re-submitted full-length on replay.
- Concurrent embed calls per artifact are bounded by the configured section concurrency.
- Overwriting an existing artifact cleans up orphaned section vectors from the previous write.
- An **overwriting** write is serialised by a bounded ETag compare-and-swap cycle, bounded by
  `CAS_MAX_ATTEMPTS`. Two conditional writes share one cycle: the `put_object` is conditional on
  the ETag read during the existence check, and the `apply_link_annotations` that follows is
  conditional on the *new* ETag returned by that `put_object`. A conflict from **either** call
  retries the whole cycle — re-read, re-merge, re-write — never just the failed half; retrying
  only the annotation write would attach link fields to an object another writer had since
  replaced. Exhausting the cycle returns `conflict`, never a partial write.
- **Each retry re-merges the caller's originally supplied `commit_refs`/`references`, never a
  previous attempt's already-merged output.** This is what stops merges compounding: re-merging
  the merged result would accumulate entries across attempts, so a write that raced twice would
  persist link fields the caller never asked for, and the final content would depend on how many
  times it happened to retry.
- A **fresh** write is not part of this cycle and has nothing to race against. Its
  `if_none_match="*"` guard addresses a different race — two concurrent creates of the same
  generated key — and yields `validation_error`, not `conflict`. Do not conflate the two
  conditions: one means "someone else changed this object mid-write", the other means "this key
  already exists".
- `last_edited_ulid` is regenerated on every write.

**Preconditions**

- `type` must be a member of `ARTIFACT_TYPES`; `tier` must be 2 or 3.
- `title` must be within the length bound and free of control characters.
- A caller intending to replace an existing artifact must pass `overwrite=True` deliberately.

**Postconditions**

- On success, returns `{"artifact_id": str, "sections_indexed": int, "last_edited_ulid": str}`,
  plus a fourth key `"warning": str` **only** when the durable annotation write was unavailable
  (see below).
- On success all three stores agree: object content present, annotations reflecting the final link
  fields, and one vector per indexed section — **unless** a `"warning"` key is present.
- Annotations are unavailable on directory and Outposts buckets, and can become unavailable through
  IAM drift. The write path degrades gracefully rather than failing: content and vectors are still
  persisted, the tool still returns success, and the response carries a top-level `"warning"`
  describing that no durable `commit_refs`/`references` copy was stored. A caller that needs the
  link fields to be durable must check for `"warning"` — a bare check for the absence of `"error"`
  is not sufficient. (`link_metadata` is the deliberate exception: its whole purpose is the durable
  write, so it surfaces `annotation_unavailable` as an error instead of absorbing it.)
- On `partial_write` the S3 object is durable and a failure-log entry exists; the artifact is
  content-complete but unsearchable until reconciled.
- A failure-log entry written because the **annotation** write failed also records the
  `commit_refs` and `references` that write was applying, as two **optional** entry fields. The
  preceding `put_object` has already cleared the object's annotations, so the entry is the only
  remaining source `reconcile_index` can restore them from — `references` is never in vector
  metadata and the vector `commit_refs` copy is capped. Both are recorded in full and uncapped, and
  are omitted when empty; an absent field means "nothing to restore", never "clear the field".
- On any `validation_error` nothing was written anywhere and no failure-log entry was created.
