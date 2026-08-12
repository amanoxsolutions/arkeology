---
type: brainstorming
title: MCP Transport Strategy — stdio vs Streamable HTTP
description: Explores whether Arkeology should adopt Streamable HTTP transport alongside or instead of stdio, what it unlocks (concurrent calls, SSE progress events, multi-client), and what it costs in deployment complexity and authentication surface.
tags: []
timestamp: 2026-06-10T00:00:00Z
okf_version: "0.1"
status: in-progress
references:
  - docs/brainstorming/brainstorming-2026-06-01-write-performance.md
authored:
  by: "pm"
  date: "2026-06-10"
revised:
  by: ""
  date: ""
techniques_used: []
assumptions_challenged: []
decisions_locked: []
decisions_pending:
  - D1: Should Arkeology support Streamable HTTP transport?
  - D2: Should stdio remain the primary/only transport, or should HTTP become the default?
  - D3: Does Streamable HTTP eliminate the need for the description_concurrency parameter on migrate_artifacts?
decisions_closed_not_applicable: []
---

# MCP Transport Strategy — stdio vs Streamable HTTP

## Description

Arkeology currently runs exclusively over stdio transport, which serialises all
MCP tool calls through a single pipe. This session explores whether switching to (or
adding) Streamable HTTP transport — which FastMCP already supports with a one-line
change — is the right move, what it unlocks (concurrent calls, SSE progress events,
multi-client), and what it costs (deployment complexity, authentication surface,
client config changes).

The question was triggered by two concrete pain points in the `migrating-to-arkeology`
skill: (A) no progress feedback during long bulk operations, and (B) slow description
generation due to low server-side concurrency. The prior write-performance brainstorm
(Session 4) already established that sub-agent parallelism does not work over stdio
due to shared connection topology.

---

## Session 2026-06-10

### Problem Statement

Two concrete pain points exposed a transport-level constraint:

- **Issue A — no progress feedback**: `migrate_artifacts` makes all Bedrock Nova Lite
  calls inside a single tool invocation and returns nothing until all descriptions are
  generated. The MCP stdio transport has no way to push intermediate results. With 95
  artifacts the operator sees silence for minutes.

- **Issue B — serialised sub-agent calls**: the write-performance brainstorm (Session 4)
  confirmed that sub-agents spawned via the `task` tool share the parent's MCP stdio
  connection. Concurrent `write_artifact` or `migrate_artifacts` calls from sub-agents
  are serialised through the pipe; only LLM inference parallelises. Z1 (`write_artifacts`
  bulk tool) was chosen as the workaround — moving all parallelism server-side within a
  single call.

**Streamable HTTP** (MCP spec 2025-06-18) changes the picture:

- Each tool call is an independent HTTP POST; the server handles them concurrently.
- The server MAY open an SSE stream in response to a POST and push progress events
  before returning the final JSON-RPC response.
- FastMCP already supports `transport="http"` — one-line change in `__main__.py`.
- Multiple clients (or multiple sub-agents acting as independent clients) can connect
  simultaneously.

The question: should Arkeology adopt Streamable HTTP, and if so, on what terms?

### Known Constraints

| Constraint | Source |
|---|---|
| FastMCP `transport="http"` is already available, no framework change | FastMCP docs |
| stdio is what every MCP client (Claude Desktop, opencode, Cline, etc.) configures by default | MCP spec — "Clients SHOULD support stdio whenever possible" |
| Streamable HTTP requires the server to be addressable at a URL (port, host) | MCP spec |
| Authentication is not handled by the MCP protocol itself — servers must implement it | MCP spec security warning |
| `migrate_artifacts` description concurrency is bottlenecked at `ARTIFACT_CONCURRENCY=3` regardless of transport | Our code analysis |
| L1 sub-agent write parallelism was already confirmed non-functional over stdio (Session 4) | write-performance brainstorm |

### Ideas Explored

<!-- To be filled in during the brainstorming session -->

### Clusters

<!-- To be filled in during the brainstorming session -->

### Selected Directions

<!-- To be filled in during the brainstorming session -->

### Challenges

<!-- To be filled in during the brainstorming session -->

### Open Questions

<!-- To be filled in during the brainstorming session -->
