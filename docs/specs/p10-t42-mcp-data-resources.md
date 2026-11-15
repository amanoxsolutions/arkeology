---
type: Spec
id: p10-t42-mcp-data-resources
title: T42 — MCP Data Resources
description: Feature spec for adding two MCP data resources — arkeology://artifact/{id*} and arkeology://artifacts — that expose artifact content and index listings for human consumption via the MCP resources protocol.
tags: []
status: stable
okf_version: "0.2"
sources:
  - resource: .docs/reviews/architecture-review-2026-11-15-arkeology-phases-9-10-12.md
    title: "Architecture review — Arkeology, plan phases 9, 10 and 12"
  - resource: docs/contracts/modules/arkeology.resources.md
    title: arkeology.resources
  - resource: docs/contracts/modules/arkeology.tools.read.md
    title: arkeology.tools.read
  - resource: docs/specs/p3-t10-list-artifacts.md
    title: T10 — List Artifacts Tool
  - resource: docs/contracts/modules/arkeology.tools.list.md
    title: arkeology.tools.list
generated:
  by: "axians-architect/claude-sonnet-4.6"
  at: 2026-06-23T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-15T20:19:59Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
  - by: "axians-architect/claude-fable-5-2"
    at: 2026-11-15T20:45:07Z
---

# T42 — MCP Data Resources

## TL;DR

