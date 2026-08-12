---
type: spec
title: T5 — Startup Validation Sequence
description: Feature spec for a startup validation sequence that verifies credentials, S3 prefix access, vector index existence, and embedding dimension before accepting any MCP tool call. Originally five checks; a sixth (text-model accessibility) was added later in p9-t30.
tags: []
timestamp: 2026-05-29T00:00:00Z
okf_version: "0.1"
feature: p1-t5-startup-validation-sequence
status: ready
phase: 1
task: 5
references: []
authored:
  by: "architect"
  date: "2026-05-29"
revised:
  by: "developer"
  date: "2026-07-05"
---

# T5 — Startup Validation Sequence

<!-- SCOPE BLOCK -->

> **Note (later evolution):** this spec defines the original **five** checks (1–5). A **sixth**
> check — text-model accessibility (`BEDROCK_TEXT_MODEL` reachable via an `invoke_text_model`
> probe, skipped when the var is unset) — was added later by **p9-t30** and is specified there.
> The running sequence was six checks; log messages and the success line below read `/6`
> accordingly at that time. See `p9-t30-write-artifacts.md` for that check's full specification.

> **Note (2026-07-05):** a **seventh** check — an embedding-model probe —
> was inserted as the new check 6, pushing the former check 6 (text-model accessibility) to
> position 7. Check 5 (`_check_model_dimension`) only ever compares two *configured* numbers
> (`BEDROCK_EMBEDDING_DIMENSIONS` vs. the index dimension reported by `describe_index`) and never
> calls Bedrock — so a wrong or unentitled embedding model previously passed every startup check
> and only failed on the first real write/search. The new check embeds a short probe string via
> `bedrock.embed` and asserts the returned vector's dimension matches, reusing the existing
> credential-error classification for entitlement/credential failures. The running sequence is now
> **seven checks**; log messages and the success line read `/7`. See `src/arkeology/startup.py`
> (`_check_embedding_probe`) for the implementation. The PRD (FR-07) and `SERVER-REFERENCE.md`
> check-count references still say
> five/six and need a corresponding update — flagged to the PM and tech-writer (out of scope for
> this spec, which documents code-adjacent drift only).

## Problem Statement

The server must validate all infrastructure prerequisites before accepting any MCP tool call.
Without this, an agent session starts normally and fails mid-task with a confusing error — only
then does the developer discover that a required AWS resource was never provisioned, or credentials
expired overnight. A hard startup failure with a precise, actionable message is strictly better
than silent success followed by a tool call failure three interactions later.

## User Stories

### Story 1 — Invalid credentials fail fast with a clear re-auth message (P1)

When credentials are expired or invalid, the server refuses to start and tells the developer
exactly what to do.

**Acceptance criteria:**
- Given AWS credentials are invalid, when the server starts, then it exits before entering the MCP event loop with the message: `"Credential check failed: AWS credentials are invalid or expired. Re-authenticate (e.g. aws sso login) and restart the server."`.
- Given the credential check fails, then no subsequent validation checks are attempted.

### Story 2 — Inaccessible storage fails with the specific prefix or bucket identified (P1)

When the write prefix is not readable or writable, the server identifies exactly which prefix failed.

**Acceptance criteria:**
- Given `WRITE_PREFIX=platform/my-service/` and that prefix is not writable, when the server starts, then it exits with: `"Write prefix access check failed for 'platform/my-service/': cannot write to this prefix. Check IAM permissions for s3:PutObject on this prefix."`.
- Given `READ_PREFIXES=network/` and that prefix is not readable, when the server starts, then it exits with a message identifying `network/` as the inaccessible foreign read prefix.

### Story 3 — Missing or wrong-dimension vector index is caught before any tool call (P1)

When the vector index does not exist or its dimension does not match the configured embedding model,
the server refuses to start with instructions for how to fix it.

