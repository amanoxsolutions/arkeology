---
type: Spec
id: p1-t5-startup-validation-sequence
title: T5 — Startup Validation Sequence
description: Feature spec for a startup validation sequence that verifies credentials, S3 prefix access, vector index existence, the index's dimension and its ENHANCED mode, and the embedding model before accepting any MCP tool call. Originally five checks; the running sequence is now eight — see the Revision sections.
tags: []
status: stable
okf_version: "0.2"
sources:
  - resource: docs/architecture-decisions/adr-2026-05-29-aws-backend-selection.md
    title: AWS S3 + S3 Vectors + Bedrock as the Storage and Embedding Backend
    last_modified: 2026-11-12T13:11:40Z
  - resource: docs/specs/p1-t3-aws-client-layer.md
    title: T3 — AWS Client Layer
    last_modified: 2026-11-12T13:11:40Z
  - resource: https://docs.aws.amazon.com/AmazonS3/latest/API/API_S3VectorBuckets_GetIndex.html
    title: Amazon S3 API Reference — GetIndex
  - resource: https://docs.aws.amazon.com/AmazonS3/latest/API/API_S3VectorBuckets_Index.html
    title: Amazon S3 API Reference — Index (indexMode)
  - resource: https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-index-mode.html
    title: Amazon S3 User Guide — Changing a vector index's mode
  - resource: .docs/reviews/architecture-review-2026-11-10-arkeology.md
    title: "Architecture review — Arkeology (whole design record)"
    last_modified: 2026-11-10T11:21:17Z
  - resource: .docs/review-fixes/calibration-2026-11-12.md
    title: "Calibration: is a filtered, paged QueryVectors (ENHANCED) an exhaustive per-artifact lookup?"
  - resource: docs/specs/p15-t92-numbered-vector-keys.md
    title: T92 — Numbered Vector Keys and Per-Artifact Vector Access by Key
    last_modified: 2026-11-12T13:11:40Z
  - resource: .docs/reviews/architecture-review-2026-11-15-arkeology-phases-9-10-12.md
    title: "Architecture review — Arkeology, plan phases 9, 10 and 12"
relationships:
  - to: p12-t52-annotation-availability-graceful
    type: supersedes
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
  - by: "axians-architect/claude-fable-5-2"
    at: 2026-11-15T21:22:34Z
---

# T5 — Startup Validation Sequence

> **Revisions:** originally five checks (1–5). Later, p9-t30 added a sixth check, text-model
> accessibility (R10). 2026-07-05: a seventh check, the embedding-model probe, was inserted as
> check 6, moving text-model accessibility to check 7 (R1, R9, R10). 2026-09-06: an eighth check,
> S3 object annotation availability, was appended after check 7, and every log message and the
> success line now read `/8` (R1, R3, R11).

## TL;DR

Before accepting any MCP tool call, the server runs a fixed sequence of eight blocking checks —
credentials, write prefix, read prefixes, vector index existence, index dimension and `ENHANCED`
mode, embedding-model probe, text-model accessibility and S3 object annotation availability — and
refuses to start with a
precise, actionable message on the first failure. Developers learn about a missing resource or expired
credentials at startup instead of mid-task.

## 1. Problem Statement

The server must validate all infrastructure prerequisites before accepting any MCP tool call. Without
this, an agent session starts normally and fails mid-task with a confusing error — only then does the
developer discover that a required AWS resource was never provisioned, or credentials expired
overnight. A hard startup failure with a precise, actionable message is strictly better than silent
success followed by a tool call failure three interactions later. Its four goals — invalid credentials
failing fast with a clear re-auth message, inaccessible storage failing with the specific prefix or
bucket identified, a missing or wrong-dimension vector index caught before any tool call, and the
server entering the event loop once all checks pass — are all priority P1.

## 2. Rules — The sequence

### R1 — Checks run in a fixed order, synchronously, before any tool call

When the server starts, it runs all startup checks in order before accepting any tool call, in a
single blocking call that completes synchronously before the server enters its async event loop —
never in a background task or deferred. The order is fixed and intentional, because earlier checks
gate later ones:

