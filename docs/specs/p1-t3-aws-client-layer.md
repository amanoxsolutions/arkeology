---
type: spec
title: T3 — AWS Client Layer
description: Feature spec for typed, testable AWS client interfaces (S3, S3 Vectors, Bedrock) with credential error wrapping and in-memory fakes for unit tests.
tags: []
timestamp: 2026-05-29T00:00:00Z
okf_version: "0.1"
feature: p1-t3-aws-client-layer
status: ready
phase: 1
task: 3
references:
  - docs/architecture-decisions/adr-2026-05-29-hexagonal-architecture.md
  - docs/specs/p7-t25-moto-migration.md
authored:
  by: "architect"
  date: "2026-05-29"
revised:
  by: "architect"
  date: "2026-09-04"
---

# T3 — AWS Client Layer

<!-- SCOPE BLOCK -->

## Problem Statement

All communication with AWS services must go through typed, testable interfaces. Without this layer,
unit tests require real AWS credentials, credential error handling is scattered across the codebase,
and swapping a service implementation requires surgery on every call site. The client layer
established in this task is the foundation every subsequent phase builds on — getting the interfaces
right here avoids refactoring under pressure in Phase 2.

## User Stories

### Story 1 — Business logic is testable without AWS credentials (P1)

A developer working on tool logic (Phase 2+) can write and run unit tests on a machine with no AWS
credentials configured. All AWS calls are replaced by in-memory fakes that implement the same
interface.

**Acceptance criteria:**
- Given a unit test using the moto-backed `s3_client` fixture, when the test calls `put_object()` and then `get_object()` with the same key, then the stored content is returned — no real AWS call is made.
- Given a unit test using the moto-backed `vectors_client` fixture, when the test calls `put_vector()` and then `query_vectors()` with a matching filter, then the vector is returned — no real AWS call is made.
- Given a unit test that simulates a credential failure via `mocker.patch.object(client, "<method>", side_effect=CredentialError(...))`, when the patched method is called, then a `CredentialError` is raised — not a raw exception.

### Story 2 — Credential errors never reach callers as raw exceptions (P1)

Any AWS call that fails due to expired or invalid credentials returns a structured, human-readable
`CredentialError` — never a raw `botocore` exception.

**Acceptance criteria:**
- Given an S3 `get_object` call fails with `botocore ClientError` code `InvalidClientTokenId`, when the error propagates, then the caller receives a `CredentialError` with a human-readable message.
- Given a Bedrock `invoke_model` call fails with `ExpiredTokenException`, when the error propagates, then the caller receives a `CredentialError` — not `botocore.exceptions.ClientError`.
- Given an S3 Vectors call fails with `AccessDeniedException`, when the error propagates, then the caller receives a `CredentialError`.

### Story 3 — All AWS communication uses HTTPS (P1)

Every boto3 client is configured to use HTTPS endpoints. An unencrypted connection is never made.

**Acceptance criteria:**
- Given a concrete client is instantiated, when it creates its boto3 session, then it uses `use_ssl=True` (the boto3 default) and does not override `endpoint_url` with an HTTP address.

## Requirements

- WHEN any AWS API call fails with an expired, invalid, or missing credential error THE SYSTEM SHALL catch the botocore exception and re-raise it as a `CredentialError` typed exception with a human-readable message and re-authentication instructions.
- WHEN a concrete client is instantiated THE SYSTEM SHALL create the boto3 session using HTTPS (the boto3 default — must not be overridden to HTTP).
- WHEN `AWS_PROFILE` is set in the environment THE SYSTEM SHALL create the boto3 session with `boto3.Session(profile_name=profile)`.
- WHEN `AWS_PROFILE` is not set THE SYSTEM SHALL create the boto3 session with `boto3.Session()` and rely on the standard credential chain.
- WHEN a unit test patches a client method with `mocker.patch.object(..., side_effect=CredentialError(...))` THE SYSTEM SHALL raise `CredentialError` at that call site, exactly as the concrete implementations do — never via a hand-rolled fake's own failure toggle.
- WHEN any AWS API call fails with a non-credential error THE SYSTEM SHALL re-raise the original exception — not swallow it, not wrap it in `CredentialError`.

## Boundaries

