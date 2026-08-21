---
type: spec
title: T44 — Browser UI (HTML/JS)
description: Feature spec for arkeology-studio.html — a self-contained HTML/JS single-pane view-switching artifact browser shipped as a static MCP App asset. The primary deliverable is the arkeology_studio non-supporting host path (structured artifact listing in structured_content). The MCP App iframe is registered and served but discovered post-implementation to have practical rendering constraints in supporting hosts.
tags: []
timestamp: 2026-06-24T00:00:00Z
okf_version: "0.1"
feature: p11-t44-browser-ui
status: complete
phase: 11
task: 44
references:
  - docs/planning-artifacts/requirements.md
  - docs/architecture-decisions/adr-2026-06-24-mcp-apps-visual-reading-interface.md
  - docs/architecture-decisions/adr-2026-08-12-studio-link-resolution.md
  - docs/architecture-decisions/adr-2026-07-03-artifact-cross-referencing.md
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
  by: "architect"
  date: "2026-08-12"
---

# T44 — Browser UI (HTML/JS)

<!-- SCOPE BLOCK — frozen after approval -->

## TL;DR

This task delivered two things:

1. `src/arkeology/static/arkeology-studio.html` — a self-contained HTML/JS single-pane
   view-switching application shipped as a static asset and served over
   `ui://arkeology-studio/index.html`. It uses the ext-apps SDK, marked.js, and mermaid.js
   loaded from CDN (`unpkg.com`, `cdn.jsdelivr.net`); no web fonts; no build step.

2. The `arkeology_studio` tool's non-supporting host path — when called from Claude Code or
   MCP Inspector, returns a structured artifact listing in `structured_content` with shape
   `{ "write_prefix": string, "artifacts": [...] }`. This is the primary interface for the team.

The MCP App iframe (supporting hosts: Claude Desktop, claude.ai, VS Code Copilot) was
registered and served successfully. Post-implementation testing revealed that the iframe
rendering environment is too small for the view-switching interface to be practical.
The non-supporting host structured listing path is the interface the team uses.

## Problem Statement

Developers using raw tool calls (`list_artifacts`, `search_artifacts`, `read_artifact`) to
browse the artifact store receive verbose, context-consuming output. T44 addressed this in
two ways: a structured listing returned directly by `arkeology_studio` on non-supporting hosts
(Claude Code), and an MCP App iframe browser for supporting hosts. The structured listing
path delivers value immediately; the iframe path was implemented and shipped but found to be
constrained by the iframe rendering environment in practice.

## User Stories

### Story 1 — Developer on a non-supporting host gets a structured listing (P1)

A developer using Claude Code calls `arkeology_studio` and receives a structured artifact listing
without issuing separate `list_artifacts` calls.

**Acceptance criteria:**
- Given the host does not support the `io.modelcontextprotocol/ui` extension, when
  `arkeology_studio` is called, then `structured_content` carries `{ "write_prefix": string,
  "artifacts": [...] }` covering all active artifacts in the write scope.
- The listing is returned without error and is machine-readable by the calling agent.

### Story 2 — Developer on a supporting host gets an MCP App iframe (P2)

A developer using Claude Desktop or claude.ai calls `arkeology_studio` and the host renders the
MCP App iframe.

**Acceptance criteria:**
- Given the host supports the `io.modelcontextprotocol/ui` extension, when `arkeology_studio` is
  called, then `ToolResult` contains a text confirmation and the host receives the
  `_meta.ui.resourceUri` pointer to `ui://arkeology-studio/index.html`.
- Note: post-implementation testing found the iframe rendering environment too small for
  the view-switching interface to be practical. The iframe is served correctly; the
  rendering constraint is a host environment limitation, not a bug in the implementation.

## Requirements

The tool contract for `arkeology_studio`:

- WHEN called from a non-supporting host THE SYSTEM SHALL return `ToolResult` with
  `structured_content = { "write_prefix": settings.write_prefix, "artifacts": [...] }`
  from `_list_artifacts_inner`, plus a short text confirmation in `content`.
