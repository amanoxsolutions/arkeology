---
type: spec
title: T45 — S3 Object Annotation Client Support + moto Self-Mock Extension
description: Add put/get/list/delete object-annotation operations to the S3 Protocol interface and boto3 implementation, plus a moto conftest self-mock extension mirroring the query_vectors cosine patch. Prerequisite for all durable link storage in Phase 12.
tags: []
timestamp: 2026-07-03T00:00:00Z
okf_version: "0.1"
feature: p12-t45-s3-annotation-client
status: ready
phase: 12
task: 45
references:
  - docs/architecture-decisions/adr-2026-07-03-annotation-backed-link-storage.md
  - docs/architecture-decisions/adr-2026-07-03-artifact-cross-referencing.md
  - docs/brainstorming/brainstorming-2026-07-01-artifact-cross-referencing.md
  - docs/planning-artifacts/prd.md
authored:
  by: "architect"
  date: "2026-07-03"
revised:
  by: ""
  date: ""
---

# T45 — S3 Object Annotation Client Support + moto Self-Mock Extension

<!-- SCOPE BLOCK — frozen after approval -->

## TL;DR

Add four S3 object-annotation operations — put / get / list / delete — to the `S3ClientInterface`
`typing.Protocol` and the concrete `S3ClientImpl` boto3 client, and add a moto conftest extension
that self-mocks the annotation APIs (moto 5.2.2 has zero native annotation support). This is the
hard prerequisite for every durable-link-storage task in Phase 12 (T46–T54): annotations are the
durable store for `commit_refs` and `references` (ADR-011, FR-54). No tool changes in this task.

## Problem Statement

ADR-011 (FR-54) moves the durable copy of the mutable link fields (`commit_refs`, `references`)
from vector-metadata-only to **S3 object annotations** — a named payload, mutable in place via
`PutObjectAnnotation`, ETag-stable, that does not disturb the object body or its write-time
timestamp. `botocore` already exposes the four annotation operations, but the project's client
layer does not surface them and moto (the mandated S3 test backend) does not implement them. Until
the client layer and a moto self-mock exist, nothing downstream can be written, read, or unit-tested.

## User Stories

### Story 1 — Annotation round-trip through the client (P1)

The write path and `link_metadata` can put, read back, list, and delete a named annotation on an
S3 object via the injected `s3` client.

**Acceptance criteria:**
- Given an object at key `K`, when `s3.put_object_annotation(K, "commit_refs", "abc,def")` is
  called then `s3.get_object_annotation(K, "commit_refs")` returns `"abc,def"`.
- Given two annotations written to `K` (`"commit_refs"` and `"references"`), when
  `s3.list_object_annotations(K)` is called then it returns both annotation names.
- Given an annotation on `K`, when `s3.delete_object_annotation(K, "commit_refs")` is called then
  a subsequent `get_object_annotation(K, "commit_refs")` raises `KeyError` (annotation absent).
- Given a key with no annotation named `"references"`, when `get_object_annotation` is called for
  it, then `KeyError` is raised (mirrors the `get_object` missing-key contract).

### Story 2 — Overwrite wipes annotations (fidelity requirement) (P1)

The moto self-mock faithfully models the real S3 behaviour that overwriting an object clears its
annotations — this is what T47's overwrite-preservation tests depend on.

**Acceptance criteria:**
- Given an object at `K` with a `"commit_refs"` annotation, when `s3.put_object(K, ...)` is called
  again (overwrite), then `get_object_annotation(K, "commit_refs")` raises `KeyError` (the
  annotation was cleared by the object overwrite).

### Story 3 — Credential and access errors are structured (P1)

**Acceptance criteria:**
- Given a credential failure during any annotation call, when the client method runs then it raises
  `CredentialError` — never a raw botocore exception (via the existing `wrap_credential_errors`).

## Requirements

