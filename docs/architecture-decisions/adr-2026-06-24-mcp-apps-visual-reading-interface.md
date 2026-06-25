---
type: adr
title: MCP Apps as the Visual Reading Interface
description: Records the adoption of the MCP Apps extension (io.modelcontextprotocol/ui) as the visual reading interface for cairn artifacts, replacing the previously considered AWS-hosted SPA (Direction 4).
tags: []
timestamp: 2026-06-24T00:00:00Z
okf_version: "0.1"
status: accepted
references:
  - docs/brainstorming/brainstorming-2026-06-14-visual-reading-interface.md
  - docs/brainstorming/brainstorming-2026-06-24-mcp-apps-visual-interface.md
  - docs/architecture-decisions/adr-2026-05-29-fastmcp-framework.md
authored:
  by: architect
  date: "2026-06-24"
revised:
  by: ""
  date: ""
---

# MCP Apps as the Visual Reading Interface

## Description

cairn-mcp needs a visual reading interface so developers can browse, search, and render artifact
content without issuing raw tool calls in a chat interface. This decision records the adoption of
the MCP Apps extension as the visual reading interface and the retirement of the previously
designed AWS-hosted SPA (Direction 4).

## Status

Accepted

## Context

Prior brainstorming (2026-06-14) concluded that a visual reading interface was needed and proposed
Direction 4: an AWS-hosted SPA backed by an AgentCore Gateway MCP endpoint, CloudFront, Lambda,
and Amazon Cognito. Before implementation began, the operator discovered the MCP Apps extension
(`io.modelcontextprotocol/ui`) — an official extension of the Model Context Protocol already
supported by Claude Desktop, claude.ai, VS Code GitHub Copilot, Microsoft 365 Copilot, Cursor,
ChatGPT, Goose, and Postman.

MCP Apps allows an MCP tool to declare a UI resource URI pointing to a resource served by the
server itself. When a supporting host calls the tool, it fetches that resource and renders it as
an interactive HTML application in a sandboxed iframe within the conversation. The application
communicates bidirectionally with the host via postMessage/JSON-RPC and can call any cairn tool
(`list_artifacts`, `search_artifacts`, `read_artifact`) directly from within the iframe.

Three assumptions behind Direction 4 did not hold for this team:

1. **"Some team members don't use Claude Desktop."** — False. Every project participant uses
   Claude Code as their primary AI interface. Requiring a supporting MCP App host is no different
   from requiring Confluence access for a wiki-based documentation environment.

2. **"Reading artifacts without an active session is required."** — Not a stated constraint.
   Reading an ADR while working on a project presupposes Claude Code is already running.

3. **"FastMCP has no MCP Apps support."** — False. FastMCP ships first-class MCP Apps support
   via the `fastmcp[apps]` optional dependency. `AppConfig(resource_uri=...)` on `@mcp.tool()`
   sets the `_meta.ui.resourceUri` field natively; `ResourceCSP(resource_domains=[...])` allows
   loading CDN-hosted dependencies (mermaid.js, ext-apps SDK) without a JS build pipeline.

## Decision

We adopt MCP Apps (`io.modelcontextprotocol/ui`) as the visual reading interface for cairn-mcp.
A `cairn_studio` tool declares a UI resource URI; calling the tool from a supporting host renders
an interactive artifact browser inline. The browser calls the existing `list_artifacts`,
`search_artifacts`, and `read_artifact` tools directly — no new backend, no new scope gate, no
new AWS infrastructure.

Direction 4's CloudFront SPA component is retired. Direction 4's surviving motivation —
Streamable HTTP transport for Workflow subagent parallelisation — remains open in the transport
strategy brainstorm as a separate, orthogonal decision.

Obsidian + Remotely Save is demoted from a project-shipped feature to a per-developer personal
preference. cairn-mcp does not own or configure Obsidian synchronisation.

## Alternatives Considered

| Option | Pros | Cons |
|--------|------|------|
| **Chosen** — MCP Apps (`fastmcp[apps]`) | No new AWS infrastructure; scope gate unchanged (existing tool calls from within the iframe); works over stdio today; future Streamable HTTP adds claude.ai web support; FastMCP first-class support | Requires a supporting MCP App host; rendering experience constrained to sandboxed iframe; CDN dependency at runtime |
| Direction 4 — CloudFront SPA + AgentCore Gateway + Cognito | Accessible without active Claude session; full browser rendering freedom | Significant AWS infrastructure cost and operational overhead; separate auth model; scope gate logic duplicated in Lambda; all of this was motivated by an assumption (team members not using Claude Code) that is false |
| TUI companion (``, `cairn read`) | Works from any terminal; no server changes | Terminal-only; no markdown or mermaid rendering; no benefit over existing tool calls for this team |
| Obsidian + Remotely Save (team-shipped feature) | Rich markdown and mermaid rendering; works offline and outside active sessions | Pull-only sync (no real-time); per-developer setup overhead; not a project-level concern for this team |

## Consequences

- **Added dependency**: `fastmcp[apps]` optional extra. The server requires it for MCP App tool
  and resource registration.

- **New tool**: `cairn_studio` follows the existing `src/cairn_mcp/tools/studio.py` →
  `register_tools()` convention.

- **New static asset**: `src/cairn_mcp/static/cairn-studio.html` — a self-contained HTML/JS
  application distributed as Python package data. No Node.js or Vite required at runtime;
  external dependencies loaded from CDN origins declared via `ResourceCSP`.

- **Graceful degradation**: hosts that do not support the `io.modelcontextprotocol/ui` extension
  receive a plain-text artifact listing. No breaking change to existing non-supporting clients.

- **Direction 4 retired**: no CloudFront, no AgentCore Gateway, no Cognito pool, no Lambda
  function, no separate deployment pipeline. The Streamable HTTP transport discussion remains
  alive as a separate concern for Workflow parallelisation.

- **Scope gate unchanged**: the browser calls existing cairn tools; all scope, tier, and
  visibility enforcement is inherited automatically from the tool layer. No new gate logic is
  needed.

- **CDN dependency at runtime**: the browser loads the MCP Apps ext-apps SDK and mermaid.js
  from external CDNs. An air-gapped environment would require self-hosted CDN alternatives or
  inlined assets; this is an accepted constraint for the current team environment.

- **In-session only**: the MCP App renders within an active MCP session. Developers who want
  offline artifact access can configure Obsidian + Remotely Save independently.

- **Relation to the FastMCP ADR**: this decision extends, not replaces,
  `adr-2026-05-29-fastmcp-framework.md`. The FastMCP framework choice is unchanged;
  `fastmcp[apps]` is an additive optional dependency layer on top of the existing framework. The
  note in that ADR about stdio being the only transport is unaffected — MCP Apps works over the
  existing stdio transport.