| # | Check |
|---|-------|
| 1 | Credentials |
| 2 | Write prefix access (read + write) |
| 3 | Read prefix access (read-only, one check per prefix) |
| 4 | Vector index existence |
| 5 | Vector index dimension and mode (R8, R12) |
| 6 | Embedding-model probe |
| 7 | Text-model accessibility |
| 8 | S3 object annotation availability |

Checks are never skipped or made conditional on configuration flags — every applicable check runs every
time. Two checks are no-ops when their input is absent: the read-prefix check when `READ_PREFIXES` is
empty, and the text-model check when `BEDROCK_TEXT_MODEL` is unset.

### R2 — A failing check stops startup

When any check fails, the server stops immediately, logs the error at ERROR level to stderr, and exits
with code 1, before entering the MCP event loop — checks after the failing one are not run. This holds
for the credential check too: when it fails, no further checks are run. A `CredentialError` raised by
any client during startup likewise terminates startup with its message on stderr and exit code 1.

### R3 — All checks pass: the server enters the event loop

When all checks pass, the server logs each check's success at DEBUG level, then a single INFO-level
"ready" message — `"Startup validation passed (8/8 checks). arkeology is ready."` — and proceeds to the
FastMCP event loop. Every check's log message and the success line read `/8`. This log line is the
developer's signal that AWS resources are correctly provisioned and the server is accepting requests.

**Example**

- Given all checks pass, when the server starts, then it logs
  `"Startup validation passed. arkeology is ready."` at INFO level and enters the FastMCP event loop.

## 3. Rules — The checks

### R4 — Check 1: credentials

Check 1 calls STS `GetCallerIdentity` to verify that the credentials are valid and capable of making
AWS API calls. How to implement this without an STS client interface is set out under **Check 1** in
For the developer agent.

Failure message:

`"Credential check failed: AWS credentials are invalid or expired. Re-authenticate (e.g. aws sso login --profile <profile>) and restart the server."`

Success log (DEBUG): `"Check 1/8 passed: credentials valid"`

**Example**

- Given AWS credentials are invalid, when the server starts, then it exits before entering the MCP event
  loop with the message:
  `"Credential check failed: AWS credentials are invalid or expired. Re-authenticate (e.g. aws sso login) and restart the server."`.

### R5 — Check 2: write prefix access

Check 2 verifies that the server can both read from and write to `WRITE_PREFIX` in `ARTIFACT_BUCKET`,
without creating real artifacts: it writes a small probe object under `WRITE_PREFIX`, reads it back,
and deletes it. When the server cannot write to the prefix (writing the probe raises a non-credential
error), the check fails with:

`"Write prefix access check failed for '{write_prefix}': cannot write to this prefix. Ensure the IAM policy includes s3:PutObject on arn:aws:s3:::{bucket}/{write_prefix}*."`

When the write succeeds but reading the probe back fails (`KeyError` — this should not happen with
correct IAM; if it does, both checks fail), the check fails with:

`"Write prefix access check failed for '{write_prefix}': cannot read from this prefix. Ensure the IAM policy includes s3:GetObject on arn:aws:s3:::{bucket}/{write_prefix}*."`

Success log (DEBUG): `"Check 2/8 passed: write prefix '{write_prefix}' is readable and writable"`

**Example**

- Given `WRITE_PREFIX=platform/my-service/` and that prefix is not writable, when the server starts,
  then it exits with:
  `"Write prefix access check failed for 'platform/my-service/': cannot write to this prefix. Check IAM permissions for s3:PutObject on this prefix."`.

### R6 — Check 3: read prefix access

For each entry in the read prefixes, check 3 verifies read-only access by listing objects under the
prefix: a successful listing — even an empty one — confirms the prefix is readable; a permission error
confirms it is not. The check runs once per prefix. If multiple prefixes fail, only the first failure is
reported, to avoid a wall of errors on badly misconfigured deployments — the developer can fix one at a
time. A failing prefix fails the check with:

`"Read prefix access check failed for '{read_prefix}': cannot list objects. Ensure the IAM policy includes s3:ListBucket with condition StringLike s3:prefix '{read_prefix}*'."`

When no read prefixes are configured, the check is skipped and logs at DEBUG:
`"Check 3/8 skipped: no foreign read prefixes configured"`.