**Acceptance criteria:**
- Given `VECTORS_INDEX=nonexistent-index`, when the server starts, then it exits with: `"Vector index check failed: index 'nonexistent-index' does not exist in bucket '...'. Create it with the correct dimension before starting the server."`.
- Given the vector index exists with 1024 dimensions but the configured model produces 512-dimensional vectors, when the server starts, then it exits with: `"Embedding model dimension mismatch: model 'X' produces 512-dimensional vectors but the index 'Y' expects 1024 dimensions. Recreate the index with dimension 512 or restore the original model."`.

### Story 4 — All checks pass: server enters the event loop (P1)

When all checks pass, the server logs a success line and enters the MCP event loop.

**Acceptance criteria:**
- Given all checks pass, when the server starts, then it logs `"Startup validation passed. arkeology is ready."` at INFO level and enters the FastMCP event loop.
- Given all checks pass, then each check's success is logged at DEBUG level.

## Requirements

- WHEN the server starts THE SYSTEM SHALL run all startup checks in order before accepting any tool call (originally five; a sixth, text-model accessibility, was added later in p9-t30).
- WHEN the credential check fails THE SYSTEM SHALL stop immediately, log the error at ERROR level to stderr, and exit with code 1 — no further checks are run.
- WHEN any subsequent check fails THE SYSTEM SHALL stop, log the error at ERROR level, and exit with code 1 — checks after the failing one are not run.
- WHEN all checks pass THE SYSTEM SHALL log a single INFO-level "ready" message and proceed to the MCP event loop.
- WHEN the write prefix check runs THE SYSTEM SHALL verify both read and write access to `WRITE_PREFIX`.
- WHEN the read prefix check runs THE SYSTEM SHALL verify read-only access to each entry in `READ_PREFIXES`.
- WHEN the vector index check runs THE SYSTEM SHALL verify the index exists by calling `describe_index` on the `VectorsClientInterface`.
- WHEN the dimension check runs THE SYSTEM SHALL compare the index's reported dimension against the embedding model's output dimension; a mismatch is a hard failure.
- WHEN the dimension check runs and the model is unknown THE SYSTEM SHALL fall back to a probe embedding to determine the output dimension.

## Boundaries

**Always:**
- Startup validation uses the client interfaces — never direct boto3 calls.
- The validation sequence is a standalone function in `startup.py` that accepts `Settings` + client instances as arguments — it must be fully testable with fakes.
- Each check raises a distinct `StartupValidationError` subclass (or a `StartupValidationError` with a distinct `check` field value) — the caller can identify which check failed.
- The order of checks is fixed: credentials → write prefix → read prefixes → vector index existence → vector index dimension (→ text-model accessibility, added later in p9-t30). This order is intentional: earlier checks gate later ones.
- All checks are run in a single blocking call before the server enters its async event loop.

**Ask First:**
- Nothing — all constraints are defined.

**Never:**
- Do not catch `StartupValidationError` inside `startup.py` — it propagates to `__main__.py` which handles the exit.
- Do not run startup validation in a background task or defer it — it must complete synchronously before the server loop starts.
- Do not skip checks or make them conditional on configuration flags — every applicable check runs every time. (Two checks are no-ops when their input is absent: the read-prefix check when `READ_PREFIXES` is empty, and the text-model check when `BEDROCK_TEXT_MODEL` is unset.)

<!-- IMPLEMENTATION BLOCK -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `src/arkeology/startup.py` | Create | `validate_startup(settings, s3, vectors, bedrock)` function |
| `src/arkeology/__main__.py` | Modify | Call `validate_startup(...)` between Settings construction and `server.run()` |
| `src/arkeology/errors.py` | Modify | `StartupValidationError` already declared in T3; verify it has the needed fields |
| `tests/unit/test_startup.py` | Create | All five failure paths + the all-pass path, using fakes |

---

## `startup.py` — Validation Sequence

### Function signature

```
validate_startup(
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface,
) -> None
```

Returns `None` on success. Raises `StartupValidationError` on any failure. Never catches exceptions
from the clients except to wrap them — it does not swallow failures.

### Check 1 — Credential check

**What it does:** Calls `STS GetCallerIdentity` to verify that the credentials are valid and
capable of making AWS API calls.

