---
status: accepted
references: []
authored:
  by: architect
  date: "2026-05-29"
revised:
  by: ""
  date: ""
---

# FastMCP as the MCP Server Framework

## Description

cairn-mcp needs a Python library to host the Model Context Protocol server. This decision
records the choice of `fastmcp` as the MCP server framework and the rationale behind it.

## Status

Accepted

## Context

The Model Context Protocol (MCP) defines a JSON-RPC 2.0-based wire protocol between AI agents
(clients) and capability servers. Implementing this protocol from scratch requires handling
connection lifecycle, JSON-RPC dispatch, schema exposure, resource registration, and transport
management — all before any tool logic can be written. The project needed a framework that
reduced that ceremony so the team could focus on the memory-store capabilities.

At project inception the available Python options were:

- **`fastmcp`** — a high-level Python library offering a decorator-based tool and resource
  registration DSL, built-in stdio transport, and automatic JSON schema generation from
  function signatures and type hints.
- **Official Anthropic `mcp` Python SDK** — lower-level; provides protocol primitives and
  transport but requires manual tool dispatch and schema wiring.
- **Custom JSON-RPC server** — full control; no dependencies on the MCP library ecosystem
  but significant upfront implementation work.

The decision was also shaped by constraints on the logging subsystem: FastMCP logs full tool
call arguments (including artifact content) at DEBUG via its internal handler
`fastmcp.server.mixins.mcp_operations`. That logger must always be suppressed to WARNING
regardless of the configured `LOG_LEVEL`.

## Decision

We chose `fastmcp` as the MCP server framework. Tool functions are registered via the
`@_app.tool()` decorator inside the `register_tools()` function in `server.py`. Resource
definitions are registered via `register_resources()` in `resources.py`. The server starts
with `_app.run(transport="stdio")`.

## Alternatives Considered

| Option | Pros | Cons |
|--------|------|------|
| **Chosen** — `fastmcp` | Minimal boilerplate; automatic JSON schema from type hints; built-in stdio transport; active development | Hard dependency on a young library; full tool arguments logged at DEBUG — must be suppressed; limited control over protocol framing |
| Official `mcp` Python SDK | Closer to the protocol specification; more stable API surface | Significantly more boilerplate; manual schema wiring; no high-level tool registration DSL |
| Custom JSON-RPC server | Complete control; no third-party dependency | Large upfront implementation cost; duplicates solved problems; no community support |

## Consequences

- Tool registration is concise: each tool is a Python async function annotated with
  `@_app.tool()`, receiving injected clients as closure variables.
- `fastmcp` and the entire `fastmcp.*` logger hierarchy are unconditionally clamped to
  `WARNING` in `__main__.py` to prevent artifact content from appearing in logs.
- Upgrading `fastmcp` is a higher-risk dependency change than a typical library — breaking
  changes to the tool registration API would require updating `server.py` and all tool
  function signatures.
- Adding a second transport (e.g. HTTP/SSE) is limited to what `fastmcp` exposes — currently
  stdio only; HTTP transport is a future consideration (NFR-05, FR future).