- WHEN `put_object_annotation(key, annotation_name, payload)` is called THE SYSTEM SHALL call the
  boto3 `put_object_annotation` operation with `Bucket`, `Key=key`, `AnnotationName=annotation_name`,
  and `AnnotationPayload=payload.encode("utf-8")`.
- WHEN `get_object_annotation(key, annotation_name)` is called THE SYSTEM SHALL return the payload
  decoded as a UTF-8 string, and SHALL raise `KeyError(key)` when the object or the named annotation
  does not exist.
- WHEN `list_object_annotations(key)` is called THE SYSTEM SHALL return the list of annotation names
  present on the object (paginating via `ContinuationToken` if the response is truncated).
- WHEN `delete_object_annotation(key, annotation_name)` is called THE SYSTEM SHALL delete the named
  annotation and SHALL NOT raise if it is already absent (mirrors `delete_object`).
- WHEN any annotation call encounters a credential error THE SYSTEM SHALL raise `CredentialError`
  via `wrap_credential_errors("s3")`.

> **Forward-pointer requirement (2026-07-06, not yet shipped) — optimistic-concurrency support.**
> `put_object_annotation` and `delete_object_annotation` gain an optional `if_match` parameter that
> is sent as the boto3 `ObjectIfMatch` parameter. WHEN `ObjectIfMatch` is supplied and does not
> match the object's current ETag THE SYSTEM SHALL translate the resulting HTTP 412
> `PreconditionFailed` into a structured conflict-signalling error (never a raw exception) — the
> caller (the write path, `link_metadata`, `archive_artifact`) is responsible for the bounded
> retry/re-merge cycle that consumes this signal; this client task's contract is only to expose the
> parameter and translate the precondition failure. This requires extending the moto self-mock
> annotation extension to honour `ObjectIfMatch` — determining first whether boto3 serialises it as
> a header or a query-string parameter for `PutObjectAnnotation`/`DeleteObjectAnnotation` (do not
> guess; inspect the installed botocore S3 service model). Full requirements and the error-type
> name: `docs/specs/review-followup-2026-07-06-design-fixes.md` ("Optimistic-Concurrency Writes"
> section, "Test infrastructure" subsection) and ADR-011 decision 6.
- WHEN the four methods are added to `S3ClientImpl` THE SYSTEM SHALL also add their signatures to
  the `S3ClientInterface` `typing.Protocol` — structural conformance only, no `ABC`.
- WHEN a unit test needs annotation behaviour THE SYSTEM SHALL exercise it through the moto
  self-mock extension registered once at conftest module load, mirroring the `query_vectors` patch.
- WHEN an object is overwritten via `put_object` THE SYSTEM SHALL (in the moto self-mock) clear all
  annotations previously stored for that key, matching real S3 semantics.

## Boundaries

**Always:**
- Interfaces are `typing.Protocol` — `S3ClientImpl` satisfies them structurally; never add `ABC`
  or `abstractmethod` (AGENTS.md non-negotiable).
- Annotation payloads are UTF-8 strings at the client boundary; the boto3 field is a blob, so the
  impl encodes/decodes `utf-8`. The client layer stays value-agnostic — field→annotation naming and
  list encoding are the tool layer's concern (T47/T49).
- The moto self-mock follows the exact precedent of the `query_vectors` cosine patch in
  `tests/unit/conftest.py`: patch at module load, active for all unit tests, never re-implemented
  per-test.
- Credential errors are wrapped at the client layer via `wrap_credential_errors` (Phase 1 concern).

**Ask First:**
- Nothing — the boto3 operation shapes are confirmed from the installed botocore service model
  (`PutObjectAnnotation`: required `Bucket, Key, AnnotationName, AnnotationPayload`;
  `GetObjectAnnotation`/`DeleteObjectAnnotation`: required `Bucket, Key, AnnotationName`;
  `ListObjectAnnotations`: required `Bucket, Key`, output `Annotations` + `NextContinuationToken`).

