---
type: Spec
id: p1-t2-fastmcp-server-skeleton
title: T2 — FastMCP Server Skeleton
description: Feature spec for wiring up a runnable FastMCP server skeleton with stdio transport, structured logging to stderr, and graceful shutdown.
tags: []
status: stable
okf_version: "0.2"
generated:
  by: "axians-architect/unknown"
  at: 2026-05-29T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-10T05:48:47Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
---

# T2 — FastMCP Server Skeleton

## TL;DR

A runnable FastMCP server skeleton: `uv run arkeology` starts the server on the stdio MCP transport,
logs only to stderr, and exits cleanly on SIGTERM/SIGINT, with no MCP tools registered. It establishes
the pattern all subsequent tasks follow when layering tools, clients and startup validation onto the
server.

## 1. Problem Statement

The server must have a runnable FastMCP skeleton before any tools, clients, or startup validation can
be layered on top. This task wires up the MCP transport, logging, and graceful shutdown, and
establishes the pattern that all subsequent tasks follow when adding capabilities to the server. The
skeleton must be functional enough to start and stop cleanly, but registers no MCP tools. Every rule
in this spec is priority P1.

## 2. Rules — Startup and shutdown

### R1 — The server starts on the stdio transport

When the developer runs `uv run arkeology`, the server starts using the stdio MCP transport and
remains ready to accept MCP messages.

### R2 — Startup log line

When the server starts, it writes a structured log line at INFO level to stderr stating the server
name and version — `arkeology vX.Y.Z starting` — before entering the MCP event loop.

### R3 — Clean shutdown on SIGTERM or SIGINT

When the server receives a SIGTERM or SIGINT signal, it exits cleanly with exit code 0, after
emitting a shutdown log line to stderr.

## 3. Rules — MCP tools

### R4 — Empty tools list

When an MCP client connects and sends a `tools/list` request, the server responds with an empty
tools array, without an error — no MCP tools are registered at this stage.

## 4. Rules — Logging

### R5 — All log output goes to stderr, never stdout

While the server is running, every log line it emits goes to stderr only — never stdout. stdout is
reserved exclusively for the MCP stdio wire protocol: mixing log lines with MCP messages on stdout
would corrupt the transport.

### R6 — Log lines are structured

Every log line the server emits includes at minimum: a timestamp, the level, the logger name, and
the message.

## 5. Boundaries

**Always:**
- The FastMCP app instance is created in `server.py` — it is the sole location that names the
  transport. Tool implementations never reference the transport.
- All log calls use Python's standard `logging` module — no `print()` calls anywhere in the server.
- The root logger is configured once, at process start, in `__main__.py` before the server runs.
- Logging level must be configurable at runtime via a `LOG_LEVEL` environment variable (default:
  `INFO`). Valid values: `DEBUG`, `INFO`, `WARNING`, `ERROR`.
- The server name used in FastMCP must match the package name: `arkeology`.

**Ask First:**
- Nothing — all constraints are defined by vision.md, requirements.md, and architecture decisions.

**Never:**
- Do not write any log output to stdout — this corrupts the MCP stdio transport.
- Do not register any MCP tools in this task — that belongs to Phases 2–3.
- Do not perform any startup validation in this task — that is T5.
- Do not add transport configuration as a hardcoded constant deep in the code — the transport choice
  must be isolated in the server module.

## 6. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `src/arkeology/server.py` | Create | FastMCP app instance, transport config, signal handling |
| `src/arkeology/__main__.py` | Modify | Replace T1 stub: configure logging, call `server.run()` |

#### `server.py` responsibilities

This module owns the FastMCP app object and the transport configuration. Its responsibilities:

1. **Create the FastMCP app instance.** Pass `name="arkeology"` and a version string. The version
   should be read from the package metadata (`importlib.metadata.version("arkeology")`), not
   hardcoded.
2. **Register no tools.** The file will have a clear comment: `# Tools registered in Phase 2+`.
3. **Expose a `run()` function** that `__main__.py` calls. This function calls the FastMCP server's
   stdio `run()` method. It also logs the R2 startup line, `"arkeology vX.Y.Z starting"`, before
   entering the event loop.
4. **Handle graceful shutdown.** FastMCP handles the event loop, but the `run()` function must ensure
   that a clean exit (SIGTERM/SIGINT) logs a shutdown message. Add an explicit `atexit` handler or
   signal handler only if FastMCP does not cover it. FastMCP does cover it — its stdio transport
   handles SIGTERM/SIGINT natively via its event loop — so no explicit signal handler is added:
   `arkeology.server.run()` delegates directly to `_app.run(transport="stdio")`, and its docstring
   records that finding.

#### `__main__.py` responsibilities

This module is the process entry point. It must:

1. **Configure the root logger before doing anything else.**
   - Read `LOG_LEVEL` from the environment (default `"INFO"`).
   - Create a `StreamHandler` directed at `sys.stderr`.
   - Apply a formatter that outputs: `%(asctime)s %(levelname)s %(name)s %(message)s`.
   - Set this handler on the root logger.
   - This configuration must happen before any import that might trigger logging, so put it at the
     top of `main()`.
2. **Call `server.run()`.** After logging is configured, delegate entirely to the server module.
3. **Expose `main()` as the entry point.** The `[project.scripts]` entry in `pyproject.toml` points
   to `arkeology.__main__:main`.

#### Logging convention

- Each module that emits log lines gets its own logger via `logger = logging.getLogger(__name__)`.
- `__main__.py` configures the root logger — all module loggers inherit from it.
- Do not use the root logger directly in module code — always use `logging.getLogger(__name__)`.
- Log levels to use:
  - `DEBUG`: internal state, boto3 call details, loop iterations
  - `INFO`: startup/shutdown, significant state transitions
  - `WARNING`: recoverable issues, unexpected-but-tolerable states
  - `ERROR`: failures that cause a structured error response or a hard stop

### Contracts

None.

### Testing Approach

T2 has very little unit-testable logic — FastMCP's stdio transport cannot be driven in a unit test
without mocking the entire MCP protocol, which adds no value here. The done condition for T2 is
manual verification, not test coverage.

**The one thing worth test-driving:** logging configuration. If you extract logging setup into a
testable function (e.g. `configure_logging(level: str) -> None`), write the test first:

1. **Red** — write a test in `tests/unit/test_config.py` (or a new `test_server.py`) that:
   - Calls `configure_logging("DEBUG")` and asserts the root logger level is `logging.DEBUG`.
   - Calls `configure_logging("INVALID")` and asserts it falls back to `INFO` (with a warning logged).
   - Asserts the root logger has exactly one `StreamHandler` directed at `sys.stderr`.

   Run `uv run pytest` — tests fail because `configure_logging` does not exist yet. ✓
2. **Green** — implement `configure_logging` in `__main__.py`. Run `uv run pytest` — tests pass. ✓
3. **Refactor** — clean up, ensure the function is still typed and mypy-clean.

Everything else in T2 (FastMCP app creation, entry point wiring, signal handling) is verified
manually:

- `uv run arkeology` → server starts, logs startup line to stderr, waits for input.
- `uv run arkeology 2>/dev/null` → stdout receives only MCP wire protocol (no log contamination).
- `Ctrl+C` during run → server exits with code 0, logs shutdown message.
- `LOG_LEVEL=DEBUG uv run arkeology` → verbose debug output on stderr.
