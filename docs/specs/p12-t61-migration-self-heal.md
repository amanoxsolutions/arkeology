---
type: Spec
id: p12-t61-migration-self-heal
title: T61 — Migration Self-Heal — skipped_unindexed Classification
description: migrate_artifacts' Step 5 skip-existing filter checks S3 existence only, never live vector-index state, making a partial write (S3 object durably written, vector never indexed) permanently un-retryable through the normal migration path. Add one bounded, per-candidate vectors.list_vectors_by_metadata existence check so an S3-exists-but-not-indexed candidate is classified distinctly as skipped_unindexed and pointed at reconcile_index instead of silently folded into skipped_existing forever.
tags: []
status: stable
okf_version: "0.2"
sources:
  - resource: docs/architecture-decisions/adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal.md
    title: Vector Metadata Budget Hardening, Guard Coverage, and Migration Self-Heal
    last_modified: 2026-09-25T00:00:00Z
  - resource: docs/specs/p12-t57-guard-coverage.md
    title: T57 — Guard Coverage in link_metadata.py and reconcile.py + Control-Character Validation Fix
    last_modified: 2026-08-17T00:00:00Z
  - resource: docs/specs/p12-t56-deterministic-content-reference-rewrite.md
    title: T56 — Deterministic Server-Side Content Reference Rewrite (Frontmatter + Body)
    last_modified: 2026-07-06T00:00:00Z
  - resource: docs/specs/p9-t30-write-artifacts.md
    title: Write Performance Z1 — write_artifacts + migrate_artifacts + P4 Section Truncation
    last_modified: 2026-07-05T00:00:00Z
generated:
  by: "axians-architect/claude-sonnet-5"
  at: 2026-08-17T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-09T20:05:33Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
---

# T61 — Migration Self-Heal — `skipped_unindexed` Classification

## TL;DR

`migrate_artifacts`' Step 5 skip-existing filter decides "already migrated" solely from `s3.head_object(candidate_key)` — it never checks whether the artifact is actually indexed. A candidate whose S3 object exists but whose vectors were never successfully written (the incident's exact permanent-partial-write shape) is silently folded into the same `skipped_existing` bucket as a genuinely fully-migrated artifact, making it un-retryable through the normal migration path forever. This spec adds one bounded, per-candidate vector-existence check to Step 5: when the S3 object exists but no vectors are indexed for it, the candidate is reported under a new, distinct `skipped_unindexed` classification that points the caller at `reconcile_index` — which, once T57's guard is in place, either self-heals it or reports a clear, structured failure instead of silently doing nothing. (ADR D3.)

## 1. Problem Statement

