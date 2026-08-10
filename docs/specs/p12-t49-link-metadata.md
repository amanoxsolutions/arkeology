---
type: spec
title: T49 — link_metadata Tool (generalizes and supersedes link_commit)
description: A link_metadata MCP tool that backfills commit_refs and/or references on existing own-scope artifacts via fetch → merge+dedup → dual-write (durable annotations first, vectors second) with the same embeddings — no Bedrock call, no content mutation, no last_edited_ulid change. Idempotent; foreign-scope IDs skipped and counted. Supersedes link_commit; keeps propose_commit_links.
tags: []
timestamp: 2026-07-03T00:00:00Z
okf_version: "0.1"
feature: p12-t49-link-metadata
status: ready
phase: 12
task: 49
references:
  - docs/architecture-decisions/adr-2026-07-03-annotation-backed-link-storage.md
  - docs/specs/p10-t38-link-commit.md
  - docs/specs/p12-t45-s3-annotation-client.md
  - docs/specs/p12-t47-annotation-dual-write.md
  - docs/planning-artifacts/prd.md
authored:
  by: "architect"
  date: "2026-07-03"
revised:
  by: "tech-writer"
  date: "2026-07-04"
---

# T49 — `link_metadata` Tool (generalizes and supersedes `link_commit`)

<!-- SCOPE BLOCK — frozen after approval -->

## TL;DR

Add a `link_metadata` MCP tool that backfills the structured link fields (`commit_refs` and/or
`references`) onto existing own-scope artifacts without re-embedding: fetch current vectors +
embeddings → read the existing state as the **union of both durable stores** → merge and deduplicate
the supplied values into that union → **dual-write** (durable S3 annotations first, vector metadata
second) with the same embeddings. No Bedrock call, no content mutation, no change to
`last_edited_ulid`. Idempotent on re-run; foreign-scope identifiers are skipped and counted. This
**supersedes `link_commit`** (p10-t38); `propose_commit_links` is retained unchanged.
(FR-53, AC-59; supersedes FR-32.)

