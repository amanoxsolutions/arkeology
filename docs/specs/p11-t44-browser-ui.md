---
type: Spec
id: p11-t44-browser-ui
title: T44 — Browser UI (HTML/JS)
description: Feature spec for arkeology-studio.html — a self-contained HTML/JS single-pane view-switching artifact browser shipped as a static MCP App asset. The primary deliverable is the arkeology_studio non-supporting host path (structured artifact listing in structured_content). The MCP App iframe is registered and served but discovered post-implementation to have practical rendering constraints in supporting hosts.
tags: []
status: stable
okf_version: "0.2"
sources:
  - resource: docs/planning-artifacts/requirements.md
    title: Arkeology — Requirements
    last_modified: 2026-09-24T00:00:00Z
  - resource: docs/architecture-decisions/adr-2026-06-24-mcp-apps-visual-reading-interface.md
    title: MCP Apps as the Visual Reading Interface
    last_modified: 2026-07-05T00:00:00Z
  - resource: docs/architecture-decisions/adr-2026-08-12-studio-link-resolution.md
    title: Studio-Side Resolution of arkeology:// Links on the Human Read Surface
    last_modified: 2026-09-25T00:00:00Z
  - resource: docs/architecture-decisions/adr-2026-07-03-artifact-cross-referencing.md
    title: Artifact Cross-Referencing — First-Class references Field, Migration Rewrite, and referenced_by Warning
    last_modified: 2026-09-29T00:00:00Z
  - resource: docs/specs/p11-t43-mcp-app-infrastructure.md
    title: T43 — MCP App Infrastructure and arkeology_studio Tool
    last_modified: 2026-06-24T00:00:00Z
  - resource: https://gofastmcp.com/apps/overview
  - resource: https://gofastmcp.com/python-sdk/fastmcp-apps-app
  - resource: https://gofastmcp.com/apps/fastmcp-app
  - resource: https://gofastmcp.com/apps/low-level
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

# T44 — Browser UI (HTML/JS)

## TL;DR

T44 delivers `src/arkeology/static/arkeology-studio.html` — a self-contained HTML/JS single-pane
view-switching application shipped as a static asset and served over
`ui://arkeology-studio/index.html`, using the ext-apps SDK, marked.js, and mermaid.js loaded from
CDN (`unpkg.com`, `cdn.jsdelivr.net`), with no web fonts and no build step — and the
`arkeology_studio` tool's non-supporting host path, which, when called from Claude Code or MCP
Inspector, returns a structured artifact listing in `structured_content` with shape
`{ "write_prefix": string, "artifacts": [...] }`. That structured listing is the primary interface
for the team: the MCP App iframe (supporting hosts: Claude Desktop, claude.ai, VS Code Copilot) is
registered and served successfully, but post-implementation testing revealed that the iframe
rendering environment is too small for the view-switching interface to be practical.

## 1. Problem Statement

Developers using raw tool calls (`list_artifacts`, `search_artifacts`, `read_artifact`) to
browse the artifact store receive verbose, context-consuming output. T44 addresses this in
two ways: a structured listing returned directly by `arkeology_studio` on non-supporting hosts
(Claude Code), and an MCP App iframe browser for supporting hosts. The structured listing
path delivers value immediately; the iframe path was implemented and shipped but found to be
constrained by the iframe rendering environment in practice: in supporting hosts (Claude Desktop,
claude.ai) it is too small for the view-switching interface to be practical. The primary value
delivered by `arkeology_studio` is therefore the non-supporting host path (structured artifact
listing in `structured_content`), which is the interface used by the team via Claude Code. Design
refinements to the HTML application are not planned given the iframe rendering constraint; the
structured listing path serves the team's needs.

The studio also lets a developer reading an artifact open a resolved cross-reference in the body
text by activating it, rather than copying an identifier out and asking an agent to fetch it; gives
a developer whose scope holds several hundred artifacts a list that renders promptly, with an
explicit statement of how much of the store is on screen; and gives an agent calling
`arkeology_studio` from a host without MCP-UI support a listing sized for a context window, telling
it when it is seeing only part of the store.

