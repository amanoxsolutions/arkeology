---
type: spec
title: T43 — MCP App Infrastructure and cairn_studio Tool
description: Server-side infrastructure for the MCP Apps visual reading interface — fastmcp[apps] dependency, cairn_studio tool with graceful degradation, ui://cairn-studio/index.html resource, and HTML placeholder as package data.
tags: []
timestamp: 2026-06-24T00:00:00Z
okf_version: "0.1"
feature: p11-t43-mcp-app-infrastructure
status: complete
phase: 11
task: 43
references:
  - docs/architecture-decisions/adr-2026-06-24-mcp-apps-visual-reading-interface.md
  - docs/planning-artifacts/prd.md
authored:
  by: "architect"
  date: "2026-06-24"
revised:
  by: ""
  date: ""
---

# T43 — MCP App Infrastructure and cairn_studio Tool

<!-- SCOPE BLOCK — frozen after approval -->

## TL;DR

Establish the server-side plumbing for the MCP Apps visual reading interface: add the
`fastmcp[apps]` dependency, register a `cairn_studio` tool that returns a `ToolResult` whose shape
depends on host support — supporting hosts receive a short confirmation in `content` only (the
iframe loads its own artifact list on mount), while non-supporting hosts additionally receive the
artifact listing in `structured_content` so they have the data without the widget — register a
`ui://cairn-studio/index.html` resource, and create an empty HTML placeholder that T44 will
populate. No HTML/JS is authored in this task.

> **Design note (corrected after implementation):** on a UI-supporting host `cairn_studio`
> deliberately **omits** `structured_content`. If the listing were returned to a supporting host,
> the model — which has no signal that the widget already rendered the data inline — would
> re-describe the artifacts in chat, duplicating what the user already sees in the UI. Supporting
> hosts therefore get only the confirmation text; the iframe fetches the list itself via its own
> `list_artifacts` call on mount.

## Problem Statement

cairn-mcp developers using Claude Desktop, claude.ai, or VS Code Copilot can only read artifacts
by issuing tool calls and reading raw JSON responses in chat. The MCP Apps extension
(`io.modelcontextprotocol/ui`) makes it possible for a tool to cause a supporting host to render
a sandboxed interactive HTML application inline — no new AWS infrastructure, no separate
deployment, no auth system. Before the browser application can be built (T44), the server-side
entry point must exist: the tool that declares the UI resource URI, the resource handler that
serves the HTML, and the package data declaration so the HTML is distributed with the package.
Without T43, T44 has nowhere to plug in and cannot be tested end-to-end.

## User Stories

### Story 1 — cairn_studio in a supporting host (P1)

A developer calls `cairn_studio` from a host that supports the `io.modelcontextprotocol/ui`
extension.

**Acceptance criteria:**
- Given a host where `ctx.client_supports_extension(UI_EXTENSION_ID)` returns `True`, when
  `cairn_studio` is called, then the tool returns a `ToolResult` with a short text confirmation
  in `content` and **no** `structured_content` — the iframe loads its own artifact list on mount
  via a `list_artifacts` call.
- Given the tool returns successfully, the host renders the `ui://cairn-studio/index.html`
  resource inline without error.
- The listing is deliberately withheld from a supporting host so the model does not re-describe
  artifacts the user is already viewing in the rendered widget.

### Story 2 — cairn_studio always returns a ToolResult regardless of host support (P1)

`cairn_studio` branches on `ctx.client_supports_extension(UI_EXTENSION_ID)` to decide the
`structured_content` payload, but always returns a valid `ToolResult` with a short human
confirmation in `content`. A supporting host receives `content` only (the iframe loads its own
list); a non-supporting host additionally receives the artifact listing in `structured_content`
so the client has the data without the widget. Hosts that support `io.modelcontextprotocol/ui`
render the iframe; others display the `content` text and read the listing from
`structured_content`.

**Acceptance criteria:**
- Given any host (supporting or non-supporting), when `cairn_studio` is called, then the tool
  returns a valid `ToolResult` with a short confirmation sentence in `content` and never raises.
- Given a non-supporting host, `structured_content` carries the `{"write_prefix", "artifacts"}`
  payload; given a supporting host, `structured_content` is absent.

### Story 3 — ui://cairn-studio/index.html resource serves HTML (P1)

An MCP host fetches the `ui://cairn-studio/index.html` resource to render the browser.

**Acceptance criteria:**
- Given the resource is registered, when a client reads `ui://cairn-studio/index.html`, then
  the handler returns a non-empty string (the HTML placeholder content).
