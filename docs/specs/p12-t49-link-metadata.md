---
type: Spec
id: p12-t49-link-metadata
title: T49 — link_metadata Tool (generalizes and supersedes link_commit)
description: A link_metadata MCP tool that backfills commit_refs and/or references on existing own-scope artifacts via fetch → merge+dedup → dual-write (durable annotations first, vectors second) with the same embeddings — no Bedrock call, no content mutation, no last_edited_ulid change. Idempotent; foreign-scope IDs skipped and counted. Supersedes link_commit; keeps propose_commit_links.
tags: []
status: stable
okf_version: "0.2"
sources:
  - resource: docs/architecture-decisions/adr-2026-07-03-annotation-backed-link-storage.md
    title: Annotation-Backed Durable Storage for Mutable Link Fields (commit_refs + references)
    last_modified: 2026-09-29T00:00:00Z
  - resource: docs/specs/p12-t45-s3-annotation-client.md
    title: T45 — S3 Object Annotation Client Support + moto Self-Mock Extension
    last_modified: 2026-07-03T00:00:00Z
  - resource: docs/specs/p12-t47-annotation-dual-write.md
    title: T47 — Annotation Dual-Write in the Write Path + Tier-3 Overwrite Preservation
    last_modified: 2026-09-06T00:00:00Z
  - resource: docs/planning-artifacts/requirements.md
    title: Arkeology — Requirements
    last_modified: 2026-09-24T00:00:00Z
  - resource: docs/contracts/modules/arkeology.tools.link_metadata.md
    title: arkeology.tools.link_metadata
  - resource: docs/contracts/data/s3-annotations.artifact.md
    title: s3-annotations.artifact
  - resource: .docs/reviews/architecture-review-2026-11-15-arkeology-phases-9-10-12.md
    title: "Architecture review — Arkeology, plan phases 9, 10 and 12"
  - resource: docs/specs/p12-t57-guard-coverage.md
    title: T57 — Guard Coverage in link_metadata.py and reconcile.py + Control-Character Validation Fix
  - resource: docs/contracts/data/s3vectors.artifact.md
    title: s3vectors.artifact
  - resource: docs/contracts/data/s3.artifact.md
    title: s3.artifact
relationships:
  - to: p10-t38-link-commit
    type: supersedes
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

# T49 — `link_metadata` Tool (generalizes and supersedes `link_commit`)

## TL;DR

Add a `link_metadata` MCP tool that backfills the structured link fields (`commit_refs` and/or
`references`) onto existing own-scope artifacts without re-embedding: fetch current vectors +
embeddings → read the existing state from the S3 object annotation alone → merge and deduplicate
the supplied values into it → **dual-write** (durable S3 annotations first, vector metadata
second) with the same embeddings. No Bedrock call, no content mutation, no change to
`last_edited_ulid`. Idempotent on re-run; foreign-scope identifiers are skipped and counted. This
**supersedes `link_commit`** (p10-t38); `propose_commit_links` is retained unchanged.
(FR-53, AC-59; supersedes FR-32.)

## 1. Problem Statement

`link_commit` (p10-t38) backfilled `commit_refs` into vector metadata **only**, so a
`reconcile_index` run silently dropped them (the documented V1 limitation). Phase 12 needs a single
primitive that (a) also backfills the new `references` field, and (b) writes a durable copy so
reconcile is lossless (ADR-011). `link_metadata` generalizes `link_commit`'s exact mechanism into
that primitive: same fetch-merge-reput shape, now dual-writing to annotations first and vectors
second so a failed vector write self-heals on the next reconcile.

All five stories this spec states are P1: backfill either field to both stores; no re-embed, no
timestamp shift; idempotent merge + dedup; durable-first ordering + scope gate; response shape +
cursor + errors.

## 2. Rules — Inputs and scope

### R1 — Accepted parameters; at least one non-empty link list

When `link_metadata` is called, it accepts `artifact_ids: list[str]`, optional
`commit_refs: list[str] | None`, and optional `references: list[str] | None`; at least one of the
two lists must be non-empty or a `validation_error` is returned. Each supplied element is validated
as `p12-t57-guard-coverage` R7 states, so a `references` element must be a full key, scope
included.

**Example**

- Given neither `commit_refs` nor `references` supplied (or both empty), then a `validation_error`
  is returned.
- Given `references=["adr-use-postgres-abc12345"]`, which has no scope, then a `validation_error`
  is returned and nothing is written.

### R2 — Foreign-scope artifacts are skipped and counted

When an `artifact_id` does not start with `settings.write_prefix + "/"`, the tool skips it and
increments `skipped` — foreign-scope artifacts cannot be linked. The scope gate uses
`startswith(settings.write_prefix + "/")` — never bare `startswith`.

