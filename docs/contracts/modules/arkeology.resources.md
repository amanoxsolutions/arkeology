---
type: Contract
title: arkeology.resources
description: The MCP resource surface — five pure read-only schema resources describing the artifact model, and two client-backed data resources returning artifact content and an own-scope index, all under the arkeology:// scheme.
tags: []
timestamp: 2026-09-04T00:00:00Z
okf_version: "0.1"
references:
  - docs/specs/p4-t18-mcp-resources.md
  - docs/specs/p10-t42-mcp-data-resources.md
authored:
  by: "tech-writer"
  date: 2026-09-04
revised:
  by: ""
  date: YYYY-MM-DD
---

# arkeology.resources

## Scope

The MCP resource boundary. Resources differ from tools in that a host may fetch them without an
agent deciding to — so their URI scheme, their purity, and their gate behaviour are a contract with
the host, not just with a calling agent.

## Symbols

### register_resources

```python
def register_resources(app: fastmcp.FastMCP) -> None: ...
```

**Errors**

None. Registration is pure bookkeeping over static content functions.

**Invariants**

- Registers exactly the five `arkeology://schema/*` resources: `artifact`, `tiers`, `visibility`,
  `types`, and `query-strategy`.
- All five are **read-only, pure, and require no injected AWS client**. They describe the model, so
  they must be fetchable on a deployment whose AWS access is broken — that is precisely when an
  agent needs to know the schema.
- Safe to call at module load time, before any client exists.
- The `types` resource's content is derived from `ARTIFACT_TYPES`, the single source of truth. It
  must never restate the type list independently.

**Preconditions**

- Called once, from server module load.

**Postconditions**

- Five schema resources are resolvable on the app.
- Their content is identical across calls and across deployments — no scope, no configuration, and
  no live data leaks into a schema resource.

### register_data_resources

```python
def register_data_resources(
    app: fastmcp.FastMCP,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface,
) -> None: ...
```

**Errors**

None at registration. Each registered handler catches every exception and returns a Markdown error
body rather than raising, because a resource read has no structured error channel the way a tool
result does.

**Invariants**

- Registers exactly two resources, both `mime_type="text/markdown"` and both annotated
  `audience: ["user"]` — they are aimed at a person reading, not an agent parsing.
- `arkeology://artifact/{id*}` uses the RFC 6570 **wildcard-path** parameter `{id*}`, not a plain
  `{id}`. `id` is the full S3 key `{write_prefix}/{bare_id}{extension}`, which contains `/`; a
  plain segment parameter matches one segment only and would reject every real artifact id.
  Changing `{id*}` back to `{id}` breaks the entire resource.
- `arkeology://artifact/{id*}` applies **the same cross-scope gate as `read_artifact`**. A resource
  read is not a gate bypass, and must never become one.
- `arkeology://artifacts` returns **active own-scope** artifacts only.
- A handler failure returns a Markdown error body, never an empty document — an empty listing and a
  failed listing must stay distinguishable to a reader.
- The per-artifact `lastModified` annotation is **deliberately waived** on the template resource: a
  resource template declares its annotations once at registration and cannot vary them per id, and
  the pinned SDK's per-read content channel has no annotations field. The derivation helper is
  retained and unit-tested against the day the protocol supports it. The static
  `audience: ["user"]` annotation is emitted because it is identical for every read.

**Preconditions**

- Must be called **after** the AWS clients are constructed — from tool registration, not at module
  load time. Registering these at import time would capture clients that do not yet exist.

**Postconditions**

- Both data resources are resolvable and return fresh content on every read; nothing is cached.
- No resource ever returns content the caller's scope may not read.
