---
type: Spec
id: p10-t37-propose-commit-links
title: T37 — propose_commit_links Tool
description: Spec for a read-only MCP tool that discovers own-scope artifacts with no commit_refs, optionally bounded by a session-start ULID, for operator confirmation before linking.
tags: []
status: stable
okf_version: "0.2"
sources:
  - resource: docs/brainstorming/brainstorming-2026-06-06-artifact-commit-refs.md
    title: Artifact Commit References
    last_modified: 2026-07-03T00:00:00Z
  - resource: docs/specs/p10-t35-filter-range-operators.md
    title: T35 — Filter Range Operators ($gte / $lte)
    last_modified: 2026-06-06T00:00:00Z
  - resource: docs/specs/p10-t36-commit-refs-metadata-fields.md
    title: T36 — commit_refs and last_edited_ulid Metadata Fields
    last_modified: 2026-07-03T00:00:00Z
generated:
  by: "axians-analyst/unknown"
  at: 2026-06-06T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-09T17:18:17Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
---

# T37 — `propose_commit_links` Tool

## TL;DR

Add a read-only MCP tool `propose_commit_links` that discovers own-scope artifacts that
have no `commit_refs` yet, optionally bounded to those written since a given session-start
ULID. It presents the candidate list to the agent for confirmation before any write occurs —
it has no side effects. This tool is the discovery half of the post-commit linking workflow
(`link_metadata`, T49, is the write half — superseding the original T38 `link_commit`).

## 1. Problem Statement

After committing, an agent needs to know which artifacts were produced during the session
and have not yet been associated with a commit SHA. Without a discovery tool, the agent
would have to reconstruct this list manually by inspecting all artifacts — expensive and
error-prone. `propose_commit_links` provides that discovery in a single call: it returns a
ranked candidate list with human-readable timestamps so the operator can confirm, trim, or
augment the set before calling `link_metadata` (the write half — `link_commit` (T38) was
superseded by `link_metadata` (T49), ADR-011; `propose_commit_links` itself is unchanged).

All five user stories this spec covers — discover unlinked artifacts since session start;
discover all unlinked artifacts in scope (no `since_ulid`); response includes a human-readable
timestamp; own-scope only, foreign-scope artifacts excluded; and credential failure returns a
structured error — are P1.

## 2. Rules — Discovering candidates

### R1 — With `since_ulid`, only own-scope artifacts written at or after it are scanned

When `propose_commit_links` is called with `since_ulid`, the system filters the vector index to
own-scope artifacts where `last_edited_ulid >= since_ulid`. At the end of a session, the agent
calls `propose_commit_links` with `since_ulid` set to the ULID it captured at session start, so
only artifacts written during this session that have no `commit_refs` are returned.

**Example**

- Given three artifacts: A written before the session (ULID < since_ulid), B written during
  the session with no `commit_refs`, and C written during the session with
  `commit_refs=["prev"]`; when `propose_commit_links` is called with `since_ulid` set to a
  value between A's and B's ULID, then only B appears in the proposed list.

### R2 — Without `since_ulid`, all own-scope artifacts are scanned regardless of age

When `propose_commit_links` is called without `since_ulid`, the system retrieves all own-scope
artifacts from the vector index without a time-range filter. An agent runs the tool this way to
find every artifact in scope that has never been linked to a commit.

**Example**

- Given several own-scope artifacts, some with `commit_refs` and some without, when
  `propose_commit_links` is called without `since_ulid`, then all artifacts without
  `commit_refs` are returned regardless of age.

### R3 — Candidates are deduplicated by `artifact_id`, then kept only when `commit_refs` is absent or empty

When results are assembled, the system deduplicates by `artifact_id` (multiple section vectors
per artifact are common) and then filters client-side to keep only artifacts where
`commit_refs` is absent or empty. Candidate filtering (checking for empty `commit_refs`) is
client-side after `get_vectors` — no `$exists` operator is needed or added. When no artifact
qualifies, `proposed` is an empty list — not an error.

**Example**

- Given no unlinked artifacts in the time range, when `propose_commit_links` returns, then
  `proposed` is an empty list — not an error.
- Given own-scope artifacts that all have `commit_refs`, when called without `since_ulid`,
  then `proposed` is empty.

### R4 — Only own-scope artifacts are proposed; foreign-scope artifacts are excluded

Scope is own-scope only: the filter uses `{"scope": {"$eq": settings.write_prefix}}`. Foreign-scope
artifacts never appear in `proposed` — only own-scope artifacts can be commit-linked.

**Example**

- Given a foreign-scope tier-3 shared artifact that has no `commit_refs`, when
  `propose_commit_links` is called, then it does NOT appear in `proposed` — only own-scope
  artifacts can be commit-linked.

