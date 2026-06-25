---
type: brainstorming
title: MCP Apps as the Visual Reading Interface for cairn-mcp
description: Evaluates MCP Apps (the official MCP interactive UI extension) as the visual reading interface for cairn artifacts, and determines whether it makes Direction 4 (AWS-hosted SPA) unnecessary.
tags: []
timestamp: 2026-06-24T00:00:00Z
okf_version: "0.1"
status: done
references:
  - docs/brainstorming/brainstorming-2026-06-14-visual-reading-interface.md
  - docs/brainstorming/brainstorming-2026-06-10-mcp-transport-strategy.md
  - https://gofastmcp.com/apps/overview
  - https://gofastmcp.com/python-sdk/fastmcp-apps-app
  - https://gofastmcp.com/apps/low-level
authored:
  by: "analyst"
  date: 2026-06-24
revised:
  by: "analyst"
  date: 2026-06-24
techniques_used:
  - inversion ("what would make MCP Apps fail for cairn?")
  - constraint-removal ("if we had to ship next week, what would block us?")
  - perspective-shift (in-session engineer vs. always-on reader)
assumptions_challenged:
  - "Readers need access to artifacts outside an active Claude session — disproved: the team works inside Claude Code; needing it open is no worse than needing Confluence open"
  - "MCP Apps requires Streamable HTTP — disproved: MCP Apps works over stdio with Claude Desktop; Streamable HTTP adds claude.ai web support but is not a prerequisite"
  - "Embedding a JS build artifact in a Python package is problematic — disproved: pre-built HTML assets as package data files is standard practice; no runtime Node.js required; furthermore a Vite build step may not be needed at all if the UI is vanilla JS with CDN-loaded dependencies"
  - "FastMCP does not support _meta.ui.resourceUri — disproved: FastMCP has first-class MCP Apps support via fastmcp[apps]; AppConfig(resource_uri=...) wires the _meta field and CSP automatically"
  - "A Vite/Node.js build pipeline is required to build the MCP App UI — disproved: FastMCP's ResourceCSP.resource_domains allows loading ext-apps SDK and mermaid.js from CDN; the UI can be a plain HTML file with vanilla JS and no build step"
decisions_locked:
  - "D1 resolved — MCP Apps is the visual reading interface for cairn-mcp. A cairn_browse tool (or equivalent) returns a bundled HTML/JS UI rendered inline in Claude Desktop / claude.ai. The UI calls existing cairn tools (list_artifacts, search_artifacts, read_artifact) directly."
  - "D2 resolved — Direction 4's CloudFront SPA component is dropped. MCP Apps covers the in-session reading need; Obsidian + Remotely Save covers outside-session reading for those who want it. No AWS-hosted reading UI will be built."
  - "D3 resolved — live semantic search is not a separate v1 requirement for the reading UI: the MCP App UI calls search_artifacts directly, which already performs vector search. Semantic search is available from day one via the existing tool."
  - "Requiring Claude Desktop (or a compatible MCP App host) to read an artifact is an acceptable constraint for this team. Every project participant uses Claude Code as their primary AI interface."
  - "Obsidian + Remotely Save is a per-developer personal preference, not a project-shipped feature. cairn-mcp will not own or configure Obsidian sync."
  - "No TUI. The reading surface is a web interface (MCP App) only."
decisions_pending:
  - "Transport orthogonality: switching to Streamable HTTP (for Workflow parallelisation and claude.ai web MCP Apps) remains open in the transport strategy brainstorm and is independent of this decision."
decisions_closed_not_applicable:
  - "FastMCP _meta compatibility — closed (2026-06-24): FastMCP ships first-class MCP Apps support via fastmcp[apps]. AppConfig(resource_uri='ui://...') on @mcp.tool() sets the _meta.ui.resourceUri field; @mcp.resource('ui://...') serves the HTML. No lower-level workaround needed."
  - "Mermaid rendering strategy — closed (2026-06-24): FastMCP's ResourceCSP(resource_domains=[...]) allows loading mermaid.js and the ext-apps SDK from CDN. No bundling required. A Vite build pipeline is not needed unless a JS framework (React/TypeScript) is desired for the UI."
  - "cairn_browse tool design (one vs two tools) — closed (2026-06-24): both cairn_browse and read_artifact can independently carry AppConfig(resource_uri=...) and use ctx.client_supports_extension(UI_EXTENSION_ID) for graceful degradation. No architectural blocker on the two-tool design; scope decision deferred to feature spec."
  - "D2 (prior) — 'Is the reading surface local or hosted in AWS?' — closed: MCP Apps (local/in-session) is the answer. AWS hosting is not needed for the reading surface."
  - "D3 (prior) — 'Is live semantic search a v1 requirement for the hosted UI?' — closed: moot. The MCP App calls search_artifacts directly; semantic search is inherited, not a separate build concern."
  - "D7 (prior) — 'Should the reading UI ship inside cairn-mcp or as a separate cairn-lens repo?' — closed: MCP Apps ships as pre-built HTML assets inside cairn-mcp. No separate repo."