- WHEN called from a supporting host THE SYSTEM SHALL return `ToolResult` with a short text
  confirmation in `content` and no `structured_content` — the iframe loads its own artifact
  list on mount via `list_artifacts`.
- The `ui://arkeology-studio/index.html` resource SHALL be registered with
  `ResourceCSP(["https://unpkg.com", "https://cdn.jsdelivr.net"])`.
- `arkeology-studio.html` SHALL be a self-contained HTML/JS file with no companion `.css` or
  `.js` files and no JS build step.

## Boundaries

**Always:**
- All CSS and JS live in the single `src/arkeology/static/arkeology-studio.html` file.
- External dependencies loaded only from `unpkg.com` (ext-apps SDK) and `cdn.jsdelivr.net`
  (marked.js, mermaid.js). No web-font origins.
- No JS build step, no `package.json`, no Node.js artefacts.

**Never:**
- No new Python MCP tools or resources beyond what T43 established.
- No inline CDN library source — load via `<script src>` tags only.

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Status |
|------|--------|--------|
| `src/arkeology/tools/studio.py` | Updated `_arkeology_studio_inner`: supporting-host path returns text-only `ToolResult`; non-supporting host returns `{ "write_prefix": ..., "artifacts": [...] }` in `structured_content` | Done |
| `src/arkeology/static/arkeology-studio.html` | Replaced placeholder with full single-pane view-switching application | Done |
| `src/arkeology/resources.py` | `ResourceCSP(["https://unpkg.com", "https://cdn.jsdelivr.net"])` registered | Done |
| `src/arkeology/server.py` | `arkeology_studio` tool registered via `register_tools()` | Done |
| `pyproject.toml` | `fastmcp[apps]` dependency and static asset inclusion | Done |
| `AGENTS.md` | `arkeology_studio` documented as the human reading entry point | Done |

## Testing Approach

The non-supporting host path has unit test coverage in `tests/unit/test_tools_studio.py`,
asserting that `structured_content` carries `write_prefix` and `artifacts` keys.

The MCP App iframe path (supporting hosts) is shipped and served correctly. Practical testing
is limited by iframe rendering constraints: the view-switching interface is too small to use
in the current iframe environment of Claude Desktop and claude.ai.

Quality gates (all passing):
- `uv run pytest tests/unit/ -q -m 'not integration'`
- `uv run ruff check src/ tests/`
- `uv run ruff format --check src/ tests/`
- `uv run mypy src/`

## Implementation Notes

`arkeology-studio.html` is a self-contained HTML/JS application using:
- System-UI font stack (no web fonts; GDPR constraint)
- CDN deps: `@modelcontextprotocol/ext-apps` from `unpkg.com`; `marked.js` and `mermaid.js`
  from `cdn.jsdelivr.net`
- Single-pane view switching: list view active by default; detail view shown when
  `#app.showing-detail` class is set (CSS: `#detail-view { display: none }` toggled by class)
- Artifact list sorted by type A-Z then date newest-first
- Mermaid code fence rewrite required before `mermaid.run()` (marked produces
  `<pre><code class="language-mermaid">` but mermaid targets `.mermaid`)

The file is shipped as-is. Design refinements are not planned given the iframe rendering
constraint; the structured listing path serves the team's needs.

## Post-implementation Note

The MCP App iframe was registered and served successfully. Post-implementation testing
revealed that the iframe rendering environment in supporting hosts (Claude Desktop, claude.ai)
is too small for the view-switching interface to be practical. The primary value delivered by
`arkeology_studio` is the non-supporting host path (structured artifact listing in
`structured_content`), which is the interface used by the team via Claude Code.

## Revised (2026-07-05)

Four defects were found and fixed in the non-supporting-host and iframe paths:

