"""arkeology.resources — MCP Resource definitions for runtime schema discovery.

All five schema resources are pure documentation with no AWS calls. Each content
function reads ``ARTIFACT_TYPES`` from the ``arkeology.artifact`` module object at
call-time so that monkey-patching in tests (and future schema changes) are reflected
without restarting the server.

Data resources (``arkeology://artifact/{id*}`` and ``arkeology://artifacts``) require live AWS
client references and are registered via ``register_data_resources``, called from
``server.py`` after clients are constructed.

The UI resource (``ui://arkeology-studio/index.html``) is static and registered via
``register_ui_resource``, which is called at module load time alongside
``register_resources``.
"""

import importlib.resources
import logging
from collections.abc import Callable
from typing import Any

import fastmcp
from fastmcp.apps.config import AppConfig, ResourceCSP
from mcp.types import Annotations
from ulid import ULID

import arkeology.artifact as _artifact_module
from arkeology.clients.interfaces import (
    BedrockClientInterface,
    S3ClientInterface,
    VectorsClientInterface,
)
from arkeology.config import Settings
from arkeology.constants import ArtifactStatus
from arkeology.tools.list import list_artifacts as _list_artifacts
from arkeology.tools.read import read_artifact as _read_artifact

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Content functions — pure, synchronous, no I/O
# ---------------------------------------------------------------------------


def artifact_schema_content() -> str:
    """Return markdown describing the full artifact schema.

    Derives the list of valid ``type`` values live from ``ARTIFACT_TYPES`` so
    that schema changes are reflected automatically on the next call.

    Returns:
        Markdown string suitable for direct consumption by a language model.
    """
    types = _artifact_module.ARTIFACT_TYPES
    types_list = "\n".join(f"  - `{t}`" for t in sorted(types))

    return f"""\
# arkeology Artifact Schema

## Required fields

| Field | Type | Valid values / constraints |
|-------|------|---------------------------|
| `type` | string | One of the types listed below |
| `team` | string | Team identifier (free text) |
| `project` | string | Project identifier (free text) |
| `tier` | integer | `2` (project-local) or `3` (permanent/shared) |
| `date` | string | ISO-8601 date — `YYYY-MM-DD` |
| `status` | string | `active` or `inactive` |
| `title` | string | Human-readable artifact title |
| `visibility` | string | `shared` or `hidden` |
| `description` | string | Short summary — **≤ 280 characters** |

## Optional fields

| Field | Type | Notes |
|-------|------|-------|
| `tags` | list[string] | Searchable tags; enables `tags` filter |
| `author_role` | string | Role of the author (e.g. `"developer"`) |
| `source_artifacts` | list[string] | Source IDs for a `synthesis` artifact |
| `commit_refs` | list[string] | Git commit SHAs linked to this artifact via `link_metadata` |
| `references` | list[string] | Full operative `artifact_id`s this artifact points at |

Each `references` element is a full operative `artifact_id` — scope prefix and file extension
included, exactly as `write_artifact` and `read_artifact` return it, and exactly what the vector
index is keyed on. Never an `arkeology://` URI, never a repository path, and never the id with
its scope prefix stripped: a prefix-less element fails the cross-scope readability check and is
silently dropped from a foreign reader's view of the artifact.

`commit_refs` is accretive: an overwriting write MERGES the supplied value with the artifact's
existing `commit_refs` (never dropped) — it is a durable audit trail with no frontmatter
counterpart. `references` mirrors the artifact's current state: an overwriting write REPLACES
the existing value outright with exactly what is supplied — omitting `references` on a write
CLEARS it, so re-supply the full intended list rather than relying on a prior value surviving.

Filtering `list_artifacts(commit_refs=[...])` searches only an artifact's most-recent 20
commit refs — the filterable index copy is capped at that many entries. An artifact linked to
more commits than that will not be found by its oldest SHAs, even though `read_artifact` and
the `commit_refs` field returned by `list_artifacts` both still show the complete list. Use the
filter for recent work; read the field when you need the whole history.

## System-generated fields

These fields are set by the server and returned in tool responses. They cannot be supplied
by the caller.

| Field | Type | Notes |
|-------|------|-------|
| `last_edited_ulid` | string | Write-time ULID; use as `since_ulid` in `propose_commit_links` |
| `last_edited_at` | string or null | ISO-8601 time from `last_edited_ulid`; `null` if unparseable |

`last_edited_ulid` is returned by `read_artifact`, `list_artifacts`, and `search_artifacts`.
`search_artifacts` results additionally carry the derived `last_edited_at`: because search
ranking is by semantic relevance only, use this last-edited time to judge recency and
discount stale hits rather than trusting rank order alone.

## Valid artifact types

{types_list}

## Enum constraints summary

- **tier**: `2` or `3`
- **status**: `active` or `inactive`
- **visibility**: `shared` or `hidden`
- **description**: maximum 280 characters
"""


