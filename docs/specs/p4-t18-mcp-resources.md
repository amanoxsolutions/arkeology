---
type: Spec
id: p4-t18-mcp-resources
title: T18 — MCP Resources
description: Exposes five Arkeology schema documents as MCP Resources so connected agents can discover valid artifact types, tier semantics, visibility rules, type catalogue, and query strategy at runtime without external documentation.
tags: []
status: stable
okf_version: "0.2"
generated:
  by: "axians-architect/unknown"
  at: 2026-05-31T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-09T12:05:23Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
---

# T18 — MCP Resources

## TL;DR

Five read-only MCP Resources expose the Arkeology schema — artifact fields, tier semantics,
visibility rules, the type catalogue and query strategy — as markdown any connected agent can list
and read at runtime, without a README or a loaded skill. The type lists derive from
`ARTIFACT_TYPES`, so the resources stay in sync with the running server as the schema evolves.

## 1. Problem Statement

Connected agents currently have no runtime mechanism to discover the Arkeology schema. Valid
artifact types, required vs optional fields, tier semantics, cross-scope visibility rules, and
effective query strategy all live in the README — external documentation an agent cannot access
during a session. Agents are forced to infer schema from tool call failures or consult a loaded
skill. MCP Resources provide a first-class runtime discovery mechanism: any MCP-compatible agent
calls `resources/list` to enumerate what is available and `resources/read` to fetch any of the five
schema documents. The resources must stay permanently in sync with the running server by deriving
their content directly from the same code constants the server uses — not from hardcoded strings
that silently drift when the schema evolves. The six stories — runtime discovery of valid types and
field constraints, tier semantics, cross-scope visibility rules, the type catalogue with usage
guidance, query strategy guidance, and all five resources appearing in `resources/list` — are all
P1.

## 2. Rules — Resource set and format

### R1 — Five schema resources, all enumerated by `resources/list`

The system exposes five MCP Resources at these URIs:

- `arkeology://schema/artifact`
- `arkeology://schema/tiers`
- `arkeology://schema/visibility`
- `arkeology://schema/types`
- `arkeology://schema/query-strategy`

When a connected agent calls `resources/list`, all five URIs are present.

Source: none

### R2 — Every resource returns markdown text a model can use directly

When any resource is read, the system returns markdown-formatted text that a language model can
directly use without post-processing.

Source: none

### R3 — Resource handlers receive no AWS clients and make no AWS calls

Resource handlers do not receive injected AWS clients — they are pure schema documentation with no
AWS calls.

Source: none

### R4 — Resources live in `resources.py` and are registered from `server.py`

The resources are implemented in a dedicated `src/arkeology/resources.py` module that exposes a
`register_resources(app)` function; `server.py` calls it alongside `register_tools()`.

Source: none

## 3. Rules — Resource content

### R5 — `arkeology://schema/artifact` states the fields and their constraints

An agent starting a new session calls `arkeology://schema/artifact` and knows immediately which
fields are required, which are optional, and what values are valid for each enum field — without
reading a README or loading a skill. When a connected agent reads `arkeology://schema/artifact`,
the response lists:

- all required fields (type, team, project, tier, date, status, title, visibility, description);
- all optional fields (tags, author_role, source_artifacts);
- all valid enum values per field;
- the description 280-character constraint.

Source: none

### R6 — `arkeology://schema/tiers` states tier semantics and key formats

When a connected agent reads `arkeology://schema/tiers`, the response describes:

- tier 2 (project-local, date-anchored key, append-only, immutable content);
- tier 3 (permanent, date-independent key, overwrites in place);
- the key format for each (`{type_slug}-{date}-{title_slug}` vs `{type_slug}-{title_slug}`).

Source: none

### R7 — `arkeology://schema/visibility` states the visibility values and the cross-scope rule

When a connected agent reads `arkeology://schema/visibility`, the response describes the two
visibility values (shared, hidden), when each applies, and the cross-scope access rule: only tier 3
shared artifacts are accessible outside the deployment's own scope.

Source: none

### R8 — `arkeology://schema/types` lists every type with usage guidance

When a connected agent reads `arkeology://schema/types`, the response lists every type in
`ARTIFACT_TYPES` with a one-line description of when to use it.

Source: none

