---
type: Contract
id: arkeology.tools.link_metadata
title: arkeology.tools.link_metadata
description: The post-hoc, accretive backfill primitive for an artifact's commit_refs and references link fields — dual-writes the durable annotation copy and the bounded vector-metadata copy without re-embedding.
tags: []
okf_version: "0.2"
sources:
  - resource: docs/specs/p12-t49-link-metadata.md
    title: T49 — link_metadata Tool (generalizes and supersedes link_commit)
    last_modified: 2026-09-06T00:00:00Z
  - resource: docs/specs/p12-t57-guard-coverage.md
    title: T57 — Guard Coverage in link_metadata.py and reconcile.py + Control-Character Validation Fix
    last_modified: 2026-08-17T00:00:00Z
  - resource: docs/specs/p12-t58-commit-refs-cap-references-removal.md
    title: T58 — commit_refs Vector-Metadata Cap (20) + references Vector-Metadata Removal + propose_commit_links Multi-Section Fix
    last_modified: 2026-08-17T00:00:00Z
  - resource: docs/architecture-decisions/adr-2026-07-03-annotation-backed-link-storage.md
    title: Annotation-Backed Durable Storage for Mutable Link Fields (commit_refs + references)
    last_modified: 2026-09-29T00:00:00Z
  - resource: docs/specs/p3-t15-partial-write-failure-log.md
    title: T15 — Partial Write Failure Log
    last_modified: 2026-11-10T16:24:49Z
  - resource: .docs/reviews/architecture-review-2026-11-10-arkeology.md
    title: Architecture review — Arkeology (whole design record)
    last_modified: 2026-11-10T11:21:17Z
  - resource: docs/architecture-decisions/adr-2026-05-29-aws-backend-selection.md
    title: AWS S3 + S3 Vectors + Bedrock as the Storage and Embedding Backend
    last_modified: 2026-11-12T13:11:40Z
  - resource: docs/specs/p15-t92-numbered-vector-keys.md
    title: T92 — Numbered Vector Keys and Per-Artifact Vector Access by Key
    last_modified: 2026-11-12T13:11:40Z
  - resource: docs/specs/p1-t3-aws-client-layer.md
    title: T3 — AWS Client Layer
    last_modified: 2026-11-10T16:40:30Z
  - resource: docs/specs/p12-t51-migration-reference-rewrite.md
    title: "T51 — Migration Frontmatter Reference Rewriting + arkeology:// Content Rewrite"
  - resource: .docs/reviews/architecture-review-2026-11-15-arkeology-phases-9-10-12.md
    title: "Architecture review — Arkeology, plan phases 9, 10 and 12"
generated:
  by: "axians-tech-writer/claude-opus-5"
  at: 2026-09-04T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-15T20:12:17Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
  - by: "axians-architect/claude-fable-5-2"
    at: 2026-11-15T21:22:34Z
---

# arkeology.tools.link_metadata

## Scope

The `link_metadata` MCP tool: the only supported way to add `commit_refs` or `references` to an
artifact that already exists, without re-embedding it or mutating its stored content. It sits on
the boundary between an agent — linking its session's artifacts to a commit, or adding by hand a
reference that migration left unresolved — and the two
durable stores that hold an artifact's link fields — the S3 object annotation copy and the S3
Vectors metadata copy.

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
  when any supplied element is empty or whitespace-only, contains a control character or a comma,
  or — for `references` — is not a full key, containing no scope separator `/`
  (`s3-annotations.artifact` § Storage Shape), or when the merged values would breach a metadata
  size budget (`MetadataTooLargeError`, rejected before either store is written). A malformed
  element rejects the whole call before any `artifact_id` is touched.
- `credential_error` — returned when any AWS call raises `CredentialError`.
- `annotation_unavailable` — returned when the durable annotation write cannot be performed. This
  is never silently absorbed: the durable write *is* this tool's contract, so the affected
  `artifact_id` is never counted as linked.
- `conflict` — returned when the bounded compare-and-swap retry cycle is exhausted without a
  successful conditional write, i.e. a concurrent object-body write changed the artifact on every
  attempt. A concurrent annotation-only write never produces this code (see the residual under
  Invariants).
- `internal_error` — returned for any otherwise unhandled exception.

**Invariants**

- No Bedrock call is ever made. Existing embeddings are reused verbatim from each vector's
  `data["float32"]`.
