---
type: spec
title: T37 — propose_commit_links Tool
description: Spec for a read-only MCP tool that discovers own-scope artifacts with no commit_refs, optionally bounded by a session-start ULID, for operator confirmation before linking.
tags: []
timestamp: 2026-06-06T00:00:00Z
okf_version: "0.1"
feature: p10-t37-propose-commit-links
status: ready
phase: 10
task: 37
references:
  - docs/contracts/modules/arkeology.tools.propose_commit_links.md
  - docs/brainstorming/brainstorming-2026-06-06-artifact-commit-refs.md
  - docs/specs/p10-t35-filter-range-operators.md
  - docs/specs/p10-t36-commit-refs-metadata-fields.md
authored:
  by: "analyst"
  date: "2026-06-06"
revised:
  by: "tech-writer"
  date: "2026-07-04"
---

# T37 — `propose_commit_links` Tool

<!-- SCOPE BLOCK — frozen after approval -->

## TL;DR

Add a read-only MCP tool `propose_commit_links` that discovers own-scope artifacts that
have no `commit_refs` yet, optionally bounded to those written since a given session-start
ULID. It presents the candidate list to the agent for confirmation before any write occurs —
it has no side effects. This tool is the discovery half of the post-commit linking workflow
(`link_metadata`, T49, is the write half — superseding the original T38 `link_commit`).

## Problem Statement

After committing, an agent needs to know which artifacts were produced during the session
and have not yet been associated with a commit SHA. Without a discovery tool, the agent
would have to reconstruct this list manually by inspecting all artifacts — expensive and
error-prone. `propose_commit_links` provides that discovery in a single call: it returns a
ranked candidate list with human-readable timestamps so the operator can confirm, trim, or
augment the set before calling `link_metadata` (the write half — `link_commit` (T38) was
superseded by `link_metadata` (T49), ADR-011; `propose_commit_links` itself is unchanged).

## User Stories

### Story 1 — Discover unlinked artifacts since session start (P1)

At the end of a session, the agent calls `propose_commit_links` with `since_ulid` set to
the ULID it captured at session start. Only artifacts written during this session that have
no `commit_refs` are returned.

**Acceptance criteria:**
- Given three artifacts: A written before the session (ULID < since_ulid), B written during
  the session with no `commit_refs`, and C written during the session with
  `commit_refs=["prev"]`; when `propose_commit_links` is called with `since_ulid` set to a
  value between A's and B's ULID, then only B appears in the proposed list.
- Given no unlinked artifacts in the time range, when `propose_commit_links` returns, then
  `proposed` is an empty list — not an error.

### Story 2 — Discover all unlinked artifacts in scope (no since_ulid) (P1)

An agent runs the tool without `since_ulid` to find every artifact in scope that has never
been linked to a commit.

**Acceptance criteria:**
- Given several own-scope artifacts, some with `commit_refs` and some without, when
  `propose_commit_links` is called without `since_ulid`, then all artifacts without
  `commit_refs` are returned regardless of age.
- Given own-scope artifacts that all have `commit_refs`, when called without `since_ulid`,
  then `proposed` is empty.

### Story 3 — Response includes human-readable timestamp (P1)

The operator needs to eyeball the write-time date to confirm which artifacts belong to the
current session.

**Acceptance criteria:**
- Given an artifact with a known `last_edited_ulid`, when it appears in `proposed`, then
  the entry includes a `last_edited_at` field containing a non-empty ISO-8601 datetime
  string derived from that ULID.

### Story 4 — Own-scope only; foreign-scope artifacts excluded (P1)

**Acceptance criteria:**
- Given a foreign-scope tier-3 shared artifact that has no `commit_refs`, when
  `propose_commit_links` is called, then it does NOT appear in `proposed` — only own-scope
  artifacts can be commit-linked.

### Story 5 — Credential failure returns structured error (P1)

**Acceptance criteria:**
- Given a credential failure during the vector scan, when `propose_commit_links` returns,
  then a structured error dict is returned — not a raw exception.

## Requirements

- WHEN `propose_commit_links` is called with `since_ulid` THE SYSTEM SHALL filter the
  vector index to own-scope artifacts where `last_edited_ulid >= since_ulid`.
- WHEN `propose_commit_links` is called without `since_ulid` THE SYSTEM SHALL retrieve all
  own-scope artifacts from the vector index without a time-range filter.
- WHEN results are assembled THE SYSTEM SHALL deduplicate by `artifact_id` (multiple
  section vectors per artifact are common) and then filter client-side to keep only
  artifacts where `commit_refs` is absent or empty.
- WHEN an artifact qualifies THE SYSTEM SHALL include in its entry: `artifact_id`, `title`,
  `type`, `last_edited_ulid`, and `last_edited_at` (ISO-8601 datetime string derived from
  the ULID via `python-ulid`).
- WHEN `last_edited_ulid` is absent from an artifact's metadata THE SYSTEM SHALL include
  `last_edited_ulid: null` and `last_edited_at: null` in that artifact's entry — it is
  still a candidate for linking.
- WHEN `propose_commit_links` completes successfully THE SYSTEM SHALL return
  `{"proposed": [...], "commit_sha": "<the supplied commit_sha>"}`.
- WHEN `propose_commit_links` encounters a CredentialError THE SYSTEM SHALL return a
  structured error — never a raw exception.
- WHEN `propose_commit_links` is called THE SYSTEM SHALL make no writes — it is strictly
  read-only.

## Boundaries

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

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_propose_commit_links.py` | Create | Written first (Red) |
| `src/arkeology/tools/propose_commit_links.py` | Create | Written after unit tests (Green) |
| `src/arkeology/server.py` | Modify | Register `propose_commit_links` on `_app` |

## Testing Approach

**TDD cycle (unit):** write `test_tools_propose_commit_links.py` → fail → implement
`tools/propose_commit_links.py` → pass → register in `server.py`.

---

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

## Open Questions

*(none — all constraints are defined)*
