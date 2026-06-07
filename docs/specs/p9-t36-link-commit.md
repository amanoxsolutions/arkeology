---
type: feature-spec
feature: p9-t36-link-commit
status: ready
phase: 9
task: 36
references:
  - docs/brainstorming/brainstorming-2026-06-06-artifact-commit-refs.md
  - docs/specs/p9-t34-commit-refs-metadata-fields.md
  - docs/specs/p9-t35-propose-commit-links.md
authored:
  by: "analyst"
  date: "2026-06-06"
revised:
  by: ""
  date: ""
---

# T26 — `link_commit` Tool and AGENTS.md Post-Commit Protocol

<!-- SCOPE BLOCK — frozen after approval -->

## TL;DR

Add a write MCP tool `link_commit` that appends a commit SHA to the `commit_refs` vector
metadata of confirmed own-scope artifacts without re-embedding them. It returns a fresh ULID
cursor (`next_since_ulid`) so the agent advances its session-start pointer after each
commit. The spec also covers the AGENTS.md post-commit protocol snippet that the cairn
installation skill must include in every project it configures.

## Problem Statement

`propose_commit_links` (T25) discovers candidates; `link_commit` performs the actual
association. It must update vector metadata for all section vectors of each artifact while
reusing their existing float32 embeddings — no Bedrock call, no S3 write. The cursor
mechanism (`next_since_ulid`) eliminates the need for the agent to independently generate
ULIDs after the initial session-start capture. Without this tool, the post-commit protocol
has no way to persist commit associations to the vector index.

## User Stories

### Story 1 — Agent links confirmed artifacts to a commit SHA (P1)

After the operator confirms the proposed list, the agent calls `link_commit`.

**Acceptance criteria:**
- Given an artifact with no `commit_refs`, when `link_commit` is called with
  `artifact_ids=[artifact.id]` and `commit_sha="abc1234"`, then `commit_refs` in its
  vector metadata becomes `["abc1234"]`.
- Given an artifact already linked to `["prev123"]`, when `link_commit` is called with
  `commit_sha="abc1234"`, then `commit_refs` becomes `["prev123", "abc1234"]` (append, no
  duplicate).
- Given the same commit SHA already in `commit_refs`, when `link_commit` is called again
  with the same SHA, then `commit_refs` is unchanged (deduplicate).

### Story 2 — Linking uses existing embeddings (no re-embed) (P1)

**Acceptance criteria:**
- Given a successful `link_commit` call, the Bedrock `embed` method is never called.
- The `put_vectors_batch` call uses the float32 vectors retrieved from `get_vectors` — the
  same embedding values, unchanged.

### Story 3 — Response includes cursor for next call (P1)

**Acceptance criteria:**
- Given a successful `link_commit` call, the response includes `next_since_ulid` — a
  non-empty ULID string.
- Given two successive `link_commit` calls, the second `next_since_ulid` is
  lexicographically greater than or equal to the first.

### Story 4 — Out-of-scope or missing artifacts are skipped, not fatal (P1)

**Acceptance criteria:**
- Given an `artifact_ids` list containing one valid own-scope artifact and one foreign-scope
  artifact ID, when `link_commit` returns, then `linked: 1`, `skipped: 1`, and the valid
  artifact is updated.
- Given an `artifact_id` for which no vectors exist in the index, when `link_commit`
  returns, then `skipped` count is incremented — no error.

### Story 5 — Credential failure returns structured error (P1)

**Acceptance criteria:**
- Given a credential failure during `list_vectors_by_metadata`, when `link_commit` returns,
  then a structured error is returned — not a raw exception.

## Requirements

- WHEN `link_commit` is called THE SYSTEM SHALL process each `artifact_id` independently;
  failure to find vectors for one artifact SHALL increment `skipped` without aborting
  processing of remaining artifacts.
- WHEN an `artifact_id` does not start with `settings.write_prefix + "/"` THE SYSTEM SHALL
  skip it and increment `skipped` — foreign-scope artifacts cannot be linked by the caller.
- WHEN processing an `artifact_id` THE SYSTEM SHALL call
  `list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}})` to retrieve all
  section vector keys for that artifact.
- WHEN vector keys are found THE SYSTEM SHALL call `get_vectors(keys)` to retrieve both the
  current metadata and the float32 embedding data.
- WHEN updating metadata THE SYSTEM SHALL merge `commit_sha` into the existing
  `commit_refs` list (append + deduplicate) and call `put_vectors_batch` with the same
  float32 vectors from `get_vectors` and the updated metadata — no Bedrock call.
- WHEN `link_commit` completes successfully THE SYSTEM SHALL return:
  `{"linked": int, "skipped": int, "commit_sha": str, "next_since_ulid": str}`.
- WHEN generating `next_since_ulid` THE SYSTEM SHALL generate a fresh ULID via
  `python-ulid` after all artifacts have been processed.
- WHEN a CredentialError is raised during any AWS call THE SYSTEM SHALL return a structured
  error — never a raw exception.

## Boundaries

**Always:**
- Scope gate uses `artifact_id.startswith(settings.write_prefix + "/")` — never bare
  `startswith(write_prefix)`.
- No Bedrock call. Float32 embedding data is taken from `get_vectors` result (`item["data"]["float32"]`).
- Vector metadata only — no S3 object metadata update in V1. The known limitation
  (reconcile drops commit_refs) must be documented in the module docstring.
