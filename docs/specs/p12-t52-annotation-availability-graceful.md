---
type: Spec
id: p12-t52-annotation-availability-graceful
title: T52 — Annotation Availability + IAM Probe, Runtime Graceful Handling, README + AGENTS.md
description: Add a one-time annotation availability + IAM-permission probe to the setting-up-arkeology skill (aws-cli ≥ 2.35.14 guard or boto3 uv run fallback); document the four required IAM actions and the unavailable regions/bucket types in the README; handle annotation-unavailable / AccessDenied gracefully at runtime in link_metadata and the write path; add arkeology:// referencing + reference-healing guidance to the AGENTS.md snippet. SUPERSEDED 2026-09-06 — annotation availability is now a hard startup gate; see the Revision section.
tags: []
status: deprecated
okf_version: "0.2"
sources:
  - resource: docs/architecture-decisions/adr-2026-07-03-annotation-backed-link-storage.md
    title: Annotation-Backed Durable Storage for Mutable Link Fields (commit_refs + references)
    last_modified: 2026-09-29T00:00:00Z
  - resource: docs/architecture-decisions/adr-2026-07-03-artifact-cross-referencing.md
    title: Artifact Cross-Referencing — First-Class references Field, Migration Rewrite, and referenced_by Warning
    last_modified: 2026-09-29T00:00:00Z
  - resource: docs/brainstorming/brainstorming-2026-07-01-artifact-cross-referencing.md
    title: Artifact Cross-Referencing (Migration and Ongoing Writes)
    last_modified: 2026-07-02T00:00:00Z
  - resource: docs/specs/p12-t45-s3-annotation-client.md
    title: T45 — S3 Object Annotation Client Support + moto Self-Mock Extension
    last_modified: 2026-07-03T00:00:00Z
  - resource: docs/specs/p12-t47-annotation-dual-write.md
    title: T47 — Annotation Dual-Write in the Write Path + Tier-3 Overwrite Preservation
    last_modified: 2026-09-06T00:00:00Z
  - resource: docs/specs/p12-t49-link-metadata.md
    title: T49 — link_metadata Tool (generalizes and supersedes link_commit)
    last_modified: 2026-09-06T00:00:00Z
  - resource: docs/planning-artifacts/requirements.md
    title: Arkeology — Requirements
    last_modified: 2026-09-24T00:00:00Z
generated:
  by: "axians-architect/claude-opus-4.8"
  at: 2026-07-03T00:00:00Z
revised:
  by: "axians-architect/claude-sonnet-5-5"
  at: 2026-11-15T16:04:49Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
---

# T52 — Annotation Availability + IAM Probe, Runtime Graceful Handling, README + AGENTS.md

## Revision — 2026-09-06

The frozen scope below specifies the **opposite** of the model now in force. It is retained only
as the historical record of what T52 delivered. The `## Revision — 2026-09-05` section of
[adr-2026-07-03-annotation-backed-link-storage.md](../architecture-decisions/adr-2026-07-03-annotation-backed-link-storage.md) reverses that ADR's decision 5, and
requirements C-08 and FR-57 moved from *Should — degrades gracefully* to *Must — verified before
the server accepts any request*.

What this spec gets wrong as of that reversal:

- **Annotation availability is a hard startup gate.** The startup sequence gained an eighth check
  that round-trips all four annotation operations against a throwaway probe object. A deployment
  that cannot use annotations is unsupported, and the server refuses to start rather than running
  with the link fields degraded.
- **A failed durable link write is no longer reported as a success.** `write_artifact` returns
  `partial_write` with a failure-log entry, and `archive_artifact` records a partial archive.
- **An annotation read failure raises rather than returning empty.** Absence of an annotation
  still returns an empty value; a failed read never masquerades as one, because an empty read on a
  read-modify-write path would be written back over good data.

What survives unchanged: the `setting-up-arkeology` skill's one-time availability and IAM probe,
the four required IAM actions, and the documented unavailable regions and bucket types. The
runtime `annotation_unavailable` structured error also survives, but it now signals post-setup IAM
drift on a deployment the startup gate already proved good — not a supported degraded mode.

## TL;DR

Handle S3 object annotation availability and IAM as a **feature-level** concern, not a hard server
startup gate (ADR-011 decision 5). Add a one-time availability + IAM-permission probe to the
`setting-up-arkeology` skill; document the four required IAM actions and the unavailable regions /
bucket types in the README; handle annotation-unavailable / access-denied errors gracefully at
runtime in `link_metadata` and the write path (structured, actionable, never a raw exception — the
core content / vector / embedding store keeps working); and add the
adr-2026-07-03-artifact-cross-referencing D9 `arkeology://` referencing and reference-healing
guidance to the AGENTS.md snippet. (FR-57, NFR-12, AC-62.)

## 1. Problem Statement

