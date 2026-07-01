---
type: brainstorming
title: Artifact Commit References
description: How to add git commit references to artifact metadata in cairn-mcp, solving the association problem where the commit SHA is unknown at write time, covering the metadata model, timestamp precision, trigger mechanism, and migration skill implications.
tags: []
timestamp: 2026-06-06T00:00:00Z
okf_version: "0.1"
status: ready
references:
  - docs/brainstorming/brainstorming-2026-06-01-adr-git-cairn-relationship.md
authored:
  by: "analyst"
  date: "2026-06-06"
revised:
  by: "analyst"
  date: "2026-06-06"
techniques_used:
  - perspective-shift
  - constraint-removal
  - inversion
assumptions_challenged:
  - "The MCP server can be called from a git hook directly (false — stdio transport is point-to-point)"
  - "A .env file is a reliable config source for all MCP tools (false — config location varies by tool)"
  - "S3 stores timestamps we can filter on (false — only date is stored today; full timestamp requires a new field)"
  - "ULIDs are only useful as IDs (false — they are also sortable timestamps enabling range queries)"
  - "A separate skill is needed to coordinate with the committing-code skill (false — AGENTS.md is always in context)"
  - "link_commit must update S3 object metadata to be correct (false — vector-only is acceptable in V1 with a documented reconcile limitation)"
  - "since_ulid must be supplied for propose_commit_links to work (false — absent means all unlinked artifacts in scope)"
decisions_locked:
  - D1: commit_refs as the metadata field name (list[str], opaque format — full SHA, short SHA, PR URL, tag all valid)
  - D2: last_edited_ulid as the write-time field (ULID generated on every write_artifact call, stored in S3 and vector metadata)
  - D3: python-ulid as the ULID library dependency
  - D4: $gte/$lte range operators must be added to filter.py as a prerequisite
  - D5: two tools — propose_commit_links (read-only discovery) and link_commit (write, vector metadata only in V1)
  - D6: link_commit updates vector metadata only in V1; known limitation — reconcile_index will not restore commit_refs (documented, not silent)
  - D7: link_commit appends to existing commit_refs (merge + deduplicate, not replace)
  - D8: V1 trigger mechanism is Path 2 — agent-driven via AGENTS.md protocol (tool-agnostic)
  - D9: propose_commit_links fetches all artifacts in time range then filters client-side for missing commit_refs (avoids needing $exists operator)
  - D10: link_commit returns next_since_ulid in its response; write_artifact returns last_edited_ulid in its response
  - D11: since_ulid is optional in propose_commit_links; when absent, returns all unlinked artifacts in own scope regardless of age
decisions_pending:
  - Path 1 (Claude Code PostToolUse mcp_tool hook) and Path 3 (git hook + cairn CLI) — deferred to installation skill milestone (see Known Limitations and Deferred Features)
  - A dedicated .cairn/config.sh written by the installation skill as the tool-agnostic config source for Path 3
decisions_locked:
  - D1: commit_refs as the metadata field name (list[str], opaque format — full SHA, short SHA, PR URL, tag all valid)
  - D2: last_edited_ulid as the write-time field (ULID generated on every write_artifact call, stored in S3 and vector metadata)
  - D3: python-ulid as the ULID library dependency
  - D4: $gte/$lte range operators must be added to filter.py as a prerequisite
  - D5: two tools — propose_commit_links (read-only discovery) and link_commit (write, vector metadata only in V1)
  - D6: link_commit updates vector metadata only in V1; known limitation — reconcile_index will not restore commit_refs (documented, not silent)
  - D7: link_commit appends to existing commit_refs (merge + deduplicate, not replace)
  - D8: V1 trigger mechanism is Path 2 — agent-driven via AGENTS.md protocol (tool-agnostic)
  - D9: propose_commit_links fetches all artifacts in time range then filters client-side for missing commit_refs (avoids needing $exists operator)
  - D10: link_commit returns next_since_ulid in its response; write_artifact returns last_edited_ulid in its response
  - D11: since_ulid is optional in propose_commit_links; when absent, returns all unlinked artifacts in own scope regardless of age
  - D12: "migration skill default is do not backfill commit_refs; three options available: (1) do not backfill, (2) link all to current HEAD via one `git rev-parse HEAD` call + one `link_commit` call — fast but imprecise (HEAD is migration-time snapshot, not per-file provenance), (3) backfill per-file from git history via `git log -1` per file — accurate but O(n) git calls"
  - D13: S3 object metadata update for commit_refs (copy_object) is out of scope; commit_refs is read from vector metadata by read_artifact — no copy_object needed for read visibility