- `commit_refs` merging: `list(dict.fromkeys(existing + [commit_sha]))` — preserves order
  and deduplicates.
- `next_since_ulid` is generated once after the processing loop, not per artifact.
- The tool receives `settings`, `s3`, `vectors`, and `bedrock` as injected dependencies;
  `s3` and `bedrock` are unused.

**Ask First:**
- Nothing — all constraints are defined.

**Never:**
- Do not call Bedrock `embed` — embeddings are reused from `get_vectors`.
- Do not write to S3 (V1 limitation — `copy_object` deferred to a future milestone).
- Do not abort the entire operation if one artifact's vector lookup fails — skip and
  continue.
- Do not include foreign-scope artifacts in `linked` — they must be rejected at the scope
  gate.

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_link_commit.py` | Create | Written first (Red) |
| `src/cairn_mcp/tools/link_commit.py` | Create | Written after unit tests (Green) |
| `src/cairn_mcp/server.py` | Modify | Register `link_commit` on `_app` |

## Testing Approach

**TDD cycle (unit):** write `test_tools_link_commit.py` → fail → implement
`tools/link_commit.py` → pass → register in `server.py`.

---

**`test_tools_link_commit.py` — unit tests (moto + FakeBedrockClient):**

Use the `aws_mock`, `s3_client`, and `vectors_client_with_index` fixtures from
`tests/unit/conftest.py`. Pre-seed the vector index with `put_vectors_batch` directly; use
`FakeBedrockClient` embeddings (or arbitrary deterministic float lists) as the stored
vectors.

Seed data:
- `artifact-own-A`: own-scope, two section vectors, no `commit_refs` in metadata.
- `artifact-own-B`: own-scope, one document vector, `commit_refs=["prev123"]` in metadata.
- `artifact-foreign`: foreign-scope, one vector, no `commit_refs`.

Test cases:

Linking:
- Call `link_commit(artifact_ids=["artifact-own-A"], commit_sha="abc1234")` → response has
  `linked=1`, `skipped=0`; after the call, `get_vectors` on `artifact-own-A`'s keys shows
  `commit_refs=["abc1234"]` on every section vector.
- Both section vectors of `artifact-own-A` carry the updated `commit_refs` (not just the
  first one).
- Float32 embedding values on all vectors are unchanged after the call (verify by comparing
  before/after `get_vectors`).
- Bedrock `embed` is never called (use `mocker.spy(bedrock, "embed")` and assert
  `call_count == 0`).

Append and deduplicate:
- Call `link_commit(artifact_ids=["artifact-own-B"], commit_sha="abc1234")` → response has
  `linked=1`; after the call, `commit_refs=["prev123", "abc1234"]`.
- Call `link_commit(artifact_ids=["artifact-own-B"], commit_sha="prev123")` (same SHA
  already stored) → `commit_refs` remains `["prev123"]` (no duplicate).

Scope gate:
- Call with `artifact_ids=["artifact-foreign"]` → `linked=0`, `skipped=1`.
- Mixed list `["artifact-own-A", "artifact-foreign"]` → `linked=1`, `skipped=1`.

Missing artifact:
- Call with `artifact_ids=["nonexistent-key"]` → `linked=0`, `skipped=1`.

Cursor:
- Response includes `next_since_ulid` (non-empty string).
- Two successive calls → second `next_since_ulid >= first` (lexicographic comparison).

Error handling:
- `list_vectors_by_metadata` raises `CredentialError` → structured error response.
- `get_vectors` raises `CredentialError` → structured error response.
- `put_vectors_batch` raises `CredentialError` → structured error response.

---

**AGENTS.md post-commit protocol note:**

After `link_commit` is implemented and passing, add the following section to the cairn
installation skill's AGENTS.md snippet. This snippet is written once by the installation
skill into the project's `AGENTS.md` (or the cairn-mcp project's own `AGENTS.md` if this
is the cairn-mcp project itself). The exact location within AGENTS.md is at the agent's
discretion — after the cairn server configuration block is appropriate.

```markdown
## Post-Commit Protocol (cairn-mcp)

**At session start:**
Capture the session ULID once and carry it in context for the entire session:
`python -c "from ulid import ULID; print(ULID())"`
Store this value as `since_ulid`.

**After every `git commit` during a session:**
1. Capture the commit SHA: `git rev-parse HEAD`
2. Call `propose_commit_links(commit_sha=<sha>, since_ulid=<since_ulid>)`
   — omit `since_ulid` if this is the very first commit of a brand-new project.
3. Present the proposed list to the operator. They may confirm, remove, or add artifact IDs.
4. If the operator confirms: call `link_commit(artifact_ids=[...], commit_sha=<sha>)`
5. Replace `since_ulid` with the `next_since_ulid` value returned by `link_commit`.
6. Skip silently if `propose_commit_links` returns an empty `proposed` list.

**Known limitation:** `reconcile_index` rebuilds vector metadata from S3 only. Because
`commit_refs` is stored in vector metadata only (V1), a reconcile run will drop all commit
links. Re-run the post-commit protocol after any reconcile to restore them.
```

This snippet must be placed in the cairn installation skill (the skill that writes AGENTS.md
into a user's project) — it is not part of the cairn-mcp server's own `AGENTS.md`.

## Open Questions

*(none — all constraints are defined)*