**Example**

- Given a mixed `artifact_ids` list (one own-scope, one foreign-scope), when `link_metadata`
  returns, then `linked=1`, `skipped=1`, and the foreign-scope artifact is untouched.

### R3 — An artifact with no vectors is skipped and counted

When processing an own-scope `artifact_id`, the tool calls
`list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}})`; when no keys are found it skips
and counts, not error.

**Example**

- Given an `artifact_id` with no vectors in the index, then it is skipped and counted — no error.

## 3. Rules — Fetch, merge and dual-write

### R4 — Fetch, read existing state, merge, dual-write

When keys are found, the tool calls `get_vectors(keys)`, reads the existing `commit_refs` /
`references` from the object's annotation (R8), merges the supplied values into it per field
(`list(dict.fromkeys(existing + supplied))`), and dual-writes: first
`apply_link_annotations(s3, artifact_id, ...)` with the merged values for BOTH fields (a field with
no supplied values re-writes its existing value unchanged, never `[]`), then `put_vectors_batch`
reusing each vector's `data["float32"]` with updated metadata.

### R5 — Metadata budget guard before either store is written

Before the `apply_link_annotations` call, the tool calls `check_metadata_budgets` on the merged
values and, on failure, rejects with `validation_error` before writing either store. The call sits
inside this tool's per-`artifact_id` CAS retry loop, before the annotation write — so an oversize
merge is rejected before either store is touched, not just before `put_vectors_batch`.

Source: adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal.md D1/D2; p12-t57-guard-coverage

### R6 — What each store carries after the dual-write

The metadata passed to `put_vectors_batch` does not include a `references` key and caps
`commit_refs` to its most-recently-appended 20 entries via `cap_commit_refs_for_vectors`; the
metadata passed to `apply_link_annotations` is the full, uncapped merged list regardless of length.
Only the annotation carries `references` after this tool runs; the vector metadata this tool writes
for a `references`-only call carries no `references` key at all.

**Example**

- Given an own-scope artifact, when `link_metadata(artifact_ids=[id], commit_refs=["abc1234"])` is
  called, then the `commit_refs` annotation on its S3 object AND its vector metadata both become
  `["abc1234"]`, and `linked=1` (this holds for lists at or below 20 entries).
- Given the same, when
  `link_metadata(artifact_ids=[id], references=["team-a/payments/adr-use-postgres-abc12345.md"])` is
  called, then only the `references` annotation carries that full key; vector metadata carries no
  `references`.
- Given both `commit_refs` and `references` supplied in one call, then both fields are backfilled:
  the annotation carries both fields (uncapped); vector metadata carries only `commit_refs` (capped
  at 20 entries), never `references`.

Source: AC-59, adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal.md D1/D2; p12-t58-commit-refs-cap-references-removal R1, R4

### R7 — Accretive, idempotent merge for both fields

The merge appends, deduplicates and preserves order: `merge_link_field` combines the existing value
with the values supplied to this call, deduplicating and preserving order. `link_metadata` is the
post-hoc, accretive backfill primitive for *both* `commit_refs` and `references`, while an ordinary
overwriting write replaces `references` outright (`p12-t46-references-field` R9). A `references`
value backfilled here can therefore later be superseded by a subsequent overwriting write whose
supplied `references` does not also carry it — this is expected, not a defect in either tool.

**Example**

- Given an artifact already linked to `["abc1234"]`, when `link_metadata(commit_refs=["def5678"])`
  is called, then `commit_refs` becomes `["abc1234","def5678"]` (append, dedup, order-preserving).
- Given `link_metadata` called twice with the same value, then the value is not appended twice.

Source: AC-59

### R8 — The existing-state read goes to the annotation alone

The existing state read before the merge comes from the S3 object annotation alone — the
annotation is the **sole** source of truth, and the vector-metadata copy is never read back. The
read goes through `annotations.read_link_annotations`, which consults the annotation and nothing
else. That read **raises** on failure rather than returning empty. Absence of an annotation returns
a true empty; a failed read never masquerades as one, because an empty value on a read-modify-write
path would be written straight back over good link data.

Source: adr-2026-07-03-annotation-backed-link-storage "Revision — 2026-09-05"

### R9 — Compare-and-swap guard, per `artifact_id`

This tool's fetch-merge-reput cycle is guarded by an optimistic-concurrency compare-and-swap (the
object's ETag, sent as `ObjectIfMatch` on the annotation writes), retried up to `CAS_MAX_ATTEMPTS`
(3) and returning `conflict` on exhaustion (R13); each `artifact_id` in the loop retries
independently. What the guard does not serialise — two
annotation-only writers to the same field — is stated in `arkeology.tools.link_metadata` §
link_metadata.