decisions_closed_not_applicable:
  - Direction 1 (caller-supplied commit_refs at write time) — caller may not know the SHA at write time; post-write annotation is the right model
  - Direction 2 (CAIRN_GIT_COMMIT env var) — does not solve interactive sessions; deferred
  - ISO-8601 datetime for written_at — ULID chosen instead (lexicographically sortable + unique + human-readable via conversion)
  - OQ1 + OQ4 (session-start ULID ergonomics) — resolved: Bash call at session start, link_commit returns next_since_ulid, since_ulid optional
  - OQ2 (S3 object metadata for commit_refs) — resolved as D6: vector-only in V1, reconcile limitation documented
  - OQ3 (commit_refs filtering in list/search) — resolved: add commit_refs filter parameter to list_artifacts mirroring feature_tags pattern
  - Migration skill backfill open question — resolved as D12: do not backfill is the default; three options (none / fast HEAD link / accurate per-file) remain available
  - Migration timestamp option (commit_refs left empty, last_edited_ulid as proxy) — rejected; produces no actionable difference from option 1 and leaves artifacts unlinked, surfacing them in all future propose_commit_links calls without a since_ulid bound
  - S3 copy_object for commit_refs open question — resolved as D13: out of scope; read_artifact reads vector metadata directly
---

# Artifact Commit References

## Description

How to add git commit references to artifact metadata in cairn-mcp, and specifically how to
solve the association problem: artifacts are written during a session before a commit happens,
so the commit SHA is unknown at write time. The session explored the metadata model, timestamp
precision requirements, the trigger mechanism for linking artifacts to commits after the fact,
and the migration skill implications.

---

## Session 2026-06-06

### Problem Statement

Artifacts written to cairn-mcp (code reviews, implementation notes, ADRs, session summaries)
describe work that is tied to a specific git commit. Without a `commit_refs` field, there is no
traceability from an artifact to the code change it documents. The core difficulty is timing:
the artifact is written during an agent session, often before the developer has committed. The
commit SHA does not exist yet at write time, so it cannot be supplied during the initial
`write_artifact` call.

A secondary problem: the server is deployment-agnostic (no git context at runtime), so
server-side auto-detection of the current HEAD is not viable.

---

### Ideas Explored

#### On what to store

1. Full commit SHA (40-char SHA-1 or 64-char SHA-256)
2. Short SHA (7–12 chars) — human-readable but ambiguous across repos
3. Branch name — mutable, non-unique
4. PR number — captures approval ceremony, not the raw commit
5. Git tag — useful for releases, useless mid-development
6. From–to range (`abc123..def456`) — complex to parse
7. Repository URL + SHA — fully qualified cross-repo reference

#### On how the association is made (original exploration)

8. Caller supplies `commit_refs` at write time (explicit field)
9. Server auto-detects from working directory (`git rev-parse HEAD`) — requires server to be in repo; breaks deployment-agnostic design
10. Environment variable injection (`CAIRN_GIT_COMMIT`) — CI/CD friendly but not interactive sessions
11. Convention in Markdown content — no metadata field; not filterable
12. Content convention + server parsing — adds parsing fragility
13. Post-write re-call of `write_artifact` — idempotent but re-embeds all sections (expensive)
14. New `annotate_artifact` / `patch_artifact_metadata` tool — metadata-only patch, no re-embed
15. Git hook (`post-commit`) calling a CLI script
16. Commit message convention — agent embeds `cairn:{artifact_id}` in commit; hook parses and backfills
17. Reverse index (commit → artifacts) — separate storage, different query direction
18. `reconcile_index` extended with `--link-commit` mode
19. Webhook/HTTP endpoint — CI calls POST after build
20. Agent AGENTS.md convention — no code change; agent supplies SHA as a `feature_tag`
21. Session-scoped `CAIRN_SESSION_COMMIT` env var
22. Soft convention for specific types (code_review, adr, implementation_note) only

#### On vector metadata update mechanics (deeper dive)

