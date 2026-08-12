---
type: adr
title: Artifact Commit Traceability — ULID Timestamps, Vector-Only Commit Links, and Agent-Driven Protocol
description: "Records the three coupled design decisions that close the artifact-to-commit traceability gap: ULID as the write-time timestamp, vector-metadata-only commit reference storage, and an agent-driven AGENTS.md post-commit protocol."
tags: []
timestamp: 2026-06-16T00:00:00Z
okf_version: "0.1"
status: Partially superseded by adr-2026-07-03-annotation-backed-link-storage.md
references:
  - docs/brainstorming/brainstorming-2026-06-06-artifact-commit-refs.md
  - docs/specs/p10-t36-commit-refs-metadata-fields.md
  - docs/specs/p10-t37-propose-commit-links.md
  - docs/specs/p10-t38-link-commit.md
  - docs/architecture-decisions/adr-2026-07-03-annotation-backed-link-storage.md
authored:
  by: architect
  date: "2026-06-16"
revised:
  by: architect
  date: "2026-07-03"
---

# Artifact Commit Traceability — ULID Timestamps, Vector-Only Commit Links, and Agent-Driven Protocol

## Description

Artifacts written to Arkeology — code reviews, implementation notes, ADRs, session summaries —
describe work tied to a specific git commit, but the commit SHA does not exist yet when the agent
writes them. This ADR records the three coupled design decisions that close that traceability gap:
using ULID as the write-time timestamp to enable session-scoped discovery, storing commit
references in vector metadata only (V1), and choosing an agent-driven AGENTS.md protocol as the
V1 trigger mechanism.

## Status

Superseded by [adr-2026-07-03-annotation-backed-link-storage.md](adr-2026-07-03-annotation-backed-link-storage.md).

**Only the "Vector-only `commit_refs` storage (V1)" decision is superseded** — along with its
consequence that `reconcile_index` drops commit links. The durable store for the mutable link
fields (`commit_refs`, and the new `references`) moves to S3 object annotations, dual-written with
vector metadata; `link_commit` is generalized into `link_metadata`. The other two decisions in this
ADR remain **in force and unchanged**: the **ULID `last_edited_ulid`** write-time timestamp, and the
**agent-driven AGENTS.md post-commit protocol (Path 2)** as the linking trigger (which now invokes
`link_metadata`). See the superseding ADR for the full rationale.

## Context

The timing problem has two parts. First, artifacts are written mid-session, before the developer
commits — the SHA is unknown at write time. Second, the server is deployment-agnostic: it is
given resource names via environment variables and has no git context at runtime, so server-side
auto-detection of the current HEAD is not viable.

Associating artifacts with their commits after the fact requires:

1. **A way to scope discovery to the current session.** The existing metadata carried only a
   `date` field (`YYYY-MM-DD`). For a busy project with many daily writes, date alone does not
   distinguish artifacts written in the current session from those written in earlier sessions on
   the same day. A millisecond-precision write-time timestamp is needed.

2. **A way to update commit references without re-embedding.** Re-calling `write_artifact` to
   add a commit SHA would re-embed all sections — expensive and semantically unnecessary, since
   the content has not changed. The S3 Vectors API's `get_vectors` with `returnData=True` returns
   the stored float32 embedding alongside metadata, making metadata-only updates possible via
   `put_vectors_batch` with the same vectors.

3. **A trigger that fires after every commit.** Three paths were evaluated:
   - **Path 1** — Claude Code `PostToolUse` MCP hook with `if: "Bash(git commit *)"`: calls
     `propose_commit_links` then `link_commit` directly within the existing MCP session, no
     separate credentials or process. Requires the installation skill to write the hook
     configuration. Claude Code-specific — not available in OpenCode, Codex, or Copilot, which
     provide shell-command-only hooks with no `mcp_tool` equivalent.
   - **Path 2** — Agent-driven via AGENTS.md post-commit protocol: the installation skill writes
     a post-commit section to the project AGENTS.md. Because AGENTS.md is loaded at session start
     in all supported tools, the protocol is in context without any tool-specific configuration.
   - **Path 3** — Git `post-commit` hook + `arkeology link-commit` CLI: universal (any git workflow,
     any IDE), fires even without an active agent session. The critical prerequisite is a
     tool-agnostic config source for AWS credentials — MCP server environment variables are stored
     in different locations across tools (Claude Code `settings.json`, OpenCode `opencode.json`,
     Copilot `.mcp.json`), so a git hook cannot source any of them reliably without a separate
     `.arkeology/config.sh` written by the installation skill. Git hooks are also non-interactive —
     confirmation before linking is not possible; the options are auto-link or a deferred-review
     pending file, neither of which is ready without the installation skill milestone.

