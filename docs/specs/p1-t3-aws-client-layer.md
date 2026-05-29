---
type: feature-spec
feature: p1-t3-aws-client-layer
created: 2026-05-29
status: ready
phase: 1
task: 3
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
- Given a unit test that uses `FakeS3Client`, when the test calls `put_object()` and then `get_object()` with the same key, then the stored content is returned — no AWS call is made.
- Given a unit test that uses `FakeVectorsClient`, when the test calls `put_vector()` and then `query_vectors()` with a matching filter, then the vector is returned — no AWS call is made.
- Given a unit test that simulates a credential failure by calling `FakeBedrockClient.set_credential_failure(True)`, when any method is called, then a `CredentialError` is raised — not a raw exception.

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
- WHEN a fake client method is called with `set_credential_failure(True)` active THE SYSTEM SHALL raise `CredentialError` as the concrete implementations do.
- WHEN any AWS API call fails with a non-credential error THE SYSTEM SHALL re-raise the original exception — not swallow it, not wrap it in `CredentialError`.

## Boundaries

**Always:**
- Three interfaces, three concrete implementations, three fakes — one per AWS service (S3, S3 Vectors, Bedrock).
- Interfaces are abstract base classes (Python `abc.ABC`, `abc.abstractmethod`).
- Fakes live under `src/cairn_mcp/clients/fakes/` and are used exclusively in tests — never imported in production code paths.
- Fakes must implement every method on their corresponding interface — incomplete fakes cause unit test gaps.
- `CredentialError` is defined in `errors.py` and imported by the clients — it does not live inside the `clients/` package.
- The credential error wrapping is in the concrete client methods, not in the abstract interface.
- boto3 client objects are created once per concrete client instance (not per call).

**Ask First:**
- Nothing — all constraints are defined.

**Never:**
- Do not make boto3 calls in the abstract interface or in the fakes.
- Do not use `os.environ` directly inside client implementations — credentials are handled via boto3's session mechanism.
- Do not create a new boto3 session per API call — sessions are created once at client initialisation.
- Do not catch non-credential AWS errors and convert them to `CredentialError` — only the specific credential-related error codes warrant that treatment.

<!-- IMPLEMENTATION BLOCK -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `src/cairn_mcp/errors.py` | Create | Defines `CredentialError` and other base error types |
| `src/cairn_mcp/clients/__init__.py` | Create | Empty package marker |
| `src/cairn_mcp/clients/interfaces.py` | Create | Abstract base classes for all three clients |
| `src/cairn_mcp/clients/s3.py` | Create | Concrete S3 boto3 implementation |
| `src/cairn_mcp/clients/vectors.py` | Create | Concrete S3 Vectors boto3 implementation |
| `src/cairn_mcp/clients/bedrock.py` | Create | Concrete Bedrock boto3 implementation |
| `src/cairn_mcp/clients/fakes/__init__.py` | Create | Empty package marker |
| `src/cairn_mcp/clients/fakes/fake_s3.py` | Create | In-memory S3 fake |
| `src/cairn_mcp/clients/fakes/fake_vectors.py` | Create | In-memory S3 Vectors fake |
| `src/cairn_mcp/clients/fakes/fake_bedrock.py` | Create | Deterministic embedding fake |
| `tests/unit/clients/test_fake_s3.py` | Create | Full interface coverage via fake |
| `tests/unit/clients/test_fake_vectors.py` | Create | Full interface coverage via fake |
| `tests/unit/clients/test_fake_bedrock.py` | Create | Full interface coverage via fake |
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

## `clients/interfaces.py` — Abstract Base Classes

### `S3ClientInterface`

Methods the interface must declare (each marked `@abstractmethod`):

| Method | Parameters | Returns | Description |
|--------|-----------|---------|-------------|
| `put_object` | `key: str, body: str, metadata: dict[str, str]` | `None` | Store object under key with optional metadata |
| `get_object` | `key: str` | `str` | Retrieve object content by key; raises `KeyError` if not found |
| `head_object` | `key: str` | `dict[str, Any]` | Retrieve object metadata without content; raises `KeyError` if not found |
| `list_objects` | `prefix: str` | `list[str]` | List all object keys under prefix |
| `head_bucket` | `bucket: str` | `None` | Check bucket existence and accessibility; raises on error |

### `VectorsClientInterface`

Methods the interface must declare:

| Method | Parameters | Returns | Description |
|--------|-----------|---------|-------------|
| `put_vector` | `key: str, vector: list[float], metadata: dict[str, Any]` | `None` | Upsert a vector with key and metadata |
| `get_vectors` | `keys: list[str]` | `list[dict[str, Any]]` | Retrieve vectors (with metadata) by key list |
| `query_vectors` | `vector: list[float], top_k: int, filter: dict[str, Any] \| None` | `list[dict[str, Any]]` | Semantic search; each result has `key`, `score`, and `metadata` |
| `delete_vectors` | `keys: list[str]` | `None` | Delete vectors by key list |
| `describe_index` | None | `dict[str, Any]` | Return index metadata including `dimensions` field |
| `list_vectors_by_metadata` | `filter: dict[str, Any]` | `list[str]` | Return all keys matching a metadata filter (used by list_artifacts and reconcile) |

