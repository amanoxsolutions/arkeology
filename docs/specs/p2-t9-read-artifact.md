---
type: feature-spec
feature: p2-t9-read-artifact
created: 2026-05-30
status: ready
phase: 2
task: 9
---

# T9 — Read Artifact Tool

<!-- SCOPE BLOCK — frozen after approval -->

## Problem Statement

Search returns metadata and description — enough to decide relevance, not enough to act.
When an agent selects an artifact from search results, it needs the full content. The read
tool fetches it by identifier, enforcing the cross-scope gate: own-scope artifacts are
always accessible; foreign-scope artifacts are gated to tier 3 + shared visibility.
Without this gate, the tier model breaks — a team subscribed to a foreign scope could read
confidential tier 2 documents simply by knowing their identifier.

## User Stories

### Story 1 — Agent retrieves full artifact content by identifier (P1)

After finding an artifact via `search_artifacts`, the agent passes its `artifact_id` to
`read_artifact` and receives the full markdown content along with all metadata.

**Acceptance criteria:**
- Given an artifact written with known content and metadata, when `read_artifact` is called
  with its `artifact_id`, then the response contains the original content unchanged.
- Given a valid `artifact_id`, when `read_artifact` returns, then the response includes all
  metadata fields: type, team, project, tier, date, status, title, visibility, feature_tags,
  author_role, description, and content.
- Given an `artifact_id` that does not exist in S3, when `read_artifact` is called, then
  a structured not-found error is returned — not a `KeyError` exception.

### Story 2 — Foreign-scope tier 2 artifacts are rejected (P1)

A tier 2 confidential artifact from a subscribed foreign scope must be inaccessible via
`read_artifact` even if the caller knows its exact identifier.

**Acceptance criteria:**
- Given a tier 2 artifact whose `scope` (S3 prefix) matches a READ_PREFIX entry, when
  `read_artifact` is called with its identifier, then a structured access-denied error is
  returned — content is never fetched.
- Given a tier 2 artifact in the own scope, when `read_artifact` is called, then the
  artifact is returned regardless of visibility setting.

### Story 3 — Foreign-scope tier 3 shared artifacts are accessible (P1)

An ADR published by the platform team should be readable by any subscribed microservices
team agent that knows its identifier.

**Acceptance criteria:**
- Given a tier 3 artifact with `visibility="shared"` whose scope matches a READ_PREFIX,
  when `read_artifact` is called, then the full content is returned.
- Given a tier 3 artifact with `visibility="confidential"` in a foreign scope, when
  `read_artifact` is called, then a structured access-denied error is returned.

### Story 4 — Credential errors return structured responses (P1)

An expired token during the S3 GetObject call must not surface as a raw exception.

**Acceptance criteria:**
- Given an S3 credential failure during `read_artifact`, when the tool returns, then the
  response contains a human-readable structured error — not a `botocore` traceback.

## Requirements

- WHEN `read_artifact` is called THE SYSTEM SHALL determine the scope of the requested
  artifact by comparing its `artifact_id` prefix against `settings.write_prefix` and each
  entry in `settings.read_prefixes_list`.
- WHEN the artifact belongs to the own scope (prefix matches `settings.write_prefix`) THE
  SYSTEM SHALL fetch and return it without any tier or visibility check.
- WHEN the artifact belongs to a subscribed foreign scope (prefix matches a READ_PREFIX
  entry) THE SYSTEM SHALL check tier and visibility before fetching content. If tier≠3 OR
  visibility≠"shared", THE SYSTEM SHALL return a structured access-denied error without
  fetching the S3 object body.
- WHEN the artifact belongs to no known scope (neither own nor any READ_PREFIX) THE SYSTEM
  SHALL return a structured access-denied error.
- WHEN the gate passes THE SYSTEM SHALL call `s3.get_object` to fetch full content and
  `s3.head_object` to fetch metadata (or combine if implementation allows), then return both
  in the response.
- WHEN the S3 key does not exist THE SYSTEM SHALL return a structured not-found error with
  the `artifact_id` in the message.
- WHEN a CredentialError is raised THE SYSTEM SHALL return a structured error response —
  never a raw exception.
- WHEN `read_artifact` succeeds THE SYSTEM SHALL return: `artifact_id`, `content` (full
  markdown string), `type`, `team`, `project`, `tier`, `date`, `status`, `title`,
  `visibility`, `feature_tags`, `author_role`, `description`.

## Boundaries