## 3. Rules — Response

### R5 — Each proposed entry carries the artifact's identity and a human-readable write time

When an artifact qualifies, the system includes in its entry: `artifact_id`, `title`, `type`,
`last_edited_ulid`, and `last_edited_at` (ISO-8601 datetime string derived from the ULID via
`python-ulid`). The operator needs to eyeball the write-time date to confirm which artifacts
belong to the current session.

**Example**

- Given an artifact with a known `last_edited_ulid`, when it appears in `proposed`, then
  the entry includes a `last_edited_at` field containing a non-empty ISO-8601 datetime
  string derived from that ULID.

### R6 — An artifact without `last_edited_ulid` is still a candidate, with null timestamps

When `last_edited_ulid` is absent from an artifact's metadata, the system includes
`last_edited_ulid: null` and `last_edited_at: null` in that artifact's entry — it is still a
candidate for linking.

### R7 — A successful call returns the proposed list and the supplied `commit_sha`

When `propose_commit_links` completes successfully, the system returns
`{"proposed": [...], "commit_sha": "<the supplied commit_sha>"}`.

### R8 — A credential failure returns a structured error

When `propose_commit_links` encounters a `CredentialError`, the system returns a structured
error — never a raw exception.

**Example**

- Given a credential failure during the vector scan, when `propose_commit_links` returns,
  then a structured error dict is returned — not a raw exception.

### R9 — `propose_commit_links` makes no writes

When `propose_commit_links` is called, the system makes no writes — it is strictly read-only.

## 4. Boundaries

**Always:**
- Scope is own-scope only: filter uses `{"scope": {"$eq": settings.write_prefix}}`.
- Candidate filtering (checking for empty `commit_refs`) is client-side after
  `get_vectors` — no `$exists` operator is needed or added.
- The tool receives `settings`, `s3`, `vectors`, and `bedrock` as injected dependencies;
  `s3` and `bedrock` are unused.
- The tool function is registered on `_app` in `server.py` via its `register_tools()`
  call.

**Ask First:**
- Nothing — all constraints are defined.

**Never:**
- Do not write to S3 or vector store — this is a read-only tool.
- Do not include foreign-scope artifacts in `proposed` — they cannot be linked by the
  caller's scope.
- Do not add a `$exists` operator to `filter.py` — client-side filtering of `commit_refs`
  absence is sufficient and simpler.

## 5. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_propose_commit_links.py` | Create | Written first (Red) |
| `src/arkeology/tools/propose_commit_links.py` | Create | Written after unit tests (Green) |
| `src/arkeology/server.py` | Modify | Register `propose_commit_links` on `_app` |

### Contracts

None.

### Testing Approach

**TDD cycle (unit):** write `test_tools_propose_commit_links.py` → fail → implement
`tools/propose_commit_links.py` → pass → register in `server.py`.

**`test_tools_propose_commit_links.py` — unit tests (moto + FakeBedrockClient):**

Use the `aws_mock`, `s3_client`, and `vectors_client_with_index` fixtures from
`tests/unit/conftest.py`. Pre-seed the vector index using `vectors.put_vectors_batch`
directly (no need to call `write_artifact`; the test controls metadata precisely).

Seed data: at least four artifacts:
- `artifact-A`: own-scope, `last_edited_ulid = ULID_LOW`, `commit_refs = []` (absent)
- `artifact-B`: own-scope, `last_edited_ulid = ULID_HIGH`, `commit_refs = []` (absent)
- `artifact-C`: own-scope, `last_edited_ulid = ULID_HIGH`, `commit_refs = ["abc123"]` (linked)
- `artifact-D`: foreign-scope, tier 3 shared, no `commit_refs`

Where `ULID_LOW < ULID_MID < ULID_HIGH` are deterministic ULID strings (hardcoded in
tests for reproducibility — generate them once from the ULID library and paste as
constants).

Test cases:
- `since_ulid = ULID_MID` → only `artifact-B` in proposed (A excluded by time, C linked, D
  foreign-scope).
- `since_ulid` absent → both `artifact-A` and `artifact-B` in proposed (C linked, D
  foreign).
- All artifacts have `commit_refs` → `proposed` is `[]`.
- Response shape: each entry has `artifact_id`, `title`, `type`, `last_edited_ulid`,
  `last_edited_at` (non-null for entries with ULID, null for entries without).
- Artifact with no `last_edited_ulid` in metadata → entry has `last_edited_ulid: null`,
  `last_edited_at: null`, still included as a candidate.
- `list_vectors_by_metadata` raises `CredentialError` → structured error response.
- `get_vectors` raises `CredentialError` → structured error response.