**How to implement this without an STS client interface:** The credential check is the one check
that does not use S3, S3 Vectors, or Bedrock. Two options:
1. Add `verify_credentials()` to one of the existing interfaces (least clean).
2. Add a fourth interface `STSClientInterface` with a single `get_caller_identity()` method, a
   concrete `STSClientImpl`, and a `FakeSTSClient` (cleanest).
3. Fold the credential check into `S3ClientInterface` as a `head_bucket()` call on `ARTIFACT_BUCKET` — this checks both credentials and bucket access in one shot, effectively merging checks 1 and 2a.

**Recommended approach:** Option 3. The `head_bucket()` call on `ARTIFACT_BUCKET` verifies that:
- Credentials are valid (otherwise it raises `CredentialError`)
- The S3 bucket exists and is accessible

This merges what would otherwise be two separate AWS calls into one and avoids adding a fourth
client. Document this as the implementation choice.

> If option 3 is chosen, the "credential check" in the sequence becomes: `s3.head_bucket(settings.artifact_bucket)`. A `CredentialError` from this call is re-raised as `StartupValidationError(check="credentials", ...)`. A non-credential S3 error (e.g. bucket does not exist) is a different failure and is reported under the bucket access check.

**Failure message:**
`"Credential check failed: AWS credentials are invalid or expired. Re-authenticate (e.g. aws sso login --profile <profile>) and restart the server."`

**Success log (DEBUG):** `"Check 1/6 passed: credentials valid"`

---

### Check 2 — Write prefix access (read + write)

**What it does:** Verifies that the server can read from and write to `WRITE_PREFIX` in
`ARTIFACT_BUCKET`.

**How to check write access without creating real artifacts:** Use a sentinel object:
1. Write a small probe object to a well-known key under `WRITE_PREFIX`: `{WRITE_PREFIX}_arkeology_probe/write-check`.
2. Read it back via `get_object` to verify read access.
3. Delete it (if the interface supports `delete_object`) or leave it with a well-known key (it is harmless — tiny and clearly named).

If the `S3ClientInterface` does not have `delete_object`, add it. The probe object is cheap and
easily identifiable.

The probe key must be deterministic and clearly named so it does not pollute the artifact namespace:
`{write_prefix}_arkeology_startup_probe` (note the leading underscore in the filename distinguishes
it from real artifact keys which start with a type segment).

**Failure scenarios:**
- `put_object` raises a non-credential error → write access denied.
- `get_object` raises `KeyError` → write succeeded but read failed (should not happen with correct IAM; if it does, both checks fail).

**Failure message for write denial:**
`"Write prefix access check failed for '{write_prefix}': cannot write to this prefix. Ensure the IAM policy includes s3:PutObject on arn:aws:s3:::{bucket}/{write_prefix}*."`

**Failure message for read denial:**
`"Write prefix access check failed for '{write_prefix}': cannot read from this prefix. Ensure the IAM policy includes s3:GetObject on arn:aws:s3:::{bucket}/{write_prefix}*."`

**Success log (DEBUG):** `"Check 2/6 passed: write prefix '{write_prefix}' is readable and writable"`

---

### Check 3 — Read prefix access (read-only, one check per prefix)

**What it does:** For each entry in `settings.read_prefixes_list`, verifies read access.

**How to check read access:** Call `list_objects(prefix=read_prefix)`. A successful call (even
returning an empty list) confirms the prefix is readable. A permission error confirms it is not.