> **Revised 2026-07-04 (tech-writer).** The original scope below read the
> "existing" value from vector metadata alone and rewrote both annotation fields unconditionally
> from the merge result. The shipped implementation reads existing state as the union of both stores
> (`annotations.read_current_link_fields`) and merges the supplied values into that union per field
> — so a field the caller did **not** supply in this call is re-written with its existing (unioned)
> value, unchanged, rather than being wiped to `[]` because the read missed a value that lived only
> in the annotation. See the corrected Requirements/Boundaries below.
>
> **Note (2026-07-06, shipped in `7a697dd`).** The write path's ordinary overwriting write now
> treats `references` differently from `commit_refs` — replacing `references` outright instead of
> merging it (full semantics: `docs/specs/p12-t46-references-field.md`'s forward-pointer note).
> **This tool's own merge mechanic below is unaffected and unchanged**: `link_metadata` remains the
> post-hoc, accretive backfill primitive for *both* `commit_refs` and `references`. One real
> interaction worth flagging: because an ordinary overwriting write now replaces `references` from
> the frontmatter, a `references` value backfilled here can later be superseded by a subsequent
> overwriting write whose supplied `references` does not also carry it — this is expected, not a
> defect in either tool. Also, this task's fetch-merge-reput cycle is now guarded by an
> optimistic-concurrency compare-and-swap (ETag `IfMatch` on the object, `ObjectIfMatch` on the
> annotation writes; ~3 bounded retry attempts → structured `conflict` error on exhaustion), each
> `artifact_id` in the loop retrying independently — see `docs/specs/p2-t7-write-artifact.md`'s
> equivalent forward-pointer note for the same mechanism; rationale: ADR-011 decision 6.

## Problem Statement

`link_commit` (p10-t38) backfilled `commit_refs` into vector metadata **only**, so a
`reconcile_index` run silently dropped them (the documented V1 limitation). Phase 12 needs a single
primitive that (a) also backfills the new `references` field, and (b) writes a durable copy so
reconcile is lossless (ADR-011). `link_metadata` generalizes `link_commit`'s exact mechanism into
that primitive: same fetch-merge-reput shape, now dual-writing to annotations first and vectors
second so a failed vector write self-heals on the next reconcile.

## User Stories

### Story 1 — Backfill either field to both stores (P1)

**Acceptance criteria:**
- Given an own-scope artifact, when `link_metadata(artifact_ids=[id], commit_refs=["abc1234"])` is
  called then the `commit_refs` annotation on its S3 object AND its vector metadata both become
  `["abc1234"]`, and `linked=1`. (AC-59)
- Given the same, when `link_metadata(artifact_ids=[id], references=["a-1"])` is called then the
  `references` annotation and vector metadata both carry `["a-1"]`.
- Given both `commit_refs` and `references` supplied in one call, then both fields are backfilled to
  both stores.

### Story 2 — No re-embed, no timestamp shift (P1)

**Acceptance criteria:**
- Given a successful `link_metadata` call, then Bedrock `embed` is never called (verified by spy),
  the `put_vectors_batch` reuses the float32 vectors from `get_vectors` unchanged, and the
  artifact's `last_edited_ulid` in vector metadata is unchanged. (AC-59)

### Story 3 — Idempotent merge + dedup (P1)

**Acceptance criteria:**
- Given an artifact already linked to `["abc1234"]`, when `link_metadata(commit_refs=["def5678"])`
  is called then `commit_refs` becomes `["abc1234","def5678"]` (append, dedup, order-preserving).
- Given `link_metadata` called twice with the same value, then the value is not appended twice. (AC-59)

### Story 4 — Durable-first ordering + scope gate (P1)

**Acceptance criteria:**
- Given the dual-write, then the S3 annotation is written **before** `put_vectors_batch`.
- Given a mixed `artifact_ids` list (one own-scope, one foreign-scope), when `link_metadata` returns
  then `linked=1`, `skipped=1`, and the foreign-scope artifact is untouched.
- Given an `artifact_id` with no vectors in the index, then it is skipped and counted — no error.

### Story 5 — Response shape + cursor + errors (P1)

**Acceptance criteria:**
- Given a successful call, the response is `{"linked": int, "skipped": int, "next_since_ulid": str}`.
- Given neither `commit_refs` nor `references` supplied (or both empty), then a `validation_error`
  is returned.
- Given a `CredentialError` during any AWS call, then a structured error is returned — not a raw
  exception.

## Requirements

- WHEN `link_metadata` is called THE SYSTEM SHALL accept `artifact_ids: list[str]`, optional
  `commit_refs: list[str] | None`, and optional `references: list[str] | None`; at least one of the
  two lists SHALL be non-empty or a `validation_error` is returned.
- WHEN an `artifact_id` does not start with `settings.write_prefix + "/"` THE SYSTEM SHALL skip it
  and increment `skipped` — foreign-scope artifacts cannot be linked.
- WHEN processing an own-scope `artifact_id` THE SYSTEM SHALL call
  `list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}})`; when no keys are found it SHALL
  skip and count, not error.
- WHEN keys are found THE SYSTEM SHALL call `get_vectors(keys)`, read the existing `commit_refs` /
  `references` as the union of both durable stores (`annotations.read_current_link_fields(s3,
  vectors, artifact_id)` — never vector metadata alone), merge the supplied
  values into that union per field (`list(dict.fromkeys(existing + supplied))`), and dual-write:
  first `apply_link_annotations(s3, artifact_id, ...)` with the merged values for BOTH fields (a
  field with no supplied values re-writes its existing unioned value unchanged, never `[]`), then
  `put_vectors_batch` reusing each vector's `data["float32"]` with updated metadata.
- WHEN writing THE SYSTEM SHALL make no Bedrock call and SHALL NOT alter `last_edited_ulid`.
- WHEN all artifacts are processed THE SYSTEM SHALL generate `next_since_ulid` once and return
  `{"linked", "skipped", "next_since_ulid"}`.
- WHEN a `CredentialError` occurs THE SYSTEM SHALL return `{"error": "credential_error", "message"}`.
- WHEN an annotation-unavailable / access-denied error occurs THE SYSTEM SHALL surface a structured
  error per T52 (durable side failed → do not treat as linked).
- WHEN the tool is registered THE SYSTEM SHALL replace the `link_commit` registration with
  `link_metadata` in `server.py`; `propose_commit_links` is unchanged.

## Boundaries

**Always:**
- Public function delegates to `_link_metadata_inner` wrapped in `try/except Exception`
  (AGENTS.md non-negotiable).
- Scope gate uses `startswith(settings.write_prefix + "/")` — never bare `startswith`.
- Dual-write ordering: annotations first (durable), vectors second (recoverable-state, ADR-011).
- Reuse the shared `annotations.py` helpers (T47) — `read_current_link_fields` for the existing-state
  read (union of both stores) and `apply_link_annotations` for the write; do not re-implement
  either.
- `next_since_ulid` generated once after the loop (as `link_commit` did).

**Ask First:**
- Nothing — mechanics fixed by ADR-011.

**Never:**
- Do not call Bedrock `embed`.
- Do not mutate content or `last_edited_ulid`.
- Do not include foreign-scope artifacts in `linked`.
- Do not abort the whole batch when one artifact has no vectors — skip and continue.
- Do not read the existing `commit_refs` / `references` state from vector metadata alone —
  always via `read_current_link_fields`, or a field the caller did not supply in this
  call can be wiped instead of preserved.

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_link_metadata.py` | Create | Dual-write, no-re-embed (Bedrock spy), merge/dedup, scope-gate, cursor, error tests — Red first |
| `src/cairn_mcp/tools/link_metadata.py` | Create | Tool implementation — Green |
| `src/cairn_mcp/server.py` | Modify | Register `link_metadata`; remove the `link_commit` registration (import + `@_app.tool()` wrapper) |
| `src/cairn_mcp/tools/link_commit.py` | Delete | Retired — superseded by `link_metadata` |
| `tests/unit/test_tools_link_commit.py` | Delete | Retired with the tool |
| `src/cairn_mcp/resources.py` | Modify | Update the tool/query-strategy resource text referencing `link_commit` → `link_metadata` |
| `tests/integration/test_tools_link_metadata.py` | Create | Real-AWS dual-write + reconcile-survival round-trip — Red for integration |

## Testing Approach

**TDD cycle (unit):** write `test_tools_link_metadata.py` → fail → implement `link_metadata.py` →
pass → swap registration in `server.py` and delete `link_commit`.

Use `aws_mock`, `s3_client`, `vectors_client_*` fixtures; pre-seed vectors via `put_vectors_batch`
with `FakeBedrockClient` (or deterministic) embeddings. The T45 moto annotation self-mock is
required for the annotation assertions.

Seed data mirrors p10-t38: `artifact-own-A` (own, two section vectors, no link fields),
`artifact-own-B` (own, `commit_refs=["prev123"]`), `artifact-foreign` (foreign scope).

Cases:
- `commit_refs` backfill → annotation + vector metadata both `["abc1234"]`; `linked=1`.
- `references` backfill → both stores carry `["a-1"]`.
- Both fields in one call → both backfilled.
- Append + dedup on `artifact-own-B`; duplicate value not appended twice (idempotent).
- Bedrock `embed` call_count == 0 (`mocker.spy(bedrock, "embed")`).
- Float32 vectors unchanged before/after.
- Annotation written before `put_vectors_batch` (recorded call-order assertion).
- Scope gate: foreign-scope skipped+counted; mixed list `linked=1, skipped=1`; missing artifact skipped.
- Validation: neither field supplied → `validation_error`.
- `CredentialError` from `list_vectors_by_metadata` / `get_vectors` / `put_object_annotation` /
  `put_vectors_batch` → structured error.
- `next_since_ulid` present; two successive calls → monotonically non-decreasing.

**Integration:** backfill `commit_refs` + `references` via `link_metadata`; run `reconcile_index`
that re-indexes the artifact; assert both fields survive (validates the T48 reconcile-from-annotations
path end-to-end).

## Open Questions

*(none — the AGENTS.md post-commit protocol snippet update from `link_commit` → `link_metadata` is
owned by T52; the p10-t38 spec supersede-pointer is Architect B's edit, not this task's)*