Annotations are unavailable in some regions (UAE, Bahrain) and on some bucket types (directory
buckets, which is what the S3 Express One Zone storage class uses, and Outposts buckets) and need
IAM actions beyond core storage. Because annotations
back only the `commit_refs` / `references` feature — not the core store — refusing to boot over an
annotation problem would be disproportionate. Instead the deployment needs a friendly early check at
setup and graceful degradation at runtime to cover post-setup drift (an IAM edit, a bucket/region
change) a one-time check cannot catch.

All four stories are P1: runtime graceful handling (P1); server still boots without annotations
(P1); setup probe reports availability + IAM (P1); README + AGENTS.md guidance (P1).

## 2. Rules — Runtime handling

### R1 — Unavailability and access denial are detected at the S3 client layer as a typed error

When an annotation client call raises a botocore error indicating unavailability (e.g.
`NotImplemented` / region/bucket-type rejection) or access denial (`AccessDenied`), the system
detects it at the S3 client layer and raises a typed, structured error — a new
`AnnotationUnavailableError`, distinct from `CredentialError` — consistent with the Phase-1
credential-wrapping pattern.

### R2 — `link_metadata` returns a structured error; the write path succeeds with a warning

When annotations are unavailable or access is denied, the outcome depends on the surface, and in
both cases the core content / vector / embedding store still functions for other operations and
no annotation failure reaches the MCP caller as a raw exception:

| Surface | Behaviour |
|---|---|
| `link_metadata` | Catches the error and returns a structured `annotation_unavailable` error with actionable text (which IAM actions / region constraints). The durable write is its contract, so it does not report `linked`. |
| The write path (`write_artifact`) | Catches the error after content + vectors are persisted and returns its normal success payload plus a top-level structured, actionable `warning` noting that durable link storage (annotations) is unavailable. The artifact (content + vectors) is preserved — degraded, not lost; it is never discarded when only the annotation write fails. |

**Why:** This split satisfies AC-62 ("structured, actionable error … core operations continue to
function") while never losing an artifact. OQ-T52-a — resolved by recommendation; confirm with the operator if
a uniform error-for-both is preferred.

Source: AC-62

### R3 — A normal deployment shows no warning

Given a normal (available) deployment, no warning appears and both fields are durably stored.

## 3. Rules — Startup

### R4 — The server still boots without annotations

When the server starts on a deployment where annotations are unavailable, startup validation still
passes and the server serves content and search: annotation availability is NOT a startup check,
the system adds no annotation availability startup check, and the existing startup sequence is
unchanged. Annotation availability is a feature-level concern — never a hard startup gate.

Because annotations back only the `commit_refs` / `references` feature — not the core store —
refusing to boot over an annotation problem would be disproportionate.

Source: ADR-011 decision 5; brainstorming-2026-07-01-artifact-cross-referencing D15

## 4. Rules — Setup probe

### R5 — The `setting-up-arkeology` skill probes annotation availability and IAM

When the `setting-up-arkeology` skill runs its pre-flight checks, it probes annotation availability
and IAM permission by put→get→deleting a throwaway annotation, and reports the outcome plus the four
required IAM actions. On failure it gives friendly remediation guidance and lets the operator decide
to proceed (feature degrades, core still works).

Given `aws-cli` ≥ 2.35.14, the probe uses the CLI natively; otherwise it falls back to a boto3
snippet run via `uv run` (botocore supports the APIs regardless of CLI version).

Source: AC-62 — the probe-and-report part

## 5. Rules — README and AGENTS.md guidance

### R6 — The README documents the four IAM actions and where annotations are unavailable

When the README reference policy is updated, it lists `s3:PutObjectAnnotation`,
`s3:GetObjectAnnotation`, `s3:ListObjectAnnotations`, `s3:DeleteObjectAnnotation`, and the README
documents the unavailable regions (UAE, Bahrain) and bucket types (directory buckets, which use the
S3 Express One Zone storage class, and Outposts buckets).

### R7 — The AGENTS.md snippet carries the referencing guidance and the `link_metadata` post-commit protocol

When the AGENTS.md snippet is updated, it includes (1) proactive `arkeology://artifact/{id}`
referencing guidance and (2) reference-healing guidance (search + propose a fix, never silently
rewrite), and its post-commit protocol references `link_metadata` (not the retired `link_commit`).

Source: adr-2026-07-03-artifact-cross-referencing D9 — the two guidance clauses part

## 6. Boundaries

**Always:**
- Annotation availability is a feature-level concern — never a hard startup gate
  (brainstorming-2026-07-01-artifact-cross-referencing D15).
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

## 7. For the developer agent

### Files to Touch

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
| `skills/setting-up-arkeology/references/agents-snippet.md` | Modify | Add adr-2026-07-03-artifact-cross-referencing D9 `arkeology://` referencing + reference-healing clauses; switch post-commit protocol to `link_metadata` |

### Contracts

None.

### Testing Approach

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