def tiers_schema_content() -> str:
    """Return markdown describing tier 2 vs tier 3 semantics and key formats.

    Returns:
        Markdown string suitable for direct consumption by a language model.
    """
    return """\
# arkeology Tier Model

## Tier 2 — Project-local, date-anchored records

Tier 2 artifacts are session-scoped working records. They are **append-only**:
once written, their content is **immutable** by default — re-writing the same
title and date targets the same key and is **rejected** (`validation_error`)
rather than silently overwritten. Pass `overwrite=true` to `write_artifact` to
intentionally replace an existing tier 2 record in place (e.g. a correction).

**Key format:** `{type_slug}-{date}-{title_slug}-{hash}` — `hash` is a deterministic
8-hex-char digest of the full title, always appended so distinct titles never
collide on the same key even after slug normalisation.

Example: a code review written on 2026-05-31 with title "Auth module review" becomes
`code-review-2026-05-31-auth-module-review-33559d57`.

**Use for:** brainstorming, code_review, session_summary, implementation_note, bug_report,
changelog, postmortem

**Cross-scope access:** tier 2 artifacts are strictly project-local. They are never
accessible outside the deployment's own `WRITE_PREFIX` scope, regardless of visibility.

---

## Tier 3 — Permanent, date-independent knowledge

Tier 3 artifacts are canonical knowledge that persists and evolves. Re-writing a tier 3
artifact with the same type and title targets the same stable, date-independent key —
but is still rejected by default (`validation_error`) unless the write explicitly passes
`overwrite=true` to `write_artifact`, which then **overwrites in place**. Orphaned
section vectors from the previous version are cleaned up automatically on an
overwrite.

**Key format:** `{type_slug}-{title_slug}-{hash}` (omits date — date-independent;
`hash` is the same deterministic 8-hex-char title digest as tier 2)

Example: an ADR with title "Use S3 Vectors for embeddings" becomes
`adr-use-s3-vectors-for-embeddings-788ff524`.

**Use for:** adr, spec, decision_note, synthesis, plan, vision, requirements, runbook, learning

**Cross-scope access:** tier 3 artifacts with `visibility=shared` are discoverable by
agents pointing at the same vector index with different `WRITE_PREFIX` scopes.
"""


