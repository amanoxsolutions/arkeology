---
type: Spec
id: p11-t43-mcp-app-infrastructure
title: T43 — MCP App Infrastructure and arkeology_studio Tool
description: Server-side infrastructure for the MCP Apps visual reading interface — fastmcp[apps] dependency, arkeology_studio tool with graceful degradation, ui://arkeology-studio/index.html resource, and HTML placeholder as package data.
tags: []
status: stable
okf_version: "0.2"
sources:
  - resource: docs/architecture-decisions/adr-2026-06-24-mcp-apps-visual-reading-interface.md
    title: MCP Apps as the Visual Reading Interface
    last_modified: 2026-07-05T00:00:00Z
  - resource: docs/planning-artifacts/requirements.md
    title: Arkeology — Requirements
    last_modified: 2026-09-24T00:00:00Z
generated:
  by: "axians-architect/claude-sonnet-4.5"
  at: 2026-06-24T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-09T18:17:40Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
---

# T43 — MCP App Infrastructure and arkeology_studio Tool

## TL;DR

Establish the server-side plumbing for the MCP Apps visual reading interface: add the
`fastmcp[apps]` dependency, register a `arkeology_studio` tool that returns a `ToolResult` whose shape
depends on host support — supporting hosts receive a short confirmation in `content` only (the
iframe loads its own artifact list on mount), while non-supporting hosts additionally receive the
artifact listing in `structured_content` so they have the data without the widget — register a
`ui://arkeology-studio/index.html` resource, and create an empty HTML placeholder that T44 will
populate. No HTML/JS is authored in this task.

## 1. Problem Statement

Arkeology developers using Claude Desktop, claude.ai, or VS Code Copilot can only read artifacts
by issuing tool calls and reading raw JSON responses in chat. The MCP Apps extension
(`io.modelcontextprotocol/ui`) makes it possible for a tool to cause a supporting host to render
a sandboxed interactive HTML application inline — no new AWS infrastructure, no separate
deployment, no auth system. Before the browser application can be built (T44), the server-side
entry point must exist: the tool that declares the UI resource URI, the resource handler that
serves the HTML, and the package data declaration so the HTML is distributed with the package.
Without T43, T44 has nowhere to plug in and cannot be tested end-to-end. All three user stories —
`arkeology_studio` in a supporting host, `arkeology_studio` always returning a `ToolResult`
regardless of host support, and the `ui://arkeology-studio/index.html` resource serving HTML — are
P1.

## 2. Rules — The arkeology_studio tool

### R1 — A supporting host receives a confirmation only, with no structured_content

When `arkeology_studio` is called from a host that supports the `io.modelcontextprotocol/ui`
extension — `ctx.client_supports_extension(UI_EXTENSION_ID)` returns `True` — the tool returns a
`ToolResult` with a short text confirmation in `content` and **no** `structured_content`
(`result.structured_content` is `None`). The iframe loads its own artifact list on mount via its
own `list_artifacts` call. Given the tool returns successfully, the host renders the
`ui://arkeology-studio/index.html` resource inline without error.

The listing is deliberately withheld from a supporting host so the model does not re-describe
artifacts the user is already viewing in the rendered widget: the model has no signal that the
widget already rendered the data inline, so a listing returned to a supporting host would make it
re-describe the artifacts in chat, duplicating what the user already sees in the UI.

### R2 — A non-supporting host also receives the listing in structured_content

When `arkeology_studio` is called and `ctx.client_supports_extension(UI_EXTENSION_ID)` is `False`,
the tool returns a `ToolResult` with a short human confirmation in `content` and the artifact
listing in `structured_content` — the `{"write_prefix": str, "artifacts": [...]}` payload — so the
non-supporting client has the data without the widget. Hosts that support
`io.modelcontextprotocol/ui` render the iframe; others display the `content` text and read the
listing from `structured_content`.

### R3 — Every call returns a valid ToolResult with a confirmation, and never raises

When `arkeology_studio` is called from any host, supporting or non-supporting, it always returns a
valid `ToolResult` with a short confirmation sentence in `content` and never raises, regardless of
whether the host supports the `io.modelcontextprotocol/ui` extension. It branches on
`ctx.client_supports_extension(UI_EXTENSION_ID)` to decide the `structured_content` payload, but
always returns that valid `ToolResult` with the confirmation in `content`.
The confirmation is `content=[TextContent(text='Arkeology Studio opened…')]` — a short human
confirmation so the model does not describe the raw JSON.

### R4 — An unexpected exception becomes an error ToolResult

When `arkeology_studio` raises an unexpected exception, the system catches it and returns an error
`ToolResult` with `is_error=True`, consistent with all other Arkeology tool outer wrappers.
`arkeology_studio` follows the `_inner` / outer wrapper pattern: the outer function catches all
exceptions; the inner function, `_arkeology_studio_inner`, does the work.