- **(a) `studio.py` error masking.** `_arkeology_studio_inner` previously did
  `listing.get("artifacts", [])` on the inner `list_artifacts` call's result, so a
  credential-error dict was silently coerced into a successful empty listing — expired
  credentials read as "the store is empty" instead of "the store could not be reached"
  (requirements.md FR-12 violation). It now detects `"error"` in the inner result and returns a structured
  `ToolResult(is_error=True, structured_content={"error": ..., "message": ...})` instead.
- **(b) Browser JS swallowed server error messages.** `loadList` rendered `data.artifacts ||
  []` and `doSearch` rendered a generic `"Search failed."`, both discarding the server's
  actual error message on failure. Both now check `data.error` first and render
  `data.message || data.error` in the empty-state `<p>`.
- **(c) `app.ontoolresult` crashed on every render.** This iframe only ever runs in a
  *supporting* host, so every plain-text confirmation it receives — including
  `arkeology_studio`'s own "Arkeology Studio opened…" text — carries no `structuredContent`. The
  handler unconditionally did `JSON.parse(content?.find(...)?.text ?? "{}")`, which threw on
  that plain text every time. It also read `data.write_prefix` into a `#scope-label` element,
  but `write_prefix` is sent only to non-supporting hosts (see (a) above) and can never reach
  this iframe — dead code. The handler now guards on `structuredContent.artifacts` being an
  array before doing anything, and the `#scope-label` element, its DOM ref, and its CSS rule
  were removed entirely (no plausible correct source exists for it in this code path).
- **(d) The "All" status filter was unreachable.** `#sel-status`'s "All" option sent
  `value=""`; `loadList` only included `args.status` when `filterStatus` was truthy, so "All"
  silently fell through to the server's `status="active"` default. `list_artifacts` (see
  `p3-t10-list-artifacts.md`, revised) now recognises `status="all"` as an explicit
  all-inclusive sentinel; the browser's default `filterStatus` and the "All" option's value
  both changed from `""` to `"all"`, which is always sent (never omitted).

Verification: (a) has unit test coverage
(`tests/unit/test_tools_studio.py::test_arkeology_studio_non_supporting_host_credential_error_is_propagated`).
(b)/(c)/(d)'s client-side JS have no unit test harness in this project (matching prior
precedent for untested client-side JS fixes in this codebase) —
verified with a throwaway Node + jsdom script that extracts the actual shipped `loadList`,
`doSearch`, and `app.ontoolresult` function bodies from `arkeology-studio.html` via string slicing
(not retyped) and exercises them against mocked `app.callServerTool` responses and a jsdom DOM;
all branches (error-message rendering, no-throw on plain-text confirmation, no accidental
list-wipe on unrelated tool results, `status="all"` sent by default) passed. The script is not
part of the repo.

## Revision (2026-08-12) — Link Resolution, List Paging, Bounded Fallback Listing

Three additions, none yet implemented. The frozen scope block above is unmodified: everything
originally approved there still holds, and the user stories, requirements, and boundaries below
extend it rather than replace any part of it. The frontmatter `status` moved from `complete` back
to `ready` because the file now carries required behaviour that is not built; the per-file Status
column in **Files to Touch (revision)** keeps the record of what is already Done.

The link-resolution contract is settled in
`adr-2026-08-12-studio-link-resolution.md` (ADR-013) — client-side resolution, the server gate as
sole access-control authority, inert rendering for anything unresolvable. This section states the
behaviour to build; it does not restate that ADR's reasoning. `adr-2026-07-03-artifact-cross-referencing.md`
(ADR-012) is unaffected: no stored content changes, and mixed addressing remains correct.

<!-- SCOPE BLOCK (revision) — frozen on approval -->

### User Stories (revision)

#### Story 3 — Reader follows a cross-reference without leaving the studio (P1)

A developer reading an artifact in Arkeology Studio meets a resolved cross-reference in the body
text and opens the referenced artifact by activating it, rather than copying an identifier out and
asking an agent to fetch it.

**Acceptance criteria:**
- Given rendered artifact content containing a link whose target is `arkeology://artifact/{id}`,
  when the reader activates it, then the studio's detail view shows that artifact's content and the
  reader can return to the list with the existing Back control.