def visibility_schema_content() -> str:
    """Return markdown describing visibility values and cross-scope access rules.

    Returns:
        Markdown string suitable for direct consumption by a language model.
    """
    return """\
# arkeology Visibility and Cross-Scope Access

## Visibility values

| Value | Meaning |
|-------|---------|
| `shared` | Discoverable by agents in other scopes pointing at the same index |
| `hidden` | Accessible only within the deployment's own `WRITE_PREFIX` scope |

## Cross-scope access rule

**Only tier 3 + shared artifacts are accessible across scopes.**

The cross-scope gate enforces two conditions simultaneously:
1. `tier == 3` — tier 2 artifacts are always project-local, regardless of visibility
2. `visibility == "shared"` — hidden tier 3 artifacts remain private to their own scope

| Tier | Visibility | Own scope | Foreign scope |
|------|-----------|-----------|---------------|
| 2 | shared | ✅ accessible | ❌ blocked |
| 2 | hidden | ✅ accessible | ❌ blocked |
| 3 | shared | ✅ accessible | ✅ accessible |
| 3 | hidden | ✅ accessible | ❌ blocked |

## Guidance

- Default to `visibility=shared` for ADRs, architecture decisions, and specs that other
  teams should be able to find — canonical knowledge benefits from cross-project
  discoverability.
- Use `visibility=hidden` for team-specific working documents, drafts, or anything
  containing information that should not cross team boundaries.
- **Note:** cross-scope visibility control is enforced at the MCP server layer, not by the
  storage layer. Artifact content in S3 can be IAM-restricted per prefix, but a shared
  vector index cannot discriminate between callers — every deployment sharing the index can
  technically read all vector metadata (titles, descriptions, tags) and embeddings,
  regardless of tier or visibility. Write descriptions of `hidden` artifacts accordingly.
"""


def types_schema_content() -> str:
    """Return markdown describing every artifact type with usage guidance.

    Derives the type list live from ``ARTIFACT_TYPES`` so changes are reflected
    automatically on the next call.

    Returns:
        Markdown string suitable for direct consumption by a language model.
    """
    types = _artifact_module.ARTIFACT_TYPES

    _descriptions: dict[str, str] = {
        "adr": (
            "Architectural Decision Record — records a significant design decision,"
            " its context, and rationale. Tier 3, shared."
        ),
        "brainstorming": (
            "Brainstorming — captures options explored, trade-offs weighed, and"
            " directions considered during ideation. Tier 2."
        ),
        "spec": (
            "Feature or technical specification — defines requirements, acceptance"
            " criteria, or implementation guidance. Tier 3, shared."
        ),
        "code_review": (
            "Code review findings — documents review observations, issues found,"
            " and recommendations for a change. Tier 2."
        ),
        "session_summary": (
            "Agent session summary — captures what was accomplished, decisions made,"
            " and next steps in a work session. Tier 2."
        ),
        "implementation_note": (
            "Implementation note — records non-obvious decisions, gotchas, and"
            " trade-offs made during implementation. Tier 2."
        ),
        "bug_report": (
            "Bug report — describes a defect, its root cause, reproduction steps,"
            " and the fix applied. Tier 2."
        ),
        "decision_note": (
            "Decision note — lighter-weight than an ADR; captures a point-in-time"
            " decision without full ADR structure. Tier 3."
        ),
        "synthesis": (
            "Synthesis — agent-compiled summary of multiple source artifacts;"
            " written back with source_artifacts=[...]. Tier 3."
        ),
        "vision": (
            "Product vision — problem statement, target users, user journeys,"
            " and differentiator. Tier 3, shared."
        ),
        "requirements": (
            "Functional, non-functional, and acceptance-criteria requirements —"
            " what to build and constraints. Tier 3, shared."
        ),
        "plan": (
            "Project or sprint plan — ordered task breakdown, milestones, and dependencies. Tier 3."
        ),
        "runbook": (
            "Operational runbook — step-by-step procedures for deployment, rollback,"
            " and incident response. Tier 3."
        ),
        "changelog": (
            "Changelog entry — records features shipped, bugs fixed, and breaking"
            " changes for a release. Tier 2."
        ),
        "postmortem": (
            "Post-incident analysis — timeline, root cause, customer impact,"
            " remediation, and follow-up actions. Tier 2."
        ),
        "learning": (
            "Durable technical learnings — a living, continuously appended record of"
            " non-obvious lessons, gotchas, and corrected assumptions. Tier 3."
        ),
    }

    lines = ["# arkeology Artifact Type Catalogue\n"]
    for t in sorted(types):
        desc = _descriptions.get(t, f"Artifact of type `{t}`.")
        lines.append(f"## `{t}`\n\n{desc}\n")

    return "\n".join(lines)