---

# MCP Apps as the Visual Reading Interface for cairn-mcp

## Description

This session evaluates the MCP Apps extension (`io.modelcontextprotocol/ui`) — which lets MCP
tools return interactive HTML/JS UIs rendered inline in the host (Claude Desktop, claude.ai,
VS Code Copilot, Cursor, etc.) — as the visual reading interface for cairn artifacts. The prior
brainstorming session (`brainstorming-2026-06-14-visual-reading-interface.md`) left the web reading
surface open as "direction to be determined." This session closes it.

## Session 2026-06-24

### Problem Statement

The prior session concluded that cairn-mcp needs a visual reading interface for human readers
(list/search artifacts, apply faceted filters, select a document, render markdown and mermaid).
It identified a complex AWS-hosted direction (Direction 4: AgentCore Gateway + CloudFront SPA +
Cognito) and a lean baseline (Direction 3: MCP data resources + Obsidian). The operator
encountered the MCP Apps blog post and asked whether it achieves what Direction 4 was trying to
achieve, and how complicated it is.

### Known Constraints (inherited from prior session)

| Constraint | Source |
|---|---|
| cairn-mcp is a Python MCP server using FastMCP; no JS runtime at server runtime | AGENTS.md |
| Artifact content in S3; embeddings in S3 Vectors; embeddings via Bedrock | AGENTS.md |
| Existing tools: list_artifacts, search_artifacts, read_artifact, synthesise_artifacts — all enforce the scope gate | server.py |
| Current transport: stdio; Streamable HTTP migration open in transport strategy brainstorm | brainstorming-2026-06-10 |
| MCP data resources already registered (Surface A of Direction 3 — implemented) | resources.py |
| Everyone on the project uses Claude Code / Claude Desktop as their primary AI interface | operator signal |
| No TUI | operator decision |
| Pre-built HTML assets in the Python wheel are acceptable (JS build step at package build time only) | operator decision |

### What MCP Apps Is

MCP Apps is an official MCP extension (`io.modelcontextprotocol/ui`), not a separate product.
It lets MCP tools return interactive HTML/JS UIs that render inline in the host application.

**Mechanism:**

1. A tool declares `_meta.ui.resourceUri: "ui://cairn-browser"` in its tool description.
2. When the host calls the tool, it also fetches the `ui://cairn-browser` resource from the MCP server.
3. The server returns a self-contained bundled HTML file (produced by Vite + `vite-plugin-singlefile`).
4. The host renders the HTML in a sandboxed iframe inside the conversation.
5. The iframe communicates bidirectionally with the host via `postMessage`/JSON-RPC.
6. The UI can call any cairn tool (`callServerTool()`) — list, search, read — directly from within the iframe.

**Client support (as of 2026-06-24):** Claude.ai web ✅, Claude Desktop ✅, VS Code GitHub
Copilot ✅, Microsoft 365 Copilot ✅, Cursor ✅, ChatGPT ✅, Goose ✅, Postman ✅.

**Transport:** works over stdio (Claude Desktop). Moving to Streamable HTTP later extends support
to claude.ai web — a free upgrade, not a prerequisite.

### Ideas Explored

**Idea A — MCP Apps as the primary in-session reading UI**
A `cairn_browse` tool declares `_meta.ui.resourceUri: "ui://cairn-browser"`. Calling it opens
an interactive artifact browser inline in Claude Desktop — faceted filter pane (type/date/tags/tier),
search box, document viewer with markdown + mermaid rendering. The UI calls the existing
`list_artifacts` / `search_artifacts` / `read_artifact` tools. Zero new AWS infrastructure, no
new auth model, scope gate unchanged — identical code path to agent tool calls.

**Idea B — MCP Apps makes Direction 4's SPA obsolete**
Direction 4 was motivated by the assumption that some team members don't use Claude Desktop.
That assumption is false for this team. The CloudFront SPA component of Direction 4 is therefore
redundant. AgentCore Gateway / Streamable HTTP survives as a separate transport decision (for
Workflow subagent parallelisation), entirely orthogonal to the reading surface.

**Idea C — Two-tool design: `cairn_browse` + enriched `read_artifact`**
`cairn_browse` shows the list/search/filter UI. `read_artifact` (when called from an MCP App
context) shows a single-document reader with rendered markdown, mermaid, metadata panel, and
"open related" action. Each tool has its own `ui://` resource; tools remain independently useful
without the UI.

**Idea D — Obsidian stays as team-shipped feature, MCP Apps adds in-session layer**
Keep Obsidian + Remotely Save as a project-shipped configuration. MCP Apps adds in-session
richness on top. Maximum coverage: in-session (MCP Apps), offline/IDE (Obsidian vault).

