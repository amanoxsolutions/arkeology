---
type: spec
title: T44 — Browser UI (HTML/JS)
description: Feature spec for building the self-contained cairn-studio.html MCP App — a single-pane visual artifact browser with list/detail view switching, faceted filtering, artifact sort order (type A→Z then date newest-first), semantic search, and markdown/mermaid rendering served as a static asset over the MCP Apps extension.
tags: []
timestamp: 2026-06-24T00:00:00Z
okf_version: "0.1"
feature: p11-t44-browser-ui
status: ready
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
  date: "2026-06-24"
---

# T44 — Browser UI (HTML/JS)

<!-- SCOPE BLOCK — frozen after approval -->

## TL;DR

Build `src/cairn_mcp/static/cairn-studio.html` — the self-contained HTML/JS MCP App that
becomes the single-pane visual artifact browser with list/detail view switching rendered inline
when a developer calls `cairn_studio` from a supporting host (Claude Desktop, claude.ai, VS Code
Copilot). The file loads three CDN libraries (MCP Apps ext-apps SDK, marked.js, mermaid.js) and
one Google Font, uses bidirectional MCP tool calls (`list_artifacts`, `read_artifact`,
`search_artifacts`) via the ext-apps SDK, and follows an approved dark design system based on CSS
custom properties. This task also adds the `cairn_studio` tool entry to `SERVER-REFERENCE.md`
and a one-sentence mention of `cairn_studio` to `AGENTS.md`.

## Problem Statement

As of T43, the server registers the `cairn_studio` tool and the `ui://cairn-studio/index.html`
resource, but the HTML file at `src/cairn_mcp/static/cairn-studio.html` is a placeholder.
Calling `cairn_studio` from Claude Desktop returns a populated tool result but renders an empty
frame. Developers must fall back to raw tool calls — `list_artifacts`, `search_artifacts`,
`read_artifact` — to browse their artifact store, which is verbose and context-consuming. T44
replaces the placeholder with the full interactive browser application, giving developers a
single-command visual entry point into their artifact memory.

## User Stories

### Story 1 — Developer opens the artifact browser (P1)

A developer in Claude Desktop calls `cairn_studio` and wants to immediately see a populated
list of their active artifacts.

**Acceptance criteria:**
- Given the host supports the `io.modelcontextprotocol/ui` extension, when `cairn_studio` is
  called, then the browser UI iframe is rendered with an artifact list populated from the
  initial `cairn_studio` tool result data.
- Given the list view loads, when the page is first rendered, then no artifact is selected
  and the detail view shows the empty-state prompt until the user makes a selection.

### Story 2 — Developer applies faceted filters (P1)

A developer wants to narrow the list to artifacts of a specific type or tier.

**Acceptance criteria:**
- Given the browser is open, when the developer changes the type, tier, or status dropdown,
  then the UI calls `list_artifacts` with the selected filters and refreshes the list view
  with the returned results.
- Given the status dropdown, when the page loads, then the default status is `active`.

### Story 3 — Developer reads an artifact (P1)

A developer selects an artifact from the list view and reads its full content.

**Acceptance criteria:**
- Given an artifact is selected, when the selection changes, then the UI calls `read_artifact`
  with that artifact's ID and renders the returned markdown content in the detail view using
  `marked.parse()`.
- Given the rendered content contains mermaid code fences, when rendering is complete, then
  `mermaid.run()` is called and diagrams are displayed.
- Given a rendering error occurs (malformed markdown or mermaid syntax error), when the error
  is caught, then the raw content is displayed as plain text and the iframe does not crash.

### Story 4 — Developer performs semantic search (P1)

A developer enters a query in the search box to find semantically relevant artifacts.

**Acceptance criteria:**
- Given a non-empty query is submitted, when the developer submits the search form, then the
  UI calls `search_artifacts` with the query text and replaces the list view listing with the
  ranked results.
- Given a search is active, when the developer clears the search box (empty value or explicit
  clear), then the filter-based listing is restored by re-calling `list_artifacts` with the
  current filter values.

## Requirements

- WHEN the browser application loads THE SYSTEM SHALL populate the list view with artifact
  listing data received from the `cairn_studio` initial tool result without issuing an
  additional tool call on startup; no artifact SHALL be selected and the detail view SHALL
  display the empty state until the user makes a selection.
- WHEN a type, tier, or status filter changes THE SYSTEM SHALL call `list_artifacts` with
  the selected filter values and replace the list view listing.