def query_strategy_content() -> str:
    """Return markdown describing the recommended query strategy for agents.

    Returns:
        Markdown string suitable for direct consumption by a language model.
    """
    return """\
# arkeology Query Strategy

## Principle: start narrow, broaden only when needed

1. **Add filters first.** Specify `type` and `tags` before relying on pure semantic
   similarity. A narrow query with `type="adr"` and `tags=["auth"]` returns the
   most relevant ADRs for the authentication domain without noise from other types.

2. **Broaden when narrow returns insufficient results.** Drop `tags` first, then
   `type`, then let the semantic query do the heavy lifting. Each iteration should be a
   deliberate widening step.

3. **Use `list_artifacts` for known-type browsing.** When you want all artifacts of a type
   (e.g. all active specs for a project), `list_artifacts` with `type`, `team`, and
   `project` filters is cheaper and more predictable than a semantic search.

4. **Use `search_artifacts` for concept queries.** When the question is conceptual — "what
   did we decide about the auth redesign?" — use `search_artifacts` with a natural-language
   `query`. Combine with `type` or `tags` to stay narrow. Results are ranked by semantic
   relevance only; each entry carries `last_edited_ulid` and a derived `last_edited_at`, so
   check the last-edited time to discount stale hits rather than trusting rank order alone.

## When to use `synthesise_artifacts`

Use `synthesise_artifacts` when you need to compile knowledge from multiple related
artifacts — for example, summarising all code reviews after a feature ships, or
consolidating session notes for a sprint.

`synthesise_artifacts` runs a semantic search and returns **full content** for the top-k
results in a single call, up to a response-size budget (1 MB of content by default,
configurable) — if the budget is reached first, the response sets `truncated: true` and
`included: N`; a single oversized top-ranked result is still returned rather than dropped.
After synthesising in-context, write the result back using `write_artifact` with:

- `type="synthesis"`
- `tier=3`
- `source_artifacts=[<list of artifact_id values from the synthesise response>]`

This records which artifacts contributed to the synthesis and makes the compiled knowledge
searchable as a standalone tier 3 artifact.

## When to use `propose_commit_links` and `link_metadata`

Use these two tools together at the end of a coding session to attach the session's commit
SHA(s) to every artifact written during that session.

**Workflow:**

1. Note the `last_edited_ulid` returned by the first `write_artifact` call of the session —
   this is the `since_ulid` value.
2. Call `propose_commit_links(commit_sha=<sha>, since_ulid=<ulid>)` — returns own-scope
   artifacts with no `commit_refs` that were written at or after `since_ulid`.
3. Review the proposed list. Confirm which artifact IDs should be linked.
4. Call `link_metadata(artifact_ids=[...], commit_refs=[<sha>])` — merges the SHA into
   each confirmed artifact's `commit_refs` without re-embedding. `link_metadata` also
   accepts a `references` list to backfill resolved artifact-to-artifact references in
   the same call.

If `since_ulid` is omitted, `propose_commit_links` returns **all** own-scope artifacts
with no `commit_refs` — useful for a bulk back-fill of an existing index.

## Runtime schema reference

For precise field constraints, valid enum values, and tier semantics, read these resources:

- `arkeology://schema/artifact` — required and optional fields, enum values, constraints
- `arkeology://schema/tiers` — tier 2 vs tier 3 semantics and key formats
- `arkeology://schema/visibility` — visibility values and cross-scope access rules
- `arkeology://schema/types` — type catalogue with usage guidance
"""


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