- `last_edited_ulid` is never altered.
- Stored artifact content is never mutated — this tool writes metadata only.
- Existing values are read from the object's **annotations**, their sole source of truth, never from
  vector metadata, and supplied values are merged into them per field, preserving first-seen order
  and de-duplicating. A failed annotation read raises rather than returning empty — merging supplied
  values into a spurious empty would delete the annotation instead of extending it.
- The merge is accretive for both fields. A field with no supplied values re-writes its existing
  value unchanged, never `[]`.
- The annotation store always receives the **full, uncapped** value for both fields.
- Vector metadata never receives a `references` key under any circumstance, and receives at most
  the most-recently-appended 20 `commit_refs` entries.
- Writes are ordered annotation-first, vectors-second. A failed vector write leaves the durable
  annotation copy correct and the vector copy stale, and appends a failure-log entry carrying the
  values that were applied. That entry is what makes the repair happen: `reconcile_index`'s
  failure-log replay re-indexes the artifact from the annotation copy on its next run, converging
  the two copies. Ordering alone would not — an artifact that still has vectors is invisible to
  the orphan scan.
- Each `artifact_id` retries its compare-and-swap cycle independently of the others.
- **Each `artifact_id`'s vectors are read by key.** One `GetVectors` over `{artifact_id}#0` to
  `{artifact_id}#99` (`s3vectors.artifact`), with data and metadata, finds them, and exactly the keys
  it returned are re-put, so a call's cost grows with the ids it is given, never with the size of
  the index every team shares. An id whose read returns no key has no indexed vector. A scan or a
  filtered query per id is the regression this forbids.
- The compare-and-swap token is the *object's* ETag, so the cycle serialises this tool against
  object-body writes (an overwriting `write_artifact`, an `archive_artifact` status re-PUT) and
  **not** against other annotation-only writes, which leave the ETag unchanged. Two `link_metadata`
  calls on the same field of the same artifact, or one `link_metadata` call whose read lands after
  such a re-PUT and races its trailing annotation re-apply, all pass the check; the later annotation
  write replaces the earlier one's value for that field with no `conflict` and no failure-log entry.
  Different-field callers never interfere. This is the accepted residual of the annotation-backed
  link storage ADR's decision 6 — no annotation-level precondition exists in the S3 API — so a
  caller that needs same-field serialisation must sequence its own calls.
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
- One `artifact_id`'s `annotation_unavailable`, metadata-budget `validation_error` or `conflict`
  stops the call: it returns that error instead of the success shape. The error response names that artifact in `artifact_id` and lists in `linked_ids` every
  `artifact_id` the call did link, in `artifact_ids` order — the ids a caller need not send again.
  Progress made on other `artifact_ids` is preserved, never rolled back. `linked_ids`, and the
  `linked` / `skipped` counts beside it, are included only when non-empty and non-zero. A malformed
  supplied element is not such a failure: it rejects the whole call before any `artifact_id` is
  touched, and that response carries none of these keys. For example, a `conflict` on the second of
  two ids after the first was linked returns `{"error": "conflict", "message": ..., "artifact_id":
  <the second id>, "linked_ids": [<the first id>], "linked": 1}`.
- An `artifact_id` whose annotation write succeeded but whose vector write failed is reported in a
  `vector_write_failed` list of ids, included only when non-empty. It is counted in neither
  `linked` (its vector copy is stale) nor `skipped` (its annotation copy was written), and a
  failure-log entry recording the applied `commit_refs` / `references` is queued for
  `reconcile_index`. A single such failure never discards the results the rest of the batch
  achieved.
- Whenever a response carries `vector_write_failed` it also carries `failure_logged: bool` —
  `true` when every listed id's failure-log entry was appended, `false` when any append failed. No
  other response carries it. On `false` at least one listed id has no entry, so `reconcile_index`
  does not repair that id's vector copy from the log; the server's stderr ERROR record names the id
  and the failed step but holds none of the entry.
- That entry also records the artifact's `last_edited_ulid` — unchanged by this tool, so it is the
  one the artifact already carried. `reconcile_index` compares it against the artifact's current one
  on replay and restores the entry's `references` only while the two still match, so a later
  overwriting write's replacement of the field is not undone by this entry. The entry's
  `commit_refs` unions unconditionally. Without the token the replay would be, in this tool's case
  especially, either a no-op or wrong: the annotation write it follows **succeeded**, so the entry's
  copy is only ever the current value or a stale one. See `arkeology.tools.reconcile`.