## Decision

**ULID as the write-time timestamp.** Every `write_artifact` call generates a `last_edited_ulid`
via `python-ulid` at the moment of writing. ULID was chosen over ISO-8601 datetime strings,
epoch milliseconds, or UUID v4 for one reason: ULID is lexicographically sortable as a plain
string. This means the existing `$gte` / `$lte` string-comparison operators added to `filter.py`
are sufficient for time-range filtering on the vector index — no dedicated timestamp type or
comparison function is needed. The same `python-ulid` library decodes a ULID to a human-readable
ISO-8601 datetime for display in `propose_commit_links` results. `last_edited_ulid` is stored
in both S3 object metadata and vector metadata; it is a server-generated field, not
caller-supplied, and is returned in `write_artifact`, `read_artifact`, and `list_artifacts`
responses.

**Vector-only `commit_refs` storage (V1).** `link_commit` reads current float32 embeddings and
metadata with `get_vectors`, merges the new SHA into `commit_refs` (append + deduplicate,
preserving order), and writes back with `put_vectors_batch` — zero Bedrock calls. Commit
references are stored in vector metadata only; S3 object metadata is not updated in V1. The
alternative — also updating S3 object metadata via `copy_object` — was rejected because it adds
a per-artifact S3 operation with its own partial-failure mode (S3 update succeeds but vector
update fails, or vice versa) for a capability that `read_artifact` does not need: it already
reads vector metadata directly to surface `commit_refs`. The accepted trade-off is that
`reconcile_index` rebuilds vector metadata from S3 object metadata only; a reconcile run
therefore drops all commit links from re-indexed artifacts. This is a known, documented V1
limitation — not a silent bug. The operator must re-run the post-commit protocol after any
reconcile to restore commit links. The mitigation for a future milestone is to also update S3
object metadata in `link_commit` via `copy_object`, so that `reconcile_index` picks up
`commit_refs` naturally.

**Agent-driven AGENTS.md post-commit protocol (Path 2) as the V1 trigger.** Path 2 was chosen
because AGENTS.md is always loaded at session start in all four supported MCP clients, and the
post-commit protocol is project-specific — Arkeology must be configured for this project for the
protocol to make sense. A separately loadable Arkeology skill would be invisible to agents that load
only `committing-code`; AGENTS.md is the correct carrier for project-specific standing
instructions. The protocol is: at session start, capture a session ULID (`python-ulid`); after
each commit, call `propose_commit_links(commit_sha=<sha>, since_ulid=<since_ulid>)` to get
unlinked session artifacts, confirm with the operator, call `link_commit`, and advance `since_ulid`
to the `next_since_ulid` returned in the response. Path 1 (Claude Code hook) and Path 3 (git
hook + CLI) are deferred to the installation skill milestone and are not blocked by any V1 design
decision.

## Alternatives Considered

### Write-time timestamp format

| Option | Pros | Cons |
|--------|------|------|
| **Chosen** — ULID (`python-ulid`) | Lexicographically sortable as a plain string — `$gte`/`$lte` string comparison is sufficient; decodes to human-readable ISO-8601; millisecond precision; collision-free | Unfamiliar to engineers who have not worked with ULIDs; requires `python-ulid` dependency |
| ISO-8601 datetime string | Human-readable; universally understood | String comparison breaks on timezone suffixes (`Z` vs `+00:00`); no built-in uniqueness within a millisecond for concurrent writes |
| Epoch milliseconds (integer) | Simple; precise | S3 Vectors metadata is string-typed; integer comparisons require a dedicated operator or cast logic; less readable |
| S3 `LastModified` header | No new field; already present on every S3 object | Reading `LastModified` requires a per-artifact `head_object` call — O(n) S3 calls to scan a session's worth of candidates; impractical for `propose_commit_links` |

