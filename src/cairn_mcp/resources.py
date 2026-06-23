"""cairn_mcp.resources — MCP Resource definitions for runtime schema discovery.

All five schema resources are pure documentation with no AWS calls. Each content
function reads ``ARTIFACT_TYPES`` from the ``cairn_mcp.artifact`` module object at
call-time so that monkey-patching in tests (and future schema changes) are reflected
without restarting the server.

Data resources (``cairn://artifact/{id}`` and ``cairn://artifacts``) require live AWS
client references and are registered via ``register_data_resources``, called from
``server.py`` after clients are constructed.
"""

import logging
from typing import Any

import fastmcp
from mcp.types import Annotations
from ulid import ULID

import cairn_mcp.artifact as _artifact_module
from cairn_mcp.clients.interfaces import (
    BedrockClientInterface,
    S3ClientInterface,
    VectorsClientInterface,
)
from cairn_mcp.config import Settings
from cairn_mcp.tools.list import list_artifacts as _list_artifacts
from cairn_mcp.tools.read import read_artifact as _read_artifact

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
# cairn-mcp Artifact Schema

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
| `commit_refs` | list[string] | Git commit SHAs linked to this artifact via `link_commit` |

## System-generated fields

These fields are set by the server and returned in tool responses. They cannot be supplied
by the caller.

| Field | Type | Notes |
|-------|------|-------|
| `last_edited_ulid` | string | Write-time ULID; use as `since_ulid` in `propose_commit_links` |

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
# cairn-mcp Tier Model

## Tier 2 — Project-local, date-anchored records

Tier 2 artifacts are session-scoped working records. They are **append-only**:
once written, their content is **immutable** — re-writing the same title and date
produces the same key (idempotent), but the content cannot be updated.

**Key format:** `{type_slug}-{date}-{title_slug}`

Example: a code review written on 2026-05-31 with title "Auth module review" becomes
`code-review-2026-05-31-auth-module-review`.

**Use for:** brainstorming, code_review, session_summary, implementation_note, bug_report,
changelog, postmortem

**Cross-scope access:** tier 2 artifacts are strictly project-local. They are never
accessible outside the deployment's own `WRITE_PREFIX` scope, regardless of visibility.

---

## Tier 3 — Permanent, date-independent knowledge

Tier 3 artifacts are canonical knowledge that persists and evolves. Re-writing a tier 3
artifact with the same type and title **overwrites in place** — the key is stable and
date-independent. Orphaned section vectors from the previous version are cleaned up
automatically.

**Key format:** `{type_slug}-{title_slug}` (omits date — date-independent)

Example: an ADR with title "Use S3 Vectors for embeddings" becomes
`adr-use-s3-vectors-for-embeddings`.

**Use for:** adr, spec, decision_note, synthesis, plan, prd, runbook, learning

**Cross-scope access:** tier 3 artifacts with `visibility=shared` are discoverable by
agents pointing at the same vector index with different `WRITE_PREFIX` scopes.
"""


def visibility_schema_content() -> str:
    """Return markdown describing visibility values and cross-scope access rules.

    Returns:
        Markdown string suitable for direct consumption by a language model.
    """
    return """\