- Given the reader activates a link to an artifact they may not read, or to one that no longer
  exists, then the detail view shows the server's own error message and stays open — it does not
  show an empty body and does not bounce back to the list.
- Given rendered content containing a raw repository path link (for example `/docs/…`) or an
  `arkeology://` URI the studio cannot resolve, then that text is visibly present but carries no
  clickable affordance — the reader is never offered a link that does nothing.

#### Story 4 — Reader browses a large store without an unbounded list (P2)

A developer whose scope holds several hundred artifacts opens the studio and gets a list that
renders promptly, with an explicit statement of how much of the store is on screen.

**Acceptance criteria:**
- Given a result set larger than one page, when the list renders, then only the first page of rows
  is present in the DOM and a boundary line states how many of how many artifacts are shown.
- Given the boundary line, when the reader activates the "Show more" control, then the next page is
  appended, the boundary line updates, and rows already on screen and the current selection are
  unchanged.
- Given a filter change or a search, when results render, then the list is back at its first page
  and scrolled to the top.

#### Story 5 — Agent on a non-supporting host gets a bounded listing (P1)

An agent calling `arkeology_studio` from a host without MCP-UI support receives a listing sized for
a context window, and is told when it is seeing only part of the store.

**Acceptance criteria:**
- Given a scope holding more artifacts than the fallback cap, when `arkeology_studio` is called from
  a non-supporting host, then `structured_content["artifacts"]` holds at most the cap,
  `structured_content["total_count"]` holds the full match count, and the `content` text states both
  numbers and how to retrieve the rest.
- Given a scope holding fewer artifacts than the cap, then the listing is complete and
  `total_count` equals the number of artifacts returned.
- Given the inner listing call fails, then the existing structured-error result is returned
  unchanged — never a capped, reordered, or empty listing.

### Requirements (revision)

*Inert*, below, means: the anchor's text content is preserved, its `href` is removed, it is not
focusable, it is not announced as a link to assistive technology, and activating it does nothing.

#### (a) Link resolution

- WHEN rendered artifact content contains a link whose target is `arkeology://artifact/{id}` with a
  non-empty `{id}` THE SYSTEM SHALL present it as an activatable control that loads `{id}` into the
  detail view through the same `read_artifact` call path already used when an artifact-list row is
  selected.
- WHEN such a link is activated THE SYSTEM SHALL pass `{id}` to `read_artifact` verbatim as the full
  S3 key, after discarding any `#fragment` or `?query` suffix and applying a single URI decode.
- IF that decode fails THEN THE SYSTEM SHALL treat the link as unresolvable and render it inert.
- WHEN the activated target is present in the currently loaded result set THE SYSTEM SHALL populate
  the detail header from that entry and mark its list row selected, exactly as row selection does.
- WHEN the activated target is absent from the currently loaded result set — filtered out, out of
  the reader's own scope, or beyond the rendered page — THE SYSTEM SHALL still load and render its
  content, show the artifact id in place of the title, omit the metadata pills it holds no value
  for, and mark no list row selected.
- IF the `read_artifact` call returns an error payload THEN THE SYSTEM SHALL render its `message`
  (falling back to `error`) in the detail content area, keep the detail view open, and leave the
  Back control available. This covers both a target the reader may not read (foreign scope, or not
  tier-3 shared) and a target that no longer exists; the server distinguishes them and THE SYSTEM
  SHALL NOT substitute its own wording, re-classify the error, or add a client-side scope, tier,
  visibility, or existence check ahead of the call.
- WHEN rendered artifact content contains an `arkeology://` link that is not of the form
  `arkeology://artifact/{id}` with a non-empty `{id}` — including `arkeology://artifacts`, any
  `arkeology://schema/…` resource, and any malformed URI — THE SYSTEM SHALL render it inert.
- WHEN rendered artifact content contains a link whose target is neither `http(s)://` nor a
  resolvable `arkeology://artifact/{id}` — in particular the raw repository paths ADR-012 leaves
  untouched — THE SYSTEM SHALL render it inert, so a target the studio cannot open is never
  presented as navigable.
