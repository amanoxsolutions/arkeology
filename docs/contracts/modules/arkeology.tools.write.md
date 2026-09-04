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
  by: ""
  date: YYYY-MM-DD
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
- `last_edited_ulid` is regenerated on every write.

**Preconditions**

- `type` must be a member of `ARTIFACT_TYPES`; `tier` must be 2 or 3.
- `title` must be within the length bound and free of control characters.
- A caller intending to replace an existing artifact must pass `overwrite=True` deliberately.

**Postconditions**

- On success, returns `{"artifact_id": str, "sections_indexed": int, "last_edited_ulid": str}`.
- On success all three stores agree: object content present, annotations reflecting the final link
  fields, and one vector per indexed section.
- On `partial_write` the S3 object is durable and a failure-log entry exists; the artifact is
  content-complete but unsearchable until reconciled.
- On any `validation_error` nothing was written anywhere and no failure-log entry was created.
