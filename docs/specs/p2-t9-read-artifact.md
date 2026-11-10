---
type: Spec
id: p2-t9-read-artifact
title: T9 — Read Artifact Tool
description: Feature spec for the read_artifact MCP tool that fetches full artifact content by identifier with cross-scope gate enforcement blocking foreign-scope tier 2 and hidden artifacts.
tags: []
status: stable
okf_version: "0.2"
generated:
  by: "axians-architect/unknown"
  at: 2026-05-30T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-10T06:08:45Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
---

# T9 — Read Artifact Tool

> **Forward-pointer note (2026-07-03, ADR-011 / ADR-012).** `read_artifact` continues to surface
> `commit_refs` from **vector metadata**, and now additionally surfaces the new first-class `references`
> field (also read from vector metadata). This field addition is specced in `p12-t46`; this spec is
> not re-opened for it.
>
> **Forward-pointer note (2026-07-06, shipped in `2aa1633`).** When the requested artifact is in a
> **foreign** scope (the cross-scope gate of R4 applies), the returned `references` list additionally
> drops any entry the requesting reader could not independently read (i.e. an entry that is not
> itself a tier 3 shared artifact) — a missing or unresolvable entry is treated the same as
> not-readable and is also stripped. Own-scope reads (R3) are unaffected and continue to return
> `references` exactly as stored. This is an additional response-shaping step layered on top of the
> existing cross-scope gate, not a change to that gate. Full semantics:
> `docs/specs/p12-t46-references-field.md`'s forward-pointer note; rationale: ADR-012's "Cross-scope
> reference visibility" section.

## TL;DR

`read_artifact` is the MCP tool an agent calls with an `artifact_id` — typically one found via
`search_artifacts` — to receive the artifact's full markdown content and all its metadata. It
enforces the cross-scope gate: own-scope artifacts are always accessible, while foreign-scope
artifacts are readable only when tier 3 and shared, so a team subscribed to a foreign scope cannot
read hidden tier 2 documents simply by knowing their identifier.

## 1. Problem Statement

Search returns metadata and description — enough to decide relevance, not enough to act.
When an agent selects an artifact from search results, it needs the full content. The read
tool fetches it by identifier, enforcing the cross-scope gate: own-scope artifacts are
always accessible; foreign-scope artifacts are gated to tier 3 + shared visibility.
Without this gate, the tier model breaks — a team subscribed to a foreign scope could read
hidden tier 2 documents simply by knowing their identifier. Its four user stories — retrieving full
content by identifier, rejecting foreign-scope tier 2 artifacts, reading foreign-scope tier 3 shared
artifacts, and structured credential errors — are all priority P1.

## 2. Rules — Identifier and scope

### R1 — `artifact_id` is used exactly as given

`artifact_id` is the full S3 key (including prefix), exactly as returned by `write_artifact`. The
tool does not transform or normalise it.

### R2 — Scope is determined by prefix matching

When `read_artifact` is called, it determines the scope of the requested artifact by comparing its
`artifact_id` prefix against `settings.write_prefix` and each entry in
`settings.read_prefixes_list`, using `artifact_id.startswith(scope_prefix + "/")`. `WRITE_PREFIX`
is guaranteed non-empty (validated at startup by the config validator), so every artifact key has the form
`{write_prefix}/{artifact_id_slug}{file_extension}`, the scope check is always unambiguous, and the
empty-prefix edge case does not arise.

**Example**

- Given an `artifact_id` that is a prefix of another `artifact_id` (e.g. `dev/review` vs
  `dev/review-v2`), when scope is determined, then prefix matching uses `startswith(scope + "/")`,
  so a shorter key never accidentally matches a longer key from a different scope.

## 3. Rules — Cross-scope gate

### R3 — Own-scope artifacts are returned without a gate

When the artifact belongs to the own scope (prefix matches `settings.write_prefix`),
`read_artifact` fetches and returns it without any tier or visibility check — a tier 2 or tier 3
own-scope artifact is returned regardless of its visibility setting.

### R4 — Foreign-scope artifacts must be tier 3 and shared

When the artifact belongs to a subscribed foreign scope (prefix matches a READ_PREFIX entry),
`read_artifact` checks tier and visibility before fetching content. If tier≠3 OR
visibility≠"shared", it returns a structured access-denied error without fetching the S3 object
body. A tier 2 hidden artifact from a subscribed foreign scope must be inaccessible via
`read_artifact` even if the caller knows its exact identifier; an ADR published by the platform team
should be readable by any subscribed microservices team agent that knows its identifier.

**Example**

- Given a tier 2 artifact whose `scope` (S3 prefix) matches a READ_PREFIX entry, when
  `read_artifact` is called with its identifier, then a structured access-denied error is returned
  — content is never fetched.
- Given a tier 3 artifact with `visibility="shared"` whose scope matches a READ_PREFIX, when
  `read_artifact` is called, then the full content is returned.
- Given a tier 3 artifact with `visibility="hidden"` in a foreign scope, when `read_artifact` is
  called, then a structured access-denied error is returned.

### R5 — An artifact in no known scope is denied

When the artifact belongs to no known scope (neither own nor any READ_PREFIX), `read_artifact`
returns a structured access-denied error.

### R6 — The gate reads S3 object metadata via `head_object`, never the vector index

The cross-scope gate is evaluated using stored metadata — tier and visibility read from S3 object
metadata using `head_object`, which does not fetch the object body — not from the vector index.
`get_object` is called only after the gate passes.