**Always:**
- Three interfaces, three concrete implementations. Only Bedrock gets a hand-written fake
  (`FakeBedrockClient`) — S3 and S3 Vectors are exercised in unit tests via moto instead, per
  `p7-t25-moto-migration.md`, which deleted this task's original `FakeS3Client`/
  `FakeVectorsClient` design and superseded it.
- Interfaces use `typing.Protocol` structural subtyping (ADR-003) — `abc.ABC`/
  `abc.abstractmethod` are never used in client code.
- The surviving fake lives under `src/arkeology/clients/fakes/` and is used exclusively in
  tests — never imported in production code paths.
- The surviving fake must implement every method on its corresponding interface — an
  incomplete fake causes unit test gaps.
- `CredentialError` is defined in `errors.py` and imported by the clients — it does not live inside the `clients/` package.
- The credential error wrapping is in the concrete client methods, not in the interface.
- boto3 client objects are created once per concrete client instance (not per call).

**Ask First:**
- Nothing — all constraints are defined.

**Never:**
- Do not make boto3 calls in the interface or in the fakes.
- Do not use `os.environ` directly inside client implementations — credentials are handled via boto3's session mechanism.
- Do not create a new boto3 session per API call — sessions are created once at client initialisation.
- Do not catch non-credential AWS errors and convert them to `CredentialError` — only the specific credential-related error codes warrant that treatment.

<!-- IMPLEMENTATION BLOCK -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `src/arkeology/errors.py` | Create | Defines `CredentialError` and other base error types |
| `src/arkeology/clients/__init__.py` | Create | Empty package marker |
| `src/arkeology/clients/interfaces.py` | Create | `typing.Protocol` interfaces for all three clients |
| `src/arkeology/clients/s3.py` | Create | Concrete S3 boto3 implementation |
| `src/arkeology/clients/vectors.py` | Create | Concrete S3 Vectors boto3 implementation |
| `src/arkeology/clients/bedrock.py` | Create | Concrete Bedrock boto3 implementation |
| `src/arkeology/clients/fakes/__init__.py` | Create | Empty package marker |
| `src/arkeology/clients/fakes/fake_s3.py` | Superseded | Deleted by `p7-t25-moto-migration.md` — S3 is exercised via moto in unit tests instead |
| `src/arkeology/clients/fakes/fake_vectors.py` | Superseded | Deleted by `p7-t25-moto-migration.md` — S3 Vectors is exercised via moto (plus a `query_vectors` extension) instead |
| `src/arkeology/clients/fakes/fake_bedrock.py` | Create | Deterministic embedding fake — the only fake that survives (moto's `invoke_model` is a generic stub, not deterministic per-text embeddings) |
| `tests/unit/clients/test_fake_bedrock.py` | Create | Full interface coverage via fake |
| `tests/unit/conftest.py` | Modify | moto-backed `s3_client`/`vectors_client` fixtures cover `S3ClientInterface`/`VectorsClientInterface` — see `p7-t25-moto-migration.md` |
| `tests/integration/clients/test_s3_client.py` | Create | Real AWS calls (requires credentials + provisioned S3 bucket) |
| `tests/integration/clients/test_vectors_client.py` | Create | Real AWS calls (requires credentials + provisioned S3 Vectors index) |
| `tests/integration/clients/test_bedrock_client.py` | Create | Real AWS calls (requires credentials + model access) |

---

## `errors.py` — Error Types

Define the following error types. Keep them simple — they are data carriers, not logic.

**`CredentialError`**: raised when an AWS call fails due to expired, invalid, or missing credentials.
Contains:
- `message: str` — human-readable explanation, e.g. `"AWS credentials have expired. Re-authenticate and restart the server."`
- `service: str` — which AWS service triggered the error, e.g. `"s3"`, `"bedrock"`, `"sts"`
- `original: Exception` — the original botocore exception, preserved for logging

**`StartupValidationError`**: raised during the startup sequence when a configuration check fails.
Contains:
- `check: str` — which check failed, e.g. `"credentials"`, `"write_prefix"`, `"vector_index_dimension"`
- `message: str` — actionable error message with remediation hint
(The startup errors are defined here but used in T5.)

---

## `clients/interfaces.py` — Protocol Interfaces

All three interfaces are `typing.Protocol` classes (ADR-003) — structural subtyping, not
inheritance. Concrete implementations and fakes satisfy them by shape alone; `abc.ABC`/
`abc.abstractmethod` are never used here. This corrects the original draft of this section,
which specified `ABC`/`abstractmethod` — the initial T3 implementation shipped that way and
was migrated to `Protocol` shortly after by a code review fix, aligning it with ADR-003
(authored the same day as this spec).

### `S3ClientInterface`

Methods this task establishes:

| Method | Parameters | Returns | Description |
|--------|-----------|---------|-------------|
| `put_object` | `key: str, body: str, metadata: dict[str, str]` | `None` | Store object under key with optional metadata |
| `get_object` | `key: str` | `str` | Retrieve object content by key; raises `KeyError` if not found |
| `head_object` | `key: str` | `dict[str, Any]` | Retrieve object metadata without content; raises `KeyError` if not found |
| `list_objects` | `prefix: str` | `list[str]` | List all object keys under prefix |
| `head_bucket` | `bucket: str` | `None` | Check bucket existence and accessibility; raises on error |
| `delete_object` | `key: str` | `None` | Delete object by key; silently ignores missing keys |

*Extended after T3 shipped, by later tasks: `put_object` gained `if_none_match`/`if_match`
conditional-write keyword arguments and now returns the object's ETag, and four annotation
methods (`put_object_annotation`, `get_object_annotation`, `list_object_annotations`,
`delete_object_annotation`) were added — both under ADR-011 /
`p12-t45-s3-annotation-client.md`. This table reflects only what T3 itself established; the
current full interface is `src/arkeology/clients/interfaces.py`.*

### `VectorsClientInterface`

Methods this task establishes:

| Method | Parameters | Returns | Description |
|--------|-----------|---------|-------------|
| `put_vector` | `key: str, vector: list[float], metadata: dict[str, Any]` | `None` | Upsert a vector with key and metadata |
| `get_vectors` | `keys: list[str]` | `list[dict[str, Any]]` | Retrieve vectors (with metadata) by key list |
| `query_vectors` | `vector: list[float], top_k: int, filter_expr: dict[str, Any] \| None` | `list[dict[str, Any]]` | Semantic search; each result has `key`, `score`, and `metadata` |
| `delete_vectors` | `keys: list[str]` | `None` | Delete vectors by key list |
| `describe_index` | None | `dict[str, Any]` | Return index metadata including `dimension` field |
| `list_vectors_by_metadata` | `filter_expr: dict[str, Any]` | `list[str]` | Return all keys matching a metadata filter (used by list_artifacts and reconcile) |

The parameter is `filter_expr`, never the bare name `filter` — `filter` is a Python builtin
and shadowing it was corrected by the same review-fix-17 pass that migrated `ABC` to
`Protocol` (see above).

*Extended after T3 shipped: `put_vectors_batch` (batched writes, chunked at the 500-item
`PutVectors` API limit) and `get_vectors`' `include_data` flag (skip fetching embedding data
when only metadata is needed) were added by later hardening work — current signatures live
in `src/arkeology/clients/interfaces.py`.*