`get_vectors` with `returnData=True` returns the float32 embedding alongside metadata. This
means the update loop is possible with existing client methods:

```
list_vectors_by_metadata({"artifact_id": {"$eq": s3_key}})
  → all vector keys for the artifact

get_vectors(keys)
  → current float32 embeddings + current metadata

put_vectors_batch([{
    "key": k,
    "vector": v["data"]["float32"],    # same embedding, unchanged
    "metadata": {**v["metadata"], "commit_refs": [...]}  # metadata updated
}])
```

No Bedrock call. No S3 content re-read. No re-embedding. The mechanism is entirely feasible
with the existing `VectorsClientInterface`.

#### On timestamp precision

The current metadata carries `date` (YYYY-MM-DD) only. There is no full write timestamp in S3
object metadata or vector metadata. S3 objects carry `LastModified` from `head_object`, but
reading it requires a per-artifact S3 call — expensive for scanning a session's worth of
candidates.

`filter.py` only supports `$eq`, `$in`, `$nin` — no range operators. Time-range filtering in
the vector index is not possible today.

**ULID** (Universally Unique Lexicographically Sortable Identifier) addresses both issues:
millisecond-precision timestamp encoded in the first 10 characters, lexicographically sortable
as a plain string, unique collision-free. Adding `$gte`/`$lte` to `filter.py` and a
`last_edited_ulid` field to metadata enables range queries on write time without any S3 reads.
A ULID can be converted back to a human-readable datetime via `python-ulid`, making it
operator-friendly when displayed in `propose_commit_links` results.

The `last_edited_ulid` field is generated on every `write_artifact` call using `python-ulid`.
It tracks "when this artifact was last written" — what is needed to find artifacts produced
during the current session. It is a write-time system field, not caller-supplied, and therefore
not part of the `Artifact` model.

#### On trigger mechanisms

Three paths were explored:

**Path 1 — IDE-level hook (Claude Code `mcp_tool` + OpenCode JS plugin)**

Claude Code supports `"type": "mcp_tool"` in `PostToolUse` hooks. A hook on `Bash` with
`if: "Bash(git commit *)"` can call MCP tools directly via the existing MCP session — no
separate config, no separate AWS credentials, no new process.

OpenCode has `tool.execute.after` in its JS plugin model, but no `mcp_tool` equivalent — it
can only execute shell commands via `$`. Codex CLI and Copilot CLI are similarly shell-command
only.

Path 1 is therefore **Claude Code-specific** and requires the installation skill to write the
hook configuration.

**Path 2 — Agent-driven via AGENTS.md (tool-agnostic)**

The project's `AGENTS.md` is always loaded at session start, regardless of which skills the
agent later loads. Adding the post-commit protocol to the `AGENTS.md` snippet written by the
cairn installation skill means the agent follows it in every session, in every MCP tool, without
any additional configuration.

When the agent loads the `committing-code` skill, both the skill instructions (commit format,
conventional commits) and the AGENTS.md protocol (post-commit cairn linking) are simultaneously
in context. No skill composition mechanism is needed; AGENTS.md is the right carrier because
the behaviour is project-specific (cairn-mcp must be configured for this project), not
generically reusable. A separately loadable cairn skill would be invisible to agents who load
only `committing-code`.

**Path 3 — Git hook + `cairn link-commit` CLI**

A `post-commit` git hook calls a CLI entry point (`cairn link-commit`) that reconstructs the
AWS clients independently from the MCP session. The hook is universal (any git workflow, no IDE
required) and fires even when no agent session is active.

The critical prerequisite: **there is no universal config file**. MCP server environment
variables are stored differently across tools:
- Claude Code: `.claude/settings.json` `env` block
- OpenCode: `opencode.json` / `opencode.jsonc` `env` block
- Claude Desktop: `~/Library/Application Support/Claude/claude_desktop_config.json`
- VS Code Copilot: `.vscode/mcp.json`

A git hook cannot source any of these reliably. The solution is a **`.cairn/config.sh`** file
written once by the installation skill (tool-agnostic, `.gitignore`d), which the hook sources:
`source "$(git rev-parse --show-toplevel)/.cairn/config.sh"`. This is a dependency on the
installation skill milestone and keeps Path 3 deferred.

