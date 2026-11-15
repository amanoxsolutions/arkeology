---
type: Spec
id: p1-t3-aws-client-layer
title: T3 — AWS Client Layer
description: Feature spec for typed, testable AWS client interfaces (S3, S3 Vectors, Bedrock) with credential error wrapping and in-memory fakes for unit tests.
tags: []
status: stable
okf_version: "0.2"
sources:
  - resource: docs/architecture-decisions/adr-2026-05-29-hexagonal-architecture.md
    title: Layered Architecture with Protocol-Based Client Interfaces
    last_modified: 2026-05-29T00:00:00Z
  - resource: docs/specs/p7-t25-moto-migration.md
    title: Migrate Unit Tests from Hand-Rolled Fakes to Moto
    last_modified: 2026-06-01T00:00:00Z
  - resource: docs/architecture-decisions/adr-2026-05-29-aws-backend-selection.md
    title: AWS S3 + S3 Vectors + Bedrock as the Storage and Embedding Backend
    last_modified: 2026-11-12T13:11:40Z
  - resource: docs/specs/p15-t92-numbered-vector-keys.md
    title: T92 — Numbered Vector Keys and Per-Artifact Vector Access by Key
    last_modified: 2026-11-12T13:11:40Z
  - resource: https://docs.aws.amazon.com/AmazonS3/latest/API/API_S3VectorBuckets_ListVectors.html
    title: Amazon S3 API Reference — ListVectors
  - resource: https://docs.aws.amazon.com/AmazonS3/latest/API/API_S3VectorBuckets_GetIndex.html
    title: Amazon S3 API Reference — GetIndex
  - resource: .docs/reviews/architecture-review-2026-11-10-arkeology.md
    title: "Architecture review — Arkeology (whole design record)"
    last_modified: 2026-11-10T11:21:17Z
  - resource: .docs/review-fixes/calibration-2026-11-12.md
    title: "Calibration: is a filtered, paged QueryVectors (ENHANCED) an exhaustive per-artifact lookup?"
  - resource: .docs/reviews/architecture-review-2026-11-15-arkeology-phases-9-10-12.md
    title: "Architecture review — Arkeology, plan phases 9, 10 and 12"
generated:
  by: "axians-architect/unknown"
  at: 2026-05-29T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-15T19:44:03Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
  - by: "human:mlnrt"
    at: 2026-11-15T11:12:39Z
---

# T3 — AWS Client Layer

## TL;DR

Typed `typing.Protocol` interfaces and boto3 implementations for S3, S3 Vectors and Bedrock, through
which all AWS communication passes. Credential failures surface as a human-readable `CredentialError`,
every connection uses HTTPS, and unit tests run with no AWS credentials. This layer is the foundation
every subsequent phase builds on.

## 1. Problem Statement

All communication with AWS services must go through typed, testable interfaces. Without this layer,
unit tests require real AWS credentials, credential error handling is scattered across the codebase,
and swapping a service implementation requires surgery on every call site. The client layer
established in this task is the foundation every subsequent phase builds on — getting the interfaces
right here avoids refactoring under pressure in Phase 2. Its three goals — business logic testable
without AWS credentials, credential errors never reaching callers as raw exceptions, and all AWS
communication over HTTPS — are all priority P1.

## 2. Rules — Testability without AWS

### R1 — Unit tests run without AWS credentials

A developer working on tool logic (Phase 2+) can write and run unit tests on a machine with no AWS
credentials configured: all AWS calls are replaced by in-memory fakes that implement the same
interface, and no real AWS call is made.

**Example**

- Given a unit test using the moto-backed `s3_client` fixture, when the test calls `put_object()` and
  then `get_object()` with the same key, then the stored content is returned — no real AWS call is
  made.
- Given a unit test using the moto-backed `vectors_client` fixture, when the test calls `put_vector()`
  and then `query_vectors()` with a matching filter, then the vector is returned — no real AWS call is
  made.

### R2 — Simulated credential failures in unit tests