### `BedrockClientInterface`

Methods this task establishes:

| Method | Parameters | Returns | Description |
|--------|-----------|---------|-------------|
| `embed` | `text: str, model_id: str, dimensions: int` | `list[float]` | Generate an embedding for text using the specified model and output dimension |

`dimensions` must be passed explicitly — omitting it lets Bedrock fall back to the model's
default output dimension, which will not match the configured `BEDROCK_EMBEDDING_DIMENSIONS`
or the S3 Vectors index dimension. (This parameter was missing from T3's initial
implementation and added immediately after, still within this task's own delivery — no
separate spec.)

*Extended after T3 shipped: `invoke_text_model(model_id: str, prompt: str) -> str` was added
by `p9-t30-write-artifacts.md` for Nova Lite description enrichment in the migration tooling
— it is not part of T3's own scope.*

---

## Concrete Implementations

### Session creation (all three clients)

Each concrete client `__init__` receives `region: str`, `profile: str | None`. Session creation logic:
- If `profile` is not None: `boto3.Session(profile_name=profile, region_name=region)`
- If `profile` is None: `boto3.Session(region_name=region)`
- Create the boto3 service client from this session. Do not pass `use_ssl=False` — the boto3 default is `True`.

### Credential error detection

The credential-related botocore error codes to catch and convert to `CredentialError` are:
- `"ExpiredTokenException"` — STS/SSO tokens have expired
- `"InvalidClientTokenId"` — access key ID is invalid
- `"AuthFailure"` — general auth failure (EC2/IAM metadata)
- `"AccessDeniedException"` — IAM policy denies the call (note: this may also mean wrong permissions, not just expired creds — wrap it as `CredentialError` to give the user a clear message to check both credentials and IAM policy)
- `"UnauthorizedOperation"` — similar to AccessDeniedException