Success log (DEBUG): `"Check 3/8 passed: {n} foreign read prefix(es) accessible"`

**Example**

- Given `READ_PREFIXES=network/` and that prefix is not readable, when the server starts, then it exits
  with a message identifying `network/` as the inaccessible foreign read prefix.

### R7 — Check 4: vector index existence

Check 4 verifies that the S3 Vectors index exists and is reachable, by calling `describe_index` on the
`VectorsClientInterface`. When the index does not exist, the check fails with:

`"Vector index check failed: index '{index_name}' does not exist in bucket '{vectors_bucket}'. Create it with the correct dimension for model '{model_id}' before starting the server."`

Success log (DEBUG): `"Check 4/8 passed: vector index '{index_name}' found with dimension {dim}"`

**Example**

- Given `VECTORS_INDEX=nonexistent-index`, when the server starts, then it exits with:
  `"Vector index check failed: index 'nonexistent-index' does not exist in bucket '...'. Create it with the correct dimension before starting the server."`.

### R8 — Check 5: embedding model dimension vs. index dimension

Check 5 compares the vector dimension reported by the index against the output dimension of the
configured embedding model. A mismatch is a hard failure: it means all future embedding calls will
produce vectors of the wrong dimension — the index is silently corrupted. For a known model, the
model's registered output dimension is used and no Bedrock call is made at startup; when the model is
unknown, the check falls back to a probe embedding to determine the output dimension, logging at DEBUG:
`"Model '{model_id}' not in known dimension registry; probing via embedding call."`. A mismatch fails the
check with:

`"Embedding model dimension mismatch: model '{model_id}' produces {model_dim}-dimensional vectors but index '{index_name}' expects {index_dim} dimensions. Either recreate the index with dimension {model_dim}, or set BEDROCK_EMBEDDING_MODEL to a model that produces {index_dim}-dimensional vectors."`

Success log (DEBUG):
`"Check 5/8 passed: model '{model_id}' dimension {model_dim} matches index dimension {index_dim}"`

**Example**

- Given the vector index exists with 1024 dimensions but the configured model produces 512-dimensional
  vectors, when the server starts, then it exits with:
  `"Embedding model dimension mismatch: model 'X' produces 512-dimensional vectors but the index 'Y' expects 1024 dimensions. Recreate the index with dimension 512 or restore the original model."`.

### R9 — Check 6: embedding-model probe

Check 6 embeds a short probe string via `bedrock.embed` and asserts that the returned vector's
dimension matches, reusing the existing credential-error classification for entitlement and credential
failures.

**Why:** check 5 (`_check_model_dimension`) only ever compares two *configured* numbers (`BEDROCK_EMBEDDING_DIMENSIONS` vs. the
index dimension reported by `describe_index`) and never calls Bedrock — so without this check, a wrong
or unentitled embedding model passes every startup check and fails only on the first real write or
search.

### R10 — Check 7: text-model accessibility

Check 7 verifies that `BEDROCK_TEXT_MODEL` is reachable via an `invoke_text_model` probe; it is skipped
when the variable is unset. Its full specification lives in `p9-t30-write-artifacts.md`.

Source: p9-t30-write-artifacts

### R11 — Check 8: S3 object annotation availability

Check 8 writes a throwaway probe object into `WRITE_PREFIX` and round-trips one annotation through the
three annotation operations the server performs (`PutObjectAnnotation`, `GetObjectAnnotation`,
`DeleteObjectAnnotation`), so a policy granting only some of the three fails here rather than at
first use. It makes no list call and so asks for no `ListObjectAnnotations` permission, which the
server never uses.
The probe object is deleted unconditionally, including when the probe itself failed. It runs last
deliberately: it writes into `WRITE_PREFIX`, which check 2 has already proved readable and writable.

It is a hard gate rather than a warning, because annotations are the sole source of truth for the
`commit_refs` and `references` link fields: a region or bucket type without annotation support is an
unsupported deployment rather than a degraded one.

Source: FR-57, adr-2026-07-03-annotation-backed-link-storage (its `## Revision — 2026-09-05` section, which reverses its decision 5)

### R12 — Check 5 also requires the vector index to run in `ENHANCED` mode