- The resource is registered with `ResourceCSP` declaring the CDN origins that T44 will use.
- The resource is registered **without** an explicit `mime_type` argument — FastMCP
  auto-resolves `ui://` URIs to `text/html;profile=mcp-app`, which is the MIME type required
  for hosts to render the MCP App iframe rather than display raw text.

## Requirements

- WHEN `cairn_studio` is called and `ctx.client_supports_extension(UI_EXTENSION_ID)` is `True`
  THE SYSTEM SHALL return a `ToolResult` with a short text confirmation in `content` and SHALL
  omit `structured_content`, so the model does not re-describe artifacts the user is already
  viewing in the rendered widget; the iframe loads its own artifact list on mount.
- WHEN `cairn_studio` is called and `ctx.client_supports_extension(UI_EXTENSION_ID)` is `False`
  THE SYSTEM SHALL return a `ToolResult` with a short human confirmation in `content` and the
  artifact listing in `structured_content` so the non-supporting client has the data.
- WHEN `cairn_studio` is called THE SYSTEM SHALL always return a valid `ToolResult` and SHALL NOT
  raise, regardless of whether the host supports the `io.modelcontextprotocol/ui` extension.
- WHEN `cairn_studio` raises an unexpected exception THE SYSTEM SHALL catch it and return an
  error `ToolResult` with `is_error=True`, consistent with all other cairn tool outer wrappers.
- WHEN the server starts THE SYSTEM SHALL expose `ui://cairn-studio/index.html` as a resource
  registered with `ResourceCSP` declaring CDN origins for the browser application.
- WHEN registering the `ui://cairn-studio/index.html` resource THE SYSTEM SHALL omit the
  explicit `mime_type` argument so FastMCP resolves it to `text/html;profile=mcp-app`
  automatically — passing `mime_type='text/html'` removes the `profile=mcp-app` suffix and
  breaks iframe rendering in Claude Desktop.
- WHEN `ui://cairn-studio/index.html` is read THE SYSTEM SHALL return the HTML content loaded
  from `src/cairn_mcp/static/cairn-studio.html` via `importlib.resources`.
- WHEN the package is installed THE SYSTEM SHALL include `src/cairn_mcp/static/` as package
  data so `cairn-studio.html` is accessible at runtime via `importlib.resources`.

## Boundaries

**Always:**
- `cairn_studio` follows the `_inner` / outer wrapper pattern: the outer function catches all
  exceptions; the inner function does the work.
- `cairn_studio` receives `settings`, `s3`, `vectors`, `bedrock` as injected dependencies,
  following the same pattern as every other cairn tool.
- `_cairn_studio_inner` calls `_list_artifacts_inner` (imported from `cairn_mcp.tools.list`)
  to build the artifact listing — do not duplicate list logic.
- The `ui://cairn-studio/index.html` resource is registered in `resources.py` via
  `register_ui_resource(app)`, a new function that mirrors the existing `register_resources`
  pattern; it is called from `server.py` at module load time alongside `register_resources`.