#: Schema resource registration table: ``(uri, description, content_fn)``.
#: ``register_resources`` loops over this to register each read-only schema
#: resource. The description was previously each handler's docstring; it is now
#: passed explicitly so the registrations are data-driven. Adding a schema
#: resource is a one-line entry here.
_SCHEMA_RESOURCES: list[tuple[str, str, Callable[[], str]]] = [
    (
        "arkeology://schema/artifact",
        "Full artifact schema: required/optional fields, enum values, and constraints.",
        artifact_schema_content,
    ),
    (
        "arkeology://schema/tiers",
        "Tier 2 vs tier 3 semantics, key formats, and access rules.",
        tiers_schema_content,
    ),
    (
        "arkeology://schema/visibility",
        "Visibility values and the cross-scope access gate.",
        visibility_schema_content,
    ),
    (
        "arkeology://schema/types",
        "Artifact type catalogue with one-line usage guidance per type.",
        types_schema_content,
    ),
    (
        "arkeology://schema/query-strategy",
        "Recommended query strategy: start narrow, when to list vs search vs synthesise.",
        query_strategy_content,
    ),
]


def register_resources(app: fastmcp.FastMCP) -> None:
    """Register all five arkeology:// schema resources on the FastMCP app.

    Resources are read-only, pure, and require no injected AWS clients. This
    function is called once from ``server.py`` at module load time, after the
    ``_app`` instance is created.

    Args:
        app: The FastMCP application instance to register resources on.
    """
    for uri, description, content_fn in _SCHEMA_RESOURCES:
        app.resource(uri, description=description)(content_fn)

    logger.debug("arkeology resources registered (%d schema resources)", len(_SCHEMA_RESOURCES))


# ---------------------------------------------------------------------------
# UI resource registration
# ---------------------------------------------------------------------------

#: CDN origins that the arkeology studio application is permitted to load from.
#: Only the ext-apps SDK (unpkg) and marked.js / mermaid.js (jsDelivr) are allowed.
#: Google Fonts origins are deliberately NOT declared — loading web fonts from a
#: third-party CDN leaks the user's IP and is disallowed on GDPR grounds; typography
#: uses the ``system-ui`` stack.
_BROWSER_CDN_ORIGINS: list[str] = [
    "https://unpkg.com",
    "https://cdn.jsdelivr.net",
]


def register_ui_resource(app: fastmcp.FastMCP) -> None:
    """Register the ``ui://arkeology-studio/index.html`` resource on the FastMCP app.

    The resource serves the arkeology studio HTML application. It is registered
    with ``ResourceCSP`` declaring the CDN origins the application loads from.
    No explicit ``mime_type`` is set — FastMCP auto-resolves ``ui://`` resources
    to ``text/html;profile=mcp-app``, which is the MIME type Claude Desktop
    requires to render an MCP App iframe rather than displaying raw text.
    The HTML is read from the ``arkeology/static/arkeology-studio.html`` package
    file using ``importlib.resources``.

    This function must be called at module load time (alongside
    ``register_resources``) because the UI resource is static — it requires no
    AWS clients and must be available before any tool calls.

    Args:
        app: The FastMCP application instance to register the resource on.
    """

    @app.resource(
        "ui://arkeology-studio/index.html",
        description="arkeology studio — visual reading interface to browse artifacts.",
        app=AppConfig(csp=ResourceCSP(resource_domains=_BROWSER_CDN_ORIGINS)),
    )
    def _arkeology_studio_html() -> str:
        """Return the arkeology studio HTML application."""
        return (
            importlib.resources.files("arkeology")
            .joinpath("static/arkeology-studio.html")
            .read_text(encoding="utf-8")
        )

    logger.debug("arkeology UI resource registered (ui://arkeology-studio/index.html)")


# ---------------------------------------------------------------------------
# Data resource helpers — testable content functions
# ---------------------------------------------------------------------------


def _error_markdown(result: dict[str, Any]) -> str:
    """Build a markdown error message from an errored tool result dict.

    Args:
        result: A tool result dict containing an ``error`` code and optional ``message``.

    Returns:
        A markdown string of the form ``# Error: <code>\\n\\n<message>\\n``.
    """
    error_code = result.get("error", "error")
    message = result.get("message", "Unknown error.")
    return f"# Error: {error_code}\n\n{message}\n"