When a unit test simulates a credential failure by patching a client method with
`mocker.patch.object(client, "<method>", side_effect=CredentialError(...))`, calling the patched
method raises `CredentialError` at that call site — not a raw exception — exactly as the concrete
implementations do. This holds for any client, including Bedrock. Credential failures are never
simulated via a hand-rolled fake's own failure toggle (such as `set_credential_failure`).

Source: p7-t25-moto-migration

## 3. Rules — Credential errors

### R3 — Credential errors become `CredentialError`

When any AWS API call fails with an expired, invalid, or missing credential error, the botocore
exception is caught and re-raised as a `CredentialError` typed exception with a human-readable message
and re-authentication instructions — a caller never receives a raw `botocore` exception for it. The
botocore error codes treated as credential errors are:

| Code | Meaning |
|------|---------|
| `"ExpiredTokenException"` | STS/SSO tokens have expired |
| `"InvalidClientTokenId"` | access key ID is invalid |
| `"AuthFailure"` | general auth failure (EC2/IAM metadata) |
| `"AccessDeniedException"` | IAM policy denies the call |
| `"UnauthorizedOperation"` | similar to `AccessDeniedException` |

`AccessDeniedException` may also mean wrong permissions, not just expired credentials; it is still
wrapped as `CredentialError` to give the user a clear message to check both credentials and IAM
policy.

**Example**

- Given an S3 `get_object` call fails with `botocore ClientError` code `InvalidClientTokenId`, when the
  error propagates, then the caller receives a `CredentialError` with a human-readable message.
- Given a Bedrock `invoke_model` call fails with `ExpiredTokenException`, when the error propagates,
  then the caller receives a `CredentialError` — not `botocore.exceptions.ClientError`.
- Given an S3 Vectors call fails with `AccessDeniedException`, when the error propagates, then the
  caller receives a `CredentialError`.

### R4 — Non-credential errors are re-raised unchanged

When any AWS API call fails with a non-credential error, the original exception is re-raised
unchanged — not swallowed, and not wrapped in `CredentialError`. Only the specific credential-related
error codes warrant `CredentialError` treatment.

## 4. Rules — Connection and session

### R5 — All AWS communication uses HTTPS

Every boto3 client is configured to use HTTPS endpoints; an unencrypted connection is never made.
When a concrete client is instantiated, it creates its boto3 session using HTTPS — `use_ssl=True`, the
boto3 default, which must not be overridden to HTTP — and does not override `endpoint_url` with an
HTTP address.

### R6 — Session creation follows `AWS_PROFILE`

When `AWS_PROFILE` is set in the environment, the boto3 session is created with
`boto3.Session(profile_name=profile)`. When `AWS_PROFILE` is not set, the boto3 session is created with
`boto3.Session()` and relies on the standard credential chain.

## 5. Boundaries

**Always:**
- Three interfaces, three concrete implementations. Only Bedrock gets a hand-written fake
  (`FakeBedrockClient`) — S3 and S3 Vectors are exercised in unit tests via moto instead, per
  `p7-t25-moto-migration.md`, which supersedes this task's original `FakeS3Client`/`FakeVectorsClient`
  design.
- Interfaces use `typing.Protocol` structural subtyping (ADR-003) — `abc.ABC`/`abc.abstractmethod` are
  never used in client code.
- The surviving fake lives under `src/arkeology/clients/fakes/` and is used exclusively in tests —
  never imported in production code paths.
- The surviving fake must implement every method on its corresponding interface — an incomplete fake
  causes unit test gaps.
- `CredentialError` is defined in `errors.py` and imported by the clients — it does not live inside the
  `clients/` package.
- The credential error wrapping is in the concrete client methods, not in the interface.
- boto3 client objects are created once per concrete client instance (not per call).

**Ask First:**
- Nothing — all constraints are defined.

**Never:**
- Do not make boto3 calls in the interface or in the fakes.
- Do not use `os.environ` directly inside client implementations — credentials are handled via boto3's
  session mechanism.