Source: ADR-011 decision 6

### R10 — Durable-first ordering

The dual-write orders annotations first (durable), vectors second (recoverable-state).

**Example**

- Given the dual-write, then the S3 annotation is written **before** `put_vectors_batch`.

Source: ADR-011

### R11 — A failed vector write after a successful annotation write is reported and logged for replay

When the vector write fails after the annotation write has succeeded, the tool appends a
failure-log entry recording the `commit_refs` and `references` it applied and the artifact's
unchanged `last_edited_ulid`, and reports the artifact in a `vector_write_failed` list of ids,
counted in neither `linked` (its vector copy is stale) nor `skipped` (its annotation was written).
Whenever the response carries `vector_write_failed` it also carries `failure_logged`: `true` when
every listed id's entry was appended, `false` when any append failed. One such failure never
discards what the rest of the batch achieved. The entry is what makes the artifact a
`reconcile_index` replay candidate; annotation-first ordering alone does not, because an artifact
that still has vectors is invisible to the orphan scan.

**Example**

- Given twelve own-scope artifacts where the vector write of one fails, when `link_metadata` runs,
  then the response reports `linked: 11` and `vector_write_failed: [<that id>]` with
  `failure_logged: true`, and that artifact's annotation already carries the new values.

Source: arkeology.tools.link_metadata

### R12 — No re-embed, no timestamp shift

When writing, the tool makes no Bedrock call and does not alter `last_edited_ulid`.

**Example**

- Given a successful `link_metadata` call, then Bedrock `embed` is never called (verified by spy),
  the `put_vectors_batch` reuses the float32 vectors from `get_vectors` unchanged, and the
  artifact's `last_edited_ulid` in vector metadata is unchanged.

Source: AC-59

## 4. Rules — Response and errors

### R13 — Response shape and cursor, and the call stopped by one artifact's failure

When all artifacts are processed, the tool generates `next_since_ulid` once, after the loop (as
`link_commit` did), and returns `{"linked", "skipped", "next_since_ulid"}`, plus R11's
`vector_write_failed` and `failure_logged` when a vector write failed.

One artifact's failure that is not a skip — R5's budget `validation_error`, R9's `conflict` or
R15's `annotation_unavailable` — stops the call with that error. The error response names the
failing artifact and lists every artifact the call did link, so the caller knows which identifiers
to send again; its shape is `arkeology.tools.link_metadata` § link_metadata's.

**Example**

- Given a successful call, the response is `{"linked": int, "skipped": int, "next_since_ulid": str}`.
- Given twelve own-scope artifacts where the fifth's merge breaches a metadata budget, when
  `link_metadata` runs, then it returns `validation_error` naming the fifth artifact's identifier
  and listing the identifiers it linked, the first four among them.

Source: arkeology.tools.link_metadata

### R14 — Credential errors are structured

When a `CredentialError` occurs during any AWS call, the tool returns
`{"error": "credential_error", "message"}` — a structured error, not a raw exception.

### R15 — Annotation-unavailable and access-denied errors return `annotation_unavailable`

When the annotation read or write raises `AnnotationUnavailableError` (annotations unavailable, or
access denied), the tool returns `annotation_unavailable` — the one code every tool returns for that
condition (`s3-annotations.artifact` § Compatibility Guarantees) — and never counts that artifact as
linked: the durable write is this tool's contract.

Source: FR-57; arkeology.tools.link_metadata

## 5. Rules — Registration

### R16 — `link_metadata` replaces `link_commit`

When the tool is registered, the `link_commit` registration is replaced with `link_metadata` in
`server.py`; `propose_commit_links` is unchanged.

## 6. Boundaries

**Always:**
- Public function delegates to `_link_metadata_inner` wrapped in `try/except Exception`
  (AGENTS.md non-negotiable).
- Scope gate uses `startswith(settings.write_prefix + "/")` — never bare `startswith`.
- Dual-write ordering: annotations first (durable), vectors second (recoverable-state, ADR-011).
- Reuse the shared `annotations.py` helpers (T47) — `read_link_annotations` for the existing-state
  read (annotation only) and `apply_link_annotations` for the write; do not re-implement either.
- `next_since_ulid` generated once after the loop (as `link_commit` did).

**Ask First:**
- Nothing — mechanics fixed by ADR-011.

**Never:**
- Do not call Bedrock `embed`.
- Do not mutate content or `last_edited_ulid`.
- Do not include foreign-scope artifacts in `linked`.
- Do not abort the whole batch when one artifact has no vectors — skip and continue.
- Do not read the existing `commit_refs` / `references` state from vector metadata, and do not
  degrade a failed annotation read to `[]` — either would let a field the caller did not supply in
  this call be wiped instead of preserved.