In each concrete method, wrap the boto3 call in a try/except that catches `botocore.exceptions.ClientError`, reads `error.response["Error"]["Code"]`, checks if it matches the list above, and either re-raises as `CredentialError` or re-raises the original exception unchanged.

### `clients/s3.py` — S3ClientImpl

Wraps `boto3.client("s3")`. Map each interface method to the corresponding boto3 call:
- `put_object` → `s3.put_object(Bucket=..., Key=key, Body=body.encode("utf-8"), Metadata=metadata)`
- `get_object` → `s3.get_object(Bucket=..., Key=key)` then decode body from bytes
- `head_object` → `s3.head_object(Bucket=..., Key=key)` — convert `NoSuchKey` to `KeyError`
- `list_objects` → `s3.get_paginator("list_objects_v2").paginate(Bucket=..., Prefix=prefix)` — paginate to handle >1000 objects
- `head_bucket` → `s3.head_bucket(Bucket=bucket)` — used in health check

The bucket name is provided to the constructor and stored as an instance attribute.

### `clients/vectors.py` — VectorsClientImpl

Wraps the S3 Vectors boto3 client (`boto3.client("s3vectors")`).

S3 Vectors API reference points:
- `put_vector` → `client.put_vectors(vectorBucketName=..., indexName=..., vectors=[{key, data: {float32: vector}, metadata}])`
- `get_vectors` → `client.get_vectors(vectorBucketName=..., indexName=..., keys=[...])`
- `query_vectors` → `client.query_vectors(vectorBucketName=..., indexName=..., queryVector={float32: vector}, topK=top_k, filter=filter, returnMetadata=True)`
- `delete_vectors` → `client.delete_vectors(vectorBucketName=..., indexName=..., keys=[...])`
- `describe_index` → `client.describe_vector_index(vectorBucketName=..., indexName=...)` — returns dict including `dimension`
- `list_vectors_by_metadata` → use `query_vectors` with a large `topK` and the given filter, or use a dedicated list API if S3 Vectors provides one; document which approach is used

The vectors bucket name and index name are provided to the constructor.

> **Note:** The exact S3 Vectors boto3 API shape (parameter names, nesting) must be verified against the latest boto3 documentation during implementation. The shapes above are directionally correct but may differ in exact casing or structure. Add an integration test that does a `put_vector` + `get_vectors` round-trip and update the concrete implementation if needed.

### `clients/bedrock.py` — BedrockClientImpl

Wraps `boto3.client("bedrock-runtime")`.

- `embed` → `client.invoke_model(modelId=model_id, body=json.dumps({"inputText": text, "dimensions": dimensions, "normalize": True}), contentType="application/json")`
  - Parse the response body JSON to extract the `embedding` field (a list of floats).
  - For Titan Text Embeddings v2 specifically: the response shape is `{"embedding": [...], "inputTextTokenCount": N}`.
  - `dimensions` is the `embed` parameter (256, 512, or 1024 for Titan v2) — always pass it explicitly; do not omit it and rely on the model default (see the interface table above).
  
> **Important:** The exact request/response shape for Titan Text Embeddings v2 and other models must be verified against the Bedrock documentation. Do not assume the shape above is final — write an integration test that calls real Bedrock and verify the response structure.

---

## Fakes

