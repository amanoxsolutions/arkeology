---
type: spec
title: T42 — MCP Data Resources
description: Feature spec for adding two MCP data resources — cairn://artifact/{id} and cairn://artifacts — that expose artifact content and index listings for human consumption via the MCP resources protocol.
tags: []
timestamp: 2026-06-23T00:00:00Z
okf_version: "0.1"
feature: p10-t42-mcp-data-resources
status: ready
phase: 10
task: 42
references: []
authored:
  by: "architect"
  date: "2026-06-23"
revised:
  by: ""
  date: ""
---

# T42 — MCP Data Resources

<!-- SCOPE BLOCK -->

## TL;DR

Add two MCP data resources to cairn-mcp: `cairn://artifact/{id}` (URI template, returns full markdown content of a named artifact) and `cairn://artifacts` (static, returns a markdown index of all active own-scope artifacts). Both carry `audience: ["user"]` annotations and delegate to the existing `read_artifact` and `list_artifacts` tool logic.

## Problem Statement

cairn-mcp already exposes five schema resources (`cairn://schema/*`) for agent-readable documentation. These are registered at module load time with no AWS calls. There is currently no way for a human using an MCP client to browse or read stored artifact content through the MCP resources protocol — they must invoke tools. Adding data resources allows human users to read individual artifacts and browse the artifact index directly from the MCP resources panel, without constructing tool calls.

## User Stories

### Story 1 — Human reads a single artifact by ID (P1)

A developer using an MCP client wants to read the full content of a known artifact.

**Acceptance criteria:**
- Given a valid own-scope artifact ID, when the user reads `cairn://artifact/{id}`, then the resource returns the full markdown content with `mimeType: "text/markdown"`.
- Given a foreign-scope tier 2 artifact ID, when the user reads `cairn://artifact/{id}`, then the resource returns an error consistent with the cross-scope gate (not the content).
- Given an artifact ID that does not exist, when the user reads `cairn://artifact/{id}`, then the resource returns a not-found error.
- Given an artifact with a `last_edited_ulid`, when the resource is returned, then the response includes a `lastModified` annotation derived from that ULID.

### Story 2 — Human browses all active own-scope artifacts (P1)

A developer wants to see what artifacts are stored in their scope without running a tool call.

**Acceptance criteria:**
- Given active own-scope artifacts exist, when the user reads `cairn://artifacts`, then the resource returns a markdown table listing identifier, title, type, and description for each artifact.
- Given no active own-scope artifacts exist, when the user reads `cairn://artifacts`, then the resource returns an empty or minimal markdown response (not an error).

## Requirements

- WHEN a client reads `cairn://artifact/{id}` THE SYSTEM SHALL return the full artifact content as `mimeType: "text/markdown"` with `audience: ["user"]` annotation.
- WHEN `cairn://artifact/{id}` is read for a foreign-scope tier 2 artifact THE SYSTEM SHALL return an error consistent with the cross-scope gate enforced by `read_artifact`.
- WHEN `cairn://artifact/{id}` is read for an artifact with `last_edited_ulid` THE SYSTEM SHALL include a `lastModified` annotation in ISO 8601 format derived from that ULID.
- WHEN a client reads `cairn://artifacts` THE SYSTEM SHALL return a markdown-formatted index of all active own-scope artifacts with identifier, title, type, and description; the scope and filter parameters SHALL match `list_artifacts` default parameters.
- WHEN `cairn://artifacts` or `cairn://artifact/{id}` is read THE SYSTEM SHALL carry `audience: ["user"]` annotation.
- WHEN the server starts, `cairn://artifact/{id}` SHALL appear in `resources/templates/list` and `cairn://artifacts` SHALL appear in `resources/list`.

## Boundaries

**Always:**
- `cairn://artifact/{id}` delegates to `_read_artifact_inner` (or calls `read_artifact`) — do not duplicate the scope/tier/visibility gate logic.
- `cairn://artifacts` delegates to `_list_artifacts_inner` (or calls `list_artifacts`) with `status="active"` and no other filters.
- Both resources carry `audience: ["user"]` annotation; use FastMCP's annotation support — do not hand-craft JSON-RPC responses.
- Register data resources via a new `register_data_resources(app, settings, s3, vectors, bedrock)` function in `resources.py`, called from the end of `register_tools()` in `server.py` after all clients are in scope.