Once check 5's dimension comparison has passed, it reads `indexMode` from the same index attributes
check 4 read with `GetIndex`, making no further call. When the mode is anything but `ENHANCED` —
`CLASSIC`, or absent from the response — the check fails with `StartupValidationError` whose `check`
is `vector_index_mode` and whose message is:

`"Vector index '{index_name}' runs in index mode '{mode}'; arkeology requires ENHANCED, which applies metadata filters before the vector search. Switch it in place, with no re-ingestion: aws s3vectors update-index-mode --vector-bucket-name {vectors_bucket} --index-name {index_name} --index-mode ENHANCED"`

where `{mode}` is the reported mode, or `unknown` when none is reported.

Success log (DEBUG): `"Check 5/8 passed: vector index '{index_name}' index mode is ENHANCED"`, after
R8's dimension line.

**Why (Scoped searches find what their filters match only on an `ENHANCED` index):** Every scoped
search, synthesis preparation, and the store-shape check that follows check 8 is a `QueryVectors`
call carrying a metadata filter over the index every team shares. On a `CLASSIC` index the filter is
applied together with the similarity search, and measured on real AWS on 2026-11-12, filtered
queries there lost vectors even for artifacts of 10 or fewer vectors — 16 of 21 came back
incomplete, one with 1 of its 3 — where `ENHANCED` returned every one of them. A scoped search would
then miss own-scope matches, and the store-shape check could pass an unmigrated scope. The server
keeps no degraded path for a `CLASSIC` index: it requires the supported deployment and refuses to
start otherwise (NFR-03). Finding one artifact's vectors does not depend on the mode — it reads them
by key (`p15-t92-numbered-vector-keys.md`). A vector bucket created on or after 30 September 2026
creates `ENHANCED` indexes; an older one is switched once by the Admin.

**Example**

- Given a vector index whose `GetIndex` reports `indexMode` `CLASSIC`, when the server starts, then it
  exits before serving requests with the message above, naming the bucket and index, and checks 6–8
  do not run.
- Given a vector index whose `GetIndex` response carries no `indexMode`, when the server starts, then
  it exits the same way with `'unknown'` as the mode.
- Given an `ENHANCED` index of the configured dimension, when the server starts, then check 5 passes
  and check 6 runs.

Source: NFR-03; adr-2026-05-29-aws-backend-selection; the calibration of 2026-11-12 (`.docs/review-fixes/calibration-2026-11-12.md`)

## 4. Boundaries

**Always:**
- Startup validation uses the client interfaces — never direct boto3 calls.
- The validation sequence is a standalone function in `startup.py` that accepts `Settings` + client
  instances as arguments — it must be fully testable with fakes.
- Each check raises a distinct `StartupValidationError` subclass (or a `StartupValidationError` with a
  distinct `check` field value) — the caller can identify which check failed.

**Ask First:**
- Nothing — all constraints are defined.

**Never:**
- Do not catch `StartupValidationError` inside `startup.py` — it propagates to `__main__.py` which
  handles the exit.
- Do not run startup validation in a background task or defer it — it must complete synchronously
  before the server loop starts.
- Do not skip checks or make them conditional on configuration flags — every applicable check runs
  every time. (Two checks are no-ops when their input is absent: the read-prefix check when
  `READ_PREFIXES` is empty, and the text-model check when `BEDROCK_TEXT_MODEL` is unset.)

## 5. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `src/arkeology/startup.py` | Create | `validate_startup(settings, s3, vectors, bedrock)` function |
| `src/arkeology/__main__.py` | Modify | Call `validate_startup(...)` between Settings construction and `server.run()` |
| `src/arkeology/errors.py` | Modify | `StartupValidationError` already declared in T3; verify it has the needed fields |
| `tests/unit/test_startup.py` | Create | All five failure paths + the all-pass path, using fakes |
| `tests/unit/test_startup.py` | Modify (R12, written first) | The two index-mode rows in the test table; existing check-5 fixtures gain `indexMode="ENHANCED"` so they keep passing |
| `src/arkeology/startup.py` | Modify (R12) | `_check_model_dimension` (check 5) adds the index-mode test after the dimension comparison, reusing check 4's `describe_index` result |
| `tests/unit/test_startup.py` | Modify (R11, written first) | Check 8's per-action denial cases cover put, get and delete; drop the `list_object_annotations` case and the `s3:ListObjectAnnotations` expectation |
| `src/arkeology/startup.py` | Modify (R11) | `_check_annotations` (check 8) drops its `list_object_annotations` call; its failure message, the module docstring and the success log name the three annotation actions |