- Do not create a new boto3 session per API call — sessions are created once at client initialisation.
- Do not catch non-credential AWS errors and convert them to `CredentialError` — only the specific
  credential-related error codes warrant that treatment.

## 6. For the developer agent

### Files to Touch

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

**Index mode (`p1-t5-startup-validation-sequence.md` R12):**

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/conftest.py` | Modify | The moto `get_index` response carries `indexMode` |
| `pyproject.toml` / `uv.lock` | Modify | `boto3`/`botocore` at a release whose `s3vectors` model declares `indexMode` on `GetIndex` — the locked 1.43.67 does not, 1.44.1 does (`.docs/review-fixes/calibration-2026-11-12.md`), and an older model drops the response field silently |

#### `errors.py` — Error Types

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

The startup errors are defined here but used in T5.

#### `clients/interfaces.py` — Protocol Interfaces

All three interfaces are `typing.Protocol` classes (ADR-003) — structural subtyping, not inheritance.
Concrete implementations and fakes satisfy them by shape alone; `abc.ABC`/`abc.abstractmethod` are
never used here.

**`S3ClientInterface`** — methods this task establishes:

| Method | Parameters | Returns | Description |
|--------|-----------|---------|-------------|
| `put_object` | `key: str, body: str, metadata: dict[str, str]` | `None` | Store object under key with optional metadata |
| `get_object` | `key: str` | `str` | Retrieve object content by key; raises `KeyError` if not found |
| `head_object` | `key: str` | `dict[str, Any]` | Retrieve object metadata without content; raises `KeyError` if not found |
| `list_objects` | `prefix: str` | `list[str]` | List all object keys under prefix |
| `head_bucket` | `bucket: str` | `None` | Check bucket existence and accessibility; raises on error |
| `delete_object` | `key: str` | `None` | Delete object by key; silently ignores missing keys |

This table reflects only what this task establishes. `put_object`'s `if_none_match`/`if_match`
conditional-write keyword arguments and its ETag return value, and the three annotation methods
(`put_object_annotation`, `get_object_annotation`, `delete_object_annotation`), belong to ADR-011 / `p12-t45-s3-annotation-client.md`, not to this spec;
the current full interface is `src/arkeology/clients/interfaces.py`.

**`VectorsClientInterface`** — methods this task establishes:

| Method | Parameters | Returns | Description |
|--------|-----------|---------|-------------|
| `put_vector` | `key: str, vector: list[float], metadata: dict[str, Any]` | `None` | Upsert a vector with key and metadata |
| `get_vectors` | `keys: list[str]` | `list[dict[str, Any]]` | Retrieve vectors (with metadata) by key list |
| `query_vectors` | `vector: list[float], top_k: int, filter_expr: dict[str, Any] \| None` | `list[dict[str, Any]]` | Semantic search; each result has `key`, `score`, and `metadata` |
| `delete_vectors` | `keys: list[str]` | `None` | Delete vectors by key list |
| `describe_index` | None | `dict[str, Any]` | Return index metadata including the `dimension` and `indexMode` fields |
| `list_vectors_by_metadata` | `filter_expr: dict[str, Any]` | `list[str]` | Return all keys matching a metadata filter, by a whole-index scan — for whole-scope enumerations only; a path working on named artifacts reads their vectors by key (`p15-t92-numbered-vector-keys.md`) |

The parameter is `filter_expr`, never the bare name `filter` — `filter` is a Python builtin and
shadowing it was corrected in the same pass that migrated `ABC` to `Protocol`.

S3 Vectors `query_vectors` filters support `$nin` (artifact_id NOT IN seen_ids), so no
over-fetch-multiplier fallback strategy is needed: `_search_helper.py`'s re-fetch loop excludes
already-seen artifact IDs via an `{"artifact_id": {"$nin": [...]}}` clause, bounded by a byte-size
budget (`_NIN_EXCLUSION_BYTE_BUDGET`) with a documented partial-results fallback once that budget is
exceeded.

`put_vectors_batch` (batched writes, chunked at the 500-item `PutVectors` API limit) and `get_vectors`'
`include_data` flag (skip fetching embedding data when only metadata is needed) come from later
hardening work, not this spec — current signatures live in `src/arkeology/clients/interfaces.py`.

**`BedrockClientInterface`** — methods this task establishes:

| Method | Parameters | Returns | Description |
|--------|-----------|---------|-------------|
| `embed` | `text: str, model_id: str, dimensions: int` | `list[float]` | Generate an embedding for text using the specified model and output dimension |

`dimensions` must be passed explicitly — omitting it lets Bedrock fall back to the model's default
output dimension, which will not match the configured `BEDROCK_EMBEDDING_DIMENSIONS` or the S3 Vectors
index dimension.

`invoke_text_model(model_id: str, prompt: str) -> str`, used for Nova Lite description enrichment in
the migration tooling, belongs to `p9-t30-write-artifacts.md` — it is not part of T3's own scope.

#### Concrete Implementations

**Session creation (all three clients).** Each concrete client `__init__` receives `region: str`,
`profile: str | None`. Session creation logic:
- If `profile` is not None: `boto3.Session(profile_name=profile, region_name=region)`
- If `profile` is None: `boto3.Session(region_name=region)`
- Create the boto3 service client from this session. Do not pass `use_ssl=False` — the boto3 default
  is `True`.

**Credential error detection.** In each concrete method, wrap the boto3 call in a try/except that
catches `botocore.exceptions.ClientError`, reads `error.response["Error"]["Code"]`, checks if it
matches the credential-related codes (R3), and either re-raises as `CredentialError` or re-raises the
original exception unchanged.

**`clients/s3.py` — S3ClientImpl.** Wraps `boto3.client("s3")`. Map each interface method to the
corresponding boto3 call:
- `put_object` → `s3.put_object(Bucket=..., Key=key, Body=body.encode("utf-8"), Metadata=metadata)`
- `get_object` → `s3.get_object(Bucket=..., Key=key)` then decode body from bytes
- `head_object` → `s3.head_object(Bucket=..., Key=key)` — convert `NoSuchKey` to `KeyError`
- `list_objects` → `s3.get_paginator("list_objects_v2").paginate(Bucket=..., Prefix=prefix)` —
  paginate to handle >1000 objects
- `head_bucket` → `s3.head_bucket(Bucket=bucket)` — used in health check

The bucket name is provided to the constructor and stored as an instance attribute.

**`clients/vectors.py` — VectorsClientImpl.** Wraps the S3 Vectors boto3 client, whose service name is
`"s3vectors"` (`boto3.client("s3vectors")`; `VectorsClientImpl` calls `session.client("s3vectors")`).

S3 Vectors API reference points:
- `put_vector` → `client.put_vectors(vectorBucketName=..., indexName=..., vectors=[{key, data: {float32: vector}, metadata}])`
- `get_vectors` → `client.get_vectors(vectorBucketName=..., indexName=..., keys=[...])`
- `query_vectors` → `client.query_vectors(vectorBucketName=..., indexName=..., queryVector={float32: vector}, topK=top_k, filter=filter, returnMetadata=True)`
- `delete_vectors` → `client.delete_vectors(vectorBucketName=..., indexName=..., keys=[...])`
- `describe_index` → `client.get_index(vectorBucketName=..., indexName=...)` — returns the `index`
  dict, including `dimension` and `indexMode`
- `list_vectors_by_metadata` → `client.list_vectors(..., maxResults=1000, returnMetadata=True,
  nextToken=...)` paged to the end and filtered in memory with `clients/filter.py`'s evaluator

The vectors bucket name and index name are provided to the constructor.

> **Note:** The exact S3 Vectors boto3 API shape (parameter names, nesting) must be verified against
> the latest boto3 documentation during implementation. The shapes above are directionally correct but
> may differ in exact casing or structure. Add an integration test that does a `put_vector` +
> `get_vectors` round-trip and update the concrete implementation if needed.

**`clients/bedrock.py` — BedrockClientImpl.** Wraps `boto3.client("bedrock-runtime")`.

- `embed` → `client.invoke_model(modelId=model_id, body=json.dumps({"inputText": text, "dimensions": dimensions, "normalize": True}), contentType="application/json")`
  - Parse the response body JSON to extract the `embedding` field (a list of floats).
  - For Titan Text Embeddings v2 specifically: the response shape is
    `{"embedding": [...], "inputTextTokenCount": N}`.
  - `dimensions` is the `embed` parameter (256, 512, or 1024 for Titan v2) — always pass it
    explicitly; do not omit it and rely on the model default (see the interface table above).

For Titan Text Embeddings v2, `"dimensions"` is a valid request parameter and the embedding array's
response field is `embedding`: `BedrockClientImpl.embed()` (see `src/arkeology/clients/bedrock.py`)
confirms the request body is `{"inputText": text, "dimensions": dimensions}` and the response body is
`{"embedding": [...], "inputTextTokenCount": N}`.

> **Important:** The exact request/response shape for Titan Text Embeddings v2 and other models must
> be verified against the Bedrock documentation. Do not assume the shape above is final — write an
> integration test that calls real Bedrock and verify the response structure.

#### Fakes

Only `FakeBedrockClient` survives; `FakeS3Client` and `FakeVectorsClient` were deleted by
`p7-t25-moto-migration.md`: S3 and S3 Vectors are exercised in unit tests via moto-backed real clients
instead (a `query_vectors` cosine-similarity extension covers the one operation moto does not
implement). `FakeBedrockClient` is still needed because moto's `invoke_model` returns a generic stub,
not deterministic per-text embeddings, so a hash-derived fake is required there. Credential-failure
simulation for any client follows R2.

**Design principles:**
- The surviving fake is a full, stateful implementation that satisfies its interface contract.
- It stores data in memory — reset at construction.
- It does not simulate network latency or partial failures.
- It is deterministic: given the same inputs, it always returns the same outputs.
- It is not a mock — do not use `unittest.mock` to build it.

**`FakeBedrockClient`**

Internals:
- `_dimension: int` (default 1024)

Behaviour:
- `embed(text, model_id, dimensions)`: returns a deterministic vector of length `dimensions`. The
  values do not need to be semantically meaningful — a simple hash-derived fixed vector is fine. The
  same `text` must always return the same vector (determinism matters for test repeatability). A
  straightforward approach: hash the text to a seed, use it to generate a fixed-length list of floats
  in [-1, 1] range, normalise to unit length. `model_id` is accepted for interface compatibility but
  does not affect the output.
- Does not simulate credential failures itself — a test needing that patches the fake's `embed`
  method directly (R2), not a `set_credential_failure` toggle.

### Contracts

None.

### Testing Approach

T3 is where TDD discipline is most critical. The entire client layer follows a strict test-first
sequence across three distinct Red/Green cycles. Do not skip ahead — the fakes are your test substrate for
all of Phase 2 and 3.

This workflow — both cycles and the ordering rule — is kept as the record of how this task was
delivered, not as current guidance; it includes `FakeS3Client`/`FakeVectorsClient` and their unit
tests, which `p7-t25-moto-migration.md` deleted — do not re-create either fake if revisiting this
task. Current unit-test coverage for `S3ClientInterface`/
`VectorsClientInterface` lives in the moto-backed tool tests instead — see that spec for the
replacement test list.

**Ordering rule.** Never write a concrete client before its integration tests exist. Never write a
fake before its unit tests exist. If you find yourself implementing something to "see if it works"
before writing a test, stop, write the test first, confirm it fails, then implement.

#### Cycle 1 — Interfaces + Fake unit tests + Fakes

1. **Write `clients/interfaces.py`** (no tests yet). The `typing.Protocol` interfaces are design, not
   implementation. Write the three Protocol classes. There is nothing to test-drive here; the
   interface is the specification.
2. **Write the unit tests (Red).** Write `tests/unit/clients/test_fake_s3.py`, `test_fake_vectors.py`,
   and `test_fake_bedrock.py` in full — all test cases from the Testing Approach section below. Import the fakes, call their
   methods, write assertions. Run `uv run pytest tests/unit/` — all tests fail with `ImportError` or
   `AttributeError` because the fakes do not exist yet. This is the Red state. ✓
3. **Write the fakes (Green).** Implement `FakeS3Client`, `FakeVectorsClient`, `FakeBedrockClient`
   under `clients/fakes/`. Each fake must satisfy its abstract interface (mypy will enforce this). Run
   `uv run pytest tests/unit/` — all tests pass. ✓
4. **Refactor.** Review the fake implementations. Are the filter operators in `FakeVectorsClient`
   correct? Is the cosine similarity deterministic? Is `set_credential_failure` consistently applied?
   Fix any issues. Tests stay green after refactoring. ✓

#### Cycle 2 — Concrete implementation + Integration tests

5. **Write the integration tests (Red).** Write `tests/integration/clients/test_s3_client.py`,
   `test_vectors_client.py`, `test_bedrock_client.py`. These call the real AWS services. Mark them
   `@pytest.mark.integration` so they do not run by default. Run `uv run pytest -m integration` — all
   tests fail with `ImportError` because the concrete clients do not exist yet. This is the Red
   state. ✓
6. **Write the concrete clients (Green).** Implement `S3ClientImpl`, `VectorsClientImpl`,
   `BedrockClientImpl`. Each must satisfy its abstract interface. Run `uv run pytest -m integration` —
   all tests pass against real AWS. ✓ Resolve the three open-risk checkpoints during this step (see
   the integration tests below), and record the findings in `docs/planning-artifacts/plan.md` under
   Learnings.
7. **Refactor.** Review credential error wrapping — is every botocore error code covered? Does
   `list_objects` paginate correctly? Is the `embed` response parsing defensive enough for unexpected
   shapes? All tests (unit + integration) stay green after refactoring. ✓

#### Unit tests — write these before writing the fakes (Cycle 1 step 2)

Each fake gets a dedicated test file. Tests must achieve full method coverage of the interface.
`test_fake_s3.py` and `test_fake_vectors.py` are superseded by `p7-t25-moto-migration.md` (see above).

**`test_fake_s3.py`** (superseded):
- Round-trip: `put_object` then `get_object` returns the same content.
- Missing key: `get_object` on absent key raises `KeyError`.
- `list_objects` with prefix returns only matching keys.
- `list_objects` returns empty list when no keys match prefix.
- `head_object` on absent key raises `KeyError`.
- Credential failure: all methods raise `CredentialError` when `set_credential_failure(True)`.

**`test_fake_vectors.py`** (superseded):
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

#### Integration tests — write these before writing the concrete clients (Cycle 2 step 5)

These tests require a fully provisioned AWS environment. Mark them with a pytest marker (e.g.
`@pytest.mark.integration`) so they can be excluded from the default `uv run pytest` run and included
explicitly with `uv run pytest -m integration`.

**`test_s3_client.py`:**
- `put_object` + `get_object` round-trip against the real test bucket.
- `list_objects` returns expected keys after writes.
- `head_bucket` on the configured bucket returns without error.

**`test_vectors_client.py`:**
- `put_vector` + `get_vectors` round-trip against the real test index.
- `query_vectors` returns a result for a vector close to an indexed one.
- `describe_index` returns the expected dimension.
- **Integration checkpoint:** Verify `put_vector` on an existing key is an upsert (not error, not
  duplicate). Document the result in `docs/planning-artifacts/plan.md` under Learnings.
- **Integration checkpoint:** Verify `#` is a valid character in S3 Vectors vector keys. If invalid,
  note that `--` is the fallback separator.

**`test_bedrock_client.py`:**
- `embed` returns a vector of the expected length for `amazon.titan-embed-text-v2:0`.
- Document the actual response shape (confirm the exact JSON field names) in
  `docs/planning-artifacts/plan.md` under Learnings.
