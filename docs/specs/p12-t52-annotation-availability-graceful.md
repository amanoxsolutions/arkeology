---
type: spec
title: T52 — Annotation Availability + IAM Probe, Runtime Graceful Handling, README + AGENTS.md
description: Add a one-time annotation availability + IAM-permission probe to the setting-up-arkeology skill (aws-cli ≥ 2.35.14 guard or boto3 uv run fallback); document the four required IAM actions and the unavailable regions/bucket types in the README; handle annotation-unavailable / AccessDenied gracefully at runtime in link_metadata and the write path; add arkeology:// referencing + reference-healing guidance to the AGENTS.md snippet. Not a hard startup gate.
tags: []
timestamp: 2026-07-03T00:00:00Z
okf_version: "0.1"
feature: p12-t52-annotation-availability-graceful
status: ready
phase: 12
task: 52
references:
  - docs/architecture-decisions/adr-2026-07-03-annotation-backed-link-storage.md
  - docs/architecture-decisions/adr-2026-07-03-artifact-cross-referencing.md
  - docs/specs/p12-t45-s3-annotation-client.md
  - docs/specs/p12-t47-annotation-dual-write.md
  - docs/specs/p12-t49-link-metadata.md
  - docs/planning-artifacts/prd.md
authored:
  by: "architect"
  date: "2026-07-03"
revised:
  by: ""
  date: ""
---

# T52 — Annotation Availability + IAM Probe, Runtime Graceful Handling, README + AGENTS.md

<!-- SCOPE BLOCK — frozen after approval -->

## TL;DR

Handle S3 object annotation availability and IAM as a **feature-level** concern, not a hard server
startup gate (ADR-011 decision 5). Add a one-time availability + IAM-permission probe to the
`setting-up-arkeology` skill; document the four required IAM actions and the unavailable regions /
bucket types in the README; handle annotation-unavailable / access-denied errors gracefully at
runtime in `link_metadata` and the write path (structured, actionable, never a raw exception — the
core content / vector / embedding store keeps working); and add the D9 `arkeology://` referencing and
reference-healing guidance to the AGENTS.md snippet. (FR-57, NFR-12, AC-62.)

## Problem Statement

Annotations are unavailable in some regions (UAE, Bahrain) and on some bucket types (directory
buckets, which is what the S3 Express One Zone storage class uses, and Outposts buckets) and need
IAM actions beyond core storage. Because annotations
back only the `commit_refs` / `references` feature — not the core store — refusing to boot over an
annotation problem would be disproportionate. Instead the deployment needs a friendly early check at
setup and graceful degradation at runtime to cover post-setup drift (an IAM edit, a bucket/region
change) a one-time check cannot catch.

## User Stories

### Story 1 — Runtime graceful handling (P1)

**Acceptance criteria:**
- Given annotations are unavailable or access is denied, when `link_metadata` runs then it returns a
  structured, actionable error (not a raw exception), and the core content / vector / embedding store
  still functions for other operations. (AC-62)
- Given the same condition, when `write_artifact` runs then the artifact's content + vectors are
  still persisted and the response carries a structured, actionable `warning` that durable link
  storage (annotations) is unavailable — never a raw exception. (AC-62)
- Given a normal (available) deployment, then no warning appears and both fields are durably stored.

### Story 2 — Server still boots without annotations (P1)

**Acceptance criteria:**
- Given a deployment where annotations are unavailable, when the server starts then startup
  validation still passes and the server serves content and search — annotation availability is NOT
  a startup check. (ADR-011 decision 5)

### Story 3 — Setup probe reports availability + IAM (P1)

**Acceptance criteria:**
- Given the `setting-up-arkeology` skill runs, then it probes annotation availability and IAM permission
  (put→get→delete a throwaway annotation) and reports the result plus the four required IAM actions;
  on failure it gives friendly remediation guidance and lets the operator decide to proceed (feature
  degrades, core still works). (AC-62)
- Given `aws-cli` ≥ 2.35.14, then the probe uses the CLI natively; otherwise it falls back to a
  boto3 snippet run via `uv run` (botocore supports the APIs regardless of CLI version).

### Story 4 — README + AGENTS.md guidance (P1)

**Acceptance criteria:**
- Given the README, then it documents the four IAM actions and the regions / bucket types where
  annotations are unavailable.
- Given the AGENTS.md snippet, then it includes (1) proactive `arkeology://artifact/{id}` referencing
  guidance and (2) reference-healing guidance (search + propose a fix, never silently rewrite). (D9)
- Given the post-commit protocol snippet, then it references `link_metadata` (not the retired
  `link_commit`).

## Requirements

- WHEN an annotation client call raises a botocore error indicating unavailability (e.g.
  `NotImplemented` / region/bucket-type rejection) or access denial (`AccessDenied`) THE SYSTEM SHALL
  detect it at the S3 client layer and raise a typed, structured error (a new
  `AnnotationUnavailableError`, distinct from `CredentialError`).