`FakeS3Client` and `FakeVectorsClient` below describe this task's *original* design. Both were
deleted by `p7-t25-moto-migration.md`: S3 and S3 Vectors are exercised in unit tests via
moto-backed real clients instead (a `query_vectors` cosine-similarity extension covers the one
operation moto does not implement). Only `FakeBedrockClient` survives — moto's `invoke_model`
returns a generic stub, not deterministic per-text embeddings, so a hash-derived fake is still
needed there. Credential-failure simulation for any client, including Bedrock, no longer uses a
fake's own toggle method — it uses `mocker.patch.object(client, "<method>",
side_effect=CredentialError(...))` (see `p7-t25-moto-migration.md`).

### Design principles

- The surviving fake is a full, stateful implementation that satisfies its interface contract.
- It stores data in memory — reset at construction.
- It does not simulate network latency or partial failures.
- It is deterministic: given the same inputs, it always returns the same outputs.
- It is not a mock — do not use `unittest.mock` to build it.

### `FakeS3Client` (deleted — superseded by moto, see above)

### `FakeVectorsClient` (deleted — superseded by moto, see above)

### `FakeBedrockClient`

Internals:
- `_dimension: int` (default 1024)

Behaviour:
- `embed(text, model_id, dimensions)`: returns a deterministic vector of length `dimensions`.
  The values do not need to be semantically meaningful — a simple hash-derived fixed vector is
  fine. The same `text` must always return the same vector (determinism matters for test
  repeatability). A straightforward approach: hash the text to a seed, use it to generate a
  fixed-length list of floats in [-1, 1] range, normalise to unit length. `model_id` is accepted
  for interface compatibility but does not affect the output.
- Does not simulate credential failures itself — a test needing that patches the fake's `embed`
  method directly (see above), not a `set_credential_failure` toggle.

---

## TDD Workflow

T3 is where TDD discipline is most critical. The entire client layer follows a strict
test-first sequence across three distinct Red/Green cycles. Do not skip ahead — the fakes are your
test substrate for all of Phase 2 and 3.

*Historical note: this workflow describes T3 as originally executed, including
`FakeS3Client`/`FakeVectorsClient`, which `p7-t25-moto-migration.md` later deleted (see the
Fakes section above). It is kept as the record of how this task itself was delivered, not as
current guidance — do not re-create either fake if revisiting this task.*

### Cycle 1 — Interfaces + Fake unit tests + Fakes

**Step 1 — Write `clients/interfaces.py`** (no tests yet).
The `typing.Protocol` interfaces are design, not implementation. Write the three Protocol
classes. There is nothing to test-drive here; the interface is the specification.

**Step 2 — Write the unit tests (Red).**
Write `tests/unit/clients/test_fake_s3.py`, `test_fake_vectors.py`, and `test_fake_bedrock.py`
in full — all test cases from the Testing Approach section below. Import the fakes, call their
methods, write assertions. Run `uv run pytest tests/unit/` — all tests fail with `ImportError` or
`AttributeError` because the fakes do not exist yet. This is the Red state. ✓

**Step 3 — Write the fakes (Green).**
Implement `FakeS3Client`, `FakeVectorsClient`, `FakeBedrockClient` under `clients/fakes/`.
Each fake must satisfy its abstract interface (mypy will enforce this). Run
`uv run pytest tests/unit/` — all tests pass. ✓

**Step 4 — Refactor.**
Review the fake implementations. Are the filter operators in `FakeVectorsClient` correct?
Is the cosine similarity deterministic? Is `set_credential_failure` consistently applied?
Fix any issues. Tests stay green after refactoring. ✓

---

### Cycle 2 — Concrete implementation + Integration tests

**Step 5 — Write the integration tests (Red).**
Write `tests/integration/clients/test_s3_client.py`, `test_vectors_client.py`,
`test_bedrock_client.py`. These call the real AWS services. Mark them
`@pytest.mark.integration` so they do not run by default. Run
`uv run pytest -m integration` — all tests fail with `ImportError` because the concrete clients
do not exist yet. This is the Red state. ✓

**Step 6 — Write the concrete clients (Green).**
Implement `S3ClientImpl`, `VectorsClientImpl`, `BedrockClientImpl`. Each must satisfy its
abstract interface. Run `uv run pytest -m integration` — all tests pass against real AWS. ✓

Resolve the three open-risk checkpoints during this step (see the integration test section below)
and record the findings in `docs/planning-artifacts/plan.md` under Learnings.

**Step 7 — Refactor.**
Review credential error wrapping — is every botocore error code covered? Does `list_objects`
paginate correctly? Is the `embed` response parsing defensive enough for unexpected shapes?
All tests (unit + integration) stay green after refactoring. ✓

---

### Ordering rule

**Never write a concrete client before its integration tests exist.**
**Never write a fake before its unit tests exist.**
If you find yourself implementing something to "see if it works" before writing a test, stop,
write the test first, confirm it fails, then implement.

---

## Test Cases

*Historical note: `test_fake_s3.py` and `test_fake_vectors.py` below were deleted by
`p7-t25-moto-migration.md` along with the fakes they tested. Current unit-test coverage for
`S3ClientInterface`/`VectorsClientInterface` lives in the moto-backed tool tests instead — see
that spec for the replacement test list.*

### Unit tests — write these before writing the fakes (Cycle 1 Step 2)

Each fake gets a dedicated test file. Tests must achieve full method coverage of the interface.

**`test_fake_s3.py`:**
- Round-trip: `put_object` then `get_object` returns the same content.
- Missing key: `get_object` on absent key raises `KeyError`.
- `list_objects` with prefix returns only matching keys.
- `list_objects` returns empty list when no keys match prefix.
- `head_object` on absent key raises `KeyError`.
- Credential failure: all methods raise `CredentialError` when `set_credential_failure(True)`.

**`test_fake_vectors.py`:**
- Round-trip: `put_vector` then `get_vectors` returns the stored vector and metadata.
- Upsert: `put_vector` twice with the same key overwrites, leaving one entry.
- `query_vectors` with `top_k=1` returns the most similar vector.
- `query_vectors` with `filter` excludes non-matching vectors.
- `query_vectors` with `$nin` filter excludes listed keys.
- `query_vectors` with `$and` filter applies all conditions.
- `delete_vectors` removes the key; subsequent `get_vectors` does not include it.
- `delete_vectors` on missing key does not raise.
- `describe_index` returns configured dimension.
- Credential failure: all methods raise `CredentialError`.

**`test_fake_bedrock.py`:**
- Same input produces the same output (determinism).
- Different inputs produce different outputs (basic discrimination).
- Output vector has expected length (`dimension`).
- Credential failure: `embed` raises `CredentialError`.

### Integration tests — write these before writing the concrete clients (Cycle 2 Step 5)

These tests require a fully provisioned AWS environment. Mark them with a pytest marker (e.g.
`@pytest.mark.integration`) so they can be excluded from the default `uv run pytest` run and
included explicitly with `uv run pytest -m integration`.

**`test_s3_client.py`:**
- `put_object` + `get_object` round-trip against the real test bucket.
- `list_objects` returns expected keys after writes.
- `head_bucket` on the configured bucket returns without error.

**`test_vectors_client.py`:**
- `put_vector` + `get_vectors` round-trip against the real test index.
- `query_vectors` returns a result for a vector close to an indexed one.
- `describe_index` returns the expected dimension.
- **Integration checkpoint:** Verify `put_vector` on an existing key is an upsert (not error, not duplicate). Document the result in `docs/planning-artifacts/plan.md` under Learnings.
- **Integration checkpoint:** Verify `#` is a valid character in S3 Vectors vector keys. If invalid, note that `--` is the fallback separator.

