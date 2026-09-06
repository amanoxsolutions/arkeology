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
  - docs/architecture-decisions/adr-2026-07-03-annotation-backed-link-storage.md
authored:
  by: "tech-writer"
  date: 2026-09-04
revised:
  by: "architect"
  date: 2026-09-06
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
  breach **detected while nothing is yet durable**, or a generated key that already exists while
  `overwrite` is `False`. A budget breach detected once a compare-and-swap attempt's `put_object`
  has landed returns `partial_write` instead; see the retry-budget-breach invariant.
- `conflict` — the bounded compare-and-swap retry cycle was exhausted on an overwriting write.
- `partial_write` — the S3 object was written but indexing, an annotation write whose cause is not
  separately diagnosable, or a compare-and-swap retry's re-merged budget check, failed. A
  failure-log entry is appended so `reconcile_index` can complete the write later.
- `annotation_unavailable` — the durable link store is unavailable or access to it is denied.
  **Two calls can raise it, and the code alone does not say which**: the read-forward of the
  current `commit_refs` at the start of an overwriting write, and the annotation write that
  follows the object write. On the read-forward nothing has been written and no failure-log entry
  exists; on the annotation write the S3 object is durable and an entry is appended, exactly as
  for `partial_write` and `credential_error`. Returned in place of `partial_write` on the same
  terms `credential_error` is, so that the caller is told the diagnosable cause rather than the
  generic state. This is the same code every other tool returns for this condition — see
  `s3-annotations.artifact` for the single-code rule and where the mapping lives.
- `not_found` — an overwriting write whose target was deleted by someone else between the initial
  existence check and a compare-and-swap retry. The retry's re-read finds the object gone, which is
  not a conflict (nothing to re-merge against) and not an internal error; nothing has been written,
  so no failure-log entry is appended.
- `credential_error` — an AWS call raised `CredentialError`. This is returned from a retry attempt's
  re-read as well as the first attempt, so a mid-retry credential expiry surfaces as the structured
  response rather than as `internal_error`.
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
  failure-log append. A rejected write touches neither store nor the log — with one carve-out: on
  a compare-and-swap retry whose predecessor attempt's `put_object` has already landed, the
  content is durable before the re-merged budget is measured, so a breach there is a durable
  partial write rather than a clean rejection. See the retry-budget-breach invariant below.
- On **any** overwriting write — a tier-3 living-document update and an explicit tier-2
  replacement alike — `commit_refs` is read forward from the object's annotations, its sole source
  of truth, and merged, then the budget check is **re-run** against the enlarged metadata before
  any write. The read-forward is keyed on `overwrite` against an existing key, never on tier.
  `references` is not read forward; see the replace-semantics invariant below.
- **A budget breach on the re-run is a clean rejection only while nothing is durable.** That
  holds on the first attempt, and on a retry a `put_object` conflict caused, since no content
  landed in either case: the write returns `validation_error` and appends nothing. Once an
  attempt's `put_object` has landed, however, that attempt has already replaced the content and
  cleared the object's annotations, so a breach on the next attempt's re-run leaves the same
  repairable state as any other post-write failure — the failure-log entry is appended and
  `partial_write` is returned. **That entry's `failure_step` names the budget re-check, not the
  annotation write.** Whether an entry is recorded at all is keyed on durability; what it is
  stamped with is keyed on cause, and this is the failure where the two most need to stay
  distinguishable — a recorded breach replays deterministically, so an entry naming
  the annotation store points whoever eventually reads the log at IAM drift instead of at the
  oversize value that is the actual reason the artifact never clears. Nothing branches on the
  value; see `arkeology.tools.reconcile` for the field's rule.
- **That recorded breach replays deterministically, and the artifact accumulates attempts until
  it is reported as stuck.** `reconcile_index` restores the entry's `commit_refs` by union, which
  puts the same oversize value back, so the re-index breaches the same budget again, and again on
  every subsequent run. This is the deliberate trade: the alternative is to record nothing, which
  leaves S3 holding the new content, the annotations cleared, and the vectors on the previous
  version — a state `reconcile_index` cannot even detect, because the artifact still has vectors
  and so the orphan scan skips it. Silent corruption is the worse outcome, but the accepted one
  re-enters exactly the replay loop the pre-write budget validation exists to prevent, so it is
  stated here rather than left to a code comment.
- A failed annotation write is **never reported as a success**. The S3 object is already durable at
  that point, so it returns `partial_write` — or `credential_error` / `annotation_unavailable` on
  the two branches whose cause is diagnosable — and appends the failure-log entry carrying the
  values it was applying, which is what lets `reconcile_index` restore them. Which of the three
  codes comes back never changes the durability facts; it names the cause where one is known, and
  falls back to naming the state where none is. An annotation-unavailable failure is handled
  identically in every respect but its code: startup check 8 proves availability before the server
  accepts a request, so at runtime it means post-setup IAM drift, not a deployment to degrade
  around.
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

- On success, returns `{"artifact_id": str, "sections_indexed": int, "last_edited_ulid": str}` and
  nothing else. There is no success-with-a-warning shape.
- On success all three stores agree: object content present, annotations reflecting the final link
  fields, and one vector per indexed section.
- A failed annotation write returns an error code, never success. Annotations are the sole durable
  store for both link fields, so telling the caller the write succeeded while that data was not
  persisted is what this forbids. Absence of an `"error"` key is therefore a sufficient check that
  the link fields are durable.
- On `partial_write` — and equally on an `annotation_unavailable` or `credential_error` returned
  after the object write had landed — the S3 object is durable and a failure-log entry exists; the
  artifact is content-complete but unsearchable until reconciled. Neither `credential_error` nor
  `annotation_unavailable` says on its own which of its two cases occurred — one raised before the
  object write, one after — so a caller needing to know re-reads the artifact rather than
  inferring durability from the code.
- A failure-log entry written **once the object write has landed**, whichever step then failed, also
  records the `commit_refs` and `references` that write was applying, as two **optional** entry
  fields. The preceding `put_object` has already cleared the object's annotations, so the entry is
  the only remaining source `reconcile_index` can restore them from — `references` is never in
  vector metadata and the vector `commit_refs` copy is capped. Both are recorded in full and
  uncapped, and are omitted when empty; an absent field means "nothing to restore", never "clear the
  field". The entry also records the `last_edited_ulid` this write generated, which
  `reconcile_index` compares against the artifact's current one to decide whether the entry's
  `references` has since been superseded by a later write; see `arkeology.tools.reconcile`.
- On any `validation_error` nothing was written anywhere and no failure-log entry was created.
  This stays unconditional because the durable-content case takes `partial_write` instead — the
  code is chosen on durability, so `validation_error` never names a state the caller must repair.