Bulk migration is commonly re-run over the same corpus (resuming an interrupted import, or re-importing an updated corpus), and must never overwrite an already-migrated artifact — this is why Step 5 exists. But "the S3 object exists" and "the artifact is fully migrated" are not the same fact: a prior migration attempt can have written the S3 object successfully and then failed on the vector write (exactly the incident's mechanism, closed going forward by T57/T58, but not retroactively for anything already stuck). Today, re-running migration over such a corpus reports that candidate as `skipped_existing` — identical wording to a genuinely complete artifact — giving the operator no signal that anything needs attention, and no path back to a healthy state through `migrate_artifacts` itself.

This spec deliberately does **not** re-implement re-indexing logic inside `migrate_artifacts` — `reconcile_index` already owns that (`_reindex_artifact`, shared by both its failure-log-replay and orphan-scan phases). `migrate_artifacts`' job is only to *detect* the distinction and report it; remediation is `reconcile_index`'s job, reused rather than duplicated (ADR D3, "detect, don't reinvent").

This spec also resolves the T56 content-rewrite-parity concern the ADR documents: because Step 3.5 (T56's content rewrite) runs *before* Step 5 in both `dry_run` modes, any candidate whose S3 object already exists from a first migration attempt already carries the correct T56 `arkeology://` rewrite — self-healing via `reconcile_index` (which never touches content, only re-derives and re-embeds metadata already durably stored) cannot re-introduce a rewrite-parity gap. No extra code is needed for this; it falls out of the existing step ordering.

All three user stories are P1: a fully-migrated candidate is reported exactly as today (R3), a partially-migrated (S3 exists, vectors absent) candidate is reported distinctly (R4, R5, R6, R7), and detection is bounded and per-candidate (R1, R2, R8).

## 2. Rules — Step 5 vector-existence check

### R1 — One bounded vector-existence query per already-existing candidate

When Step 5 of `migrate_artifacts` finds that a candidate's `s3.head_object(candidate_key)` succeeds (the object exists), it additionally queries `vectors.list_vectors_by_metadata({"artifact_id": {"$eq": candidate_key}})` for that candidate, before deciding its classification — one bounded query per already-existing candidate, never a bulk pre-scan of the whole vector index.

Source: adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal D3, Open Questions resolution 3

### R2 — No vector-existence query for a genuinely-new candidate

When a candidate's S3 object does not exist (`head_object` raises `KeyError`), Step 5 follows the existing `to_write_indices` path unchanged — no vector-existence query is ever issued for a genuinely-new candidate.

Source: adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal D3

## 3. Rules — Classification

### R3 — An indexed candidate is reported under `skipped_existing` exactly as today

When the vector-existence query returns one or more vector keys — the candidate's S3 object exists AND its vectors are indexed — the candidate is classified as `skipped_existing`, exactly as today: identical shape and wording, no response-shape change for this case. This spec changes nothing about the fully-migrated case.

Source: None

### R4 — An unindexed candidate is classified `skipped_unindexed` and nothing is written for it

When the vector-existence query returns zero vector keys — the candidate's S3 object exists but has **no** indexed vectors — the candidate is classified as `skipped_unindexed` instead of `skipped_existing` (never folded into `skipped_existing`), and `migrate_artifacts` still performs **no write** for it: the skip-existing guard still applies and is never bypassed, even for an unindexed candidate — `overwrite=True` is never implicitly applied by this detection. This is a detection-and-reporting change, not a remediation-inline change: `migrate_artifacts` remains a strictly non-destructive, idempotent bulk-write tool, and remediation happens via a separate `reconcile_index` call, not inline.

Source: adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal D3, Open Questions resolution

### R5 — A mixed corpus is classified per candidate, independently

When `migrate_artifacts` runs over a corpus containing a mix of fully-migrated, unindexed, and genuinely-new candidates, each is classified correctly and independently — `skipped_existing`, `skipped_unindexed`, and normally-written results all coexist in the same response.

Source: None

## 4. Rules — Response shape

### R6 — A new top-level `skipped_unindexed` list, present only when non-empty

When the response is assembled, it carries a new top-level `skipped_unindexed` list, mirroring the existing `skipped_existing` list's shape: `index`, `artifact_id`, `title`, plus a `message` naming `reconcile_index` as the remediation path. The list is included only when non-empty, matching the existing convention for `skipped_existing`/`generation_failed`.

Source: adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal D3, Open Questions resolution

### R7 — An unindexed candidate's `combined_results` entry carries `"reason": "unindexed"`

When `combined_results[idx]` is set for an unindexed candidate, it includes a `"reason": "unindexed"` key, distinguishing it from the plain `skipped_existing` entry shape (which carries no `reason` key today) and from `"description_generation_failed"`.

Source: None

## 5. Rules — Errors

### R8 — A `CredentialError` from the vector-existence query returns the existing credential-error response

When the vector-existence query raises `CredentialError`, `migrate_artifacts` returns the same structured credential-error response Step 5 already returns for a `head_object` credential failure — no new error-handling shape is introduced.

Source: None

## 6. Boundaries

**Always:**
- The existence check is per-candidate, bounded, issued only for candidates whose S3 object already exists — never a bulk pre-scan (D3's chosen option; the bulk pre-scan alternative was considered and explicitly deferred to a future performance refinement only if measured necessary, per the ADR's Open Questions resolution).
- Remediation is `reconcile_index`, reused as-is — this task adds **no** re-indexing logic inside `migrate_artifacts` itself (ADR D3, "detect, don't reinvent" — the rejected alternative was teaching `migrate_artifacts` to re-index inline, which would duplicate `_reindex_artifact`).
- `migrate_artifacts` never writes to or overwrites an unindexed candidate itself — it only detects and reports; the operator (or an automated follow-up) calls `reconcile_index` separately.
- Step ordering (Step 3.5 content rewrite before Step 5 skip-existing) is unchanged — this is what makes the self-heal path safe for T56 rewrite parity; do not reorder these steps.

**Ask First:**
- Nothing — the per-candidate (not bulk) detection mechanism and the "detect, don't reinvent" remediation approach are both locked, operator-approved decisions (ADR D3, Open Questions resolution 3).

**Never:**
- Do not bypass the skip-existing guard for an unindexed candidate — even though its vectors are missing, `migrate_artifacts` must never implicitly overwrite it; that remains `reconcile_index`'s job.
- Do not add a bulk vector-listing pre-scan as part of this task — the per-candidate query was explicitly approved as-is; only revisit if a measured performance problem emerges at implementation/operation time (see ADR D3 Alternatives Considered).
- Do not fold `skipped_unindexed` candidates into the existing `skipped_existing` list — they must be reported distinctly so the operator has an actionable signal.

## 7. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_migrate_artifacts.py` | Modify | Add: S3-exists + vectors-indexed → `skipped_existing` unchanged; S3-exists + vectors-absent → `skipped_unindexed`, no write, `reconcile_index`-pointing message; S3-absent → unaffected `to_write_indices` path, no vector-existence query issued (`mocker.spy` asserting zero extra `list_vectors_by_metadata` calls for new candidates); `CredentialError` from the existence query → structured credential-error response; mixed corpus (all three cases in one call) — Red first |
| `src/arkeology/tools/migrate_artifacts.py` | Modify | In Step 5, after `s3.head_object(candidate_key)` succeeds, add the `vectors.list_vectors_by_metadata` existence check; branch into `skipped_existing` vs. new `skipped_unindexed` list + `combined_results[idx]["reason"] = "unindexed"`; assemble the new `skipped_unindexed` response field alongside the existing `skipped_existing`/`generation_failed` fields |
| `tests/integration/test_tools_migrate_artifacts.py` | Modify (flag) | Real-AWS: write an artifact, delete only its vectors (simulating the incident's partial-write state), re-run migration over the same descriptor, assert `skipped_unindexed` — Red for integration, if a suitable fixture pattern exists |

### Contracts

None.

### Testing Approach

**TDD cycle — test file before the implementation file it gates:**

1. **`test_tools_migrate_artifacts.py` → `migrate_artifacts.py`** — seed three candidates via moto: (a) S3 object + indexed vectors (expect `skipped_existing`), (b) S3 object only, no vectors (expect `skipped_unindexed`, zero writes, message references `reconcile_index`), (c) neither (expect normal write via `to_write_indices`). Run all three in one `migrate_artifacts` call and assert each response section is populated correctly and independently. Add a `mocker.spy` on `vectors.list_vectors_by_metadata` asserting it is called exactly once per already-existing candidate and never for case (c). Add a `CredentialError`-from-existence-query test asserting the existing structured credential-error response shape.

Use `aws_mock`, `s3_client`, `vectors_client_*` fixtures; `FakeBedrockClient` for embeddings.
