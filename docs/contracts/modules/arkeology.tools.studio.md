---
type: Contract
title: arkeology.tools.studio
description: The arkeology_studio MCP tool — triggers the inline MCP Apps visual artifact browser on supporting hosts and returns a bounded plain-text listing on non-supporting hosts, never coercing a failure into an empty listing.
tags: []
timestamp: 2026-09-04T00:00:00Z
okf_version: "0.1"
references:
  - docs/specs/p11-t43-mcp-app-infrastructure.md
  - docs/specs/p11-t44-browser-ui.md
  - docs/specs/p10-t42-mcp-data-resources.md
authored:
  by: "tech-writer"
  date: 2026-09-04
revised:
  by: "tech-writer"
  date: 2026-09-06
---

# arkeology.tools.studio

## Scope

The human reading entry point. It is the only tool whose result is aimed at a person rather than an
agent, and the only one returning a `ToolResult` rather than a plain dict — because its job is to
hand rendering to a UI extension where one exists.

## Symbols

### arkeology_studio

```python
async def arkeology_studio(
    *,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    ctx: Context,
) -> ToolResult: ...
```

**Errors**

Never raises. A failure is returned as a structured error `ToolResult` with `is_error=True` and
`structured_content` carrying `error` and `message`.

**Invariants**

- Always returns a `ToolResult` carrying a short `content` block for the LLM, on every path.
- On a **UI-supporting host**, `structured_content` is **omitted**. The iframe loads the artifact
  list itself on mount, so duplicating it in the tool result would spend context for nothing.
- On a **non-supporting host**, `structured_content` is populated with `write_prefix`, `artifacts`,
  and `total_count`, so the client gets a usable listing without a second `list_artifacts` call.
- The fallback listing is **bounded** by `FALLBACK_LISTING_CAP` (50), because it is destined for an
  agent's context window and an unbounded store would fill it.
- The cap keeps the **50 most recent** artifacts, not an arbitrary 50. The listing is ordered
  `date` **descending**, tie-broken by `artifact_id` **ascending**, and the cap slices the head of
  that order. Both halves are required: the date ordering is what makes "most recent" true, and
  the `artifact_id` tie-break is what makes the result **stable** — without it, two artifacts
  sharing a `date` could swap places between identical calls, so which one survived the cap would
  vary run to run. An implementation satisfying every other clause here while returning an
  arbitrary 50 would be wrong, and `total_count` would still report the correct pre-cap total, so
  nothing else in this contract would catch it.
- `total_count` carries the full **pre-cap** match count, so a truncated listing can never be
  mistaken for a complete one. Reporting the post-cap length here would silently misrepresent the
  store's size.
- A failure of the inner `list_artifacts` call is surfaced as a structured error — **never** coerced
  into an empty listing, and never capped or reordered. An empty listing and a broken listing must
  remain distinguishable.
- The outer catch-all's `content` message is a **fixed, generic** one and **never** the underlying
  exception text. `str(exc)` on a boto error can carry a bucket name, an ARN, or an account id,
  and this message reaches the client verbatim. The exception detail belongs in the server log,
  written via `logger.exception`.
- The underlying cross-scope gate is inherited from `list_artifacts`; this tool adds no access
  control of its own and must not weaken it.
- When this tool is active and the browser UI triggers `read_artifact`, `list_artifacts`, or
  `search_artifacts` on a user's behalf, the calling agent must not summarize, reformat, or
  interpret the result — the UI handles rendering, and the agent's role ends after the initial
  invocation.

**Preconditions**

- `ctx` is the FastMCP request context; host UI capability is detected from it rather than
  configured.
- The tool is registered with its `resource_uri` app config pointing at the bundled HTML asset.

**Postconditions**

- Host UI support determines the shape of `structured_content` on every path that reaches the
  fallback logic — omitted (host supports the UI extension), populated with the listing, or an
  error payload from a failed inner `list_artifacts`.
- A fourth shape exists and callers must handle it: the outer catch-all, on an unexpected
  exception anywhere in the tool, returns `is_error=True` with the message in `content` and **no**
  `structured_content` at all. A host that reads errors only from `structured_content` sees
  nothing on this path, so error detection must key on `is_error`, with `content` as the fallback
  message source. The four shapes together are exhaustive.
- The returned listing, when present, reflects only artifacts the caller's scope may read.