# cairn-mcp Visibility and Cross-Scope Access

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
- **Note:** cross-scope visibility control is enforced at the MCP server layer. True
  access restriction requires IAM permissions on the S3 bucket and S3 Vectors index.
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
        "prd": (
            "Product Requirements Document — defines what to build, user needs, goals,"
            " and non-goals. Tier 3, shared."
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

    lines = ["# cairn-mcp Artifact Type Catalogue\n"]
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
# cairn-mcp Query Strategy

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
   `query`. Combine with `type` or `tags` to stay narrow.

## When to use `synthesise_artifacts`

Use `synthesise_artifacts` when you need to compile knowledge from multiple related
artifacts — for example, summarising all code reviews after a feature ships, or
consolidating session notes for a sprint.

`synthesise_artifacts` runs a semantic search and returns **full content** for the top-k
results in a single call. After synthesising in-context, write the result back using
`write_artifact` with:

- `type="synthesis"`
- `tier=3`
- `source_artifacts=[<list of artifact_id values from the synthesise response>]`

This records which artifacts contributed to the synthesis and makes the compiled knowledge
searchable as a standalone tier 3 artifact.

## When to use `propose_commit_links` and `link_commit`

Use these two tools together at the end of a coding session to attach the session's commit
SHA(s) to every artifact written during that session.

**Workflow:**

1. Note the `last_edited_ulid` returned by the first `write_artifact` call of the session —
   this is the `since_ulid` value.
2. Call `propose_commit_links(commit_sha=<sha>, since_ulid=<ulid>)` — returns own-scope
   artifacts with no `commit_refs` that were written at or after `since_ulid`.
3. Review the proposed list. Confirm which artifact IDs should be linked.
4. Call `link_commit(artifact_ids=[...], commit_sha=<sha>)` — appends the SHA to each
   confirmed artifact without re-embedding.

If `since_ulid` is omitted, `propose_commit_links` returns **all** own-scope artifacts
with no `commit_refs` — useful for a bulk back-fill of an existing index.

## Runtime schema reference

For precise field constraints, valid enum values, and tier semantics, read these resources:

- `cairn://schema/artifact` — required and optional fields, enum values, constraints
- `cairn://schema/tiers` — tier 2 vs tier 3 semantics and key formats
- `cairn://schema/visibility` — visibility values and cross-scope access rules
- `cairn://schema/types` — type catalogue with usage guidance
"""


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_resources(app: fastmcp.FastMCP) -> None:
    """Register all five cairn:// schema resources on the FastMCP app.

    Resources are read-only, pure, and require no injected AWS clients. This
    function is called once from ``server.py`` at module load time, after the
    ``_app`` instance is created.

    Args:
        app: The FastMCP application instance to register resources on.
    """

    @app.resource("cairn://schema/artifact")
    def _artifact_schema() -> str:
        """Full artifact schema: required/optional fields, enum values, and constraints."""
        return artifact_schema_content()

    @app.resource("cairn://schema/tiers")
    def _tiers_schema() -> str:
        """Tier 2 vs tier 3 semantics, key formats, and access rules."""
        return tiers_schema_content()

    @app.resource("cairn://schema/visibility")
    def _visibility_schema() -> str:
        """Visibility values and the cross-scope access gate."""
        return visibility_schema_content()

    @app.resource("cairn://schema/types")
    def _types_schema() -> str:
        """Artifact type catalogue with one-line usage guidance per type."""
        return types_schema_content()

    @app.resource("cairn://schema/query-strategy")
    def _query_strategy() -> str:
        """Recommended query strategy: start narrow, when to list vs search vs synthesise."""
        return query_strategy_content()

    logger.debug("cairn-mcp resources registered (5 schema resources)")


# ---------------------------------------------------------------------------
# Data resource helpers — testable content functions
# ---------------------------------------------------------------------------


async def _artifact_resource_content(
    *,
    artifact_id: str,
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface | None,
    bedrock: BedrockClientInterface | None,
) -> tuple[str, str]:
    """Fetch artifact content for the cairn://artifact/{id} resource.

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
        error_code = result.get("error", "error")
        message = result.get("message", "Unknown error.")
        markdown = f"# Error: {error_code}\n\n{message}\n"
        return markdown, "text/markdown"

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
        identifier = str(artifact.get("artifact_id", ""))
        title = str(artifact.get("title", ""))
        artifact_type = str(artifact.get("type", ""))
        description = str(artifact.get("description", ""))
        # Escape pipe characters inside cell values
        identifier = identifier.replace("|", "\\|")
        title = title.replace("|", "\\|")
        artifact_type = artifact_type.replace("|", "\\|")
        description = description.replace("|", "\\|")
        lines.append(f"| {identifier} | {title} | {artifact_type} | {description} |")

    return "\n".join(lines) + "\n"


async def _artifacts_listing_content(
    *,
    settings: Settings,
    s3: S3ClientInterface | None,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface | None,
) -> str:
    """Fetch the active own-scope artifact listing for the cairn://artifacts resource.

    Delegates to ``list_artifacts`` with ``status="active"`` and no other filters.

    Returns:
        A markdown string.  On error, returns a minimal markdown error message.
    """
    result: dict[str, Any] = await _list_artifacts(
        settings=settings,
        s3=s3,
        vectors=vectors,
        bedrock=bedrock,
        status="active",
    )

    if "error" in result:
        error_code = result.get("error", "error")
        message = result.get("message", "Unknown error.")
        return f"# Error: {error_code}\n\n{message}\n"

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
    """Register cairn data resources on the FastMCP app.

    Registers two resources with ``audience: ["user"]`` annotations:

    - ``cairn://artifact/{id}`` — URI template; returns full markdown content of
      a named artifact, applying the same cross-scope gate as ``read_artifact``.
      Includes a ``lastModified`` annotation derived from ``last_edited_ulid`` when
      present.
    - ``cairn://artifacts`` — static listing; returns a markdown table of all active
      own-scope artifacts.

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
        "cairn://artifact/{id}",
        mime_type="text/markdown",
        annotations=Annotations(audience=["user"]),
        description="Full markdown content of a named artifact.",
    )
    async def _artifact_resource(id: str) -> str:  # noqa: A002
        """Return the full markdown content of the artifact identified by ``id``."""
        try:
            # Derive lastModified from ULID — requires a read_artifact call.
            # We do this first so the handler can set the annotation before returning.
            # (FastMCP does not support per-response annotations on template resources;
            # the annotation on the registration is static.  lastModified is therefore
            # a best-effort static annotation from the registration-time perspective.
            # The content itself is always fresh.)
            content, _mime = await _artifact_resource_content(
                artifact_id=id,
                settings=settings,
                s3=s3,
                vectors=vectors,
                bedrock=bedrock,
            )
            return content
        except Exception as exc:
            logger.exception("Unexpected error in cairn://artifact/{id} resource handler")
            return f"# Error: internal_error\n\n{exc}\n"

    @app.resource(
        "cairn://artifacts",
        mime_type="text/markdown",
        annotations=Annotations(audience=["user"]),
        description="Markdown index of all active own-scope artifacts.",
    )
    async def _artifacts_resource() -> str:
        """Return a markdown listing of all active own-scope artifacts."""
        try:
            return await _artifacts_listing_content(
                settings=settings,
                s3=s3,
                vectors=vectors,
                bedrock=bedrock,
            )
        except Exception as exc:
            logger.exception("Unexpected error in cairn://artifacts resource handler")
            return f"# Error: internal_error\n\n{exc}\n"

    logger.debug("cairn-mcp data resources registered (cairn://artifact/{id}, cairn://artifacts)")