- WHEN `link_metadata` catches that error THE SYSTEM SHALL return a structured `annotation_unavailable`
  error with actionable text (which IAM actions / region constraints) — the durable write is its
  contract, so it does not report `linked`.
- WHEN the write path catches that error after content + vectors are persisted THE SYSTEM SHALL
  return its normal success payload plus a top-level `warning` noting durable link storage is
  unavailable — the artifact is never lost.
- WHEN the server starts THE SYSTEM SHALL NOT add an annotation availability startup check
  (ADR-011 decision 5) — the existing startup sequence is unchanged.
- WHEN the `setting-up-arkeology` skill runs its pre-flight checks THE SYSTEM SHALL add an annotation
  availability + IAM probe (CLI ≥ 2.35.14 or boto3 `uv run` fallback) that put→get→deletes a
  throwaway annotation and reports the outcome + the four IAM actions.
- WHEN the README reference policy is updated THE SYSTEM SHALL list `s3:PutObjectAnnotation`,
  `s3:GetObjectAnnotation`, `s3:ListObjectAnnotations`, `s3:DeleteObjectAnnotation` and the
  unavailable regions (UAE, Bahrain) and bucket types (directory buckets, which use the S3 Express
  One Zone storage class, and Outposts buckets).
- WHEN the AGENTS.md snippet is updated THE SYSTEM SHALL add the two D9 guidance clauses and switch
  the post-commit protocol to `link_metadata`.

## Boundaries

**Always:**
- Annotation availability is a feature-level concern — never a hard startup gate (D15).
- Detection of the unavailable / access-denied condition happens at the S3 client layer and is
  surfaced as a typed error, consistent with the Phase-1 credential-wrapping pattern.
- The write path preserves the artifact (content + vectors) even when annotations fail — degraded,
  not lost.

**Ask First:**
- Nothing — placement and behaviour fixed by ADR-011 decision 5 / FR-57.

**Never:**
- Do not add a seventh/eighth startup check for annotations.
- Do not let an annotation failure raise a raw exception to the MCP caller.
- Do not discard the artifact content/vectors when only the annotation write fails.

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/clients/test_s3_annotations.py` | Modify | Tests: unavailable / AccessDenied codes → `AnnotationUnavailableError` — Red first |
| `src/arkeology/errors.py` | Modify | Add `AnnotationUnavailableError` (subclass of `ArkeologyError`) |
| `src/arkeology/clients/s3.py` | Modify | Detect unavailable/access-denied codes on annotation calls; raise `AnnotationUnavailableError` |
| `tests/unit/test_tools_write.py` | Modify | Test: annotation-unavailable → success + `warning`, content/vectors persisted — Red first |
| `src/arkeology/tools/write.py` | Modify | Catch `AnnotationUnavailableError`; return success + `warning` |
| `tests/unit/test_tools_link_metadata.py` | Modify | Test: annotation-unavailable → structured `annotation_unavailable` error — Red first |
| `src/arkeology/tools/link_metadata.py` | Modify | Catch `AnnotationUnavailableError`; return structured error |
| `src/arkeology/constants.py` | Modify | Add `ANNOTATION_UNAVAILABLE` to `ErrorCode` |
| `skills/setting-up-arkeology/SKILL.md` | Modify | Add the annotation availability + IAM probe as a pre-flight check (CLI ≥ 2.35.14 guard / boto3 `uv run` fallback) |
| `README.md` | Modify | Add the four IAM actions to the reference policy; document unavailable regions / bucket types |
| `skills/setting-up-arkeology/references/agents-snippet.md` | Modify | Add D9 `arkeology://` referencing + reference-healing clauses; switch post-commit protocol to `link_metadata` |

## Testing Approach

**TDD cycle — test file before implementation file in each pair (code portions only):**

1. **`test_s3_annotations.py` → `errors.py` + `s3.py`** — a botocore `ClientError` with an
   access-denied / not-implemented code on an annotation call is re-raised as
   `AnnotationUnavailableError` (use `mocker.patch.object` to inject the error side effect).
2. **`test_tools_write.py` → `write.py`** — annotation write raises `AnnotationUnavailableError`;
   assert the response still contains `artifact_id` + `sections_indexed` (content/vectors persisted)
   plus a non-empty `warning`; no raw exception.
3. **`test_tools_link_metadata.py` → `link_metadata.py`** — annotation write raises
   `AnnotationUnavailableError`; assert a structured `annotation_unavailable` error is returned and
   `linked` is not reported for that artifact.

Skill / README / snippet changes are prose (no unit tests); verify against the plan's done-condition
manually (probe present, IAM actions listed, regions/bucket-types documented, AGENTS.md guidance
present, `uv run arkeology` still starts).

## Open Questions

- **OQ-T52-a (resolved by recommendation):** write-path degrade = success + `warning` (artifact
  preserved); `link_metadata` degrade = structured error (durable link write is its contract). This
  split satisfies AC-62 ("structured, actionable error … core operations continue to function")
  while never losing an artifact. Confirm with the operator if a uniform error-for-both is preferred.