#### `startup.py` — Validation Sequence

**Function signature:**

```
validate_startup(
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface,
) -> None
```

Returns `None` on success. Raises `StartupValidationError` on any failure. Never catches exceptions from
the clients except to wrap them — it does not swallow failures.

**Check 1 — credentials, without an STS client interface.** The credential check is the one check that
does not use S3, S3 Vectors, or Bedrock. The options are:
1. Add `verify_credentials()` to one of the existing interfaces (least clean).
2. Add a fourth interface `STSClientInterface` with a single `get_caller_identity()` method, a
   concrete `STSClientImpl`, and a `FakeSTSClient` (cleanest).
3. Fold the credential check into `S3ClientInterface` as a `head_bucket()` call on `ARTIFACT_BUCKET` —
   this checks both credentials and bucket access in one shot, effectively merging checks 1 and 2a.

Recommended approach: option 3. The `head_bucket()` call on `ARTIFACT_BUCKET` verifies that
credentials are valid (otherwise it raises `CredentialError`) and that the S3 bucket exists and is
accessible. This merges what would otherwise be two separate AWS calls into one and avoids adding a
fourth client. Document this as the implementation choice.

If option 3 is chosen, the credential check becomes `s3.head_bucket(settings.artifact_bucket)`. A
`CredentialError` from this call is re-raised as `StartupValidationError(check="credentials", ...)`. A
non-credential S3 error (e.g. the bucket does not exist) is a different failure and is reported under
the bucket access check.

**Check 2 — write prefix, via a sentinel object:**
1. Write a small probe object to a well-known key under `WRITE_PREFIX`:
   `{WRITE_PREFIX}_arkeology_probe/write-check`.
2. Read it back via `get_object` to verify read access.
3. Delete it via `delete_object`.

`delete_object` is on `S3ClientInterface` and implemented in `S3ClientImpl` (see
`src/arkeology/clients/s3.py`, `src/arkeology/clients/interfaces.py`); S3 is mocked via moto in unit
tests rather than a hand-rolled fake, so no separate fake implementation exists. The probe object is
cheap and easily identifiable.

**Why:** `delete_object` is needed for the archive tool in Phase 3 anyway.

The probe key must be deterministic and clearly named so it does not pollute the artifact namespace:
`{write_prefix}_arkeology_startup_probe` (the leading underscore in the filename distinguishes it from
real artifact keys, which start with a type segment).

**Check 3 — read prefixes.** For each entry in `settings.read_prefixes_list`, call
`list_objects(prefix=read_prefix)`. If `read_prefixes_list` is empty, skip the check (R6).

**Check 4 — vector index existence.** `VectorsClientImpl.describe_index()` raises
`VectorIndexNotFoundError` (a new type in `errors.py`) when the index does not exist; `startup.py`
catches this specific exception type and converts it to a `StartupValidationError`. Rather than
relying on a single error code, `vectors.py` defensively matches a set of known codes
(`NoSuchIndex`, `IndexNotFoundException`, `ResourceNotFoundException`, `NoSuchResource`,
`NotFoundException`) in `_is_index_not_found()` before raising `VectorIndexNotFoundError`.

**Check 5 — model dimension.**

*Strategy A — static registry (preferred for known models).* Maintain a small dict in `config.py` or
`startup.py` that maps known model IDs to their default output dimensions:

```
KNOWN_MODEL_DIMENSIONS = {
    "amazon.titan-embed-text-v2:0": 1024,
}
```

If the configured model ID is in the registry, use the registered dimension. No Bedrock call needed at
startup.

*Strategy B — probe call (fallback for unknown models).* If the model ID is not in the registry, call
`bedrock.embed(text="probe", model_id=model_id)` and measure `len(result)` to determine the output
dimension, logging the R8 DEBUG line.