### `BedrockClientInterface`

Methods the interface must declare:

| Method | Parameters | Returns | Description |
|--------|-----------|---------|-------------|
| `embed` | `text: str, model_id: str` | `list[float]` | Generate embedding for text using specified model |

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

- `embed` → `client.invoke_model(modelId=model_id, body=json.dumps({"inputText": text, "dimensions": N, "normalize": True}), contentType="application/json")`
  - Parse the response body JSON to extract the `embedding` field (a list of floats).
  - For Titan Text Embeddings v2 specifically: the response shape is `{"embedding": [...], "inputTextTokenCount": N}`.
  - The `dimensions` parameter in the request body controls the output dimension (256, 512, or 1024 for Titan v2). Leave it out to use the model default.
  
> **Important:** The exact request/response shape for Titan Text Embeddings v2 and other models must be verified against the Bedrock documentation. Do not assume the shape above is final — write an integration test that calls real Bedrock and verify the response structure.

---

## Fakes

### Design principles

- Fakes are full, stateful implementations that satisfy the interface contract.
- They store data in Python dicts/lists in memory — they are reset at construction.
- They support `set_credential_failure(True/False)` to simulate auth failures on demand.
- They do not simulate network latency or partial failures (beyond credential failure).
- They are deterministic: given the same inputs, they always return the same outputs.
- They are not mocks — do not use `unittest.mock` to build them.

### `FakeS3Client`

Internals:
- `_objects: dict[str, tuple[str, dict]]` — maps key → (content, metadata)
- `_credential_failure: bool`

Behaviour:
- `put_object`: stores `(body, metadata)` under `key`.
- `get_object`: returns stored content; raises `KeyError` if key absent.
- `head_object`: returns stored metadata dict; raises `KeyError` if absent.
- `list_objects(prefix)`: returns all keys that start with `prefix`.
- `head_bucket`: always succeeds unless `_credential_failure` is True.
- Any method: if `_credential_failure` is True, raises `CredentialError` before doing anything else.

### `FakeVectorsClient`

Internals:
- `_vectors: dict[str, tuple[list[float], dict]]` — maps key → (vector, metadata)
- `_credential_failure: bool`

Behaviour:
- `put_vector`: upserts `(vector, metadata)` under `key`.
- `get_vectors(keys)`: returns list of `{"key": k, "metadata": m, "data": {"float32": v}}` for found keys; omits missing keys silently.
- `query_vectors(vector, top_k, filter)`: returns the `top_k` stored vectors sorted by cosine similarity to `vector`, filtered by `filter`. The filter implementation must support the metadata filter operators used in Phase 2+:
  - `{"field": {"$eq": value}}` — exact match (also handles list fields: true if value is in the list)
  - `{"field": {"$nin": [v1, v2, ...]}}` — not in list
  - `{"$and": [expr, expr, ...]}` — logical AND of sub-expressions
  Return format: `[{"key": k, "score": s, "metadata": m}]` ordered by score descending.
- `delete_vectors(keys)`: removes each key from `_vectors`; silently ignores missing keys.
- `describe_index()`: returns `{"dimension": 1024}` by default. The dimension is configurable at fake construction time via `FakeVectorsClient(dimension=1024)`.
- `list_vectors_by_metadata(filter)`: return all keys whose metadata matches `filter`.
- Cosine similarity: implement a simple dot-product / (norm_a * norm_b) formula. This does not need to be numerically perfect — it needs to return meaningful ordering for test assertions.

### `FakeBedrockClient`

Internals:
- `_credential_failure: bool`
- `_dimension: int` (default 1024)

Behaviour:
- `embed(text, model_id)`: returns a deterministic vector of length `_dimension`. The values do not need to be semantically meaningful — a simple hash-derived fixed vector is fine. The same `text` must always return the same vector (determinism matters for test repeatability). A straightforward approach: hash the text to a seed, use it to generate a fixed-length list of floats in [-1, 1] range, normalise to unit length.
- If `_credential_failure` is True: raises `CredentialError`.

---

## TDD Workflow

T3 is where TDD discipline is most critical. The entire client layer follows a strict
test-first sequence across three distinct Red/Green cycles. Do not skip ahead — the fakes are your
test substrate for all of Phase 2 and 3.

### Cycle 1 — Interfaces + Fake unit tests + Fakes

**Step 1 — Write `clients/interfaces.py`** (no tests yet).
The abstract base classes are design, not implementation. Write the three ABCs with all `@abstractmethod`
declarations. There is nothing to test-drive here; the interface is the specification.

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

- [ ] Confirm the exact boto3 service client name for S3 Vectors (`"s3vectors"` or another string). Check against the AWS SDK changelog for the boto3 version installed.
- [ ] Confirm the S3 Vectors `query_vectors` filter syntax for `$nin` (artifact_id NOT IN seen_ids) is supported. If not, document the fallback strategy (over-fetch with multiplier) in `plan.md` under Learnings.
- [ ] Confirm the Bedrock `invoke_model` request body schema for Titan Text Embeddings v2 — specifically whether `"dimensions"` is a valid request parameter and what the exact response field name is for the embedding array.
