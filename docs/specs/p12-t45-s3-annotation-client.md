---
type: Spec
id: p12-t45-s3-annotation-client
title: T45 — S3 Object Annotation Client Support + moto Self-Mock Extension
description: Add put/get/delete object-annotation operations to the S3 Protocol interface and boto3 implementation, plus a moto conftest self-mock extension mirroring the query_vectors cosine patch. Prerequisite for all durable link storage in Phase 12.
tags: []
status: stable
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
  - resource: docs/planning-artifacts/requirements.md
    title: Arkeology — Requirements
    last_modified: 2026-09-24T00:00:00Z
  - resource: docs/specs/p12-t52-annotation-availability-graceful.md
    title: T52 — Annotation Availability + IAM Probe, Runtime Graceful Handling, README + AGENTS.md
  - resource: docs/contracts/data/s3-annotations.artifact.md
    title: s3-annotations.artifact
  - resource: .docs/reviews/architecture-review-2026-11-15-arkeology-phases-9-10-12.md
    title: "Architecture review — Arkeology, plan phases 9, 10 and 12"
generated:
  by: "axians-architect/claude-opus-4.8"
  at: 2026-07-03T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-15T20:35:38Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
  - by: "axians-architect/claude-fable-5-2"
    at: 2026-11-15T20:45:07Z
---

# T45 — S3 Object Annotation Client Support + moto Self-Mock Extension

## TL;DR

Add three S3 object-annotation operations — put / get / delete — to the `S3ClientInterface`
`typing.Protocol` and the concrete `S3ClientImpl` boto3 client, and add a moto conftest extension
that self-mocks the annotation APIs (moto 5.2.2 has zero native annotation support). This is the
hard prerequisite for every durable-link-storage task in Phase 12 (T46–T54): annotations are the
durable store for `commit_refs` and `references` (ADR-011, FR-54). No tool changes in this task.

## 1. Problem Statement

ADR-011 (FR-54) moves the durable copy of the mutable link fields (`commit_refs`, `references`)
from vector-metadata-only to **S3 object annotations** — a named payload, mutable in place via
`PutObjectAnnotation`, ETag-stable, that does not disturb the object body or its write-time
timestamp. `botocore` already exposes the annotation operations, but the project's client
layer does not surface them and moto (the mandated S3 test backend) does not implement them. Until
the client layer and a moto self-mock exist, nothing downstream can be written, read, or unit-tested.
With them, the write path and `link_metadata` can put, read back and delete a named annotation on an
S3 object via the injected `s3` client. Every flow addresses the two link-field annotations by their
fixed names, so the client offers no operation that lists the annotations an object carries.

Priority: the annotation round-trip through the client (R1, R2, R4), the overwrite-wipe fidelity of the
self-mock (R9) and structured credential and access errors (R6, R10) are all P1.

## 2. Rules — Annotation operations on the S3 client

### R1 — Put an annotation

When `put_object_annotation(key, annotation_name, payload)` is called, the client calls the boto3
`put_object_annotation` operation with `Bucket`, `Key=key`, `AnnotationName=annotation_name`, and
`AnnotationPayload=payload.encode("utf-8")`.

**Example**

- Given an object at key `K`, when `s3.put_object_annotation(K, "commit_refs", "abc,def")` is
  called, then `s3.get_object_annotation(K, "commit_refs")` returns `"abc,def"`.

### R2 — Get an annotation

When `get_object_annotation(key, annotation_name)` is called, the client returns the payload
decoded as a UTF-8 string. When the call finds nothing, the client raises the outcome
`s3-annotations.artifact` § Not-Found Semantics assigns to the S3 error code received, keeping an
absent annotation, a missing object and an unclassified not-found distinct.

**Examples**

- Given an existing object with no annotation named `"references"`, when `get_object_annotation`
  is called for it, then `AnnotationNotFoundError` is raised.
- Given no object at key `K`, when `get_object_annotation(K, "commit_refs")` is called, then
  `ObjectNotFoundError` is raised, not `AnnotationNotFoundError`.

### R4 — Delete an annotation

When `delete_object_annotation(key, annotation_name)` is called, the client deletes the named
annotation and does not raise if it is already absent (mirrors `delete_object`).

**Example**

- Given an annotation on `K`, when `s3.delete_object_annotation(K, "commit_refs")` is called, then
  a subsequent `get_object_annotation(K, "commit_refs")` raises `AnnotationNotFoundError`
  (annotation absent).

### R5 — Optional `if_match` on put and delete (optimistic concurrency)