**`test_bedrock_client.py`:**
- `embed` returns a vector of the expected length for `amazon.titan-embed-text-v2:0`.
- Document the actual response shape (confirm the exact JSON field names) in `docs/planning-artifacts/plan.md` under Learnings.

## Open Questions

- [x] Confirm the exact boto3 service client name for S3 Vectors (`"s3vectors"` or another string). Check against the AWS SDK changelog for the boto3 version installed. **Resolved** — `VectorsClientImpl` calls `session.client("s3vectors")` (see `src/arkeology/clients/vectors.py`).
- [x] Confirm the S3 Vectors `query_vectors` filter syntax for `$nin` (artifact_id NOT IN seen_ids) is supported. If not, document the fallback strategy (over-fetch with multiplier) in `plan.md` under Learnings. **Resolved** — `$nin` is supported and shipped: `_search_helper.py`'s re-fetch loop excludes already-seen artifact IDs via an `{"artifact_id": {"$nin": [...]}}` clause, bounded by a byte-size budget (`_NIN_EXCLUSION_BYTE_BUDGET`) with a documented partial-results fallback once that budget is exceeded — no over-fetch-multiplier strategy was needed.
- [x] Confirm the Bedrock `invoke_model` request body schema for Titan Text Embeddings v2 — specifically whether `"dimensions"` is a valid request parameter and what the exact response field name is for the embedding array. **Resolved** — `BedrockClientImpl.embed()` (see `src/arkeology/clients/bedrock.py`) confirms the request body is `{"inputText": text, "dimensions": dimensions}` and the response body is `{"embedding": [...], "inputTextTokenCount": N}`.