- WHEN rendered artifact content contains an `http(s)://` link THE SYSTEM SHALL leave it navigable
  and SHALL open it outside the application frame, so following it never replaces the studio.
- THE SYSTEM SHALL NOT widen the HTML sanitiser's URI allow-list to admit the `arkeology:` scheme,
  and no `arkeology:` `href` SHALL reach the DOM; a resolvable target SHALL be carried by
  sanitiser-preserved inert data that the click handler reads.
- THE SYSTEM SHALL apply this link treatment only to links rendered from artifact content, leaving
  the application's own controls unaffected.

#### (b) List paging

- WHILE a result set holds more entries than the page size THE SYSTEM SHALL render only the first
  page of rows.
- WHILE a result set holds at least one entry THE SYSTEM SHALL display a boundary line below the
  list stating how many of how many artifacts are shown, whether or not the set is truncated.
- WHEN the operator activates the "Show more" control THE SYSTEM SHALL append the next page of rows,
  update the boundary line, and leave already-rendered rows and the current selection untouched.
- WHEN every entry of the result set is rendered THE SYSTEM SHALL remove the "Show more" control and
  keep the boundary line showing the total.
- WHEN a type, tier, or status filter changes, or a search runs, THE SYSTEM SHALL reset the list to
  its first page and return the list scroll position to the top; search results and filtered
  listings SHALL page identically, both flowing through the existing shared render path.
- THE SYSTEM SHALL page the result set already returned by the tool call, client-side. `list_artifacts`
  and `search_artifacts` return their complete result set in a single call and gain no paging
  parameters (see **Constraint noted for the operator** below).
- THE SYSTEM SHALL use a fixed page size of 50 rows, held as a constant in the browser application —
  not a server setting, not an environment variable, not an operator control.
- WHILE keyboard navigation is in use THE SYSTEM SHALL move across rendered rows only, with `End`
  reaching the last rendered row and the "Show more" control following the list in tab order.

#### (c) Bounded plain-text fallback listing

- WHEN `arkeology_studio` is called from a non-supporting host and the inner listing succeeds THE
  SYSTEM SHALL include at most 50 artifacts in `structured_content["artifacts"]` and SHALL include
  `structured_content["total_count"]` carrying the number of artifacts matched before the cap.
- THE SYSTEM SHALL order the fallback listing by `date` descending, ties broken by `artifact_id`
  ascending, and the cap SHALL retain the head of that order — the newest artifacts.
- WHEN the cap truncates the listing THE SYSTEM SHALL state in the `content` text how many of how
  many artifacts are included and that `list_artifacts` with filters retrieves the remainder.
- THE SYSTEM SHALL leave `structured_content["write_prefix"]` unchanged and SHALL leave the existing
  error result unchanged — an error is never capped, reordered, or coerced into a listing.
- THE SYSTEM SHALL hold the cap as a module-level constant in `studio.py`; it is not a new
  environment variable, `Settings` field, or tool parameter.
- THE SYSTEM SHALL NOT change `list_artifacts` — the cap applies to the `arkeology_studio` fallback
  result only.

### Boundaries (revision)

**Always:**
- Link resolution and paging live entirely in `src/arkeology/static/arkeology-studio.html`.
- Server error messages are rendered verbatim; the browser adds no wording of its own to them.
- Artifact identifiers taken from rendered content are treated as untrusted input and used for
  nothing but a `read_artifact` argument.

**Never:**
- No new MCP tool, resource, or URI scheme, and no new parameter on any existing tool.
- No client-side scope, tier, or visibility check — the server gate decides (ADR-013).
- No widening of the HTML sanitiser's URI allow-list, and no `arkeology:` `href` in the DOM.
- No browser history, URL routing, or deep-linking in the studio — the Back control remains the only
  return path from the detail view.
- No new environment variable or `Settings` field for the page size or the fallback cap.
- No new runtime CDN dependency, no JS build step, no JS test harness added to the repo.
- No stored artifact content is rewritten, re-migrated, or re-embedded by this work.