`put_object_annotation` and `delete_object_annotation` take an optional `if_match` parameter that
is sent as the boto3 `ObjectIfMatch` parameter. When `ObjectIfMatch` is supplied and does not match
the object's current ETag, the client translates the resulting HTTP 412 `PreconditionFailed` into
`ArtifactConflictError` (never a raw exception). The caller (the write path, `link_metadata`,
`archive_artifact`) owns the bounded retry/re-merge cycle that consumes this signal; this client
only exposes the parameter and translates the precondition failure. The moto self-mock annotation
extension honours `ObjectIfMatch`. How callers consume the signal: `s3-annotations.artifact` §
apply_link_annotations.

Source: ADR-011 decision 6

### R6 — Credential errors are structured

When any annotation call encounters a credential error, the client raises `CredentialError` via
`wrap_credential_errors("s3")` — never a raw botocore exception.

**Example**

- Given a credential failure during any annotation call, when the client method runs, then it
  raises `CredentialError` (via the existing `wrap_credential_errors`).

### R7 — The Protocol carries the three signatures

When the three methods are added to `S3ClientImpl`, their signatures are also added to the
`S3ClientInterface` `typing.Protocol` — structural conformance only, no `ABC`.

### R10 — Annotation unavailability and access denial are a typed error

When an annotation call fails because annotations are unavailable for the bucket or its region
(for example a `NotImplemented` rejection on a directory bucket) or because the caller lacks the
annotation permission (`AccessDenied`), the client raises `AnnotationUnavailableError` — distinct
from `CredentialError`, never a raw botocore exception. Every tool maps it to the one
`annotation_unavailable` code (`s3-annotations.artifact` § Compatibility Guarantees).

**Example**

- Given a role without `s3:GetObjectAnnotation`, when `get_object_annotation` is called, then it
  raises `AnnotationUnavailableError`, not `CredentialError` and not a `ClientError`.

Source: FR-57

## 3. Rules — moto self-mock extension

### R8 — Unit tests use the conftest self-mock

When a unit test needs annotation behaviour, it exercises it through the moto self-mock extension
registered once at conftest module load, mirroring the `query_vectors` patch.

### R9 — Overwrite wipes annotations (fidelity requirement)

When an object is overwritten via `put_object`, the moto self-mock clears all annotations
previously stored for that key, matching real S3 semantics. T47's overwrite-preservation tests
depend on the self-mock modelling this faithfully.

**Example**

- Given an object at `K` with a `"commit_refs"` annotation, when `s3.put_object(K, ...)` is called
  again (overwrite), then `get_object_annotation(K, "commit_refs")` raises
  `AnnotationNotFoundError` (the annotation was cleared by the object overwrite).

## 4. Boundaries

**Always:**
- Interfaces are `typing.Protocol` — `S3ClientImpl` satisfies them structurally; never add `ABC`
  or `abstractmethod` (AGENTS.md non-negotiable).
- Annotation payloads are UTF-8 strings at the client boundary; the boto3 field is a blob, so the
  impl encodes/decodes `utf-8`. The client layer stays value-agnostic — field→annotation naming and
  list encoding are the tool layer's concern (T47/T49).
- The moto self-mock follows the exact precedent of the `query_vectors` cosine patch in
  `tests/unit/conftest.py`: patch at module load, active for all unit tests, never re-implemented
  per-test.
- Credential errors are wrapped at the client layer via `wrap_credential_errors` (Phase 1 concern),
  and annotation unavailability or access denial is raised there as `AnnotationUnavailableError`
  (R10).

**Ask First:**
- Nothing — the boto3 operation shapes are confirmed from the installed botocore service model
  (`PutObjectAnnotation`: required `Bucket, Key, AnnotationName, AnnotationPayload`;
  `GetObjectAnnotation`/`DeleteObjectAnnotation`: required `Bucket, Key, AnnotationName`).

**Never:**
- No operation that lists an object's annotations, and so no `s3:ListObjectAnnotations` permission
  for the deployment to grant: every flow reads, writes and deletes the two link-field annotations
  by their fixed names. Revisit if a flow needs to discover which annotations an object carries.
- Do not store artifact content in annotations here — this task is the transport only.
- Do not add tool-layer logic (encoding, field names, dual-write ordering) — that is T47/T49.
- Do not re-implement the `query_vectors` patch or touch it — add a parallel annotation extension.