### R5 — It takes settings, s3, vectors and ctx, no bedrock, and reuses the list logic

`arkeology_studio` takes keyword-only `settings`, `s3`, `vectors` and `ctx`, and returns a
`ToolResult`. It takes no `bedrock`: it only lists artifacts and never embeds. No committed
implementation ever accepted `bedrock`; `s3` joined the signature in commit c911ae5. The normative
signature is `### arkeology_studio` under `## Symbols` in
`docs/contracts/modules/arkeology.tools.studio.md`.

`_arkeology_studio_inner` calls `_list_artifacts_inner` (imported from `arkeology.tools.list`) to
build the artifact listing — the list logic is not duplicated.

### R6 — It is registered as a tool, in register_tools()

`arkeology_studio` is a tool: it is registered via `register_tools()` in `server.py`, as an
`arkeology_studio` closure inside `register_tools()` following the existing tool registration
pattern — never in `resources.py`.

## 3. Rules — The ui://arkeology-studio/index.html resource

### R7 — The resource serves the static HTML file, read with importlib.resources

When the server starts, it exposes `ui://arkeology-studio/index.html` as a resource. When a client
reads `ui://arkeology-studio/index.html`, the handler returns a non-empty string: the HTML content
loaded from `src/arkeology/static/arkeology-studio.html` via `importlib.resources` —
`importlib.resources.files("arkeology").joinpath("static/arkeology-studio.html")` (Python 3.9+
API), not via `__file__`-relative path manipulation. No `__file__`-relative fallback is needed:
`importlib.resources` resolves the file from the editable source tree.

### R8 — register_ui_resource(app) registers it, statically and without AWS calls

The `ui://arkeology-studio/index.html` resource is registered in `resources.py` via
`register_ui_resource(app)`, a new function that mirrors the existing `register_resources`
pattern; it is called from `server.py` at module load time alongside `register_resources`; the
implementation calls it immediately after `register_resources(_app)`, matching the ordering the ADR
implies (schema resources first, then UI resource). FastMCP registration order is irrelevant for
correctness.

The resource is not registered via `register_data_resources`: data resources require live AWS
clients; the UI resource is static and must be available without AWS calls.

### R9 — The CSP declares only unpkg.com and cdn.jsdelivr.net, never a Google Fonts origin

The resource is registered with `ResourceCSP` declaring the CDN origins for the browser
application that T44 will use. `ResourceCSP` must declare **only** these origins:
`https://unpkg.com`, `https://cdn.jsdelivr.net`. **Google Fonts origins
(`https://fonts.googleapis.com`, `https://fonts.gstatic.com`) MUST NOT be declared** — loading
fonts from Google's CDN is disallowed on GDPR grounds (it exposes the user's IP to a third party).
Typography uses the `system-ui` stack or a font self-hosted under `src/arkeology/static/`; no
external font origin is ever permitted in the CSP.

The origins are hard-coded in `ResourceCSP` and documented in the ADR as accepted constants, with
no config env var for them. The accepted set is exactly `unpkg.com` + `cdn.jsdelivr.net`.

Source: adr-2026-06-24-mcp-apps-visual-reading-interface

### R10 — The MIME type is auto-resolved, never passed explicitly

The resource is registered **without** an explicit `mime_type` argument, so FastMCP resolves it to
`text/html;profile=mcp-app` automatically — FastMCP's `resolve_ui_mime_type` helper returns
`'text/html;profile=mcp-app'` for `ui://` URIs when no explicit MIME type is given. That is the
MIME type required for hosts to render the MCP App iframe rather than display raw text.

Passing `mime_type='text/html'` to `@app.resource('ui://…')` overrides this, removes the
`profile=mcp-app` suffix and breaks iframe rendering in Claude Desktop: Claude Desktop reads the
MIME type to decide whether to render the MCP App iframe, and without the profile suffix it falls
back to displaying the tool result as raw text.

## 4. Rules — Packaging and placeholder

### R11 — fastmcp[apps] is a dependency and the static directory ships as package data

`pyproject.toml` lists `fastmcp[apps]` in `dependencies`. When the package is installed,
`src/arkeology/static/` is included as package data — declared in `pyproject.toml` under
`[tool.hatch.build.targets.wheel]` so that it is included in the installed wheel — so
`arkeology-studio.html` is accessible at runtime via `importlib.resources`.

### R12 — The HTML file is a minimal placeholder; no browser application is authored here

`src/arkeology/static/arkeology-studio.html` is created as a minimal placeholder
(`<!doctype html><html><body><p>arkeology studio placeholder</p></body></html>`) — not empty, not
a full application — so the resource returns non-empty content before T44 replaces it. No HTML/JS
browser application is authored in this task; that is T44's scope.