Implementation logic:
1. Get `index_dimension` from the `describe_index()` result (from Check 4 — reuse the result, do not
   call `describe_index` twice).
2. Determine `model_dimension` via strategy A first, falling back to strategy B.
3. If `index_dimension != model_dimension`: raise
   `StartupValidationError(check="vector_index_dimension", ...)`.
4. If the same result's `indexMode` is not `"ENHANCED"` (including when the key is absent): raise
   `StartupValidationError(check="vector_index_mode", ...)` with R12's message. The `indexMode` key
   reaches the result only if the installed `botocore` model for `s3vectors` declares it — see
   `p1-t3-aws-client-layer.md`'s Files to Touch.

**Check 6 — embedding-model probe.** Implemented as `_check_embedding_probe` in
`src/arkeology/startup.py`.

#### `__main__.py` integration

After constructing `Settings` and before calling `server.run(settings)`:

1. Construct the three client instances using `Settings` values:
   ```
   s3 = S3ClientImpl(region=settings.aws_region, profile=settings.aws_profile, bucket=settings.artifact_bucket)
   vectors = VectorsClientImpl(region=settings.aws_region, profile=settings.aws_profile, bucket=settings.vectors_bucket, index=settings.vectors_index)
   bedrock = BedrockClientImpl(region=settings.aws_region, profile=settings.aws_profile)
   ```
2. Call `validate_startup(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)`.
3. If `StartupValidationError` is raised, print its `message` to stderr and exit with code 1.
4. If `CredentialError` is raised (from any client during startup), print its `message` to stderr and
   exit with code 1.
5. If no error: proceed to `server.run(settings)`.

Pass the constructed client instances into `server.run()` so the server can inject them into tools
(Phase 2+). The clients are not recreated inside the server.

### Contracts

None.

### Testing Approach

`startup.py` is pure orchestration logic — it calls the client interfaces and raises typed errors. The
fakes from T3 make every failure path simulatable without AWS. This is straightforward TDD.

**Ordering rule:** `startup.py` must not exist before `test_startup.py` is written and fails.

1. **Write `tests/unit/test_startup.py` in full (Red).** Write all test cases from the table below.
   Import `validate_startup` from `arkeology.startup` — which does not exist yet. Run
   `uv run pytest tests/unit/test_startup.py` — every test fails with `ImportError`. This is the Red
   state. ✓
2. **Write `startup.py` (Green).** Implement `validate_startup`. Run
   `uv run pytest tests/unit/test_startup.py` after each check is implemented. Work through the checks
   in order (1 → 5). Do not implement all five at once — let failing tests guide you. ✓
3. **Wire into `__main__.py` (also test-first).** Before updating `__main__.py`, write a test that calls
   `main()` with a fake that triggers a credential failure and asserts the process would exit with
   code 1. Then implement the `validate_startup` call in `__main__.py`. ✓
4. **Refactor.** Review error messages — are they actionable? Is the check ordering enforced (no check
   N+1 runs after check N fails)? Run the full test suite. ✓

Tests use the fakes from T3. `test_startup.py` constructs a `Settings` instance using test env vars (via
monkeypatch) and injects fake clients.

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
| Check 5 fails (index mode `CLASSIC`) — R12 | `describe_index` result carries `indexMode="CLASSIC"`, dimension matching | `StartupValidationError(check="vector_index_mode")`; message names bucket, index and the `update-index-mode` command; checks 6–8 not reached |
| Check 5 fails (index mode absent) — R12 | `describe_index` result carries no `indexMode` | `StartupValidationError(check="vector_index_mode")` with `'unknown'` as the mode |
| Credential error mid-startup (check 3) | `fake_s3.set_credential_failure(True)` after check 2 passes | `CredentialError` propagates — startup terminates |

**Verify via test that no check after the failing one is executed.** Track calls using a simple counter
or spy on the fake methods — the method for check N+1 must not be called after check N raises.

### Hand-offs

- **PM and tech-writer:** `requirements.md` (FR-07) and `SERVER-REFERENCE.md` check-count references
  still say five/six and need a corresponding update — flagged to the PM and tech-writer in the
  2026-07-05 note (out of scope for this spec, which documents code-adjacent drift only).