The stories' priorities: developer on a non-supporting host gets a structured listing (P1);
developer on a supporting host gets an MCP App iframe (P2); reader follows a cross-reference without
leaving the studio (P1); reader browses a large store without an unbounded list (P2); agent on a
non-supporting host gets a bounded listing (P1).

The link-resolution contract is settled in `adr-2026-08-12-studio-link-resolution.md` (ADR-013) —
client-side resolution, the server gate as sole access-control authority, inert rendering for
anything unresolvable. This spec states the behaviour to build; it does not restate that ADR's
reasoning. `adr-2026-07-03-artifact-cross-referencing.md` (ADR-012) is unaffected: no stored content
changes, and mixed addressing remains correct.

## 2. Rules — The arkeology_studio tool

### R1 — A non-supporting host receives the artifact listing in structured_content

When `arkeology_studio` is called from a host that does not support the
`io.modelcontextprotocol/ui` extension (such as Claude Code or MCP Inspector), it returns a `ToolResult` with
`structured_content = { "write_prefix": settings.write_prefix, "artifacts": [...] }` from
`_list_artifacts_inner`, covering all active artifacts in the write scope, plus a short text
confirmation in `content`. The listing is returned without error and is machine-readable by the
calling agent, so a developer using Claude Code receives a structured artifact listing without
issuing separate `list_artifacts` calls.

### R2 — A supporting host receives a confirmation and the iframe pointer, with no structured_content

When `arkeology_studio` is called from a host that supports the `io.modelcontextprotocol/ui`
extension (such as Claude Desktop or claude.ai), it returns a `ToolResult` with a short text confirmation in
`content` and no `structured_content` — the iframe loads its own artifact list on mount via
`list_artifacts` — and the host receives the `_meta.ui.resourceUri` pointer to
`ui://arkeology-studio/index.html` and renders the MCP App iframe.

Post-implementation testing found the iframe rendering environment too small for the
view-switching interface to be practical. The iframe is served correctly; the rendering constraint
is a host environment limitation, not a bug in the implementation.

### R3 — A failed inner listing returns the structured error, never a listing

When the inner `list_artifacts` call's result carries `"error"`, `_arkeology_studio_inner` returns a
structured `ToolResult(is_error=True, structured_content={"error": ..., "message": ...})` — it never
coerces the result into a successful listing with `listing.get("artifacts", [])`. When the inner
listing call fails, that existing structured-error result is returned unchanged — never a capped,
reordered, or empty listing; an error is never capped, reordered, or coerced into a listing.

A credential-error dict silently coerced into a successful empty listing would make expired
credentials read as "the store is empty" instead of "the store could not be reached" — a
requirements.md FR-12 violation.

Source: FR-12

### R4 — The fallback listing holds at most 50 artifacts, newest first, with total_count

When `arkeology_studio` is called from a non-supporting host and the inner listing succeeds,
`structured_content["artifacts"]` holds at most 50 artifacts and `structured_content["total_count"]`
carries the number of artifacts matched before the cap. The fallback listing is ordered by `date`
descending, ties broken by `artifact_id` ascending, and the cap retains the head of that order — the
newest artifacts. Given a scope holding fewer artifacts than the cap, the listing is complete and
`total_count` equals the number of artifacts returned. `structured_content["write_prefix"]` is
unchanged.

The cap is held as a module-level constant in `studio.py`; it is not a new environment variable,
`Settings` field, or tool parameter. `list_artifacts` does not change — the cap applies to the
`arkeology_studio` fallback result only.

### R5 — A truncated fallback listing says so in its content text

When the cap truncates the listing, the `content` text states both numbers — how many of how many
artifacts are included — and that `list_artifacts` with filters retrieves the remainder.

## 3. Rules — The studio application