## 7. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_link_metadata.py` | Create | Dual-write, no-re-embed (Bedrock spy), merge/dedup, scope-gate, cursor, error tests — Red first |
| `src/arkeology/tools/link_metadata.py` | Create | Tool implementation — Green |
| `src/arkeology/server.py` | Modify | Register `link_metadata`; remove the `link_commit` registration (import + `@_app.tool()` wrapper) |
| `src/arkeology/tools/link_commit.py` | Delete | Retired — superseded by `link_metadata` |
| `tests/unit/test_tools_link_commit.py` | Delete | Retired with the tool |
| `src/arkeology/resources.py` | Modify | Update the tool/query-strategy resource text referencing `link_commit` → `link_metadata` |
| `tests/integration/test_tools_link_metadata.py` | Create | Real-AWS dual-write + reconcile-survival round-trip — Red for integration |

### Contracts

- `docs/contracts/modules/arkeology.tools.link_metadata.md` § link_metadata — the parameters and element validation, the read-merge-dual-write cycle and its compare-and-swap residual, the response, `vector_write_failed` and `failure_logged`, and the error that stops the call (R1–R15).
- `docs/contracts/data/s3-annotations.artifact.md` § read_link_annotations, § apply_link_annotations and § Storage Shape — the raise-never-degrade existing-state read, the `if_match` guard, the full uncapped annotation write, and the full-key form of a `references` element (R1, R4, R8, R9).
- `docs/contracts/data/s3vectors.artifact.md` § cap_commit_refs_for_vectors and § Storage Shape — the capped `commit_refs` copy, no `references`, and the numbered keys an artifact's vectors are read by (R3, R6).
- `docs/contracts/data/s3.artifact.md` § check_metadata_budgets — the budget guard run before either store is written (R5).

### Testing Approach

**TDD cycle (unit):** write `test_tools_link_metadata.py` → fail → implement `link_metadata.py` →
pass → swap registration in `server.py` and delete `link_commit`.

Use `aws_mock`, `s3_client`, `vectors_client_*` fixtures; pre-seed vectors via `put_vectors_batch`
with `FakeBedrockClient` (or deterministic) embeddings. The T45 moto annotation self-mock is
required for the annotation assertions.

Seed data mirrors p10-t38: `artifact-own-A` (own, two section vectors, no link fields),
`artifact-own-B` (own, `commit_refs=["prev123"]`), `artifact-foreign` (foreign scope).

Cases:
- `commit_refs` backfill → annotation + vector metadata both `["abc1234"]`; `linked=1`.
- `references` backfill with a full key (`team-a/payments/adr-use-postgres-abc12345.md`) →
  annotation only carries it; vector metadata never carries `references` (T58).
- Both fields in one call → both backfilled (annotation carries both, uncapped; vector metadata
  carries only the capped `commit_refs`, per T58).
- Append + dedup on `artifact-own-B`; duplicate value not appended twice (idempotent).
- Bedrock `embed` call_count == 0 (`mocker.spy(bedrock, "embed")`).
- Float32 vectors unchanged before/after.
- Annotation written before `put_vectors_batch` (recorded call-order assertion).
- Scope gate: foreign-scope skipped+counted; mixed list `linked=1, skipped=1`; missing artifact skipped.
- Validation: neither field supplied → `validation_error`.
- `CredentialError` from `list_vectors_by_metadata` / `get_vectors` / `put_object_annotation` /
  `put_vectors_batch` → structured error.
- `AnnotationUnavailableError` from the annotation read or write → `annotation_unavailable`; that
  artifact is not counted in `linked` (R15).
- A per-artifact failure after other artifacts were linked (an injected `ArtifactConflictError` on
  every attempt for the second of three ids) → `conflict` with `artifact_id` naming that id and
  `linked_ids` holding every id the call linked (R13).
- Annotation read fails with a transient error → no annotation write for that artifact; its
  existing values are never merged into `[]` and written back (R8).
- `put_vectors_batch` fails for one of several artifacts → that id in `vector_write_failed`, counted
  in neither `linked` nor `skipped`, `failure_logged: true`, failure-log entry carrying the applied
  values and `last_edited_ulid`; the other artifacts linked (R11).
- `next_since_ulid` present; two successive calls → monotonically non-decreasing.

**Integration:** backfill `commit_refs` + `references` via `link_metadata`; run `reconcile_index`
that re-indexes the artifact; assert both fields survive (validates the T48 reconcile-from-annotations
path end-to-end).

### Hand-offs

- The AGENTS.md snippet's post-commit protocol, which calls `link_metadata`, is owned by
  `p9-t31a-setting-up-arkeology-skill` R35.