Add two MCP data resources to arkeology: `arkeology://artifact/{id*}` (URI template, returns full markdown content of a named artifact) and `arkeology://artifacts` (static, returns a markdown index of every active artifact `list_artifacts` returns by default — own-scope artifacts and other teams' tier 3 shared ones). Both carry `audience: ["user"]` annotations and delegate to the existing `read_artifact` and `list_artifacts` tool logic.

## 1. Problem Statement

Arkeology already exposes five schema resources (`arkeology://schema/*`) for agent-readable documentation. These are registered at module load time with no AWS calls. There is currently no way for a human using an MCP client to browse or read stored artifact content through the MCP resources protocol — they must invoke tools. Adding data resources allows human users to read individual artifacts and browse the artifact index directly from the MCP resources panel, without constructing tool calls.

Both user stories this spec covers — a human reads a single artifact by ID, and a human browses
every active artifact they can read — are P1.

## 2. Rules — `arkeology://artifact/{id*}`

### R1 — Reading `arkeology://artifact/{id*}` returns the artifact's full markdown content

When a client reads `arkeology://artifact/{id*}`, the system returns the full artifact content as
`mimeType: "text/markdown"` with `audience: ["user"]` annotation. The template's parameter is the
wildcard-path form `{id*}`, because an artifact id is the full key `{write_prefix}/{id}{ext}` and
contains `/`. A developer using an MCP client uses it to read the full content of a known artifact.

**Example**

- Given a valid own-scope artifact ID, when the user reads `arkeology://artifact/{id*}`, then the
  resource returns the full markdown content with `mimeType: "text/markdown"`.

### R2 — A foreign-scope tier 2 artifact returns `access_denied`, not its content

When `arkeology://artifact/{id*}` is read for a foreign-scope tier 2 artifact, the system returns
the error `read_artifact` returns for it under the cross-scope gate, `access_denied`
(`arkeology.tools.read` § read_artifact, Errors), not the content. `arkeology://artifact/{id*}`
delegates to `_read_artifact_inner` (or calls `read_artifact`) — it does not duplicate the
scope/tier/visibility gate logic.

### R3 — An unknown artifact ID returns `not_found`

Given an artifact ID that does not exist, when the user reads `arkeology://artifact/{id*}`, then
the resource returns the error `not_found` (`arkeology.tools.read` § read_artifact, Errors).

### R4 — Resource handlers return a structured markdown error string rather than raising

Resource handlers return a structured markdown error string rather than raising; `resources.py`'s
`_error_markdown()` builds it from the tool result's `error`/`message` fields, and both resource
handlers additionally catch unexpected exceptions and return an `internal_error` markdown string
rather than letting them propagate. The error string's heading names the error code
(`# Error: <code>`), followed by the message, so a reader can tell `not_found` from
`access_denied`.

### R5 — A read of `arkeology://artifact/{id*}` carries no `lastModified`, and none is derived

When `arkeology://artifact/{id*}` is read, the result carries no `lastModified` annotation, and the
resource handler derives no last-modified value from the artifact's `last_edited_ulid`.

**Why:** `lastModified` cannot be emitted per-read on a template resource: `TextResourceContents`
has no `annotations` field and template registration annotations are static (cannot vary per
`{id*}`). A value nothing can emit is not computed; the ULID-to-ISO-8601 conversion already exists
once, in `derive_last_edited_at()`, which the search results use.

## 3. Rules — `arkeology://artifacts`

### R6 — Reading `arkeology://artifacts` returns a markdown index of every active artifact `list_artifacts` returns by default

When a client reads `arkeology://artifacts`, the system returns a markdown-formatted index, with
identifier, title, type, and description, of every active artifact `list_artifacts` returns with
its default scope: own-scope artifacts and foreign-scope artifacts that pass the cross-scope gate
(tier 3 and `shared`). `arkeology://artifacts` delegates to `_list_artifacts_inner` (or calls
`list_artifacts`) with `status="active"` and no other filters, and is never narrowed to own scope
on its own (`arkeology.resources` § register_data_resources). It never asks `list_artifacts` for
link fields (`include_links`): the index shows none, so reading it costs one vector-index query and
no S3 object annotation read, however many artifacts it lists. A developer uses it to see what
artifacts they can read without running a tool call.

**Example**

- Given active own-scope artifacts exist, when the user reads `arkeology://artifacts`, then the
  resource returns a markdown table listing identifier, title, type, and description for each
  artifact.
- Given another team's active tier 3 `shared` artifact, when the user reads
  `arkeology://artifacts`, then it appears in the index, as it does in `list_artifacts`.
- Given 50 active artifacts that each carry `commit_refs` and `references`, when the user reads
  `arkeology://artifacts`, then no S3 object annotation is read and no link field appears in the
  index.

Source: FR-46, AC-52; p3-t10-list-artifacts R11

### R7 — An empty listing returns minimal markdown, not an error

Given no active artifact is readable, when the user reads `arkeology://artifacts`, then the
resource returns an empty or minimal markdown response (not an error).

## 4. Rules — Both resources

### R8 — Both resources carry the `audience: ["user"]` annotation on every read

When `arkeology://artifacts` or `arkeology://artifact/{id*}` is read, the system carries
`audience: ["user"]` annotation. `audience` is set as a static `Annotations` on the resource
registration (decorator parameter) and is emitted on every read, using FastMCP's annotation
support — not hand-crafted JSON-RPC responses.

### R9 — Both resources are listed once the server starts

When the server starts, `arkeology://artifact/{id*}` appears in `resources/templates/list` and
`arkeology://artifacts` appears in `resources/list`.

## 5. Boundaries

**Always:**
- `arkeology://artifact/{id*}` delegates to `_read_artifact_inner` (or calls `read_artifact`) — do not duplicate the scope/tier/visibility gate logic.
- `arkeology://artifacts` delegates to `_list_artifacts_inner` (or calls `list_artifacts`) with `status="active"`, no other filters, and never `include_links=True`.
- Both resources carry `audience: ["user"]` annotation; use FastMCP's annotation support — do not hand-craft JSON-RPC responses.
- Register data resources via a new `register_data_resources(app, settings, s3, vectors, bedrock)` function in `resources.py`, called from the end of `register_tools()` in `server.py` after all clients are in scope.

**Ask First:**
- Nothing — R5 settles `lastModified`: no annotation is emitted and no value is derived.

**Never:**
- Do not register data resources at module load time (`register_resources` call site) — data resources need live client references.
- Do not re-implement the cross-scope gate inline in the resource handler — always delegate to the existing tool logic.
- Do not store artifact content in the resource URI or annotations — content belongs in the `text` field of the resource content object.
- Do not derive or emit a per-read `lastModified` (R5) — revisit when the pinned MCP SDK lets a template resource carry per-read annotations; `derive_last_edited_at()` then supplies the value.

## 6. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_data_resources.py` | Create | Tests for both data resource handlers; uses existing `aws_mock`, `s3_client`, `vectors_client_*`, `settings` fixtures from `conftest.py` |
| `src/arkeology/resources.py` | Modify | Add `register_data_resources(app, settings, s3, vectors, bedrock)` function with the two resource handlers as closures; no `_artifact_last_modified` helper (R5) |
| `src/arkeology/server.py` | Modify | Import `register_data_resources` and call it at the end of `register_tools()` |

### Contracts

- `docs/contracts/modules/arkeology.resources.md` § register_data_resources — both resources, their annotations, their error strings and the index's scope (R1–R9).
- `docs/contracts/modules/arkeology.tools.read.md` § read_artifact — the read `arkeology://artifact/{id*}` delegates to, and its `access_denied` and `not_found` errors (R1–R3).
- `docs/contracts/modules/arkeology.tools.list.md` § list_artifacts — the default listing `arkeology://artifacts` delegates to, without `include_links` (R6, R7).

### Testing Approach

This project uses TDD. Test file is written before the implementation it gates.

**1. `tests/unit/test_data_resources.py`** — gates `resources.py` changes and `server.py` wiring.

Write and pass all tests in this file before touching `resources.py` or `server.py`:

- `test_register_data_resources_artifact_template_uri_present` — after calling `register_data_resources(app, ...)`, the URI template `arkeology://artifact/{id*}` appears in the app's template list.
- `test_register_data_resources_artifacts_static_uri_present` — after calling `register_data_resources(app, ...)`, the static URI `arkeology://artifacts` appears in the app's resource list.
- `test_artifact_resource_returns_markdown_content` — reading `arkeology://artifact/{id*}` for a known own-scope artifact returns `mimeType: "text/markdown"` and the artifact's content string.
- `test_artifact_resource_foreign_scope_tier2_returns_error` — reading `arkeology://artifact/{id*}` for a foreign-scope tier 2 artifact returns a markdown error string headed `# Error: access_denied` (not content).
- `test_artifact_resource_not_found_returns_error` — reading `arkeology://artifact/{id*}` for a non-existent ID returns a markdown error string headed `# Error: not_found`.
- `test_artifacts_resource_returns_markdown_listing` — reading `arkeology://artifacts` with active own-scope artifacts returns a markdown string containing each artifact's identifier, title, type, and description.
- `test_artifacts_resource_includes_foreign_shared` — reading `arkeology://artifacts` lists another scope's active tier 3 `shared` artifact and omits another scope's tier 2 one, exactly as `list_artifacts` does.
- `test_artifacts_resource_empty_scope_returns_markdown` — reading `arkeology://artifacts` with no active artifacts returns a non-error markdown string.
- `test_artifacts_resource_reads_no_annotation` — reading `arkeology://artifacts` over artifacts that carry `commit_refs` and `references` records zero annotation reads on a spied S3 client, and the call into `list_artifacts` carries no `include_links=True` (R6).

**2. `src/arkeology/resources.py`** — gated by the test file above.

Add `register_data_resources`. Both handlers are async closures over `settings`, `s3`, `vectors`, `bedrock`. The `arkeology://artifact/{id*}` handler extracts `id` from the URI, delegates to the read tool, converts the result to a markdown resource, and returns the markdown error string of R4 on error rather than raising. The `arkeology://artifacts` handler delegates to the list tool and renders a markdown table from the returned artifact list.

**3. `src/arkeology/server.py`** — gated by the test file above.

Import `register_data_resources` from `arkeology.resources`. Call `register_data_resources(_app, settings, s3, vectors, bedrock)` as the last statement in `register_tools()`.