**Idea E — Obsidian is personal preference; MCP Apps is the only project-shipped reading surface**
Drop Obsidian as a project concern. Developers who want local files can configure Remotely Save
themselves. cairn-mcp ships one reading surface: the MCP App.

### Clusters

**Cluster 1 — MCP App as the reading surface (Idea A, C):** The MCP App is the visual reading
interface. Idea C refines A into a two-tool design; decision deferred to feature spec.

**Cluster 2 — Impact on Direction 4 (Idea B):** MCP Apps makes the AWS-hosted SPA redundant.
Direction 4's only surviving motivation is Workflow parallelisation via Streamable HTTP — a
transport decision, not a UI decision.

**Cluster 3 — Obsidian role (Idea D, E):** Whether Obsidian is a project-shipped feature or
personal developer choice.

### Selected Direction

**MCP Apps is the visual reading interface.** No AWS-hosted SPA. Obsidian is per-developer
personal preference.

**Rationale:**

- Every project participant uses Claude Desktop / Claude Code. The "in-session only" constraint
  is not a real constraint: needing Claude Code open to read an ADR is no worse than needing
  Confluence open in a Confluence-based documentation environment.
- MCP Apps renders markdown and mermaid natively in the browser iframe — the two rendering
  capabilities Direction 4's SPA was designed to provide.
- The scope gate is the existing cairn tool gate — no new gate to build, no re-implementation
  in Lambda or a separate backend.
- The implementation starts with what works today and improves iteratively: even a basic faceted
  list + single-document markdown view is a significant improvement over the current state (no
  visual reading surface at all).
- Direction 4's CloudFront SPA is now doubly redundant: MCP Apps covers in-session reading,
  Obsidian + Remotely Save covers outside-session reading for those who want it. The AWS
  infrastructure, Cognito pool, and AgentCore Gateway MCP endpoint remain candidates for the
  transport/parallelisation decision — but no longer for the reading surface.

### Challenge: Inversion — What Would Make MCP Apps Fail for cairn?

**Question posed:** *What would make MCP Apps a bad choice for cairn, or even make it fail?*

**Operator answer:** It would fail if team members couldn't simply read documents without an
active Claude session — the way you can open a file in an IDE.

**Resolution:** The concern does not apply to this team. Every project participant uses Claude
Code as their primary interface; reading an artifact in Claude Desktop is the natural workflow,
not a friction point. The inversion concern is closed.

### Challenge: Constraint Removal — What Would Block Shipping This Next Week?

**Question posed:** *If we had to ship the MCP Apps reading UI inside cairn-mcp next week, what
would block us?*

Candidates surfaced and evaluated:

| Candidate blocker | Assessment |
|---|---|
| FastMCP doesn't support `_meta.ui.resourceUri` on tools | Implementation detail. May require lower-level MCP SDK access or a small workaround. Worth investigating early but not a fundamental blocker. Even a partial UI (basic list) is better than nothing. |
| Vite/Node.js build step in a Python project | Non-issue. Pre-built HTML as package data is standard. The operator already confirmed JS build toolchain is acceptable. |
| Scope isolation: MCP App always shows the session's WRITE_PREFIX scope | UX constraint, not a blocker. Same behaviour as today. Can be documented; can be improved later (e.g., scope picker). |
| Development testing without Claude Desktop | Non-issue. The ext-apps repo ships a `basic-host` test server for local development. Real rendering verified in Claude Desktop. Standard frontend development workflow. |

**Operator response:** None of these are blockers. A UI with current limitations is far better
than no UI. Can improve iteratively.

### Open Questions

- **Transport** — moving cairn-mcp to Streamable HTTP (for Workflow parallelisation + claude.ai
  web MCP Apps support) remains open in the transport strategy brainstorm. Independent of and
  not blocking this decision.

### Resolved During Session (Post-Challenge)

The following were open questions at the end of the Challenge step; all were resolved by
discovering FastMCP's native MCP Apps support (`fastmcp[apps]`, `gofastmcp.com/apps`):

| Question | Resolution |
|---|---|
| FastMCP `_meta` support | `AppConfig(resource_uri="ui://...")` on `@mcp.tool()` handles it natively. `pip install "fastmcp[apps]"` required. |
| Mermaid rendering: bundle vs CDN | `ResourceCSP(resource_domains=["https://cdn.jsdelivr.net"])` on the `@mcp.resource()` allows CDN loading. No Vite build needed for external dependencies. |
| Vite build pipeline required? | Not required. UI can be plain HTML + vanilla JS with CDN-loaded mermaid.js and ext-apps SDK. Vite is optional if a JS framework is wanted. |
| One tool vs two tools | Both `cairn_browse` and `read_artifact` can carry independent `AppConfig`; `ctx.client_supports_extension(UI_EXTENSION_ID)` gives graceful degradation. Two-tool design has no architectural blocker; scope deferred to feature spec. |