The confirmation problem also applies: git hooks are non-interactive. Options are auto-link
without confirmation (Path 3a) or write a `.cairn_pending_links` file for the next agent
session to review (Path 3b).

#### On the reconcile_index known limitation

`reconcile_index` rebuilds vector metadata entirely from S3 object metadata via
`_reindex_artifact`. It reads every field that is stored in S3 — `feature_tags`,
`source_artifacts`, `title`, `type`, etc. If `link_commit` writes `commit_refs` only to vector
metadata (D6), `reconcile_index` will silently drop all commit links from any artifact it
re-indexes. The operator would need to re-run the post-commit protocol to restore them.

This is an **accepted known limitation in V1**, not a silent bug. The reconcile case is rare
(partial write failures, orphaned objects) and the re-linking effort is bounded. The mitigation
for a future milestone is to also update S3 object metadata in `link_commit` via `copy_object`,
so that `reconcile_index` picks up `commit_refs` naturally.

---

### Clusters

**Cluster A — Metadata field design**
`commit_refs: list[str]` stored as comma-joined string in S3 object metadata and as `list[str]`
in vector metadata — identical to the pattern used by `feature_tags` and `source_artifacts`.
Format is opaque: full SHA, short SHA, PR URL, and tags are all valid entries. Field name is
explicit: `commit_refs`.

**Cluster B — Write-time timestamp**
`last_edited_ulid` stored in both S3 metadata and vector metadata. Generated on every
`write_artifact` call. Enables time-range discovery of session artifacts without S3 reads.
Prerequisite: `$gte`/`$lte` operators in `filter.py`. Dependency: `python-ulid`. Returned in
the `write_artifact` response so agents and tools have immediate visibility into the stored
value.

**Cluster C — Post-write linking mechanics**
The update requires no Bedrock re-embedding: `get_vectors` returns float32 data, allowing
`put_vectors_batch` with the same vectors and enriched metadata. The `link_commit` tool appends
to existing `commit_refs` (merge + deduplicate, not replace) — an artifact can accumulate
multiple commit SHAs across sessions. V1 updates vector metadata only; S3 metadata update via
`copy_object` is a future milestone. `link_commit` returns `next_since_ulid` so the agent can
advance its cursor without generating ULIDs independently.

**Cluster D — Discovery**
`propose_commit_links(commit_sha, since_ulid?)` fetches all artifacts in own scope optionally
bounded by `last_edited_ulid >= since_ulid`, then filters client-side for those with no
`commit_refs`. `since_ulid` is optional — when absent, all unlinked artifacts in scope are
returned regardless of age. Client-side filtering avoids needing a `$exists` operator. Returns
a proposed list with human-readable timestamps for operator review before any write occurs.

**Cluster E — Trigger mechanism**
Three paths (IDE hook, agent-driven, git hook CLI) are not mutually exclusive. Path 2
(AGENTS.md protocol) is the V1 foundation. Path 1 (Claude Code hook) and Path 3 (git hook +
CLI) are enhancements targeted at the installation skill milestone.

---

### Selected Directions

#### D1 — `commit_refs: list[str]` on `Artifact` and in both metadata stores

Add `commit_refs: list[str] = Field(default_factory=list)` to the `Artifact` model. Store as
comma-joined string in S3 object metadata; as `list[str]` in vector metadata (consistent with
`feature_tags` and `source_artifacts`). Empty list → field omitted from both stores (S3 Vectors
rejects empty arrays; S3 metadata carries an empty string handled at read time).

Encoding/decoding mirrors the existing pattern in `write.py` and `list.py`.

#### D2 — `last_edited_ulid` in metadata, generated on every write

Add `last_edited_ulid: str` to S3 object metadata and vector metadata in `_write_artifact_inner`.
Generated via `python-ulid` at the point of writing, not at validation time. No model-level
field (not part of `Artifact` — it is a write-time system field, not caller-supplied).

Include `last_edited_ulid` in the `write_artifact` response alongside `artifact_id` and
`sections_indexed`. The agent can inspect it immediately after each write.

Prerequisite: add `$gte` and `$lte` operators to `filter.py`. These work correctly with ULID
strings because ULID is lexicographically sortable.

#### D3 — `propose_commit_links` MCP tool (read-only discovery)