**Why:** the vector index may be out of sync (partial write); S3 is the authoritative source of
truth for content and metadata.

### R7 — "Access denied" is distinguishable from "not found"

The error message must clearly distinguish "access denied" from "not found" (different message or
field), so the agent can understand why retrieval failed.

## 4. Rules — Fetch and response

### R8 — A passed gate fetches content and metadata

When the gate passes, `read_artifact` calls `s3.get_object` to fetch full content and
`s3.head_object` to fetch metadata (or combine if implementation allows), then returns both in the
response.

### R9 — Success returns the full content and all metadata fields

When `read_artifact` succeeds, it returns: `artifact_id`, `content` (full markdown string), `type`,
`team`, `project`, `tier`, `date`, `status`, `title`, `visibility`, `tags`, `author_role`,
`description`, `source_artifacts` (list of artifact IDs the artifact was synthesised from; empty
list for non-synthesis artifacts). The content is the original content, unchanged. `tags` in the
response is a list, not a comma-separated string (deserialised from the S3 metadata encoding);
`tier` is an int; `date` is a string in YYYY-MM-DD format.

**Example**

- Given an artifact written with known content and metadata, when `read_artifact` is called with
  its `artifact_id`, then the response contains the original content unchanged.

### R10 — A missing artifact returns a structured not-found error

When the S3 key does not exist, `read_artifact` returns a structured not-found error with the
`artifact_id` in the message — not a `KeyError` exception. When `head_object` raises `KeyError`
before `get_object` is called, the result is a not-found error, not an unhandled exception.

### R11 — Credential errors return a structured response

An expired token during the S3 GetObject call must not surface as a raw exception: when a `CredentialError` is
raised, `read_artifact` returns a structured error response — never a raw exception — whose message
is human-readable, not a `botocore` traceback. When `head_object` raises `CredentialError`, no
`get_object` call is made.

**Example**

- Given an S3 credential failure during `read_artifact`, when the tool returns, then the response
  contains a human-readable structured error — not a `botocore` traceback.

## 5. Boundaries

**Always:**
- The tool function receives `settings`, `s3`, `vectors` (unused but injected for consistency), and
  `bedrock` (unused) as injected dependencies.

**Ask First:**
- Nothing — all constraints are defined.

**Never:**
- Do not fetch S3 object body before the cross-scope gate passes.
- Do not use the S3 Vectors index to evaluate the cross-scope gate — the index is not the
  authoritative metadata source.
- Do not return partial content if the S3 `get_object` call is interrupted mid-stream; surface as a
  structured error.
- Do not silently downgrade a hidden foreign artifact to "not found" — the error message must
  clearly distinguish "access denied" from "not found" so the agent can understand why retrieval
  failed.

## 6. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_read.py` | Create | Written first (Red) |
| `src/arkeology/tools/read.py` | Create | Written after unit tests (Green) |
| `tests/integration/test_tools_read.py` | Create | Written before integration wiring |
| `src/arkeology/server.py` | Modify | Register `read_artifact` tool on `_app` |

### Contracts

None.

### Testing Approach

**TDD cycle A (unit):** write `test_tools_read.py` first → fail → implement `tools/read.py` → unit
tests pass.

**TDD cycle B (integration):** write integration tests first → fail → wire tool → pass.

**`test_tools_read.py` — unit tests (FakeS3Client, no vectors or bedrock calls):**

Seed the fake S3 with objects covering: own-scope tier 2, own-scope tier 3 shared, own-scope tier 3
hidden, foreign-scope tier 2, foreign-scope tier 3 shared, foreign-scope tier 3 hidden.

Happy path (R3, R4, R9):
- Own-scope tier 2 artifact returned with correct content and all metadata fields.
- Own-scope tier 3 shared artifact returned.
- Own-scope tier 3 hidden artifact returned (no gate on own scope).
- Foreign-scope tier 3 shared artifact returned.
- All metadata fields present in response: type, team, project, tier, date, status, title,
  visibility, tags, author_role, description, content.
- `tags` in response is a list, not a comma-separated string (deserialise from S3 metadata
  encoding).

Access control (R4, R5, R6, R7):
- Foreign-scope tier 2 artifact → access-denied error; `get_object` never called on fake.
- Foreign-scope tier 3 hidden → access-denied error.
- Artifact whose prefix matches no known scope → access-denied error.
- Error type distinguishes "access denied" from "not found" (different message or field).

Not found (R10):
- Non-existent `artifact_id` in own scope → not-found error (KeyError from fake S3 caught and
  wrapped).

Edge cases (R2, R10):
- `artifact_id` that is a prefix of another `artifact_id` (e.g. `dev/review` vs `dev/review-v2`):
  prefix matching uses `startswith(scope + "/")` so a shorter key never accidentally matches a
  longer key from a different scope.
- `head_object` raises `KeyError` before `get_object` is called → not-found error, not an unhandled
  exception.

Credential failure (R11):
- `head_object` raises `CredentialError` → structured error, no `get_object` call.
- `get_object` raises `CredentialError` after gate passes → structured error.

**`test_tools_read.py` — integration tests (`@pytest.mark.integration`):**

Prerequisites: run after T7 integration tests have written known artifacts.
- Write an artifact via the write tool or directly via clients; read it back by identifier; content
  matches exactly.
- All metadata fields are present and correctly typed in the response (tags is a list, tier is int,
  date is a string in YYYY-MM-DD format).
- Non-existent identifier returns a not-found error (no exception propagation).