### R9 — `arkeology://schema/query-strategy` covers narrow-first querying and tool choice

When a connected agent reads `arkeology://schema/query-strategy`, the response covers:

- start narrow (type filter + tags before relying on pure semantic similarity);
- broaden only when narrow queries return insufficient results;
- when to use `list_artifacts` vs `search_artifacts`;
- when to use `synthesise_artifacts` (and how to write the result back as a tier 3 synthesis with
  `source_artifacts`).

Source: none

## 4. Rules — Sync with `ARTIFACT_TYPES`

### R10 — Both type lists derive from `ARTIFACT_TYPES`, never a hardcoded copy

The `arkeology://schema/artifact` resource derives its list of valid types from `ARTIFACT_TYPES` in
`artifact.py` — not a hardcoded copy. The `arkeology://schema/types` resource also derives its type
list from `ARTIFACT_TYPES` directly, so both stay in sync automatically on schema changes rather
than silently drifting when the schema evolves.

**Example**

- Given `ARTIFACT_TYPES` in `artifact.py` gains a new entry, when the server restarts, then
  `arkeology://schema/artifact` includes the new type with no other file changed.

Source: none

## 5. Boundaries

**Always:**
- Resources are read-only — no write path, no state changes.
- Type lists are derived from `ARTIFACT_TYPES` at call time (or at module load if
  generated once) — never a hardcoded list that could diverge.
- Resources are registered on the same `_app` FastMCP instance as the tools.
- Resource handlers are synchronous pure functions (no async needed — no I/O).

**Ask First:**
- Nothing — all constraints are defined.

**Never:**
- Do not hardcode the artifact type list — always read from `ARTIFACT_TYPES`.
- Do not expose runtime configuration (WRITE_PREFIX, bucket names, credentials) in
  resources — schema documentation only.
- Do not make AWS API calls from resource handlers.
- Do not return resource content as structured JSON — markdown text only (MCP Resources
  spec expects text/markdown MIME type for documentation resources).

## 6. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_resources.py` | Create | Written first (Red) |
| `src/arkeology/resources.py` | Create | Written after unit tests (Green) |
| `src/arkeology/server.py` | Modify | Call `register_resources(_app)` — add the import and call |

### Contracts

None.

### Testing Approach

**TDD cycle:** write `test_resources.py` first → fail → implement `resources.py` → pass.

**`test_resources.py` — unit tests (no AWS, no fakes needed):**

Use a bare FastMCP app instance or inspect the module's exported content functions
directly — resources are pure functions; test the content-generation functions directly
without needing a running server.

All five URIs present:
- After `register_resources(app)`, all five URIs appear in the app's resource list.

Content correctness — `arkeology://schema/artifact`:
- Response string is non-empty.
- Contains each required field name: `type`, `team`, `project`, `tier`, `date`, `status`,
  `title`, `visibility`, `description`.
- Contains each optional field name: `tags`, `author_role`, `source_artifacts`.
- Contains the string `"280"` (description length constraint).
- Contains every value currently in `ARTIFACT_TYPES` (verify by iterating the set and
  checking membership).

Content correctness — `arkeology://schema/tiers`:
- Contains `"tier 2"` and `"tier 3"` (case-insensitive).
- Contains `"immutable"`.
- Contains the tier 2 key format pattern (must mention `date`).
- Contains the tier 3 key format pattern (must mention no date / date-independent).

Content correctness — `arkeology://schema/visibility`:
- Contains `"shared"` and `"hidden"`.
- Contains `"tier 3"` (the cross-scope gate).

Content correctness — `arkeology://schema/types`:
- Contains every value currently in `ARTIFACT_TYPES`.
- Each type appears with at least a one-line description (verify by checking that the type
  string appears as a distinct entry, not just a substring).

Content correctness — `arkeology://schema/query-strategy`:
- Contains `"type"`, `"tags"`, `"synthesise_artifacts"`.
- Contains guidance about starting narrow and broadening (verify key terms are present).

Sync invariant:
- If `ARTIFACT_TYPES` is temporarily monkey-patched to add a fake type during the test,
  both `arkeology://schema/artifact` and `arkeology://schema/types` responses include the new
  type — confirming live derivation rather than a cached copy.

No integration tests are needed — resources contain no AWS calls.