- WHEN an artifact is selected in the list view THE SYSTEM SHALL call `read_artifact` with
  that artifact's identifier and render the returned content in the detail view.
- WHEN the artifact list is rendered THE SYSTEM SHALL sort artifacts by type ascending (A→Z),
  then by date descending (newest first) within each type.
- WHEN `read_artifact` returns content THE SYSTEM SHALL render markdown via `marked.parse()`
  and then call `mermaid.run()` to render any mermaid diagrams present.
- WHEN a non-empty search query is submitted THE SYSTEM SHALL call `search_artifacts` with the
  query text and replace the list view listing with the ranked results.
- WHEN the search input is cleared THE SYSTEM SHALL restore the filter-based listing by
  re-calling `list_artifacts` with the current filter values.
- WHEN a markdown or mermaid rendering error is caught THE SYSTEM SHALL display the raw
  content as plain text fallback; the iframe MUST NOT crash.
- WHEN no artifact is selected (on load or after an empty-result filter) THE SYSTEM SHALL
  display a centred empty-state message in the detail view rather than a blank pane.
- WHEN the browser is rendered THE SYSTEM SHALL apply the approved design system (CSS custom
  properties, single-pane layout with view switching, toolbar, type colour mapping,
  glassmorphism focus effect) exactly as specified below.
- WHEN `prefers-reduced-motion` is active THE SYSTEM SHALL suppress the animated gradient
  accent rule on the toolbar.

## Boundaries

**Always:**
- All CSS and JS live in the single `src/cairn_mcp/static/cairn-studio.html` file — no
  companion `.css` or `.js` files.
- External dependencies are loaded only from the four declared CDN origins: `unpkg.com`
  (ext-apps SDK), `fonts.googleapis.com` + `fonts.gstatic.com` (Inter font),
  `cdn.jsdelivr.net` (marked.js and mermaid.js). No other external origins.
- No JS build step, no Vite, no bundler — the file must work as-is in a browser sandbox.
- The CSS design system (all `--c-*`, `--g`, `--g90`, base palette tokens, layout structure)
  is defined exclusively as CSS custom properties in `:root`, enabling future extraction to an
  AWS-hosted SPA as a single CSS block with no token value changes.
- All 15 artifact types from `ARTIFACT_TYPES` in `src/cairn_mcp/artifact.py` must be
  represented in the type colour mapping and the type dropdown. The canonical list is:
  `adr`, `prd`, `spec`, `plan`, `runbook`, `changelog`, `implementation_note`, `code_review`,
  `decision_note`, `postmortem`, `brainstorming`, `session_summary`, `learning`, `synthesis`,
  `bug_report`.
- The design system is pre-approved; implement it precisely. Token values are not negotiable.

**Ask First:**
- Whether the type dropdown should display raw type key strings (e.g. `implementation_note`)
  or humanised labels (e.g. `Implementation Note`). Default assumption: humanised labels
  with the raw value as the `<option value>`.
- Whether an "All types" / "All tiers" default option should be present in each dropdown to
  allow unfiltered listing. Default assumption: yes, with `value=""` that omits the filter
  parameter from the `list_artifacts` call.

**Never:**
- Do not make any Python source code changes in this task — T43 has already established all
  server-side infrastructure; T44 is HTML/JS only.
- Do not introduce any new MCP tool or resource — only call existing tools via the ext-apps SDK.
- Do not inline CDN library source code — load them via `<script src>` tags only.
- Do not add a build step, `package.json`, or any Node.js artefact.
- Do not modify `pyproject.toml`, `server.py`, `resources.py`, `studio.py`, or any Python file.
- Do not write to stdout — this constraint applies to Python code but is noted here to
  prevent inadvertent JS `console.log` calls that could interfere with the MCP stdio transport
  in edge cases; use `console.error` for debug output if needed.

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `src/cairn_mcp/tools/studio.py` | Modify | Update `_cairn_studio_inner` supporting-host path to return `{ "write_prefix": settings.write_prefix, "artifacts": result["artifacts"] }` instead of the bare `_list_artifacts_inner` result. Update the corresponding unit test in `tests/unit/test_tools_studio.py` to assert the `write_prefix` key is present. |
| `src/cairn_mcp/static/cairn-studio.html` | Replace | Replace T43 placeholder with the full application |
| `SERVER-REFERENCE.md` | Modify | Add `cairn_studio` tool entry to the Tools table; add a new "MCP App — Visual Browser" subsection after the data resources section describing the tool, its parameters (none required), return value (browser UI on supporting hosts / plain-text listing on others), and a one-line usage example |
| `AGENTS.md` | Modify | Add one sentence to the Overview paragraph mentioning `cairn_studio` as the human reading entry point alongside the existing tool list |