**Ask First:**
- Whether `lastModified` should be omitted entirely when `last_edited_ulid` is absent, or whether a fallback (e.g. current time) is acceptable. Default assumption: omit the annotation when absent.

**Never:**
- Do not register data resources at module load time (`register_resources` call site) — data resources need live client references.
- Do not re-implement the cross-scope gate inline in the resource handler — always delegate to the existing tool logic.
- Do not store artifact content in the resource URI or annotations — content belongs in the `text` field of the resource content object.

<!-- IMPLEMENTATION BLOCK -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_data_resources.py` | Create | Tests for both data resource handlers; uses existing `aws_mock`, `s3_client`, `vectors_client_*`, `settings` fixtures from `conftest.py` |
| `src/cairn_mcp/resources.py` | Modify | Add `register_data_resources(app, settings, s3, vectors, bedrock)` function with the two resource handlers as closures |
| `src/cairn_mcp/server.py` | Modify | Import `register_data_resources` and call it at the end of `register_tools()` |

## Testing Approach

This project uses TDD. Test file is written before the implementation it gates.

**1. `tests/unit/test_data_resources.py`** — gates `resources.py` changes and `server.py` wiring.

Write and pass all tests in this file before touching `resources.py` or `server.py`:

- `test_register_data_resources_artifact_template_uri_present` — after calling `register_data_resources(app, ...)`, the URI template `cairn://artifact/{id}` appears in the app's template list.
- `test_register_data_resources_artifacts_static_uri_present` — after calling `register_data_resources(app, ...)`, the static URI `cairn://artifacts` appears in the app's resource list.
- `test_artifact_resource_returns_markdown_content` — reading `cairn://artifact/{id}` for a known own-scope artifact returns `mimeType: "text/markdown"` and the artifact's content string.
- `test_artifact_resource_foreign_scope_tier2_returns_error` — reading `cairn://artifact/{id}` for a foreign-scope tier 2 artifact returns an error (not content), consistent with the cross-scope gate.
- `test_artifact_resource_not_found_returns_error` — reading `cairn://artifact/{id}` for a non-existent ID returns a not-found error.
- `test_artifact_resource_last_modified_annotation_present` — when the artifact has a `last_edited_ulid`, the returned resource includes a `lastModified` annotation.
- `test_artifact_resource_last_modified_annotation_absent` — when the artifact has no `last_edited_ulid`, the `lastModified` annotation is omitted.
- `test_artifacts_resource_returns_markdown_listing` — reading `cairn://artifacts` with active own-scope artifacts returns a markdown string containing each artifact's identifier, title, type, and description.
- `test_artifacts_resource_empty_scope_returns_markdown` — reading `cairn://artifacts` with no active artifacts returns a non-error markdown string.

**2. `src/cairn_mcp/resources.py`** — gated by the test file above.

Add `register_data_resources`. Both handlers are async closures over `settings`, `s3`, `vectors`, `bedrock`. The `cairn://artifact/{id}` handler extracts `id` from the URI, delegates to the read tool, converts the result to a markdown resource or raises on error. The `cairn://artifacts` handler delegates to the list tool and renders a markdown table from the returned artifact list.

**3. `src/cairn_mcp/server.py`** — gated by the test file above.

Import `register_data_resources` from `cairn_mcp.resources`. Call `register_data_resources(_app, settings, s3, vectors, bedrock)` as the last statement in `register_tools()`.

## Open Questions

- [ ] ULID-to-ISO-8601: confirm the correct conversion approach for deriving `lastModified` from `last_edited_ulid`. ULIDs encode a millisecond timestamp in their first 10 characters — confirm the extraction formula before implementing.
- [ ] FastMCP annotation API: confirm the exact FastMCP 3.x API for setting `audience` and `lastModified` on a resource response (decorator parameter vs. returned object field). Check FastMCP docs or source before implementing to avoid guessing.
- [ ] Error surface for resource handlers: confirm whether FastMCP resource handlers should raise a Python exception (FastMCP maps it to `-32002`/`-32603`) or return a structured error string. Check FastMCP 3.x resource error handling conventions.