## 5. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/conftest.py` | Modify | Add the moto S3-annotation self-mock extension (Red-enabling infra); model overwrite-wipe. Dispatches put, get and delete only — remove the list dispatch (the `ListObjectAnnotations` action branch) |
| `tests/unit/clients/test_s3_annotations.py` | Create | Client-method + extension round-trip tests — written first (Red). Remove every `list_object_annotations` test, and the `s3:ListObjectAnnotations` assertion on the unavailability message |
| `src/arkeology/clients/interfaces.py` | Modify | Add the three annotation methods to `S3ClientInterface` Protocol; remove `list_object_annotations` |
| `src/arkeology/clients/s3.py` | Modify | Implement the three methods on `S3ClientImpl` using `wrap_credential_errors`; raise `AnnotationUnavailableError` on an unavailable or access-denied annotation call (R10). Remove `list_object_annotations` |
| `src/arkeology/clients/credentials.py` | Modify | The annotation-unavailability message names the three annotation actions, without `s3:ListObjectAnnotations` |
| `src/arkeology/errors.py` | Modify | `AnnotationUnavailableError`, a subclass of `ArkeologyError` (R10); `AnnotationNotFoundError` and `ObjectNotFoundError`, the two `KeyError` subclasses of the not-found outcomes (R2) |
| `src/arkeology/clients/credentials.py` | Modify | The annotation-unavailability error-code detection helper `s3.py` uses (R10) |
| `tests/integration/clients/test_s3_annotations.py` | Create | Real-AWS round-trip against a real bucket (written first for integration Red). Remove the `list_object_annotations` assertions and the `s3:ListObjectAnnotations` line of its required-permissions docstring |
| `AGENTS.md` | Modify | Add the annotation methods to the repo-structure / testing-conventions notes (self-mocked via conftest extension, precedent: `query_vectors`) |

### Contracts

- `docs/contracts/data/s3-annotations.artifact.md` § Not-Found Semantics, § apply_link_annotations and § Compatibility Guarantees — the three not-found outcomes a get reports, how the callers consume the `if_match` conflict, the overwrite wipe the self-mock models, and the one `annotation_unavailable` code (R2, R4, R5, R9, R10).

### Testing Approach

**TDD cycle — moto extension + client tests before implementation:**

1. **`tests/unit/conftest.py` (extension) → `tests/unit/clients/test_s3_annotations.py` (Red):**
   Build the moto self-mock first (it is test infrastructure), then write the failing client tests
   that exercise it. Recommended extension approach, mirroring the `query_vectors` precedent:
   - Keep a module-level annotation store keyed by `(bucket, key) → {annotation_name: payload_bytes}`.
   - Register moto response handlers for the `?annotation` subresource on the S3 URL routes
     (`PUT`/`GET`/`DELETE` on `/{bucket}/{key}?annotation`) — the analog of the
     `url_paths["{0}/QueryVectors$"]` registration. Patch `moto.s3.responses.S3Response` to dispatch
     the annotation subresource to get, put or delete by `AnnotationName`.
   - Hook moto's `put_object` (patch `S3Backend.put_object` or clear on the response path) so that
     writing a new object version at a key **clears** that key's annotation-store entry — this
     models the real overwrite-wipe and is required by T47's tests.
   - The exact moto integration seam may need empirical iteration; the store + overwrite-wipe
     semantics and the three-operation behaviour are the fixed contract.

2. **`test_s3_annotations.py` unit cases (Red → Green against `s3.py`):**
   Use the `aws_mock` + `s3_client` fixtures. Pre-create an object via `s3.put_object`.
   - put→get: `put_object_annotation(K, "commit_refs", "abc,def")` then `get_object_annotation`
     returns `"abc,def"`.
   - delete: after `delete_object_annotation(K, "commit_refs")`, `get_object_annotation` raises `AnnotationNotFoundError`.
   - missing annotation: `get_object_annotation(K, "references")` with none set raises `AnnotationNotFoundError`.
   - missing object: `get_object_annotation` on a key with no object raises `ObjectNotFoundError`, not `AnnotationNotFoundError`.
   - unclassified not-found: `mocker.patch.object` the underlying boto3 call to raise a `ClientError` with a bare `404` code → assert a plain `KeyError` that is neither subclass.
   - overwrite-wipe: annotate `K`, `put_object(K, ...)` again, assert `get_object_annotation` raises `AnnotationNotFoundError`.
   - credential error: `mocker.patch.object` the underlying boto3 call to raise a credential error
     side effect → assert `CredentialError` propagates (never a raw exception).
   - unavailable / access denied: `mocker.patch.object` the underlying boto3 call to raise a
     `ClientError` with an `AccessDenied` or `NotImplemented` code → assert
     `AnnotationUnavailableError` (R10).

3. **`interfaces.py` → `s3.py` (Green):** add the Protocol signatures, then implement on
   `S3ClientImpl` (each wrapped in `with wrap_credential_errors("s3")`, mapping each not-found
   cause on a get to its outcome, R2).

4. **Integration (`tests/integration/clients/test_s3_annotations.py`, Red for integration):**
   put→get→delete round-trip against a real bucket; assert the moto extension's behaviour
   matches the real annotation API (per the plan's done-condition).
