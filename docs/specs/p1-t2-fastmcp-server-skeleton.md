---
type: feature-spec
feature: p1-t2-fastmcp-server-skeleton
created: 2026-05-29
status: ready
phase: 1
task: 2
---

# T2 — FastMCP Server Skeleton

<!-- SCOPE BLOCK -->

## Problem Statement

The server must have a runnable FastMCP skeleton before any tools, clients, or startup validation
can be layered on top. This task wires up the MCP transport, logging, and graceful shutdown, and
establishes the pattern that all subsequent tasks follow when adding capabilities to the server.
The skeleton must be functional enough to start and stop cleanly, but registers no MCP tools.

## User Stories

### Story 1 — Server starts, logs, and exits cleanly (P1)

When the developer runs `uv run cairn-mcp`, the server starts the stdio MCP transport, emits a
structured startup log line, and remains ready to accept MCP messages.

**Acceptance criteria:**
- Given the server is started, when it initialises, then a log line at INFO level is written to stderr stating the server name and version.
- Given the server is started, when it receives a SIGTERM or SIGINT signal, then it exits cleanly with exit code 0 and logs a shutdown message.
- Given the server is started with no MCP tools registered, when an MCP client connects and lists tools, then it receives an empty tools list without an error.

### Story 2 — Logging is structured and directed to stderr (P1)

All server log output goes to stderr, not stdout. stdout is reserved for the MCP stdio protocol.
Mixing MCP messages with log lines on stdout would corrupt the transport.

**Acceptance criteria:**
- Given the server is running, when a log line is emitted, then it goes to stderr only — never stdout.
- Given the server is running, when a log line is emitted, then it includes at minimum: timestamp, level, logger name, and message.

## Requirements

- WHEN the server starts THE SYSTEM SHALL emit an INFO log line to stderr with the server name and version before entering the MCP event loop.
- WHEN the server receives SIGTERM or SIGINT THE SYSTEM SHALL exit cleanly with exit code 0, after emitting a shutdown log line to stderr.
- WHEN the server is running THE SYSTEM SHALL write all log output to stderr; stdout is exclusively for the MCP stdio wire protocol.
- WHEN an MCP client sends a `tools/list` request THE SYSTEM SHALL respond with an empty array (no tools registered at this stage).
- WHEN the server starts THE SYSTEM SHALL use the stdio transport.

## Boundaries

**Always:**
- The FastMCP app instance is created in `server.py` — it is the sole location that names the transport. Tool implementations never reference the transport.
- All log calls use Python's standard `logging` module — no `print()` calls anywhere in the server.
- The root logger is configured once, at process start, in `__main__.py` before the server runs.
- Logging level must be configurable at runtime via a `LOG_LEVEL` environment variable (default: `INFO`). Valid values: `DEBUG`, `INFO`, `WARNING`, `ERROR`.
- The server name used in FastMCP must match the package name: `cairn-mcp`.

**Ask First:**
- Nothing — all constraints are defined by the PRD and architecture decisions.

**Never:**
- Do not write any log output to stdout — this corrupts the MCP stdio transport.
- Do not register any MCP tools in this task — that belongs to Phases 2–3.
- Do not perform any startup validation in this task — that is T5.
- Do not add transport configuration as a hardcoded constant deep in the code — the transport choice must be isolated in the server module.

<!-- IMPLEMENTATION BLOCK -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `src/cairn_mcp/server.py` | Create | FastMCP app instance, transport config, signal handling |
| `src/cairn_mcp/__main__.py` | Modify | Replace T1 stub: configure logging, call `server.run()` |

### `server.py` responsibilities

This module owns the FastMCP app object and the transport configuration. Its responsibilities:

1. **Create the FastMCP app instance.** Pass `name="cairn-mcp"` and a version string. The version
   should be read from the package metadata (`importlib.metadata.version("cairn-mcp")`), not hardcoded.
2. **Register no tools.** The tool registrations will be added in Phase 2 and 3. The file will have a clear comment: `# Tools registered in Phase 2+`.
3. **Expose a `run()` function** that `__main__.py` calls. This function calls the FastMCP server's stdio `run()` method. It also logs `"cairn-mcp vX.Y.Z starting"` before entering the event loop.
4. **Handle graceful shutdown.** FastMCP handles the event loop, but the `run()` function must ensure that a clean exit (SIGTERM/SIGINT) logs a shutdown message. In practice, FastMCP's stdio transport handles SIGINT natively — verify this and add an explicit `atexit` handler or signal handler only if FastMCP does not cover it.

### `__main__.py` responsibilities

This module is the process entry point. It must:

1. **Configure the root logger before doing anything else.**
   - Read `LOG_LEVEL` from the environment (default `"INFO"`).
   - Create a `StreamHandler` directed at `sys.stderr`.
   - Apply a formatter that outputs: `%(asctime)s %(levelname)s %(name)s %(message)s`.
   - Set this handler on the root logger.
   - This configuration must happen before any import that might trigger logging, so put it at the top of `main()`.

2. **Call `server.run()`.** After logging is configured, delegate entirely to the server module.

3. **Expose `main()` as the entry point.** The `[project.scripts]` entry in `pyproject.toml` points to `cairn_mcp.__main__:main`.

### Logging convention

- Each module that emits log lines gets its own logger via `logger = logging.getLogger(__name__)`.
- `__main__.py` configures the root logger — all module loggers inherit from it.
- Do not use the root logger directly in module code — always use `logging.getLogger(__name__)`.
- Log levels to use:
  - `DEBUG`: internal state, boto3 call details, loop iterations
  - `INFO`: startup/shutdown, significant state transitions
  - `WARNING`: recoverable issues, unexpected-but-tolerable states
  - `ERROR`: failures that cause a structured error response or a hard stop

## TDD Workflow

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

- `uv run cairn-mcp` → server starts, logs startup line to stderr, waits for input.
- `uv run cairn-mcp 2>/dev/null` → stdout receives only MCP wire protocol (no log contamination).
- `Ctrl+C` during run → server exits with code 0, logs shutdown message.
- `LOG_LEVEL=DEBUG uv run cairn-mcp` → verbose debug output on stderr.

## Open Questions

- [ ] Confirm whether FastMCP's stdio `run()` handles SIGTERM/SIGINT natively so an explicit signal handler is not needed. Check FastMCP docs or source before adding one.
