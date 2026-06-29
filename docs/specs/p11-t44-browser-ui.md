---
type: spec
title: T44 — Browser UI (HTML/JS)
description: Feature spec for cairn-studio.html — a self-contained HTML/JS single-pane view-switching artifact browser shipped as a static MCP App asset. The primary deliverable is the cairn_studio non-supporting host path (structured artifact listing in structured_content). The MCP App iframe is registered and served but discovered post-implementation to have practical rendering constraints in supporting hosts.
tags: []
timestamp: 2026-06-24T00:00:00Z
okf_version: "0.1"
feature: p11-t44-browser-ui
status: complete
phase: 11
task: 44
references:
  - docs/planning-artifacts/prd.md
  - docs/architecture-decisions/adr-2026-06-24-mcp-apps-visual-reading-interface.md
  - docs/specs/p11-t43-mcp-app-infrastructure.md
  - docs/specs/p11-t44-browser-ui-design.html
  - https://gofastmcp.com/apps/overview
  - https://gofastmcp.com/python-sdk/fastmcp-apps-app
  - https://gofastmcp.com/apps/fastmcp-app
  - https://gofastmcp.com/apps/low-level
authored:
  by: "architect"
  date: "2026-06-24"
revised:
  by: "pm"
  date: "2026-06-29"
---

# T44 — Browser UI (HTML/JS)

<!-- SCOPE BLOCK — frozen after approval -->

## TL;DR

This task delivered two things:

1. `src/cairn_mcp/static/cairn-studio.html` — a self-contained HTML/JS single-pane
   view-switching application shipped as a static asset and served over
   `ui://cairn-studio/index.html`. It uses the ext-apps SDK, marked.js, and mermaid.js
   loaded from CDN (`unpkg.com`, `cdn.jsdelivr.net`); no web fonts; no build step.

2. The `cairn_studio` tool's non-supporting host path — when called from Claude Code or
   MCP Inspector, returns a structured artifact listing in `structured_content` with shape
   `{ "write_prefix": string, "artifacts": [...] }`. This is the primary interface for the team.

The MCP App iframe (supporting hosts: Claude Desktop, claude.ai, VS Code Copilot) was
registered and served successfully. Post-implementation testing revealed that the iframe
rendering environment is too small for the view-switching interface to be practical.
The non-supporting host structured listing path is the interface the team uses.

## Problem Statement

Developers using raw tool calls (`list_artifacts`, `search_artifacts`, `read_artifact`) to
browse the artifact store receive verbose, context-consuming output. T44 addressed this in
two ways: a structured listing returned directly by `cairn_studio` on non-supporting hosts
(Claude Code), and an MCP App iframe browser for supporting hosts. The structured listing
path delivers value immediately; the iframe path was implemented and shipped but found to be
constrained by the iframe rendering environment in practice.

## User Stories

### Story 1 — Developer on a non-supporting host gets a structured listing (P1)

A developer using Claude Code calls `cairn_studio` and receives a structured artifact listing
without issuing separate `list_artifacts` calls.

**Acceptance criteria:**
- Given the host does not support the `io.modelcontextprotocol/ui` extension, when
  `cairn_studio` is called, then `structured_content` carries `{ "write_prefix": string,
  "artifacts": [...] }` covering all active artifacts in the write scope.
- The listing is returned without error and is machine-readable by the calling agent.

### Story 2 — Developer on a supporting host gets an MCP App iframe (P2)

A developer using Claude Desktop or claude.ai calls `cairn_studio` and the host renders the
MCP App iframe.

**Acceptance criteria:**
- Given the host supports the `io.modelcontextprotocol/ui` extension, when `cairn_studio` is
  called, then `ToolResult` contains a text confirmation and the host receives the
  `_meta.ui.resourceUri` pointer to `ui://cairn-studio/index.html`.
- Note: post-implementation testing found the iframe rendering environment too small for
  the view-switching interface to be practical. The iframe is served correctly; the
  rendering constraint is a host environment limitation, not a bug in the implementation.

