---
type: Contract
title: arkeology.tools.link_metadata
description: The post-hoc, accretive backfill primitive for an artifact's commit_refs and references link fields — dual-writes the durable annotation copy and the bounded vector-metadata copy without re-embedding.
tags: []
timestamp: 2026-09-04T00:00:00Z
okf_version: "0.1"
references:
  - docs/specs/p12-t49-link-metadata.md
  - docs/specs/p12-t57-guard-coverage.md
  - docs/specs/p12-t58-commit-refs-cap-references-removal.md
authored:
  by: "tech-writer"
  date: 2026-09-04
revised:
  by: ""
  date: YYYY-MM-DD
---

# arkeology.tools.link_metadata

## Scope

The `link_metadata` MCP tool: the only supported way to add `commit_refs` or `references` to an
artifact that already exists, without re-embedding it or mutating its stored content. It sits on
the boundary between an agent (or the `backfilling-references` skill) and the two durable stores
that hold an artifact's link fields — the S3 object annotation copy and the S3 Vectors metadata
copy.

## Symbols

### link_metadata

```python
async def link_metadata(
    *,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface | None = None,
    artifact_ids: list[str],
    commit_refs: list[str] | None = None,
    references: list[str] | None = None,
) -> dict[str, Any]: ...
```

**Errors**

This symbol never raises to its caller — every failure is returned as a structured result dict
carrying an `"error"` key whose value is an `ErrorCode` member, per the project's `_inner`
delegation rule. It raises nothing.

- `validation_error` — returned when neither `commit_refs` nor `references` is supplied non-empty,
  when any supplied element is empty or whitespace-only, or when the merged values would breach a
  metadata size budget (`MetadataTooLargeError`, rejected before either store is written).
- `credential_error` — returned when any AWS call raises `CredentialError`.
- `annotation_unavailable` — returned when the durable annotation write cannot be performed. This
  is never silently absorbed: the durable write *is* this tool's contract, so the affected
  `artifact_id` is never counted as linked.
- `conflict` — returned when the bounded compare-and-swap retry cycle is exhausted without a
  successful conditional write, i.e. a concurrent writer changed the artifact on every attempt.
  Carries the offending `artifact_id`.
- `internal_error` — returned for any otherwise unhandled exception.

**Invariants**

- No Bedrock call is ever made. Existing embeddings are reused verbatim from each vector's
  `data["float32"]`.
- `last_edited_ulid` is never altered.
- Stored artifact content is never mutated — this tool writes metadata only.
- Existing values are read as the **union of both durable stores**, never from vector metadata
  alone, and supplied values are merged into that union per field, preserving first-seen order
  and de-duplicating.
- The merge is accretive for both fields. A field with no supplied values re-writes its existing
  unioned value unchanged, never `[]`.
- The annotation store always receives the **full, uncapped** value for both fields.
- Vector metadata never receives a `references` key under any circumstance, and receives at most
  the most-recently-appended 20 `commit_refs` entries.
- Writes are ordered annotation-first, vectors-second, so a failed vector write self-heals on the
  next `reconcile_index` run rather than losing the value.
- Each `artifact_id` retries its compare-and-swap cycle independently of the others.
- Where two different abort-worthy outcomes occur in the same concurrent batch, the returned error
  is decided deterministically in the original `artifact_ids` order.

**Preconditions**

- At least one of `commit_refs` or `references` must be supplied and non-empty.
- `settings`, `s3`, and `vectors` are injected by the server; the symbol never constructs a client
  itself.

**Postconditions**

- On success, returns `{"linked": int, "skipped": int, "next_since_ulid": str}`, with
  `next_since_ulid` generated once per call rather than per artifact.
- An `artifact_id` that does not start with `settings.write_prefix + "/"` is counted in `skipped`
  and left entirely untouched — foreign-scope artifacts can never be linked.
- An `artifact_id` with no indexed vector is counted in `skipped`, not treated as an error.
- Every `artifact_id` counted in `linked` has had its annotation copy durably written.
- On an `annotation_unavailable`, `validation_error`-from-budget, or `conflict` return, partial
  progress accumulated on other `artifact_ids` in the same call is preserved and reported via
  `linked` / `skipped` keys, included only when non-zero.
