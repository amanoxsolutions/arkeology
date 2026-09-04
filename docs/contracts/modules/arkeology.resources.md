---
type: Contract
title: arkeology.resources
description: The MCP resource surface — five pure read-only schema resources describing the artifact model and two client-backed data resources returning artifact content and an own-scope index, both under the arkeology:// scheme, plus the ui:// resource serving the Arkeology Studio MCP App and declaring its content-security policy.
tags: []
timestamp: 2026-09-04T00:00:00Z
okf_version: "0.1"
references:
  - docs/specs/p4-t18-mcp-resources.md
  - docs/specs/p10-t42-mcp-data-resources.md
  - docs/specs/p11-t43-mcp-app-infrastructure.md
authored:
  by: "tech-writer"
  date: 2026-09-04
revised:
  by: "architect"
  date: 2026-09-04
---

# arkeology.resources

## Scope

The MCP resource boundary. Resources differ from tools in that a host may fetch them without an
agent deciding to — so their URI scheme, their purity, and their gate behaviour are a contract with
the host, not just with a calling agent.

Two URI schemes are served, and the distinction is load-bearing. `arkeology://` resources are data:
schema documents and artifact content. `ui://` serves the Studio MCP App itself — the host renders
it as a sandboxed iframe, so its declared content-security policy is a security boundary, not a
presentation detail.

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

### register_ui_resource

```python
def register_ui_resource(app: fastmcp.FastMCP) -> None: ...
```

Registers the single `ui://arkeology-studio/index.html` resource, which returns the bundled
`arkeology/static/arkeology-studio.html` as text. This is the resource
`arkeology_studio`'s `resource_uri` app config points at; without it that tool has nothing to
render.

**Errors**

Registration itself cannot fail. A read fails only if the packaged HTML asset is missing from the
installed distribution, which surfaces as the underlying `importlib.resources` error.

**Invariants**

- No `mime_type` is set explicitly. FastMCP auto-resolves `ui://` resources to
  `text/html;profile=mcp-app`, which is the MIME type a host requires to render an MCP App iframe
  rather than displaying the HTML as raw text. Setting `mime_type` by hand overrides that
  resolution and breaks rendering.
- The resource is **static** — it takes no AWS clients and holds no state, which is why it is
  registered at module load time alongside `register_resources` rather than after client
  construction.
- The HTML is read from the installed package via `importlib.resources`, never from a path relative
  to the source tree, so it resolves identically from a wheel, an editable install, and a zipapp.
- The app is a single self-contained file. It has no build step, which is what makes the design
  token layer (see `docs/contracts/design/arkeology-studio-tokens.html`) plain CSS custom
  properties rather than DTCG.

**Content-security policy**

The resource is registered with `AppConfig(csp=ResourceCSP(resource_domains=...))`. That allow-list
is the app's **complete** set of permitted external origins; a host is entitled to block anything
outside it. The current allow-list is:

| Origin | Loaded for |
|---|---|
| `https://unpkg.com` | the MCP Apps client extension bridge |
| `https://cdn.jsdelivr.net` | Markdown rendering, HTML sanitisation, and Mermaid diagram rendering |

- The allow-list is an **origin** allow-list, not a package or version allow-list. Permitting an
  origin permits every asset served from it, so widening it widens the app's script-execution
  surface — it is a security decision, not a dependency bump.
- Adding an origin here without a corresponding load in the HTML grants reach the app does not
  need; adding a load to the HTML without the origin here produces a silent runtime failure in a
  CSP-enforcing host. The two must be changed together.
- HTML sanitisation of artifact content is not delegated to the CSP. The app sanitises rendered
  Markdown itself, and the `npm test` link-sanitisation guard covers that; the CSP bounds where
  code may be *fetched from*, not what the app does with artifact text.

**Preconditions**

- May be called at module load time; requires no AWS clients.

**Postconditions**

- `ui://arkeology-studio/index.html` is resolvable and returns the app HTML verbatim on every read;
  nothing is cached and no artifact data is embedded in it.