## 5. Boundaries

**Always:**
- `arkeology_studio` follows the `_inner` / outer wrapper pattern: the outer function catches all
  exceptions; the inner function does the work (R4).
- `arkeology_studio` takes keyword-only `settings`, `s3`, `vectors` and `ctx`, returning a
  `ToolResult`; it takes no `bedrock` (R5).
- `_arkeology_studio_inner` calls `_list_artifacts_inner` (imported from `arkeology.tools.list`)
  to build the artifact listing — do not duplicate list logic (R5).
- The `ui://arkeology-studio/index.html` resource is registered in `resources.py` via
  `register_ui_resource(app)`, called from `server.py` at module load time alongside
  `register_resources` (R8).
- `ResourceCSP` declares **only** `https://unpkg.com` and `https://cdn.jsdelivr.net`; Google Fonts
  origins MUST NOT be declared, and no external font origin is ever permitted in the CSP (R9).
- The HTML file is read using
  `importlib.resources.files("arkeology").joinpath("static/arkeology-studio.html")`, not via
  `__file__`-relative path manipulation (R7).
- `src/arkeology/static/arkeology-studio.html` is created as the minimal placeholder (R12).
- Package data is declared in `pyproject.toml` under `[tool.hatch.build.targets.wheel]` so that
  `src/arkeology/static/` is included in the installed wheel (R11).
- `AGENTS.md` repository structure table gains rows for `src/arkeology/static/arkeology-studio.html`
  and `src/arkeology/tools/studio.py`.

**Ask First:**
- Whether the structured result shape on the supported path (R1) must match a specific
  MCP Apps SDK contract. The ADR leaves this open; confirm with FastMCP docs whether
  `AppConfig` mandates a specific return shape before implementing.

**Never:**
- Do not author any HTML/JS browser application in this task — that is T44's scope.
- Do not register `arkeology_studio` in `resources.py` — it is a tool; register it via
  `register_tools()` in `server.py`.
- Do not register the `ui://` resource via `register_data_resources` — data resources require
  live AWS clients; the UI resource is static and must be available without AWS calls.
- Do not use `__file__`-relative path manipulation to locate the static file — always use
  `importlib.resources`.
- Do not add a new config env var for the CDN origins — they are hard-coded in
  `ResourceCSP` and documented in the ADR as accepted constants. The accepted set is exactly
  `unpkg.com` + `cdn.jsdelivr.net`; **no Google Fonts origins** (see the GDPR note in R9).

## 6. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_studio.py` | Create | TDD Red — three tests written and confirmed failing before any implementation; uses `aws_mock`, `settings`, `s3_client`, `vectors_client_populated` fixtures from `conftest.py`; mocks `ctx` |
| `src/arkeology/tools/studio.py` | Create | `arkeology_studio` public function + `_arkeology_studio_inner`; imports `_list_artifacts_inner` from `arkeology.tools.list` |
| `tests/unit/test_resources.py` | Modify | Add test asserting `ui://arkeology-studio/index.html` resource returns non-empty string content |
| `src/arkeology/static/arkeology-studio.html` | Create | Minimal HTML placeholder — not empty, not a full application |
| `src/arkeology/resources.py` | Modify | Add `register_ui_resource(app)` function; read HTML via `importlib.resources`; decorate with `ResourceCSP` |
| `src/arkeology/server.py` | Modify | Import `browse_artifact` from `arkeology.tools.browse`; import `register_ui_resource`; call `register_ui_resource(_app)` at module load; register `arkeology_studio` closure inside `register_tools()` |
| `pyproject.toml` | Modify | Add `fastmcp[apps]` to `dependencies`; add `include` for `src/arkeology/static/` under `[tool.hatch.build.targets.wheel]` |
| `AGENTS.md` | Modify | Add rows for `src/arkeology/static/arkeology-studio.html` and `src/arkeology/tools/studio.py` in the repository structure table |

`fastmcp[apps]` facts, found by inspecting its source:

- FastMCP's `AppConfig` return shape is unconstrained — FastMCP imposes no specific return shape on
  the tool when `AppConfig` is active.
- `arkeology_studio` returns a `ToolResult` from `fastmcp.tools.base`.
- `UI_EXTENSION_ID` and `AppConfig` are both exported from `fastmcp.apps`:
  `from fastmcp.apps import AppConfig, UI_EXTENSION_ID`. `UI_EXTENSION_ID` is the string constant
  `"io.modelcontextprotocol/ui"`.
- FastMCP resolves `ctx` as a typed dependency. Declare it as `ctx: Context` (imported from
  `fastmcp`) on the inner closure registered via `@_app.tool()`.
- `ResourceCSP` is imported with `from fastmcp.apps import ResourceCSP`. It accepts
  `resource_domains: list[str]` containing the full origin strings (scheme + host, no trailing
  slash).