<!-- IMPLEMENTATION BLOCK (revision) — agent-owned -->

### Files to Touch (revision)

| File | Action | Status |
|------|--------|--------|
| `tests/unit/test_tools_studio.py` | New cases for the fallback cap, `total_count`, ordering, sub-cap completeness, and the untouched error path | Done |
| `src/arkeology/tools/studio.py` | `FALLBACK_LISTING_CAP` constant; sort, cap, and `total_count` in `_arkeology_studio_inner`'s success path; truncation sentence in the `content` text | Done |
| `src/arkeology/static/arkeology-studio.html` (paging) | `PAGE_SIZE` constant, page state, boundary line and "Show more" via `appendPage`/`renderFooter`; page and scroll reset in `renderList`, so filter changes and searches both reset through the one shared render path | Done |
| `src/arkeology/static/arkeology-studio.html` (link resolution) | `artifactTarget`/`classifyContentLinks` and delegated click and Enter activation on the detail body; error-payload guard in `selectArtifact`; link affordance scoped to activatable anchors in CSS | Done |
| `docs/architecture-decisions/adr-2026-08-12-studio-link-resolution.md` | Records the link-resolution contract (ADR-013) | Done |
| `docs/architecture-decisions/overview.md` | ADR-013 added to the decision index | Done |

### Testing Approach (revision)

**Project uses TDD** (requirements.md NFR-07). Sequence:

1. Extend `tests/unit/test_tools_studio.py` first (Red) — fallback listing capped at the constant;
   `total_count` reports the pre-cap match count; ordering is newest-first with `artifact_id`
   tie-break and the cap keeps the head; a sub-cap scope returns everything with `total_count`
   equal to the returned length; the credential-error path still returns the existing structured
   error untouched. Use the `aws_mock` fixture and `FakeBedrockClient` per the project's testing
   conventions.
2. Then implement the cap in `src/arkeology/tools/studio.py` (Green).
3. Then `src/arkeology/static/arkeology-studio.html`.

The client-side work in step 3 has no unit test harness in this project, and this revision adds
none — that matches the precedent recorded in **Revised (2026-07-05)** above. Verify it the same
way: a throwaway Node + jsdom script that extracts the shipped function bodies from the HTML by
string slicing (not retyped) and exercises them against mocked `app.callServerTool` responses,
covering at minimum — a resolvable `arkeology://artifact/{id}` link reaching `read_artifact` with
the exact id; a link whose target is absent from the loaded result set still rendering content with
the id as the header; an error payload rendering the server message with the detail view still open;
a non-`artifact` `arkeology://` URI, a malformed one, and a raw `/docs/…` path all rendering with no
`href` and no activation; an `http(s)://` link surviving with an out-of-frame target; the first page
bounded to the page size with a boundary line naming both counts; "Show more" appending without
disturbing the selection; and a filter change resetting to page one. The script stays out of the
repo.

### Constraint noted for the operator

Paging here bounds **rendering**, not transfer. `list_artifacts` has no limit or offset parameter
and returns every matching artifact's metadata in one response, so the studio already holds the
whole result set before it renders the first page — this revision bounds DOM and render cost, and
gives the operator an explicit boundary, but does not reduce the response the browser receives.
Bounding that too would mean adding paging parameters to `list_artifacts`, a server-side change
outside this spec's scope and not assumed here. Nothing in this revision depends on it; if the
metadata response itself ever becomes the constraint, that is a separate decision.

### Post-implementation note (revision)

Built as specified. Two things worth recording, both about where link treatment sits relative to
the sanitiser:

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

Verified with a throwaway Node + jsdom script, per the approach above, run against the real pinned
`marked` and `dompurify` rather than stubs — the mechanism turns entirely on what the sanitiser
keeps and drops, so a stubbed sanitiser would have verified nothing. Each check was confirmed
non-vacuous by reverting the corresponding behaviour and observing the matching failure. The script
is not part of the repo.
