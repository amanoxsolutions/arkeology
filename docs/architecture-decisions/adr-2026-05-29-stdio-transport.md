---
status: accepted
references: []
authored:
  by: architect
  date: "2026-05-29"
revised:
  by: pm
  date: "2026-06-08"
---

# stdio as the Primary MCP Transport

## Description

The MCP protocol supports multiple transport mechanisms. This decision records the choice of
stdio (stdin/stdout) as the primary transport for cairn-mcp and documents the implications
for deployment topology and future extensibility.

## Status

Accepted

## Context

MCP clients (AI coding agents running in IDEs or terminals — Claude Code, opencode,
GitHub Copilot CLI, and OpenAI Codex) expect to launch MCP servers as child processes and
communicate over their standard input and output streams. This is the most universally
supported transport and requires zero network configuration: no port, no TLS certificate,
no firewall rule.

The alternative transports available in `fastmcp` at project inception were:

- **HTTP/SSE** — the server listens on a TCP port; clients connect via HTTP and receive
  events over Server-Sent Events. Enables a single server process to serve multiple clients
  simultaneously.
- **WebSocket** — similar to HTTP/SSE for shared deployments.

For cairn-mcp's primary use case — an AI coding agent running interactively on a developer's
machine — the agent and the server are co-located. HTTP/SSE would add a TCP port, TLS
management, and authentication that provide no value in this topology.

A secondary concern is MCP protocol safety: the stdio transport transmits JSON-RPC messages
over stdout. Any `print()` call in the server process corrupts the framing. This makes stdout
discipline a hard constraint enforced by the logging configuration (`configure_logging()` in
`__main__.py` routes all log output to stderr unconditionally).

## Decision

We chose stdio as the primary MCP transport. The server starts with
`_app.run(transport="stdio")`. All logging is routed to stderr. `print()` calls anywhere in
the server are treated as bugs.

The architecture is deliberately structured to allow additional transports to be added as a
configuration choice without rework (NFR-05): tool logic lives in `tools/*.py` independently
of the transport; `server.py` isolates the FastMCP app and transport invocation. A future
HTTP/SSE transport would add a new `run_http()` function in `server.py` and a transport
selector in `__main__.py`.

## Alternatives Considered

| Option | Pros | Cons |
|--------|------|------|
| **Chosen** — stdio | Universally supported by all MCP clients; zero network config; co-located agent + server is the primary use case | One client per server process; not suitable for shared or remote deployments; stdout discipline is a hard constraint |
| HTTP/SSE | Multiple clients can share one server process; enables remote or containerised deployment | Adds TLS, port management, and authentication overhead; not needed for the interactive local use case; not universally supported by all IDE MCP clients |
| WebSocket | Bidirectional streaming; lower overhead than SSE for high-frequency calls | Same operational overhead as HTTP/SSE; even less client support at project inception |

## Consequences

- One MCP client connects to one server process. Team members each run their own server
  instance; there is no shared in-process state.
- `print()` anywhere in the server silently corrupts the MCP message stream. The
  `_NOISY_LOGGERS` list in `__main__.py` and the `FakeBedrockClient` both route exclusively
  to `logging`, never to stdout.
- Adding HTTP/SSE transport in the future is an additive change: it does not require
  modifying any tool, domain, or client code — only `server.py` and `__main__.py`.
- CI/CD agents running in pipelines connect via the same stdio mechanism, provided the MCP
  client in the pipeline supports stdio child-process spawning.
- Because each MCP client spawns its own server process, project-scoped configuration is
  natural: Claude Code and GitHub Copilot CLI share `.mcp.json` at the workspace root
  (Copilot CLI added per-project config in v0.0.401, ≈ February 2026); opencode uses
  `opencode.json` and OpenAI Codex uses `.codex/config.toml`. All
  four clients support per-project config files that supply project-specific environment
  variables (e.g. `WRITE_PREFIX`) to the child process. This means a developer working
  across multiple projects runs multiple cairn-mcp processes, one per active project
  session, each correctly scoped to its own write prefix by the client.