### Contracts

- `arkeology_studio` — `### arkeology_studio` under `## Symbols` in
  `docs/contracts/modules/arkeology.tools.studio.md`, the normative signature.

### Testing Approach

This project uses TDD. Each test file is written and confirmed failing before the implementation
file it gates is touched.

In unit tests, pass `ctx` as a `MagicMock` with
`ctx.client_supports_extension.return_value = True/False`. `importlib.resources` works correctly in
editable installs (`uv sync`); the placeholder file must exist on disk before the test runs (create
it before running the resource tests).

---

**1. `tests/unit/test_tools_studio.py`** — gates `src/arkeology/tools/studio.py`

Write and confirm all three tests fail (Red) before creating `studio.py`. Both hosting modes return
a valid `ToolResult`, but the `structured_content` payload differs by host support:

- `test_arkeology_studio_non_supporting_host_returns_tool_result` — constructs a mock `ctx` where
  `ctx.client_supports_extension(UI_EXTENSION_ID)` returns `False`; calls `arkeology_studio` with
  the standard injected dependencies; asserts `isinstance(result, ToolResult)`,
  `not result.is_error`, `result.structured_content` contains an `"artifacts"` key, and
  `result.content[0].text` mentions Arkeology Studio.
- `test_arkeology_studio_supporting_host_omits_structured_content` — constructs a mock `ctx` where
  `ctx.client_supports_extension(UI_EXTENSION_ID)` returns `True`; calls `arkeology_studio`;
  asserts `isinstance(result, ToolResult)`, `not result.is_error`,
  `result.structured_content` is `None` (deliberately omitted so the model does not re-render
  the listing), and `result.content[0].text` mentions Arkeology Studio.
- `test_arkeology_studio_exception_returns_error_tool_result` — patches `_arkeology_studio_inner` to
  raise an unexpected `RuntimeError`; calls `arkeology_studio`; asserts
  `isinstance(result, ToolResult)` and `result.is_error` is `True`, consistent with all other
  Arkeology tool outer wrappers.

**2. `src/arkeology/tools/studio.py`** — gated by `test_tools_studio.py`

Implement `arkeology_studio` — keyword-only `settings`, `s3`, `vectors` and `ctx`, returning a
`ToolResult` — and `_arkeology_studio_inner(...)`. The outer function catches all exceptions and
returns an error `ToolResult` with `is_error=True` on failure. The inner function branches on
`is_ui` (result of `ctx.client_supports_extension(UI_EXTENSION_ID)`): on a supporting host it
returns a `ToolResult` with a short confirmation sentence in `content` and **no**
`structured_content`; on a non-supporting host it calls `_list_artifacts_inner` and returns the
listing in `structured_content` as well. The listing is withheld from supporting hosts so the model
does not re-describe artifacts already shown in the widget.

---

**3. `tests/unit/test_resources.py`** (existing file) — add one test, gates `resources.py` changes

- `test_register_ui_resource_returns_non_empty_html` — calls `register_ui_resource(app)`;
  invokes the registered `ui://arkeology-studio/index.html` handler; asserts the return value
  is a non-empty string.

Write this additional test and confirm it fails (Red) before modifying `resources.py`.

**4. `src/arkeology/resources.py`** — gated by the new test in `test_resources.py`

Add `register_ui_resource(app)`. Inside, define an async resource handler decorated with
`@app.resource("ui://arkeology-studio/index.html")` and `ResourceCSP(resource_domains=[...])`.
The handler reads `arkeology-studio.html` from the `static/` directory using
`importlib.resources.files("arkeology").joinpath("static/arkeology-studio.html").read_text()`.

**5. `src/arkeology/server.py`** — gated by `test_tools_studio.py` and the `test_resources.py` addition

Import `arkeology_studio as _arkeology_studio` from `arkeology.tools.browse`. Import
`register_ui_resource` from `arkeology.resources`. Call `register_ui_resource(_app)` at module
load time alongside the existing `register_resources(_app)` call. Add the `arkeology_studio`
closure inside `register_tools()`, following the existing tool registration pattern.

---

**Green gate** — all of the following must be true before the task is declared done:

- All three tests in `test_tools_studio.py` pass.
- The new test in `test_resources.py` passes.
- All previously passing unit tests continue to pass.
- `uv run ruff check src/ tests/` is clean.
- `uv run ruff format --check src/ tests/` is clean.
- `uv run mypy src/` is clean.
- `src/arkeology/static/arkeology-studio.html` exists and is non-empty.
- `pyproject.toml` lists `fastmcp[apps]` in `dependencies` and `src/arkeology/static/` in
  `[tool.hatch.build.targets.wheel]`.

### Hand-offs

None.