If `read_prefixes_list` is empty, this check is skipped (log at DEBUG: "Check 3/6 skipped: no
foreign read prefixes configured").

This check runs once per prefix. If multiple prefixes fail, report only the first failure (to avoid
a wall of errors on badly misconfigured deployments). The developer can fix one at a time.

**Failure message:**
`"Read prefix access check failed for '{read_prefix}': cannot list objects. Ensure the IAM policy includes s3:ListBucket with condition StringLike s3:prefix '{read_prefix}*'."`

**Success log (DEBUG):** `"Check 3/6 passed: {n} foreign read prefix(es) accessible"`

---

### Check 4 — Vector index existence

**What it does:** Calls `vectors.describe_index()` to verify that the S3 Vectors index exists and
is reachable.

**What `describe_index` returns on a missing index:** This depends on the S3 Vectors API — it may
raise a `ClientError` with a code like `NoSuchIndex` or similar. The concrete `VectorsClientImpl`
must be written to:
1. Attempt `describe_index()`.
2. If the API returns a "not found" error, raise a specific exception — either a new typed
   exception `VectorIndexNotFoundError` defined in `errors.py`, or include it as a `StartupValidationError` raised from the concrete implementation.

The cleanest approach: have `VectorsClientImpl.describe_index()` raise `VectorIndexNotFoundError`
(a new type in `errors.py`) when the index does not exist. `startup.py` catches this specific
exception type and converts it to a `StartupValidationError`.

**Failure message (index missing):**
`"Vector index check failed: index '{index_name}' does not exist in bucket '{vectors_bucket}'. Create it with the correct dimension for model '{model_id}' before starting the server."` 

**Success log (DEBUG):** `"Check 4/6 passed: vector index '{index_name}' found with dimension {dim}"`

---

### Check 5 — Embedding model dimension vs. index dimension

**What it does:** Compares the vector dimension reported by `describe_index()` against the output
dimension of the configured embedding model. A mismatch means all future embedding calls will
produce vectors of the wrong dimension — the index is silently corrupted. This is a hard failure.

**Getting the model dimension:**

Two strategies:

**Strategy A — Static registry (preferred for known models):**

Maintain a small dict in `config.py` or `startup.py` that maps known model IDs to their default
output dimensions:

```
KNOWN_MODEL_DIMENSIONS = {
    "amazon.titan-embed-text-v2:0": 1024,
}
```

If the configured model ID is in the registry, use the registered dimension. No Bedrock call
needed at startup.

**Strategy B — Probe call (fallback for unknown models):**

If the model ID is not in the registry, call `bedrock.embed(text="probe", model_id=model_id)` and
measure `len(result)` to determine the output dimension. Log at DEBUG: `"Model '{model_id}' not in
known dimension registry; probing via embedding call."`.

**Implementation logic:**

1. Get `index_dimension` from the `describe_index()` result (from Check 4 — reuse the result, do not call `describe_index` twice).
2. Determine `model_dimension` via strategy A first, falling back to strategy B.
3. If `index_dimension != model_dimension`: raise `StartupValidationError(check="vector_index_dimension", ...)`.

**Failure message:**
`"Embedding model dimension mismatch: model '{model_id}' produces {model_dim}-dimensional vectors but index '{index_name}' expects {index_dim} dimensions. Either recreate the index with dimension {model_dim}, or set BEDROCK_EMBEDDING_MODEL to a model that produces {index_dim}-dimensional vectors."`.

**Success log (DEBUG):** `"Check 5/6 passed: model '{model_id}' dimension {model_dim} matches index dimension {index_dim}"`

---

### After all checks pass

Log at INFO: `"Startup validation passed (6/6 checks). arkeology is ready."`.

This log line is the developer's signal that AWS resources are correctly provisioned and the server
is accepting requests.

---

## `__main__.py` integration

After constructing `Settings` and before calling `server.run(settings)`:

1. Construct the three client instances using `Settings` values:
   ```
   s3 = S3ClientImpl(region=settings.aws_region, profile=settings.aws_profile, bucket=settings.artifact_bucket)
   vectors = VectorsClientImpl(region=settings.aws_region, profile=settings.aws_profile, bucket=settings.vectors_bucket, index=settings.vectors_index)
   bedrock = BedrockClientImpl(region=settings.aws_region, profile=settings.aws_profile)
   ```
2. Call `validate_startup(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)`.
3. If `StartupValidationError` is raised, print its `message` to stderr and exit with code 1.
4. If `CredentialError` is raised (from any client during startup), print its `message` to stderr and exit with code 1.
5. If no error: proceed to `server.run(settings)`.

Pass the constructed client instances into `server.run()` so the server can inject them into tools
(Phase 2+). The clients are not recreated inside the server.

---

## TDD Workflow

`startup.py` is pure orchestration logic — it calls the client interfaces and raises typed errors.
The fakes from T3 make every failure path simulatable without AWS. This is straightforward TDD.

**Step 1 — Write `tests/unit/test_startup.py` in full (Red).**
Write all test cases from the Test Cases section below. Import `validate_startup` from
`arkeology.startup` — which does not exist yet. Run `uv run pytest tests/unit/test_startup.py`
— every test fails with `ImportError`. This is the Red state. ✓

**Step 2 — Write `startup.py` (Green).**
Implement `validate_startup`. Run `uv run pytest tests/unit/test_startup.py` after each check is
implemented. Work through the checks in order (1 → 5). Do not implement all five at once — let
failing tests guide you. ✓

**Step 3 — Wire into `__main__.py` (also test-first).**
Before updating `__main__.py`, write a test that calls `main()` with a fake that triggers a
credential failure and asserts the process would exit with code 1. Then implement the
`validate_startup` call in `__main__.py`. ✓

**Step 4 — Refactor.**
Review error messages — are they actionable? Is the check ordering enforced (no check N+1 runs
after check N fails)? Run the full test suite. ✓

**Ordering rule:** `startup.py` must not exist before `test_startup.py` is written and fails.

---

## Test Cases

Tests use the fakes from T3. `test_startup.py` constructs a `Settings` instance using test
env vars (via monkeypatch) and injects fake clients.

**Required test cases:**

| Scenario | How to simulate | Expected outcome |
|----------|----------------|-----------------|
| All checks pass | All fakes healthy, valid settings | `validate_startup()` returns `None`; no exception |
| Check 1 fails (credential error) | `fake_s3.set_credential_failure(True)` | `StartupValidationError(check="credentials")` raised; subsequent checks not reached |
| Check 2 fails (write access denied) | Override `fake_s3.put_object` to raise a non-credential error for the probe key | `StartupValidationError(check="write_prefix")` raised |
| Check 2 fails (read access denied) | `put_object` succeeds; `get_object` for probe key raises `KeyError` | `StartupValidationError(check="write_prefix")` raised |
| Check 3 fails (foreign prefix not readable) | Override `fake_s3.list_objects` to raise for specific prefix | `StartupValidationError(check="read_prefix")` raised |
| Check 3 skipped (no read prefixes) | `READ_PREFIXES=""` | No exception; debug log shows check skipped |
| Check 4 fails (index missing) | `fake_vectors.describe_index()` raises `VectorIndexNotFoundError` | `StartupValidationError(check="vector_index")` raised |
| Check 5 fails (dimension mismatch) | `FakeVectorsClient(dimension=512)` + settings with Titan model (expected 1024) | `StartupValidationError(check="vector_index_dimension")` raised with both dimensions in message |
| Check 5 passes (unknown model, probe) | Model ID not in registry; `fake_bedrock.embed` returns 1024-dim vector; index dim = 1024 | No exception; probe was used |
| Check 5 passes (known model, registry) | Titan model; index dim = 1024 | No exception; no bedrock call made |
| Credential error mid-startup (check 3) | `fake_s3.set_credential_failure(True)` after check 2 passes | `CredentialError` propagates — startup terminates |

**Verify via test that no check after the failing one is executed.** Track calls using a simple
counter or spy on the fake methods — the method for check N+1 must not be called after check N
raises.

## Open Questions

- [ ] Decide whether to add a `delete_object` method to `S3ClientInterface` (and its fake + concrete impl) for the write probe cleanup. If not added, document that `_arkeology_startup_probe` keys will accumulate (they are tiny and clearly named, so this is acceptable). Recommendation: add `delete_object` — it is needed for the archive tool in Phase 3 anyway.
- [ ] Confirm the S3 Vectors API error code/name for a missing index (needed to implement `VectorIndexNotFoundError` correctly in the concrete client). Check the boto3 S3 Vectors error catalogue.