async def _artifact_resource_content(
    *,
    artifact_id: str,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface | None,
    bedrock: BedrockClientInterface | None,
) -> tuple[str, str]:
    """Fetch artifact content for the arkeology://artifact/{id*} resource.

    Delegates entirely to ``read_artifact`` so the cross-scope gate is enforced
    without duplication.

    Returns:
        A ``(content, mime_type)`` tuple.  On error, ``content`` is a markdown
        error message and ``mime_type`` is ``"text/markdown"``.
    """
    result: dict[str, Any] = await _read_artifact(
        settings=settings,
        s3=s3,
        vectors=vectors,
        bedrock=bedrock,
        artifact_id=artifact_id,
    )

    if "error" in result:
        return _error_markdown(result), "text/markdown"

    content: str = str(result.get("content", ""))
    return content, "text/markdown"


async def _artifact_last_modified(
    *,
    artifact_id: str,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface | None,
    bedrock: BedrockClientInterface | None,
) -> str | None:
    """Derive the ``lastModified`` ISO 8601 string from an artifact's ``last_edited_ulid``.

    Returns ``None`` when the artifact has no ``last_edited_ulid`` (annotation omitted).

    Intentionally retained though not wired into the resource handler: emitting a per-read
    ``lastModified`` annotation on the ``arkeology://artifact/{id*}`` *template* resource is not
    expressible in the pinned stack (FastMCP 3.4 + MCP SDK) — template annotations are static
    and ``TextResourceContents`` carries no ``annotations`` field. This helper keeps the
    (unit-tested) ULID→ISO conversion ready to wire in once the protocol supports it. See the
    waiver in ``docs/specs/p10-t42-mcp-data-resources.md``.
    """
    result: dict[str, Any] = await _read_artifact(
        settings=settings,
        s3=s3,
        vectors=vectors,
        bedrock=bedrock,
        artifact_id=artifact_id,
    )
    if "error" in result:
        return None

    ulid_str: str | None = result.get("last_edited_ulid") or None
    if ulid_str is None:
        return None

    try:
        return ULID.from_str(ulid_str).datetime.isoformat()
    except Exception:
        logger.warning("Failed to parse last_edited_ulid %r as ULID", ulid_str)
        return None


def _render_artifacts_markdown(artifacts: list[dict[str, Any]]) -> str:
    """Render a list of artifact dicts as a markdown table.

    Columns: Identifier, Title, Type, Description.
    """
    if not artifacts:
        return "# Artifacts\n\nNo active artifacts found in the current scope.\n"

    lines = [
        "# Artifacts\n",
        "| Identifier | Title | Type | Description |",
        "|------------|-------|------|-------------|",
    ]
    for artifact in artifacts:
        # Escape pipe characters and collapse embedded line breaks inside each cell
        # value (via splitlines) so a '\n'/'\r' can never split one logical table row
        # into multiple physical lines.
        cells = [
            " ".join(str(artifact.get(key, "")).replace("|", "\\|").splitlines())
            for key in ("artifact_id", "title", "type", "description")
        ]
        lines.append("| " + " | ".join(cells) + " |")

    return "\n".join(lines) + "\n"


async def _artifacts_listing_content(
    *,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface | None,
) -> str:
    """Fetch the active readable-scope artifact listing for the arkeology://artifacts resource.

    Delegates to ``list_artifacts`` with ``status="active"`` and no other filters, so the
    listing carries exactly what that tool returns by default: active own-scope artifacts
    plus any foreign-scope artifact that passes the cross-scope gate (tier 3 and shared).
    It is deliberately not own-scope-only — the resource mirrors the tool.

    Returns:
        A markdown string.  On error, returns a minimal markdown error message.
    """
    result: dict[str, Any] = await _list_artifacts(
        settings=settings,
        s3=s3,
        vectors=vectors,
        bedrock=bedrock,
        status=ArtifactStatus.ACTIVE,
    )

    if "error" in result:
        return _error_markdown(result)

    artifacts: list[dict[str, Any]] = result.get("artifacts", [])
    return _render_artifacts_markdown(artifacts)