### R6 — The resource's CSP admits unpkg.com and cdn.jsdelivr.net

The `ui://arkeology-studio/index.html` resource is registered with
`ResourceCSP(["https://unpkg.com", "https://cdn.jsdelivr.net"])`.

### R7 — arkeology-studio.html is one self-contained HTML/JS file loading its libraries from CDN

`arkeology-studio.html` is a self-contained HTML/JS file with no companion `.css` or `.js` files and
no JS build step: all CSS and JS live in the single `src/arkeology/static/arkeology-studio.html`
file, with no `package.json` and no Node.js artefacts. External dependencies are loaded only from
`unpkg.com` (`@modelcontextprotocol/ext-apps`, the ext-apps SDK) and `cdn.jsdelivr.net`
(`marked.js` and `mermaid.js`), via `<script src>` tags only — no inline CDN library source. It uses the
System-UI font stack: no web fonts and no web-font origins (GDPR constraint).

### R8 — A single pane switches between the list view and the detail view

The application uses single-pane view switching: the list view is active by default; the detail
view is shown when the `#app.showing-detail` class is set (CSS: `#detail-view { display: none }`
toggled by class). The existing Back control returns the reader from the detail view to the list.

### R9 — The artifact list is sorted by type A-Z, then date newest-first

The artifact list is sorted by type A-Z, then by date newest-first.

### R10 — Mermaid code fences are rewritten before mermaid.run()

A Mermaid code fence rewrite is required before `mermaid.run()`: marked produces
`<pre><code class="language-mermaid">`, but mermaid targets `.mermaid`.

### R11 — app.ontoolresult acts only on a result whose structuredContent.artifacts is an array

`app.ontoolresult` guards on `structuredContent.artifacts` being an array before doing anything.
This iframe only ever runs in a *supporting* host, so every plain-text confirmation it receives —
including `arkeology_studio`'s own "Arkeology Studio opened…" text — carries no
`structuredContent`; an unconditional `JSON.parse(content?.find(...)?.text ?? "{}")` throws on that
plain text every time.

The application has no `#scope-label` element, DOM ref or CSS rule: `write_prefix` is sent only to
non-supporting hosts and can never reach this iframe, so no plausible correct source exists for it
in this code path.

### R12 — List loads and searches render the server's own error message

`loadList` and `doSearch` check `data.error` first and, on failure, render
`data.message || data.error` in the empty-state `<p>` — never discarding the server's actual error
message, as rendering `data.artifacts || []` or a generic `"Search failed."` would.

### R13 — The "All" status filter sends status="all"

`#sel-status`'s "All" option has the value `"all"`, and the browser's default `filterStatus` is
`"all"`; it is always sent (never omitted). `list_artifacts` (see `p3-t10-list-artifacts.md`,
revised) recognises `status="all"` as an explicit all-inclusive sentinel. With `value=""`, the
"All" option was unreachable: `loadList` only included `args.status` when `filterStatus` was
truthy, so "All" silently fell through to the server's `status="active"` default.

## 4. Rules — Link resolution

### R14 — An inert link keeps its text and does nothing

Where a link is rendered *inert*, the anchor's text content is preserved, its `href` is removed, it
is not focusable, it is not announced as a link to assistive technology, and activating it does
nothing. Its text is visibly present but carries no clickable affordance — the reader is never
offered a link that does nothing.

### R15 — An arkeology://artifact/{id} link opens that artifact in the detail view

When rendered artifact content contains a link whose target is `arkeology://artifact/{id}` with a
non-empty `{id}`, the application presents it as an activatable control that loads `{id}` into the
detail view through the same `read_artifact` call path already used when an artifact-list row is
selected. When the reader activates it, the studio's detail view shows that artifact's content and
the reader can return to the list with the existing Back control.

### R16 — The id is passed verbatim after dropping any fragment or query and one URI decode