No Python source files are touched. `ruff`, `mypy`, and the unit test suite must remain clean
after this task — since no Python changes occur, these gates are verified by running them and
confirming no regressions were introduced by side effects of the HTML file landing in the
package.

## Testing Approach

This project uses TDD. However, T44 delivers only a static HTML/JS asset and two documentation
edits — there is no Python business logic to unit test. The done conditions serve as the
verification checklist in place of automated tests:

1. **Manual smoke test in Claude Desktop** — call `cairn_studio` with a live cairn deployment;
   confirm the browser iframe renders with a populated artifact list, artifact selection renders
   markdown and mermaid, and search returns ranked results that restore on clear.

2. **Regression gate** — run `uv run pytest tests/unit/ -q -m 'not integration'`,
   `uv run ruff check src/ tests/`, `uv run ruff format --check src/ tests/`, and
   `uv run mypy src/` after T44 changes land; all must pass with zero new failures (since no
   Python was modified, this is a regression safety check only).

3. **Degradation gate** — call `cairn_studio` from a non-supporting host (e.g. MCP Inspector);
   confirm a plain-text artifact listing is returned without error (this behaviour is already
   tested in T43's unit tests; T44 must not break it).

## Design System — Implementation Reference

> **Visual reference:** open [`docs/specs/p11-t44-browser-ui-design.html`](p11-t44-browser-ui-design.html)
> in a browser before reading this section. It is a standalone HTML preview showing the
> approved colour palette, the animated spectrum accent strip, all 15 artifact type chips,
> glassmorphism stat panels, and a full single-pane browser mockup with real artifact data. The spec
> below is the normative source of truth; the HTML file is the visual companion.

Implement the following design tokens and layout rules precisely. This section is a
normative reference; the agent must not deviate from token values or structural rules.

### CSS Tokens (`:root`)

```
--base: #09091a
--surface: #12142a
--surface-up: #1a1d3a
--surface-hi: #222548
--bd-faint: rgba(148,158,220,0.07)
--bd: rgba(148,158,220,0.13)
--bd-strong: rgba(148,158,220,0.22)
--t1: #e2eaff
--t2: #8390bc
--t3: #404870
--mono: "SF Mono","Cascadia Code","Fira Code",ui-monospace,monospace
--g:   linear-gradient(135deg, #00d4b8, #0088ff 33%, #8844ee 66%, #e800b0)
--g90: linear-gradient(90deg,  #00d4b8, #0088ff 33%, #8844ee 66%, #e800b0)
```

### Artifact Type Colour Tokens

```
--c-adr: #00d4b8     --c-prd: #00bccc     --c-spec: #00a0e0
--c-plan: #0088f8    --c-runbook: #1a66ee  --c-changelog: #3344ee
--c-impl: #5533ee    --c-cr: #7733ee       --c-dn: #9933dd
--c-pm: #bb33cc      --c-brain: #cc22bb    --c-ss: #dd11aa
--c-learn: #e80088   --c-synth: #f00077    --c-bug: #f50060
```

Type-to-token mapping (canonical):
- `adr`→`--c-adr`, `prd`→`--c-prd`, `spec`→`--c-spec`, `plan`→`--c-plan`,
  `runbook`→`--c-runbook`, `changelog`→`--c-changelog`, `implementation_note`→`--c-impl`,
  `code_review`→`--c-cr`, `decision_note`→`--c-dn`, `postmortem`→`--c-pm`,
  `brainstorming`→`--c-brain`, `session_summary`→`--c-ss`, `learning`→`--c-learn`,
  `synthesis`→`--c-synth`, `bug_report`→`--c-bug`

### Typography

- Body: Inter (weights 300–700 from Google Fonts); fallback `system-ui, -apple-system, sans-serif`
- Monospace: `var(--mono)`
- Base: `font-size: 14px`, `line-height: 1.6`, `-webkit-font-smoothing: antialiased`

### Layout

Single-pane with view switching. Full viewport height (`height: 100vh`). `html, body` use
`overflow: hidden`; the `#app` container is a flex column with `overflow: hidden`.

**Toolbar** (56px height):
- Background `var(--surface)`, 1px bottom border `var(--bd-faint)`
- Animated 1px gradient accent rule as `::after` on the bottom edge: `background: var(--g90)`,
  `background-size: 200% 100%`, `animation: gb 10s ease infinite` on `background-position`;
  suppressed when `prefers-reduced-motion: reduce` is active
- Logo text "cairn" with `background: var(--g)`, `background-clip: text`,
  `-webkit-background-clip: text`, `color: transparent`
- Search input `flex: 1`; on focus: `box-shadow` using the spectrum accent colour at 0.18 opacity
- Right-aligned scope label showing `WRITE_PREFIX` value from the initial tool result data
- Search placeholder colour: `var(--t2)` (#8390bc) — never `var(--t3)` which is near-invisible
  on `var(--base)`

**List view** (`#list-view`, active by default):
- Full remaining height, flex column, `overflow: hidden`
- Filters bar: three `<select>` elements — type (all 15 types + "All types"), tier ("2", "3",
  "All tiers"), status ("active" default, "inactive", "All")
- Artifact list (`#artifact-list`): `display: flex; flex-direction: column; overflow-y: auto`
  - Each `.li` item has `flex-shrink: 0` — items always render at natural height; the container
    scrolls rather than compressing items
  - Item structure: 4px left colour stripe using the artifact's type colour; type badge chip
    with semi-transparent type-colour background, type-colour text, `font-family: var(--mono)`,
    uppercase; title in `var(--t1)` with ellipsis overflow; date + tier in `var(--t3)`
  - Active (selected) item: background `var(--surface-hi)`, border `1px solid var(--bd)`
  - List sort order: type ascending (A→Z), then date descending (newest first) within each type
    — applied inside `renderList()` before any DOM manipulation

**Detail view** (`#detail-view`, shown when `#app.showing-detail` class is set):
- Full height, flex column, `overflow: hidden`
- Back bar (48px): "All artifacts" button that removes `showing-detail` class and clears selection
- Document body (`#detail-body`): `overflow-y: auto`, `background: var(--base)`, `padding: 24px`
  - Selected artifact view: type name eyebrow in type colour, H1 title in `var(--t1)`, metadata
    pill row (tier, date, scope, status)
  - Markdown rendered content: `<h2>` with `border-bottom: 1px solid var(--bd-faint)`;
    `<p>` in `var(--t2)`; `<code>` with `background: var(--surface)`, `color: var(--c-spec)`;
    `<table>` with consistent border and padding
- Empty state: centred message in `var(--t3)` shown until first artifact selection

### JavaScript Behaviour

**SDK initialisation:**
- Import the ext-apps SDK from `https://unpkg.com/@modelcontextprotocol/ext-apps/app-with-deps`
  (the bundled build — includes all dependencies)
- Construct the app: `const app = new App({ name: "cairn studio", version: "1.0.0" })`
- Set `app.ontoolresult` **before** calling `app.connect()` — the callback fires with the
  initial `cairn_studio` result when the iframe loads
- Call `app.connect()` to complete the handshake

**Initialisation** (via `app.ontoolresult`):
- The callback receives `{ content, structuredContent }` where `content` is an array of
  `ContentBlock` and `structuredContent` is the structured payload (if present)
- Parse the initial artifact listing from:
  `structuredContent ?? JSON.parse(content?.find(c => c.type === "text")?.text ?? "{}")`
- Note: `content` will contain a short human confirmation sentence (e.g. `"Cairn studio
  opened — N artifacts available…"`); the actual data is always in `structuredContent`.
  The parse pattern handles both cases safely.
- The parsed object has shape `{ write_prefix: string, artifacts: ArtifactMetadata[] }` — see Initial Data Format below
- Display `write_prefix` as the scope label in the toolbar
- Render the list view from `artifacts`
- Show the empty state in the detail view; no artifact is selected or fetched on load

**Calling tools** (all subsequent tool calls):
- Use `await app.callServerTool({ name: "tool_name", arguments: { ...params } })`
- The return value has the same `{ content, isError, structuredContent }` shape as `ontoolresult`
- Omit filter parameters with empty string values from `list_artifacts` arguments

**Filter changes:**
- On any filter `<select>` change: call
  `app.callServerTool({ name: "list_artifacts", arguments: { status, type, tier } })`
  (omit empty string values); re-render the list view

**Artifact selection:**
- On item click: call `app.callServerTool({ name: "read_artifact", arguments: { artifact_id: id } })`;
  render content with `marked.parse(content)`, then run the mermaid DOM rewrite and call `mermaid.run()`

**Search:**
- On non-empty form submit: call `app.callServerTool({ name: "search_artifacts", arguments: { query } })`;
  replace list view with ranked results
- On clear (empty input value): re-call `list_artifacts` with current filter values;
  restore the filter-based listing

**Mermaid rendering** (always in this order after `marked.parse()`):
1. Call `mermaid.initialize({ theme: 'dark', darkMode: true })` once at page load
2. After injecting marked output into the DOM, rewrite mermaid blocks before calling `mermaid.run()`:
   `marked.parse()` produces `<pre><code class="language-mermaid">…</code></pre>`; mermaid's
   default selector targets `.mermaid`, which does not match that structure. Rewrite:
   ```js
   document.querySelectorAll('code.language-mermaid').forEach(el => {
     const pre = el.parentElement;
     pre.className = 'mermaid';
     pre.textContent = el.textContent;
   });
   await mermaid.run({ querySelector: 'pre.mermaid' });
   ```

**Graceful degradation:**
- Wrap all `marked.parse()` and `mermaid.run()` calls in try/catch; on error, display raw
  content as `<pre>` in the detail view; do not propagate the error or crash the iframe

## Implementation Notes

These questions were open at spec authoring time and resolved before implementation began.

### Ext-apps SDK API surface

- **Package:** `@modelcontextprotocol/ext-apps@1.7.4`
- **CDN bundle:** load `https://unpkg.com/@modelcontextprotocol/ext-apps/app-with-deps` — this
  is the self-contained build that includes all SDK dependencies. Do not load the bare
  `@modelcontextprotocol/ext-apps` entry which requires separate dependency loading.
- **Initialisation pattern:**
  ```js
  const app = new App({ name: "cairn  studio", version: "1.0.0" });
  app.ontoolresult = (result) => { /* parse initial data here */ };
  app.connect();  // must be called AFTER setting ontoolresult
  ```
- **Tool call signature:** `await app.callServerTool({ name: string, arguments: object })`
  — takes a single options object (not two separate arguments).
- **WRITE_PREFIX:** the ext-apps SDK does not surface `WRITE_PREFIX` in its handshake payload.
  `studio.py` has been updated (as part of T44's file changes) to include `write_prefix` in
  the supporting-host return dict alongside `artifacts`.

### Type dropdown labels

Humanised labels with the raw key as `<option value>`. Examples: "ADR" for `adr`,
"Implementation Note" for `implementation_note`, "Code Review" for `code_review`,
"Session Summary" for `session_summary`, "Bug Report" for `bug_report`. Apply title-case
with standard acronym exceptions (ADR, PRD). An "All types" option with `value=""` is
present as the first entry in each dropdown (type, tier, status); omit the corresponding
parameter from `list_artifacts` arguments when the value is `""`.

### Initial data format

`_cairn_studio_inner` returns (as updated in this task):
```json
{
  "write_prefix": "string",
  "artifacts": [
    {
      "artifact_id": "string",
      "type": "string | null",
      "team": "string | null",
      "project": "string | null",
      "tier": 2,
      "date": "string | null",
      "status": "string | null",
      "title": "string | null",
      "visibility": "string | null",
      "tags": ["string"],
      "author_role": "string | null",
      "description": "string | null",
      "source_artifacts": ["string"],
      "commit_refs": ["string"],
      "last_edited_ulid": "string | null"
    }
  ]
}
```
FastMCP may deliver this via `result.structuredContent` or as a JSON string in
`result.content[0].text`. Parse safely:
`structuredContent ?? JSON.parse(content?.find(c => c.type === "text")?.text ?? "{}")`.

**ToolResult shape:** `cairn_studio` returns a `fastmcp.tools.base.ToolResult` with `content`
(a short human-readable confirmation sentence) and `structured_content` (the
`{"write_prefix", "artifacts"}` payload above). The `content` text is intentionally minimal so
the model does not generate a verbose description of the data. The iframe reads
`structuredContent` first and falls back to parsing the text only if `structuredContent` is
absent.

### Mermaid code fence detection

`mermaid.run()` (v11.x) targets `.mermaid` by default — it does **not** auto-detect the
`<pre><code class="language-mermaid">` structure that `marked.parse()` produces. A DOM
rewrite is required before every `mermaid.run()` call (see the Mermaid rendering steps in
the JavaScript Behaviour section above).