**Never:**
- Do not store artifact content in annotations here — this task is the transport only.
- Do not add tool-layer logic (encoding, field names, dual-write ordering) — that is T47/T49.
- Do not gate server startup on annotation availability (that is T52 / D15).
- Do not re-implement the `query_vectors` patch or touch it — add a parallel annotation extension.

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/conftest.py` | Modify | Add the moto S3-annotation self-mock extension (Red-enabling infra); model overwrite-wipe |
| `tests/unit/clients/test_s3_annotations.py` | Create | Client-method + extension round-trip tests — written first (Red) |
| `src/cairn_mcp/clients/interfaces.py` | Modify | Add the four annotation methods to `S3ClientInterface` Protocol |
| `src/cairn_mcp/clients/s3.py` | Modify | Implement the four methods on `S3ClientImpl` using `wrap_credential_errors` |
| `tests/integration/clients/test_s3_annotations.py` | Create | Real-AWS round-trip against a real bucket (written first for integration Red) |
| `AGENTS.md` | Modify | Add the annotation methods to the repo-structure / testing-conventions notes (self-mocked via conftest extension, precedent: `query_vectors`) |

## Testing Approach

**TDD cycle — moto extension + client tests before implementation:**

1. **`tests/unit/conftest.py` (extension) → `tests/unit/clients/test_s3_annotations.py` (Red):**
   Build the moto self-mock first (it is test infrastructure), then write the failing client tests
   that exercise it. Recommended extension approach, mirroring the `query_vectors` precedent:
   - Keep a module-level annotation store keyed by `(bucket, key) → {annotation_name: payload_bytes}`.
   - Register moto response handlers for the `?annotation` subresource on the S3 URL routes
     (`PUT`/`GET`/`DELETE` on `/{bucket}/{key}?annotation`) — the analog of the
     `url_paths["{0}/QueryVectors$"]` registration. Patch `moto.s3.responses.S3Response` to dispatch
     the annotation subresource (list when no `AnnotationName`, get/put/delete otherwise).
   - Hook moto's `put_object` (patch `S3Backend.put_object` or clear on the response path) so that
     writing a new object version at a key **clears** that key's annotation-store entry — this
     models the real overwrite-wipe and is required by T47's tests.
   - The exact moto integration seam may need empirical iteration; the store + overwrite-wipe
     semantics and the four-op behaviour are the fixed contract.

2. **`test_s3_annotations.py` unit cases (Red → Green against `s3.py`):**
   Use the `aws_mock` + `s3_client` fixtures. Pre-create an object via `s3.put_object`.
   - put→get: `put_object_annotation(K, "commit_refs", "abc,def")` then `get_object_annotation`
     returns `"abc,def"`.
   - list: two annotations written → `list_object_annotations(K)` returns both names.
   - delete: after `delete_object_annotation(K, "commit_refs")`, `get_object_annotation` raises `KeyError`.
   - missing: `get_object_annotation(K, "references")` with none set raises `KeyError`.
   - overwrite-wipe: annotate `K`, `put_object(K, ...)` again, assert `get_object_annotation` raises `KeyError`.
   - credential error: `mocker.patch.object` the underlying boto3 call to raise a credential error
     side effect → assert `CredentialError` propagates (never a raw exception).

3. **`interfaces.py` → `s3.py` (Green):** add the Protocol signatures, then implement on
   `S3ClientImpl` (each wrapped in `with wrap_credential_errors("s3")`, mapping missing
   object/annotation to `KeyError`).

4. **Integration (`tests/integration/clients/test_s3_annotations.py`, Red for integration):**
   put→get→list→delete round-trip against a real bucket; assert the moto extension's behaviour
   matches the real annotation API (per the plan's done-condition).

## Open Questions

*(none — boto3 operation shapes confirmed from the installed botocore service model; the moto
integration seam is an implementation detail to iterate on, with a fixed behavioural contract above)*