**Always:**
- The cross-scope gate is evaluated using stored metadata (S3 object metadata via
  `head_object`), not from the vector index. The vector index may be out of sync (partial
  write); S3 is the authoritative source of truth for content and metadata.
- Scope determination uses prefix matching: `artifact_id.startswith(scope_prefix)`. If
  `write_prefix` is empty (root), all artifacts belong to the own scope — treat empty
  prefix as matching everything.
- The gate check reads tier and visibility from S3 object metadata using `head_object`,
  which does not fetch the object body. Only call `get_object` after the gate passes.
- `artifact_id` is the full S3 key (including prefix), exactly as returned by
  `write_artifact`. The tool does not transform or normalise it.
- The tool function receives `settings`, `s3`, `vectors` (unused but injected for
  consistency), and `bedrock` (unused) as injected dependencies.

**Ask First:**
- Nothing — all constraints are defined.

**Never:**
- Do not fetch S3 object body before the cross-scope gate passes.
- Do not use the S3 Vectors index to evaluate the cross-scope gate — the index is not the
  authoritative metadata source.
- Do not return partial content if the S3 `get_object` call is interrupted mid-stream;
  surface as a structured error.
- Do not silently downgrade a confidential foreign artifact to "not found" — the error
  message must clearly distinguish "access denied" from "not found" so the agent can
  understand why retrieval failed.

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_read.py` | Create | Written first (Red) |
| `src/cairn_mcp/tools/read.py` | Create | Written after unit tests (Green) |
| `tests/integration/test_tools_read.py` | Create | Written before integration wiring |
| `src/cairn_mcp/server.py` | Modify | Register `read_artifact` tool on `_app` |

## Testing Approach

**TDD cycle A (unit):** write `test_tools_read.py` first → fail → implement `tools/read.py`
→ unit tests pass.

**TDD cycle B (integration):** write integration tests first → fail → wire tool → pass.

---

**`test_tools_read.py` — unit tests (FakeS3Client, no vectors or bedrock calls):**

Seed the fake S3 with objects covering: own-scope tier 2, own-scope tier 3 shared,
own-scope tier 3 confidential, foreign-scope tier 2, foreign-scope tier 3 shared,
foreign-scope tier 3 confidential.

Happy path:
- Own-scope tier 2 artifact returned with correct content and all metadata fields.
- Own-scope tier 3 shared artifact returned.
- Own-scope tier 3 confidential artifact returned (no gate on own scope).
- Foreign-scope tier 3 shared artifact returned.
- All metadata fields present in response: type, team, project, tier, date, status, title,
  visibility, feature_tags, author_role, description, content.
- `feature_tags` in response is a list, not a comma-separated string (deserialise from S3
  metadata encoding).

Access control:
- Foreign-scope tier 2 artifact → access-denied error; `get_object` never called on fake.
- Foreign-scope tier 3 confidential → access-denied error.
- Artifact whose prefix matches no known scope → access-denied error.
- Error type distinguishes "access denied" from "not found" (different message or field).

Not found:
- Non-existent `artifact_id` in own scope → not-found error (KeyError from fake S3 caught
  and wrapped).

Edge cases:
- Empty `write_prefix` (root deployment): all own-scope artifact IDs are accessible; a
  foreign-scope artifact with an explicit READ_PREFIX still passes the gate if tier=3+shared.
- `artifact_id` that is a prefix of another `artifact_id` (e.g. `dev/review` vs
  `dev/review-v2`): prefix matching must not accidentally grant access to a longer key
  whose scope does not match.
- `head_object` raises `KeyError` before `get_object` is called → not-found error, not an
  unhandled exception.

Credential failure:
- `head_object` raises `CredentialError` → structured error, no `get_object` call.
- `get_object` raises `CredentialError` after gate passes → structured error.

**`test_tools_read.py` — integration tests (`@pytest.mark.integration`):**

Prerequisites: run after T7 integration tests have written known artifacts.
- Write an artifact via the write tool or directly via clients; read it back by identifier;
  content matches exactly.
- All metadata fields are present and correctly typed in the response (feature_tags is a
  list, tier is int, date is a string in YYYY-MM-DD format).
- Non-existent identifier returns a not-found error (no exception propagation).

## Open Questions

- [ ] When `write_prefix` is empty (root-level deployment), scope determination becomes
  "artifact_id belongs to own scope if its prefix is empty". Clarify: does this mean ALL
  artifacts in the index are own-scope? Yes — an empty write prefix means the deployment
  owns the entire S3 bucket. This has security implications the operator should be aware of;
  document in the setup README (Phase 4), not in the tool itself.
