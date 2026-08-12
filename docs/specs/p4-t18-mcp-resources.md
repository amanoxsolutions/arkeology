---
type: spec
title: T18 — MCP Resources
description: Exposes five Arkeology schema documents as MCP Resources so connected agents can discover valid artifact types, tier semantics, visibility rules, type catalogue, and query strategy at runtime without external documentation.
tags: []
timestamp: 2026-05-31T00:00:00Z
okf_version: "0.1"
feature: p4-t18-mcp-resources
status: ready
phase: 4
task: 18
references: []
authored:
  by: "architect"
  date: "2026-05-31"
revised:
  by: ""
  date: ""
---

# T18 — MCP Resources

<!-- SCOPE BLOCK — frozen after approval -->

## Problem Statement

Connected agents currently have no runtime mechanism to discover the Arkeology schema.
Valid artifact types, required vs optional fields, tier semantics, cross-scope visibility
rules, and effective query strategy all live in the README — external documentation an
agent cannot access during a session. Agents are forced to infer schema from tool call
failures or consult a loaded skill. MCP Resources provide a first-class runtime discovery
mechanism: any MCP-compatible agent calls `resources/list` to enumerate what is available
and `resources/read` to fetch any of the five schema documents. The resources must stay
permanently in sync with the running server by deriving their content directly from the
same code constants the server uses — not from hardcoded strings that silently drift when
the schema evolves.

## User Stories

### Story 1 — Agent discovers valid types and field constraints at runtime (P1)

An agent starting a new session calls `arkeology://schema/artifact` and knows immediately
which fields are required, which are optional, and what values are valid for each enum
field — without reading a README or loading a skill.

**Acceptance criteria:**
- Given a connected agent reads `arkeology://schema/artifact`, then the response lists all
  required fields (type, team, project, tier, date, status, title, visibility,
  description), all optional fields (tags, author_role, source_artifacts),
  all valid enum values per field, and the description 280-character constraint.
- Given `ARTIFACT_TYPES` in `artifact.py` gains a new entry, when the server restarts,
  then `arkeology://schema/artifact` includes the new type with no other file changed.

### Story 2 — Agent understands tier semantics without external docs (P1)

**Acceptance criteria:**
- Given a connected agent reads `arkeology://schema/tiers`, then the response describes:
  tier 2 (project-local, date-anchored key, append-only, immutable content), tier 3
  (permanent, date-independent key, overwrites in place), and the key format for each
  (`{type_slug}-{date}-{title_slug}` vs `{type_slug}-{title_slug}`).

### Story 3 — Agent understands cross-scope visibility rules (P1)

**Acceptance criteria:**
- Given a connected agent reads `arkeology://schema/visibility`, then the response describes
  the two visibility values (shared, hidden), when each applies, and the cross-scope access
  rule: only tier 3 shared artifacts are accessible outside the deployment's own scope.

### Story 4 — Agent reads type catalogue with usage guidance (P1)

**Acceptance criteria:**
- Given a connected agent reads `arkeology://schema/types`, then the response lists every type
  in `ARTIFACT_TYPES` with a one-line description of when to use it.

### Story 5 — Agent reads query strategy guidance (P1)

**Acceptance criteria:**
- Given a connected agent reads `arkeology://schema/query-strategy`, then the response covers:
  start narrow (type filter + tags before relying on pure semantic similarity),
  broaden only when narrow queries return insufficient results, when to use `list_artifacts`
  vs `search_artifacts`, and when to use `synthesise_artifacts` (and how to write the
  result back as a tier 3 synthesis with `source_artifacts`).

### Story 6 — All five resources appear in resources/list (P1)

**Acceptance criteria:**
- Given a connected agent calls `resources/list`, then all five URIs are present:
  `arkeology://schema/artifact`, `arkeology://schema/tiers`, `arkeology://schema/visibility`,
  `arkeology://schema/types`, `arkeology://schema/query-strategy`.

## Requirements

- THE SYSTEM SHALL expose five MCP Resources at these URIs: `arkeology://schema/artifact`,
  `arkeology://schema/tiers`, `arkeology://schema/visibility`, `arkeology://schema/types`,
  `arkeology://schema/query-strategy`.
- WHEN any resource is read THE SYSTEM SHALL return markdown-formatted text that a
  language model can directly use without post-processing.
- THE `arkeology://schema/artifact` resource SHALL derive its list of valid types from
  `ARTIFACT_TYPES` in `artifact.py` — not a hardcoded copy.
- THE `arkeology://schema/types` resource SHALL also derive its type list from `ARTIFACT_TYPES`
  directly so both stay in sync automatically on schema changes.
- THE SYSTEM SHALL implement resources in a dedicated `src/arkeology/resources.py` module
  that exposes a `register_resources(app)` function; `server.py` calls it alongside
  `register_tools()`.
- Resource handlers SHALL NOT receive injected AWS clients — they are pure schema
  documentation with no AWS calls.
- WHEN `resources/list` is called THE SYSTEM SHALL enumerate all five URIs.

## Boundaries

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

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_resources.py` | Create | Written first (Red) |
| `src/arkeology/resources.py` | Create | Written after unit tests (Green) |
| `src/arkeology/server.py` | Modify | Call `register_resources(_app)` — add the import and call |

## Testing Approach

**TDD cycle:** write `test_resources.py` first → fail → implement `resources.py` → pass.

---

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

## Open Questions

*(none — all constraints are defined)*