```
propose_commit_links(
    commit_sha: str,
    since_ulid: str | None = None,  # optional lower bound; absent = all unlinked in scope
) → {
    "proposed": [
        {
            "artifact_id": str,
            "title": str,
            "type": str,
            "last_edited_ulid": str,
            "last_edited_at": str,   # human-readable ISO-8601 derived from ULID
        },
        ...
    ],
    "commit_sha": str,
}
```

Implementation:
1. If `since_ulid` is provided, call `list_vectors_by_metadata` with filter:
   `scope=$eq[write_prefix]` AND `last_edited_ulid=$gte[since_ulid]`.
   If absent, call with filter: `scope=$eq[write_prefix]` only.
2. `get_vectors` on result keys
3. Deduplicate by `artifact_id`
4. Filter client-side: keep only artifacts where `commit_refs` is absent or empty
5. Convert each `last_edited_ulid` to a human-readable `last_edited_at` string via `python-ulid`
6. Return proposed list

No writes. No side effects. Returns an empty `proposed` list if no candidates found.

#### D4 — `link_commit` MCP tool (vector metadata update, returns cursor)

```
link_commit(
    artifact_ids: list[str],   # confirmed list from operator
    commit_sha: str
) → {
    "linked": int,
    "commit_sha": str,
    "skipped": int,
    "next_since_ulid": str,    # fresh ULID generated at call time — use as since_ulid for next call
}
```

Implementation (per artifact_id):
1. Derive `s3_key` from `artifact_id` (it is already the S3 key)
2. `list_vectors_by_metadata({"artifact_id": {"$eq": s3_key}})` → vector keys
3. `get_vectors(keys)` → float32 embeddings + current metadata
4. Merge `commit_sha` into existing `commit_refs` list (append, deduplicate)
5. `put_vectors_batch` with same embeddings, updated metadata
6. After all artifacts processed, generate and return `next_since_ulid`

Scope gate: reject `artifact_id` values that do not start with `settings.write_prefix + "/"`.
No Bedrock call. No S3 write (V1). Returns count of artifacts linked, count skipped (not found
or out of scope), and a fresh ULID for the agent to carry as the next `since_ulid`.

**Known limitation (V1):** `reconcile_index` rebuilds vectors from S3 metadata. Because
`commit_refs` is stored in vector metadata only, a reconcile will drop all commit links from
re-indexed artifacts. The operator must re-run the post-commit protocol after a reconcile to
restore them. This will be resolved in a future milestone by also updating S3 object metadata.

#### D5 — AGENTS.md post-commit protocol (V1 trigger)

The cairn installation skill appends a post-commit section to the project's `AGENTS.md`:

```markdown
## Post-commit protocol

At session start:
- Capture the session ULID once: `python -c "from ulid import ULID; print(ULID())"`
- Store it as `since_ulid`. Always carry `since_ulid` in context for the entire session.

After every `git commit` during a session:
1. Note the commit SHA: `git rev-parse HEAD`
2. Call `propose_commit_links(commit_sha=<sha>, since_ulid=<since_ulid>)`
   If this is the first commit of a new project and since_ulid is unavailable, omit since_ulid.
3. Present the proposed list to the operator — they can confirm, remove, or add artifact IDs
4. If the operator confirms: call `link_commit(artifact_ids=[...], commit_sha=<sha>)`
5. Update `since_ulid` to the `next_since_ulid` value returned by `link_commit`
   Always carry the updated `since_ulid` in context.
6. Skip silently if `propose_commit_links` returns an empty proposed list
```

The agent never needs to generate ULIDs after the initial session-start capture — the cursor
advances automatically via `link_commit`'s `next_since_ulid` return value.

---

### Prerequisites

These changes are required before `propose_commit_links` can be implemented:

| Prerequisite | Scope | Notes |
|---|---|---|
| `$gte` and `$lte` operators in `filter.py` | `filter.py` | Enables range filtering on `last_edited_ulid`; also useful for future date-range queries |
| `python-ulid` dependency | `pyproject.toml` | ULID generation and human-readable conversion |
| `last_edited_ulid` field in write path and write response | `write.py` | Must be stored in S3 + vector metadata and returned in write response |
| `last_edited_ulid` exposed in list and read responses | `list.py`, `read.py` | Agents and operators need visibility into write timestamps |
| `commit_refs` field in `Artifact`, write, list, read paths | `artifact.py`, `write.py`, `list.py`, `read.py` | Same encoding pattern as `feature_tags` |
| `commit_refs` filter parameter in `list_artifacts` | `list.py` | Mirrors `feature_tags` pattern — one `$eq` clause per entry |