When such a link is activated, `{id}` is passed to `read_artifact` verbatim as the full S3 key,
after discarding any `#fragment` or `?query` suffix and applying a single URI decode. If that decode
fails, the link is treated as unresolvable and rendered inert.

### R17 — A target outside the loaded result set still opens, with its id in place of the title

| Activated target | Content | Detail header | List row |
|---|---|---|---|
| Present in the currently loaded result set | Loaded and rendered | Populated from that entry, exactly as row selection does | Marked selected, exactly as row selection does |
| Absent from the currently loaded result set — filtered out, out of the reader's own scope, or beyond the rendered page | Still loaded and rendered | The artifact id in place of the title; the metadata pills it holds no value for are omitted | No list row marked selected |

### R18 — A read_artifact error shows the server's message and keeps the detail view open

If the `read_artifact` call returns an error payload, the application renders its `message`
(falling back to `error`) in the detail content area, keeps the detail view open, and leaves the
Back control available — it does not show an empty body and does not bounce back to the list. This
covers both a target the reader may not read (foreign scope, or not tier-3 shared) and a target that
no longer exists; the server distinguishes them, and the application does not substitute its own
wording, re-classify the error, or add a client-side scope, tier, visibility, or existence check
ahead of the call.

Source: adr-2026-08-12-studio-link-resolution

### R19 — Links the studio cannot open are rendered inert

The application renders inert:

- an `arkeology://` link that is not of the form `arkeology://artifact/{id}` with a non-empty
  `{id}` — including `arkeology://artifacts`, any `arkeology://schema/…` resource, and any malformed
  URI;
- a link whose target is neither `http(s)://` nor a resolvable `arkeology://artifact/{id}` — in
  particular the raw repository paths ADR-012 leaves untouched (for example `/docs/…`) — so a target
  the studio cannot open is never presented as navigable.

### R20 — An http(s) link stays navigable and opens outside the application frame

When rendered artifact content contains an `http(s)://` link, it stays navigable and opens outside
the application frame, so following it never replaces the studio.

### R21 — The sanitiser's URI allow-list is not widened, and no arkeology: href reaches the DOM

The HTML sanitiser's URI allow-list is not widened to admit the `arkeology:` scheme, and no
`arkeology:` `href` reaches the DOM; a resolvable target is carried by sanitiser-preserved inert
data that the click handler reads.

### R22 — Link treatment applies only to links rendered from artifact content

This link treatment applies only to links rendered from artifact content, leaving the application's
own controls unaffected.

## 5. Rules — List paging

### R23 — Only the first page of 50 rows is rendered at first

While a result set holds more entries than the page size, only the first page of rows is rendered —
only those rows are present in the DOM. The page size is fixed at 50 rows, held as a constant in the
browser application — not a server setting, not an environment variable, not an operator control.

### R24 — A boundary line states how many of how many artifacts are shown

While a result set holds at least one entry, a boundary line below the list states how many of how
many artifacts are shown, whether or not the set is truncated.

### R25 — "Show more" appends the next page without disturbing what is on screen

When the operator activates the "Show more" control, the next page of rows is appended, the boundary
line updates, and already-rendered rows and the current selection are left untouched. When every
entry of the result set is rendered, the "Show more" control is removed and the boundary line keeps
showing the total.

### R26 — A filter change or a search resets the list to its first page and the top

When a type, tier, or status filter changes, or a search runs, the list resets to its first page and
the list scroll position returns to the top. Search results and filtered listings page identically,
both flowing through the existing shared render path.

### R27 — Paging is client-side, over the result set the tool call already returned

The application pages the result set already returned by the tool call, client-side.
`list_artifacts` and `search_artifacts` return their complete result set in a single call and gain
no paging parameters.

Paging here bounds **rendering**, not transfer. `list_artifacts` has no limit or offset parameter
and returns every matching artifact's metadata in one response, so the studio already holds the
whole result set before it renders the first page — paging bounds DOM and render cost, and gives
the operator an explicit boundary, but does not reduce the response the browser receives. Bounding
that too would mean adding paging parameters to `list_artifacts`, a server-side change outside this
spec's scope and not assumed here. Nothing in this spec depends on it; if the metadata response
itself ever becomes the constraint, that is a separate decision.

