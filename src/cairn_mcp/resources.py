"""cairn_mcp.resources — MCP Resource definitions for runtime schema discovery.

All five resources are pure schema documentation with no AWS calls. Each content
function reads ``ARTIFACT_TYPES`` from the ``cairn_mcp.artifact`` module object at
call-time so that monkey-patching in tests (and future schema changes) are reflected
without restarting the server.
"""

import logging

import fastmcp

import cairn_mcp.artifact as _artifact_module

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
| `feature_tags` | list[string] | Searchable tags; enables `feature_tags` filter |
| `author_role` | string | Role of the author (e.g. `"developer"`) |
| `source_artifacts` | list[string] | Source IDs for a `synthesis` artifact |

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

**Use for:** code_review, session_summary, implementation_note, bug_report

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

**Use for:** adr, spec, decision_note, synthesis

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

1. **Add filters first.** Specify `type` and `feature_tags` before relying on pure semantic
   similarity. A narrow query with `type="adr"` and `feature_tags=["auth"]` returns the
   most relevant ADRs for the authentication domain without noise from other types.

2. **Broaden when narrow returns insufficient results.** Drop `feature_tags` first, then
   `type`, then let the semantic query do the heavy lifting. Each iteration should be a
   deliberate widening step.

3. **Use `list_artifacts` for known-type browsing.** When you want all artifacts of a type
   (e.g. all active specs for a project), `list_artifacts` with `type`, `team`, and
   `project` filters is cheaper and more predictable than a semantic search.

4. **Use `search_artifacts` for concept queries.** When the question is conceptual — "what
   did we decide about the auth redesign?" — use `search_artifacts` with a natural-language
   `query`. Combine with `type` or `feature_tags` to stay narrow.

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