## Requirements

The tool contract for `cairn_studio`:

- WHEN called from a non-supporting host THE SYSTEM SHALL return `ToolResult` with
  `structured_content = { "write_prefix": settings.write_prefix, "artifacts": [...] }`
  from `_list_artifacts_inner`, plus a short text confirmation in `content`.
- WHEN called from a supporting host THE SYSTEM SHALL return `ToolResult` with a short text
  confirmation in `content` and no `structured_content` — the iframe loads its own artifact
  list on mount via `list_artifacts`.
- The `ui://cairn-studio/index.html` resource SHALL be registered with
  `ResourceCSP(["https://unpkg.com", "https://cdn.jsdelivr.net"])`.
- `cairn-studio.html` SHALL be a self-contained HTML/JS file with no companion `.css` or
  `.js` files and no JS build step.

## Boundaries

**Always:**
- All CSS and JS live in the single `src/cairn_mcp/static/cairn-studio.html` file.
- External dependencies loaded only from `unpkg.com` (ext-apps SDK) and `cdn.jsdelivr.net`
  (marked.js, mermaid.js). No web-font origins.
- No JS build step, no `package.json`, no Node.js artefacts.

**Never:**
- No new Python MCP tools or resources beyond what T43 established.
- No inline CDN library source — load via `<script src>` tags only.

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Status |
|------|--------|--------|
| `src/cairn_mcp/tools/studio.py` | Updated `_cairn_studio_inner`: supporting-host path returns text-only `ToolResult`; non-supporting host returns `{ "write_prefix": ..., "artifacts": [...] }` in `structured_content` | Done |
| `src/cairn_mcp/static/cairn-studio.html` | Replaced placeholder with full single-pane view-switching application | Done |
| `src/cairn_mcp/resources.py` | `ResourceCSP(["https://unpkg.com", "https://cdn.jsdelivr.net"])` registered | Done |
| `src/cairn_mcp/server.py` | `cairn_studio` tool registered via `register_tools()` | Done |
| `pyproject.toml` | `fastmcp[apps]` dependency and static asset inclusion | Done |
| `AGENTS.md` | `cairn_studio` documented as the human reading entry point | Done |

## Testing Approach

The non-supporting host path has unit test coverage in `tests/unit/test_tools_studio.py`,
asserting that `structured_content` carries `write_prefix` and `artifacts` keys.

The MCP App iframe path (supporting hosts) is shipped and served correctly. Practical testing
is limited by iframe rendering constraints: the view-switching interface is too small to use
in the current iframe environment of Claude Desktop and claude.ai.

Quality gates (all passing):
- `uv run pytest tests/unit/ -q -m 'not integration'`
- `uv run ruff check src/ tests/`
- `uv run ruff format --check src/ tests/`
- `uv run mypy src/`

## Implementation Notes

`cairn-studio.html` is a self-contained HTML/JS application using:
- System-UI font stack (no web fonts; GDPR constraint)
- CDN deps: `@modelcontextprotocol/ext-apps` from `unpkg.com`; `marked.js` and `mermaid.js`
  from `cdn.jsdelivr.net`
- Single-pane view switching: list view active by default; detail view shown when
  `#app.showing-detail` class is set (CSS: `#detail-view { display: none }` toggled by class)
- Artifact list sorted by type A-Z then date newest-first
- Mermaid code fence rewrite required before `mermaid.run()` (marked produces
  `<pre><code class="language-mermaid">` but mermaid targets `.mermaid`)

The file is shipped as-is. Design refinements are not planned given the iframe rendering
constraint; the structured listing path serves the team's needs.

## Post-implementation Note

The MCP App iframe was registered and served successfully. Post-implementation testing
revealed that the iframe rendering environment in supporting hosts (Claude Desktop, claude.ai)
is too small for the view-switching interface to be practical. The primary value delivered by
`cairn_studio` is the non-supporting host path (structured artifact listing in
`structured_content`), which is the interface used by the team via Claude Code.