### R28 — Keyboard navigation moves across rendered rows only

While keyboard navigation is in use, it moves across rendered rows only, with `End` reaching the
last rendered row and the "Show more" control following the list in tab order.

## 6. Boundaries

**Always:**
- All CSS and JS live in the single `src/arkeology/static/arkeology-studio.html` file.
- External dependencies loaded only from `unpkg.com` (ext-apps SDK) and `cdn.jsdelivr.net`
  (marked.js, mermaid.js). No web-font origins.
- No JS build step, no `package.json`, no Node.js artefacts.
- Link resolution and paging live entirely in `src/arkeology/static/arkeology-studio.html`.
- Server error messages are rendered verbatim; the browser adds no wording of its own to them.
- Artifact identifiers taken from rendered content are treated as untrusted input and used for
  nothing but a `read_artifact` argument.

**Ask First:**
- None.

**Never:**
- No new Python MCP tools or resources beyond what T43 established.
- No inline CDN library source — load via `<script src>` tags only.
- No new MCP tool, resource, or URI scheme, and no new parameter on any existing tool.
- No client-side scope, tier, or visibility check — the server gate decides (ADR-013).
- No widening of the HTML sanitiser's URI allow-list, and no `arkeology:` `href` in the DOM.
- No browser history, URL routing, or deep-linking in the studio — the Back control remains the only
  return path from the detail view.
- No new environment variable or `Settings` field for the page size or the fallback cap.
- No new runtime CDN dependency, no JS build step, no JS test harness added to the repo.
- No stored artifact content is rewritten, re-migrated, or re-embedded by this work.

## 7. For the developer agent

### Files to Touch

| File | Action | Status |
|------|--------|--------|
| `src/arkeology/tools/studio.py` | Updated `_arkeology_studio_inner`: supporting-host path returns text-only `ToolResult`; non-supporting host returns `{ "write_prefix": ..., "artifacts": [...] }` in `structured_content` | Done |
| `src/arkeology/static/arkeology-studio.html` | Replaced placeholder with full single-pane view-switching application | Done |
| `src/arkeology/resources.py` | `ResourceCSP(["https://unpkg.com", "https://cdn.jsdelivr.net"])` registered | Done |
| `src/arkeology/server.py` | `arkeology_studio` tool registered via `register_tools()` | Done |
| `pyproject.toml` | `fastmcp[apps]` dependency and static asset inclusion | Done |
| `AGENTS.md` | `arkeology_studio` documented as the human reading entry point | Done |
| `tests/unit/test_tools_studio.py` | New cases for the fallback cap, `total_count`, ordering, sub-cap completeness, and the untouched error path | Done |
| `src/arkeology/tools/studio.py` | `FALLBACK_LISTING_CAP` constant; sort, cap, and `total_count` in `_arkeology_studio_inner`'s success path; truncation sentence in the `content` text | Done |
| `src/arkeology/static/arkeology-studio.html` (paging) | `PAGE_SIZE` constant, page state, boundary line and "Show more" via `appendPage`/`renderFooter`; page and scroll reset in `renderList`, so filter changes and searches both reset through the one shared render path | Done |
| `src/arkeology/static/arkeology-studio.html` (link resolution) | `artifactTarget`/`classifyContentLinks` and delegated click and Enter activation on the detail body; error-payload guard in `selectArtifact`; link affordance scoped to activatable anchors in CSS | Done |
| `docs/architecture-decisions/adr-2026-08-12-studio-link-resolution.md` | Records the link-resolution contract (ADR-013) | Done |
| `docs/architecture-decisions/overview.md` | ADR-013 added to the decision index | Done |

Where link treatment sits relative to the sanitiser:

- **Classification runs before sanitising, in a `DOMParser` document.** The sanitiser destroys an
  `arkeology:` `href` before any post-sanitise pass could read it, so the target has to be moved
  into `data-artifact-id` while the original href is still present. A `DOMParser` document has no
  browsing context, so nothing loads or executes there, and the sanitiser still has the last word
  on what reaches the DOM.
- **`target` is not in the sanitiser's default attribute allow-list, so out-of-frame treatment runs
  *after* sanitising.** Setting `target="_blank"` before sanitising silently loses it. Adding
  `target` to the allow-list would have restored it in one argument, but that relaxes the sanitiser
  for a presentational detail and would let artifact content set `target` on its own elements — so
  instead, every anchor that still holds an `href` after sanitising gets `target` and
  `rel="noopener noreferrer"` applied in a short pass. By that point the only surviving hrefs are
  ones the sanitiser's own URI allow-list admitted.

### Contracts

None.

### Testing Approach

**Project uses TDD** (requirements.md NFR-07). Sequence:

1. Extend `tests/unit/test_tools_studio.py` first (Red) — fallback listing capped at the constant;
   `total_count` reports the pre-cap match count; ordering is newest-first with `artifact_id`
   tie-break and the cap keeps the head; a sub-cap scope returns everything with `total_count`
   equal to the returned length; the credential-error path still returns the existing structured
   error untouched. Use the `aws_mock` fixture and `FakeBedrockClient` per the project's testing
   conventions.
2. Then implement the cap in `src/arkeology/tools/studio.py` (Green).
3. Then `src/arkeology/static/arkeology-studio.html`.

The non-supporting host path has unit test coverage in `tests/unit/test_tools_studio.py`,
asserting that `structured_content` carries `write_prefix` and `artifacts` keys. The propagated
inner-listing error has unit test coverage in
`tests/unit/test_tools_studio.py::test_arkeology_studio_non_supporting_host_credential_error_is_propagated`.

The MCP App iframe path (supporting hosts) is shipped and served correctly. Practical testing
is limited by iframe rendering constraints: the view-switching interface is too small to use
in the current iframe environment of Claude Desktop and claude.ai.

The client-side JS has no unit test harness in this project, and none is added — matching prior
precedent for untested client-side JS fixes in this codebase. It is verified with a throwaway
Node + jsdom script that extracts the actual shipped function bodies from `arkeology-studio.html`
via string slicing (not retyped) and exercises them against mocked `app.callServerTool` responses
and a jsdom DOM. The script is not part of the repo.

- For the error-message rendering, `app.ontoolresult` guard and "All" status filter: the script
  extracts the shipped `loadList`, `doSearch`, and `app.ontoolresult` function bodies and covers all
  branches — error-message rendering, no-throw on plain-text confirmation, no accidental list-wipe
  on unrelated tool results, `status="all"` sent by default.
- For link resolution and paging, it covers at minimum — a resolvable `arkeology://artifact/{id}`
  link reaching `read_artifact` with the exact id; a link whose target is absent from the loaded
  result set still rendering content with the id as the header; an error payload rendering the
  server message with the detail view still open; a non-`artifact` `arkeology://` URI, a malformed
  one, and a raw `/docs/…` path all rendering with no `href` and no activation; an `http(s)://` link
  surviving with an out-of-frame target; the first page bounded to the page size with a boundary
  line naming both counts; "Show more" appending without disturbing the selection; and a filter
  change resetting to page one. This run uses the real pinned `marked` and `dompurify` rather than
  stubs — the mechanism turns entirely on what the sanitiser keeps and drops, so a stubbed sanitiser
  would have verified nothing. Each check was confirmed non-vacuous by reverting the corresponding
  behaviour and observing the matching failure.

Quality gates:
- `uv run pytest tests/unit/ -q -m 'not integration'`
- `uv run ruff check src/ tests/`
- `uv run ruff format --check src/ tests/`
- `uv run mypy src/`

### Hand-offs

None.