- `ResourceCSP` must declare **only** these origins: `https://unpkg.com`,
  `https://cdn.jsdelivr.net`. **Google Fonts origins (`https://fonts.googleapis.com`,
  `https://fonts.gstatic.com`) MUST NOT be declared** — loading fonts from Google's CDN is
  disallowed on GDPR grounds (it exposes the user's IP to a third party). Typography uses the
  `system-ui` stack or a font self-hosted under `src/cairn_mcp/static/`; no external font origin
  is ever permitted in the CSP. (Review 2026-06-29, finding C1.)
- The HTML file is read using `importlib.resources.files("cairn_mcp").joinpath("static/cairn-studio.html")` (Python 3.9+ API), not via `__file__`-relative path manipulation.
- `src/cairn_mcp/static/cairn-studio.html` is created as a minimal placeholder
  (`<!doctype html><html><body><p>cairn studio placeholder</p></body></html>`) so the
  resource returns non-empty content before T44 replaces it.
- Package data is declared in `pyproject.toml` under `[tool.hatch.build.targets.wheel]` so
  that `src/cairn_mcp/static/` is included in the installed wheel.
- `AGENTS.md` repository structure table gains rows for `src/cairn_mcp/static/cairn-studio.html`
  and `src/cairn_mcp/tools/studio.py`.

**Ask First:**
- Whether the structured result shape on the supported path (Story 1) must match a specific
  MCP Apps SDK contract. The ADR leaves this open; confirm with FastMCP docs whether
  `AppConfig` mandates a specific return shape before implementing.

**Never:**
- Do not author any HTML/JS browser application in this task — that is T44's scope.
- Do not register `cairn_studio` in `resources.py` — it is a tool; register it via
  `register_tools()` in `server.py`.
- Do not register the `ui://` resource via `register_data_resources` — data resources require
  live AWS clients; the UI resource is static and must be available without AWS calls.
- Do not use `__file__`-relative path manipulation to locate the static file — always use
  `importlib.resources`.
- Do not add a new config env var for the CDN origins — they are hard-coded in
  `ResourceCSP` and documented in the ADR as accepted constants. The accepted set is exactly
  `unpkg.com` + `cdn.jsdelivr.net`; **no Google Fonts origins** (see GDPR note above).

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_studio.py` | Create | TDD Red — three tests written and confirmed failing before any implementation; uses `aws_mock`, `settings`, `s3_client`, `vectors_client_populated` fixtures from `conftest.py`; mocks `ctx` |
| `src/cairn_mcp/tools/studio.py` | Create | `cairn_studio` public function + `_cairn_studio_inner`; imports `_list_artifacts_inner` from `cairn_mcp.tools.list` |
| `tests/unit/test_resources.py` | Modify | Add test asserting `ui://cairn-studio/index.html` resource returns non-empty string content |
| `src/cairn_mcp/static/cairn-studio.html` | Create | Minimal HTML placeholder — not empty, not a full application |
| `src/cairn_mcp/resources.py` | Modify | Add `register_ui_resource(app)` function; read HTML via `importlib.resources`; decorate with `ResourceCSP` |
| `src/cairn_mcp/server.py` | Modify | Import `browse_artifact` from `cairn_mcp.tools.browse`; import `register_ui_resource`; call `register_ui_resource(_app)` at module load; register `cairn_studio` closure inside `register_tools()` |
| `pyproject.toml` | Modify | Add `fastmcp[apps]` to `dependencies`; add `include` for `src/cairn_mcp/static/` under `[tool.hatch.build.targets.wheel]` |
| `AGENTS.md` | Modify | Add rows for `src/cairn_mcp/static/cairn-studio.html` and `src/cairn_mcp/tools/studio.py` in the repository structure table |

## Testing Approach

This project uses TDD. Each test file is written and confirmed failing before the implementation
file it gates is touched.

---

**1. `tests/unit/test_tools_studio.py`** — gates `src/cairn_mcp/tools/studio.py`

Write and confirm all three tests fail (Red) before creating `studio.py`.

Note: both hosting modes return a valid `ToolResult`, but the `structured_content` payload
differs by host support. There are now three tests:

- `test_cairn_studio_non_supporting_host_returns_tool_result` — constructs a mock `ctx` where
  `ctx.client_supports_extension(UI_EXTENSION_ID)` returns `False`; calls `cairn_studio` with
  the standard injected dependencies; asserts `isinstance(result, ToolResult)`,
  `not result.is_error`, `result.structured_content` contains an `"artifacts"` key, and
  `result.content[0].text` mentions Cairn Studio.
- `test_cairn_studio_supporting_host_omits_structured_content` — constructs a mock `ctx` where
  `ctx.client_supports_extension(UI_EXTENSION_ID)` returns `True`; calls `cairn_studio`;
  asserts `isinstance(result, ToolResult)`, `not result.is_error`,
  `result.structured_content` is `None` (deliberately omitted so the model does not re-render
  the listing), and `result.content[0].text` mentions Cairn Studio.
- `test_cairn_studio_exception_returns_error_tool_result` — patches `_cairn_studio_inner` to
  raise an unexpected `RuntimeError`; calls `cairn_studio`; asserts
  `isinstance(result, ToolResult)` and `result.is_error` is `True`, consistent with all other
  cairn tool outer wrappers.

**2. `src/cairn_mcp/tools/studio.py`** — gated by `test_tools_studio.py`

Implement `cairn_studio(settings, s3, vectors, bedrock, ctx)` and `_cairn_studio_inner(...)`.
The outer function catches all exceptions and returns an error `ToolResult` with `is_error=True`
on failure. The inner function branches on `is_ui` (result of
`ctx.client_supports_extension(UI_EXTENSION_ID)`): on a supporting host it returns a `ToolResult`
with a short confirmation sentence in `content` and **no** `structured_content`; on a
non-supporting host it calls `_list_artifacts_inner` and returns the listing in
`structured_content` as well. The listing is withheld from supporting hosts so the model does not
re-describe artifacts already shown in the widget.

---

**3. `tests/unit/test_resources.py`** (existing file) — add one test, gates `resources.py` changes

- `test_register_ui_resource_returns_non_empty_html` — calls `register_ui_resource(app)`;
  invokes the registered `ui://cairn-studio/index.html` handler; asserts the return value
  is a non-empty string.

Write this additional test and confirm it fails (Red) before modifying `resources.py`.

**4. `src/cairn_mcp/resources.py`** — gated by the new test in `test_resources.py`

Add `register_ui_resource(app)`. Inside, define an async resource handler decorated with
`@app.resource("ui://cairn-studio/index.html")` and `ResourceCSP(resource_domains=[...])`.
The handler reads `cairn-studio.html` from the `static/` directory using
`importlib.resources.files("cairn_mcp").joinpath("static/cairn-studio.html").read_text()`.

**5. `src/cairn_mcp/server.py`** — gated by `test_tools_studio.py` and the `test_resources.py` addition

Import `cairn_studio as _cairn_studio` from `cairn_mcp.tools.browse`. Import
`register_ui_resource` from `cairn_mcp.resources`. Call `register_ui_resource(_app)` at module
load time alongside the existing `register_resources(_app)` call. Add the `cairn_studio`
closure inside `register_tools()`, following the existing tool registration pattern.

---

**Green gate** — all of the following must be true before the task is declared done:

- All three tests in `test_tools_studio.py` pass.
- The new test in `test_resources.py` passes.
- All previously passing unit tests continue to pass.
- `uv run ruff check src/ tests/` is clean.
- `uv run ruff format --check src/ tests/` is clean.
- `uv run mypy src/` is clean.
- `src/cairn_mcp/static/cairn-studio.html` exists and is non-empty.
- `pyproject.toml` lists `fastmcp[apps]` in `dependencies` and `src/cairn_mcp/static/` in
  `[tool.hatch.build.targets.wheel]`.

## Implementation Notes

These questions were open at spec time and resolved by inspecting the `fastmcp[apps]` source
during T43 implementation. Recorded here for T44 and future reference.

- **FastMCP `AppConfig` return shape** — unconstrained. FastMCP imposes no specific return shape
  on the tool when `AppConfig` is active. `cairn_studio` returns a `ToolResult` (from
  `fastmcp.tools.base`) with `content=[TextContent(text='Cairn Studio opened…')]` (a short human
  confirmation so the model does not describe the raw JSON). On a **supporting** host
  `structured_content` is omitted — the model has no signal that the widget rendered the data, so
  returning the listing would make it re-describe the artifacts the user already sees; the iframe
  instead loads its own list on mount. On a **non-supporting** host `structured_content` carries
  `{"write_prefix": str, "artifacts": [...]}` so the client has the data without the widget.

- **`UI_EXTENSION_ID` and `AppConfig` import path** — both are exported from `fastmcp.apps`:
  `from fastmcp.apps import AppConfig, UI_EXTENSION_ID`. `UI_EXTENSION_ID` is the string
  constant `"io.modelcontextprotocol/ui"`.

- **`ctx` injection in FastMCP tools** — FastMCP resolves `ctx` as a typed dependency. Declare
  it as `ctx: Context` (imported from `fastmcp`) on the inner closure registered via
  `@_app.tool()`. In unit tests, pass a `MagicMock` with
  `ctx.client_supports_extension.return_value = True/False`.

- **`importlib.resources` at test time** — works correctly in editable installs (`uv sync`).
  The placeholder file must exist on disk before the test runs (create it before running the
  resource tests). No `__file__`-relative fallback is needed; `importlib.resources` resolves
  the file from the editable source tree.

- **`ResourceCSP` import path** — `from fastmcp.apps import ResourceCSP`. It accepts
  `resource_domains: list[str]` containing the full origin strings (scheme + host, no trailing
  slash).

- **`register_ui_resource` call ordering** — FastMCP registration order is irrelevant for
  correctness. The implementation calls `register_ui_resource(_app)` immediately after
  `register_resources(_app)` at module load, matching the ADR's implied ordering (schema
  resources first, then UI resource).

- **Resource MIME type must be auto-resolved** — Do not pass `mime_type='text/html'` to
  `@app.resource('ui://…')`. FastMCP's `resolve_ui_mime_type` helper returns
  `'text/html;profile=mcp-app'` for `ui://` URIs when no explicit MIME type is given. Passing
  `'text/html'` overrides this and strips the `profile=mcp-app` suffix — Claude Desktop reads
  the MIME type to decide whether to render the MCP App iframe, and without the profile suffix
  it falls back to displaying the tool result as raw text.