---

### Resolved Questions

**Migration skill backfill of `commit_refs` (→ D12).**
When running the `migrating-to-cairn` skill on an existing project, each migrated artifact
may optionally be linked to its historical git commit. The default is **do not backfill**;
the skill offers the operator three choices:

| Option | Behaviour | Trade-offs |
|---|---|---|
| **Do not backfill** (default) | `commit_refs` left empty on all migrated artifacts | Safe, fast, zero git calls; unlinked artifacts surface in future `propose_commit_links` calls without a `since_ulid` bound |
| **Link to current HEAD** | Run `git rev-parse HEAD` once; call `link_commit(artifact_ids=[all_written], commit_sha=<HEAD>)` — one git call, one `link_commit` call | Fast; all artifacts become linked; HEAD is migration-time snapshot, not per-file provenance; fails gracefully when the repository has no commits yet |
| **Backfill from git history** | For each file, run `git log -1 --format=%H -- <filepath>`; group artifact_ids by SHA; call `link_commit` once per unique SHA | Most accurate; O(n) git calls — warn the operator upfront for large projects; files never committed to git are skipped |

The "link to current HEAD" option was chosen over "set migration timestamp" (leave `commit_refs`
empty, `last_edited_ulid` serves as proxy) because the latter is indistinguishable from "do not
backfill" in terms of artifact state — both leave `commit_refs` empty and produce the same
downstream noise in `propose_commit_links`. "Link to current HEAD" makes all artifacts genuinely
linked (one git call, one server call) and removes them from future `propose_commit_links`
results, which is the operator's actual goal.

The `git log -1` approach (option 3) yields the SHA of the last commit that touched each file —
the most semantically accurate association. Commits may be arbitrarily old (pre-dating cairn-mcp
adoption), which is expected.

---

### Known Limitations and Deferred Features

#### KL1 — `reconcile_index` drops `commit_refs` (V1 known limitation)

`reconcile_index` rebuilds vector metadata entirely from S3 object metadata. Because
`link_commit` writes `commit_refs` to **vector metadata only** (D6), a reconcile run
overwrites those vectors with fresh ones constructed from S3 — which carries no `commit_refs`.
All commit links are erased from any artifact that is re-indexed.

This is an accepted V1 limitation, not a silent bug. The reconcile case is rare (partial write
failures, orphaned objects) and the operator can restore links by re-running the post-commit
protocol. Adding `copy_object` to `link_commit` (so S3 object metadata also carries
`commit_refs`) would resolve this, but that is out of scope (D13): the `copy_object` call adds
per-artifact cost and a partial-failure mode that is not justified until reconcile stability
becomes a stated need. `read_artifact` already presents `commit_refs` by reading vector metadata
directly — no S3 copy is required for read visibility.

#### DF1 — Automated trigger paths (deferred to installation skill milestone)

The V1 trigger is Path 2: the agent follows the AGENTS.md post-commit protocol and calls
`propose_commit_links` then `link_commit` manually after each commit. Two automation paths are
deferred:

**Path 1 — Claude Code `PostToolUse` hook**
A hook entry in `.claude/settings.json` with `"type": "mcp_tool"` and
`if: "Bash(git commit *)"` can call `propose_commit_links` then `link_commit` directly
within the existing MCP session — no separate credentials, no new process. This is
Claude Code-specific and requires the installation skill to write the hook configuration.

**Path 3 — `cairn link-commit` CLI + git hook**
A `post-commit` hook calls a `cairn link-commit` CLI entry point that reconstructs AWS clients
independently of any agent session. Requires a `.cairn/config.sh` file (written once by the
installation skill) that the hook sources for AWS credentials and bucket names — solving the
lack of a universal MCP config location across tools. Because git hooks are non-interactive,
confirmation before linking is not possible; options are auto-link (3a) or write a
`.cairn_pending_links` file for the next session to review (3b).

Both paths depend on the installation skill milestone and are not blocked by any V1 design
decision.
