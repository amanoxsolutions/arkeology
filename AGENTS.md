# cairn-mcp

## Overview
cairn-mcp is a Python MCP server that gives AI agents persistent artifact memory backed by AWS S3
(durable content storage), AWS S3 Vectors (vector embeddings + metadata filtering), and Amazon
Bedrock (embeddings via Titan Text v2). Agents connect via MCP to write, search, and recall
structured artifacts — code reviews, ADRs, implementation notes, specs, session summaries — across
sessions and across team boundaries. It directly resolves the tier 2 artifact gap from the F3.2
research: knowledge produced in one agent session is no longer discarded when the context window
closes. Any agent or workflow that depends on recalled context relies on this server; if it is
unavailable or misconfigured, all persisted memory is inaccessible.

## Project
- **Name:** cairn-mcp
- **Type:** mcp-server
- **Description:** MCP server for persistent artifact memory powered by AWS S3, S3 Vectors, and Bedrock embeddings

## Stack
- **Languages:** python
- **Frameworks:** fastmcp
- **Infrastructure:** none — the server is deployment-agnostic; S3 bucket, S3 Vectors bucket/index, and IAM are provisioned externally

## Agent Settings
- **Documentation:** docs/
- **Scratchpad:** .docs/

## Conventions
- **Testing approach:** test driven development
- **Python:**
  - **Logging:** logging

<!-- ──────────────────────────────────────────────────────────── -->
<!-- The sections below are OPTIONAL.                             -->
<!-- Include only what adds real value for agents.               -->
<!-- Missing sections are never errors.                          -->
<!-- ──────────────────────────────────────────────────────────── -->

## Repository Structure

| Path                              | Purpose                                                    |
|-----------------------------------|------------------------------------------------------------|
| `src/cairn_mcp/`                  | MCP server source                                          |
| `src/cairn_mcp/artifact.py`       | Artifact model, key generation, section parsing            |
| `src/cairn_mcp/failure_log.py`    | Failure log helper: append_failure_entry, JSONL format     |
| `src/cairn_mcp/tools/`            | MCP tool implementations (write, search, read, and more)   |
| `src/cairn_mcp/tools/list.py`     | list_artifacts MCP tool                                    |
| `src/cairn_mcp/tools/archive.py`  | archive_artifact MCP tool                                  |
| `src/cairn_mcp/tools/delete.py`   | delete_artifact MCP tool                                   |
| `src/cairn_mcp/tools/purge.py`    | purge_archived MCP tool                                    |
| `src/cairn_mcp/tools/health.py`   | health_check MCP tool                                      |
| `src/cairn_mcp/tools/synthesise.py` | synthesise_artifacts MCP tool                            |
| `src/cairn_mcp/clients/`          | AWS client interfaces, implementations, fakes, filter      |
| `src/cairn_mcp/config.py`         | Settings (pydantic-settings, all env vars)                 |
| `src/cairn_mcp/server.py`         | FastMCP app, tool registration                             |
| `src/cairn_mcp/__main__.py`       | Entry point: logging, config, clients, startup, server     |
| `tests/unit/`                     | Unit tests (fakes only, no AWS)                            |
| `tests/integration/`              | Integration tests (real AWS, @pytest.mark.integration)     |
| `docs/planning-artifacts/`        | PRD and plan                                               |
| `docs/specs/`                     | Per-task feature specs                                     |
| `.docs/`                          | Agent scratchpad (gitignored)                              |

## Component Dependencies
<!-- TODO: List external services, data stores, or other repos this project depends on,
     and what a breaking change in each would mean for this project.
     Example: "Reads AWS Cost Explorer billing exports from the `billing-exports` S3 bucket owned
     by the management account team. A schema change in their export format requires updates to the
     Glue job in `src/etl/` and the Athena DDL in `sql/`." -->

## Working Conventions

- All new tool functions go in `src/cairn_mcp/tools/<name>.py`; register on `_app` in `server.py` via `register_tools()`
- Tool functions receive `settings`, `s3`, `vectors`, `bedrock` as injected dependencies — never import clients directly
- `ARTIFACT_TYPES` in `artifact.py` is the single source of truth for valid artifact types — never duplicate it elsewhere
- All metadata stored in S3 object metadata is string-valued; lists (`feature_tags`, `source_artifacts`) are comma-joined
- Vector metadata stores `feature_tags` as `list[str]` (enables `$eq` element-in-list filtering); S3 object metadata stores them as a comma-joined string — these are intentionally different representations
- Scope check always uses `artifact_id.startswith(scope + "/")` — never bare `startswith(scope)` (prevents false prefix matches where a scope `"team-a"` would incorrectly match `"team-abc/..."`)
- Tier 2 artifact IDs are date-anchored: `{type_slug}-{date}-{title_slug}`; tier 3 are date-independent: `{type_slug}-{title_slug}` — do not alter this scheme
- Client interfaces in `src/cairn_mcp/clients/interfaces.py` use `typing.Protocol` — concrete implementations (`s3.py`, `vectors.py`, `bedrock.py`) and fakes satisfy the structural contract without inheriting from the interface class; never add `ABC` or `abstractmethod` to client code

## Non-Negotiable Rules

- Never print to stdout — it corrupts the MCP stdio transport; use `logging.getLogger(__name__)` to write to stderr
- Never bypass the cross-scope gate — read and search tools must always check tier + visibility for foreign-scope artifacts
- Never store artifact content in S3 Vectors metadata — content belongs in S3 only
- Never generate random or UUID artifact keys — keys are fully deterministic from artifact attributes
- All tool public functions delegate to an `_inner` variant wrapped in `try/except Exception` — never let raw exceptions escape to the MCP caller
- The synthesis reference check in `delete_artifact` is scoped to own scope only — foreign-scope synthesis identifiers must never appear in delete warnings

## High-Friction Areas
<!-- TODO: Gotchas, implicit contracts, and non-obvious dependencies that have caused problems before.
     Example: "The KMS key in InfraStack has a circular dependency with the S3 bucket policy.
     Adding new key grants requires a two-step deploy — see docs/adr/2026-03-kms-circular-dep.md.
     The Glue job IAM role must be updated manually when a new S3 bucket is added to the lake." -->

## CI and Quality Gates

Run before pushing:

```bash
uv run pytest tests/unit/ -q -m 'not integration'    # must pass
uv run ruff check src/ tests/                        # must be clean
uv run mypy src/                                     # must be clean
uv run cairn-mcp                                     # must start without error (requires .env)
```

Integration tests (require real AWS credentials in `.env`):

```bash
uv run pytest tests/integration/ -q
```