# ---------------------------------------------------------------------------
# Data resource registration
# ---------------------------------------------------------------------------


def register_data_resources(
    app: fastmcp.FastMCP,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface,
) -> None:
    """Register arkeology data resources on the FastMCP app.

    Registers two resources with ``audience: ["user"]`` annotations:

    - ``arkeology://artifact/{id*}`` — URI template; returns full markdown content of
      a named artifact, applying the same cross-scope gate as ``read_artifact``. The
      ``{id*}`` RFC 6570 wildcard-path parameter (not plain ``{id}``) is required
      because ``id`` is the full S3 key — ``{write_prefix}/{bare_id}{extension}`` —
      which contains ``/`` characters; a plain ``{id}`` segment parameter (the FastMCP
      default) only matches a single path segment and would reject every real
      artifact_id. Does NOT include a per-artifact ``lastModified`` annotation — see
      the ``NOTE:`` comment in ``_artifact_resource`` below for why this is waived.
    - ``arkeology://artifacts`` — static listing; returns a markdown table of every active
      artifact readable in this scope (own-scope plus gate-passing foreign tier-3 shared),
      matching ``list_artifacts``' default scope.

    This function must be called after the AWS clients are constructed (i.e. from
    ``register_tools()`` in ``server.py``), not at module load time.

    Args:
        app: The FastMCP application instance to register resources on.
        settings: Validated server configuration.
        s3: Concrete S3 client.
        vectors: Concrete S3 Vectors client.
        bedrock: Concrete Bedrock client.
    """

    @app.resource(
        "arkeology://artifact/{id*}",
        mime_type="text/markdown",
        annotations=Annotations(audience=["user"]),
        description="Full markdown content of a named artifact.",
    )
    async def _artifact_resource(id: str) -> str:  # noqa: A002
        """Return the full markdown content of the artifact identified by ``id``.

        ``id`` is the full S3 key (``{write_prefix}/{bare_id}{extension}``), matched via
        the ``{id*}`` RFC 6570 wildcard-path template parameter so that the ``/``
        characters in a real artifact_id are captured rather than truncating the match
        at the first path segment.
        """
        try:
            # NOTE: the per-artifact `lastModified` annotation (T42) is intentionally NOT
            # emitted here — it is waived. This is a resource *template* (`{id*}`): its
            # `annotations` are declared once at registration and cannot vary per id, and the
            # only per-read channel, `TextResourceContents`, has no `annotations` field in the
            # pinned MCP SDK. So a per-artifact `lastModified` cannot be attached to a template
            # read. The derivation helper (`_artifact_last_modified`) is retained and unit-tested
            # for when the protocol supports it. See the waiver in docs/specs/p10-t42. The static
            # `audience: ["user"]` annotation IS emitted (it is identical for every read), and the
            # content itself is always fresh.
            content, _mime = await _artifact_resource_content(
                artifact_id=id,
                settings=settings,
                s3=s3,
                vectors=vectors,
                bedrock=bedrock,
            )
            return content
        except Exception as exc:
            logger.exception("Unexpected error in arkeology://artifact/{id*} resource handler")
            return f"# Error: internal_error\n\n{exc}\n"

    @app.resource(
        "arkeology://artifacts",
        mime_type="text/markdown",
        annotations=Annotations(audience=["user"]),
        description=(
            "Markdown index of all active artifacts readable in this scope — own-scope "
            "plus shared tier-3 artifacts from readable foreign scopes."
        ),
    )
    async def _artifacts_resource() -> str:
        """Return a markdown listing of every active artifact readable in this scope."""
        try:
            return await _artifacts_listing_content(
                settings=settings,
                s3=s3,
                vectors=vectors,
                bedrock=bedrock,
            )
        except Exception as exc:
            logger.exception("Unexpected error in arkeology://artifacts resource handler")
            return f"# Error: internal_error\n\n{exc}\n"

    logger.debug(
        "arkeology data resources registered (arkeology://artifact/{id*}, arkeology://artifacts)"
    )