### `commit_refs` storage scope

| Option | Pros | Cons |
|--------|------|------|
| **Chosen** — Vector metadata only (V1) | Zero extra API calls in `link_commit`; no partial-failure mode beyond vector write; `read_artifact` already reads vector metadata for `commit_refs` | `reconcile_index` drops commit links — operator must re-run post-commit protocol after any reconcile |
| Vector metadata + S3 object metadata (`copy_object`) | Survives `reconcile_index` | `copy_object` is a per-artifact S3 operation with its own partial-failure mode; added latency; `copy_object` replaces the S3 object — any concurrent write to the same artifact creates a race; complexity not justified until reconcile stability is a stated need |
| S3 object metadata only | Survives `reconcile_index` | `read_artifact` would need an extra S3 `head_object` call per read to surface `commit_refs`; `propose_commit_links` cannot filter by `commit_refs` in the vector index — all artifacts would need to be fetched from S3 to check the field |

### V1 trigger mechanism

| Option | Pros | Cons |
|--------|------|------|
| **Chosen** — Agent-driven AGENTS.md protocol (Path 2) | Tool-agnostic; no additional config; always in context via AGENTS.md; works today across all four supported clients | Requires an active agent session; relies on operator discipline to follow the protocol; CI pipelines without an active agent session must supply `commit_refs` at write time |
| Claude Code `PostToolUse` MCP hook (Path 1) | Fires automatically after `git commit` within the session; no operator discipline required; calls MCP tools directly in the existing session | Claude Code-specific; requires installation skill to write hook config; deferred to installation skill milestone |
| Git `post-commit` hook + CLI (Path 3) | Universal — fires even without an active agent session; not tool-specific | Requires `.arkeology/config.sh` for a tool-agnostic credential source (no universal MCP config location across tools); non-interactive — confirmation before linking not possible; deferred to installation skill milestone |

## Consequences

- **`propose_commit_links` is efficient.** Time-range discovery via `last_edited_ulid >= since_ulid`
  is a single vector index filter call — no per-artifact S3 reads. Fetching all own-scope artifacts
  and filtering client-side for empty `commit_refs` avoids needing a `$exists` operator.

- **`link_commit` makes no Bedrock calls.** The metadata-only update path (`get_vectors` →
  `put_vectors_batch` with same float32 vectors + updated metadata) is the only embedding-free
  write path in the server. This is verified by unit test spy on the Bedrock client.

- **`next_since_ulid` as a session cursor.** `link_commit` generates a fresh ULID after processing
  all artifacts and returns it as `next_since_ulid`. The agent replaces `since_ulid` with this
  value after each linking call, so the cursor advances automatically without the agent generating
  ULIDs independently.

- **Reconcile drops commit links (V1 known limitation).** Any `reconcile_index` run re-indexes
  affected artifacts from S3 object metadata, which carries no `commit_refs` in V1. All commit
  links on re-indexed artifacts are erased. The operator must re-run the post-commit protocol to
  restore them. This is documented in: the `link_commit` module docstring, the AGENTS.md snippet
  written by the installation skill, and the PRD Known Limitations section.

- **CI pipelines without an agent session.** Automated pipelines (e.g. a CI code-reviewer agent)
  that commit without an active agent session following the AGENTS.md protocol can supply
  `commit_refs` directly on the `write_artifact` call if the commit SHA is known at write time.
  `link_commit` is an after-the-fact enrichment path — it is not the only way to associate
  commits with artifacts.

- **Path 1 and Path 3 automation deferred.** Neither automated trigger path is blocked by any V1
  design decision. Path 1 (Claude Code hook) is unblocked once the installation skill is updated
  to write the hook configuration. Path 3 (git hook + CLI) requires a `.arkeology/config.sh` written
  by the installation skill as a tool-agnostic config source.
