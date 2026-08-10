# cairn-mcp

## Overview
cairn-mcp is a Python MCP server that gives AI agents persistent artifact memory backed by AWS S3
(durable content storage), AWS S3 Vectors (vector embeddings + metadata filtering), and Amazon
Bedrock (embeddings via Titan Text v2). Agents connect via MCP to write, search, and recall
structured artifacts — code reviews, ADRs, implementation notes, specs, session summaries — across
sessions and across team boundaries. It directly resolves the tier 2 artifact gap from the F3.2
research: knowledge produced in one agent session is no longer discarded when the context window
closes. Any agent or workflow that depends on recalled context relies on this server; if it is
unavailable or misconfigured, all persisted memory is inaccessible. The `cairn_studio`
tool is the human reading entry point — it renders a visual two-pane artifact browser
inline in supporting MCP hosts (Claude Desktop, claude.ai, VS Code Copilot) and falls
back to a plain-text listing on non-supporting hosts. When `cairn_studio` is active and
the browser UI triggers `read_artifact`, `list_artifacts`, or `search_artifacts` on behalf
of a user interaction, do not summarize, reformat, or interpret the tool result — the
browser UI handles rendering; Claude's role ends after the initial `cairn_studio` invocation.

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
- **Source-control branching model:** trunk-based (main branch)
- **Versioning:** semver
- **Changelog format:** keep-a-changelog
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
| `src/cairn_mcp/__init__.py`       | Package marker (empty)                                     |
| `src/cairn_mcp/__main__.py`       | Entry point: logging, config, clients, startup, server     |
| `src/cairn_mcp/annotations.py`    | Shared helpers for the annotation-backed durable copy of `commit_refs`/`references` |
| `src/cairn_mcp/artifact.py`       | Artifact model, key generation, section parsing            |
| `src/cairn_mcp/config.py`         | Settings (pydantic-settings, all env vars)                 |
| `src/cairn_mcp/constants.py`      | Centralised string-literal constants: error codes, artifact status values |
| `src/cairn_mcp/errors.py`         | Typed exceptions: CairnError, CredentialError, etc.        |
| `src/cairn_mcp/failure_log.py`    | Failure log helper: append_failure_entry, JSONL format     |
| `src/cairn_mcp/references.py`     | Pure migration reference-resolution helpers (AWS-free, I/O-free) |
| `src/cairn_mcp/resources.py`      | FastMCP resource registrations                             |
| `src/cairn_mcp/server.py`         | FastMCP app, tool registration                             |
| `src/cairn_mcp/startup.py`        | Seven-check startup validation sequence                    |
| `src/cairn_mcp/tools/`            | MCP tool implementations (write, search, read, and more)   |
| `src/cairn_mcp/tools/_search_helper.py` | Shared vector re-fetch loop used by search + synthesise |
| `src/cairn_mcp/tools/_section_pipeline.py` | Shared write-path section embedding pipeline (min-length filter, max-sections cap, truncation) — used by `write.py` and `reconcile.py` |
| `src/cairn_mcp/tools/archive.py`  | archive_artifact MCP tool                                  |
| `src/cairn_mcp/tools/studio.py`   | cairn_studio MCP tool — UI extension + plain-text fallback |
| `src/cairn_mcp/tools/delete.py`   | delete_artifact MCP tool                                   |
| `src/cairn_mcp/tools/freshness.py`| check_synthesis_freshness MCP tool                         |
| `src/cairn_mcp/tools/health.py`   | health_check MCP tool                                      |
| `src/cairn_mcp/tools/link_metadata.py` | link_metadata MCP tool — backfills `commit_refs`/`references` without re-embedding (was `link_commit.py`) |
| `src/cairn_mcp/tools/list.py`     | list_artifacts MCP tool                                    |
| `src/cairn_mcp/tools/migrate_artifacts.py` | migrate_artifacts MCP tool — bulk migration write with Nova Lite description enrichment |
| `src/cairn_mcp/tools/propose_commit_links.py` | propose_commit_links MCP tool — read-only discovery of unlinked own-scope artifacts |
| `src/cairn_mcp/tools/purge.py`    | purge_archived MCP tool                                    |
| `src/cairn_mcp/tools/read.py`     | read_artifact MCP tool                                     |
| `src/cairn_mcp/tools/reconcile.py`| reconcile_index MCP tool                                   |
| `src/cairn_mcp/tools/search.py`   | search_artifacts MCP tool                                  |
| `src/cairn_mcp/tools/synthesise.py` | synthesise_artifacts MCP tool                            |
| `src/cairn_mcp/tools/write.py`    | write_artifact MCP tool                                    |
| `src/cairn_mcp/tools/write_artifacts.py` | write_artifacts MCP tool — bulk concurrent write bounded by caller-supplied `artifact_concurrency` |
| `src/cairn_mcp/static/cairn-studio.html` | Self-contained HTML/JS MCP App: single-pane, view-switching browser (list view ↔ detail view) with faceted filter, artifact list, markdown + mermaid rendering, semantic search |
| `src/cairn_mcp/clients/`          | AWS client interfaces, implementations, fakes, filter      |
| `src/cairn_mcp/clients/interfaces.py` | Protocol interfaces for S3, S3 Vectors, Bedrock        |
| `src/cairn_mcp/clients/s3.py`     | Concrete boto3 S3 client, incl. object-annotation put/get/list/delete |
| `src/cairn_mcp/clients/vectors.py`| Concrete boto3 S3 Vectors client                           |
| `src/cairn_mcp/clients/bedrock.py`| Concrete boto3 Bedrock embeddings client                   |
| `src/cairn_mcp/clients/credentials.py` | Credential error code detection helper                |
| `src/cairn_mcp/clients/filter.py` | In-process metadata filter evaluator ($eq, $in, $nin, …)   |
| `src/cairn_mcp/clients/fakes/`    | `FakeBedrockClient` only — S3 and S3 Vectors are mocked via moto |
| `src/cairn_mcp/clients/fakes/fake_bedrock.py` | Deterministic hash-derived embeddings fake for tests |
| `tests/unit/`                     | Unit tests (moto + `FakeBedrockClient`, no real AWS)       |
| `tests/unit/conftest.py`          | moto `query_vectors` extension + shared fixtures (settings, aws_mock, s3_client, vectors_client_*) |
| `tests/unit/clients/test_moto_query_vectors_extension.py` | Verifies the cosine-similarity moto extension |
| `tests/unit/clients/test_s3_annotations.py` | Verifies the S3 object-annotation client methods + moto self-mock extension |
| `tests/integration/`              | Integration tests (real AWS, @pytest.mark.integration)     |
| `docs/planning-artifacts/`        | PRD and plan                                               |
| `docs/specs/`                     | Per-task feature specs                                     |
| `.docs/`                          | Agent scratchpad (gitignored)                              |

## Component Dependencies

This server depends on three AWS services at runtime. Loss or misconfiguration of any
one makes all persisted memory inaccessible:

- **Amazon S3** (`ARTIFACT_BUCKET`): stores full artifact content. A bucket deletion or
  IAM policy change that removes `s3:GetObject` / `s3:PutObject` / `s3:DeleteObject`
  prevents all reads and writes. The bucket name is baked into the deployment; renaming
  it requires updating `ARTIFACT_BUCKET` and re-running startup validation.

- **Amazon S3 Vectors** (`VECTORS_BUCKET` + `VECTORS_INDEX`): stores all vector embeddings
  and metadata. The vector index dimension is immutable — once created it cannot be changed
  without deleting and recreating the index (losing all vectors). A dimension mismatch
  between the index and `BEDROCK_EMBEDDING_DIMENSIONS` causes startup check 5 to fail.
  Deleting the index loses all searchability; content in S3 is unaffected but
  `reconcile_index` can rebuild the index from S3.

- **Amazon Bedrock** (`BEDROCK_EMBEDDING_MODEL`): generates embeddings for write and search
  operations. Changing the embedding model after data has been written produces semantically
  incompatible vectors — search results degrade silently. Model changes require a full
  re-index. Throttle transients are retried with jitter; persistent throttling surfaces as an error.
  Concurrent embed calls per artifact write are bounded by `SECTION_CONCURRENCY` (default 5).

## Testing Conventions

- **Mock AWS services with moto** — before writing any test that touches S3 or S3 Vectors,
  confirm the operation is supported at https://docs.getmoto.org/en/latest/docs/services/index.html.
  Use `@mock_aws` (or the `aws_mock` fixture from `tests/unit/conftest.py`) for all unit tests.
- **`query_vectors` is not implemented in moto** — `S3VectorsBackend.query_vectors` is patched
  with a cosine similarity extension in `tests/unit/conftest.py`. This patch is applied once at
  module load and is active for all unit tests. Do not reimplement it per-test. The extension
  returns `score = 1.0 − cosine_distance` (cosine similarity, range [−1, 1]), matching
  `VectorsClientImpl` exactly.
- **S3 object annotations are not implemented in moto** — the four annotation operations
  (`put_object_annotation` / `get_object_annotation` / `list_object_annotations` /
  `delete_object_annotation`) are self-mocked in `tests/unit/conftest.py` by intercepting
  `S3Response`'s key-level GET/PUT/DELETE dispatch for the `?annotation` subresource and
  backing it with an in-memory store, plus a `S3Backend.put_object` wrapper that clears a
  key's annotations on overwrite (matching real S3 semantics). This patch is applied once
  at module load and is active for all unit tests. Do not reimplement it per-test.
- **`FakeBedrockClient` is kept intentionally** — moto's `invoke_model` returns a generic
  stub, not deterministic per-text embedding vectors. `FakeBedrockClient` generates
  hash-derived unit vectors (SHA-256) so the same text always produces the same vector,
  enabling search ordering assertions. Do not replace it with moto.
- **Credential error simulation** — use `mocker.patch.object(client, "method", side_effect=CredentialError(...))` to simulate credential failures in unit tests. Do not create hand-rolled fakes with `set_credential_failure` for this purpose.
- **Call tracking and failure injection** — use `mocker.spy(client, "method")` to track call counts; use `mocker.patch.object(client, "method", side_effect=...)` to inject failures. Do not subclass concrete clients for tracking or failure simulation.

## Working Conventions

- **PRD describes what, never how** — no env var names, file names, paths, CLI flags, or formula strings anywhere in the PRD; describe observable behaviours and constraints only
- All new tool functions go in `src/cairn_mcp/tools/<name>.py`; register on `_app` in `server.py` via `register_tools()`
- Tool functions receive `settings`, `s3`, `vectors`, `bedrock` as injected dependencies — never import clients directly
- `ARTIFACT_TYPES` in `artifact.py` is the single source of truth for valid artifact types — never duplicate it elsewhere
- All metadata stored in S3 object metadata is string-valued; lists (`tags`, `source_artifacts`) are comma-joined
- Vector metadata stores `tags` as `list[str]` (enables `$eq` element-in-list filtering); S3 object metadata stores them as a comma-joined string — these are intentionally different representations
- Scope check always uses `artifact_id.startswith(scope + "/")` — never bare `startswith(scope)` (prevents false prefix matches where a scope `"team-a"` would incorrectly match `"team-abc/..."`)
- Tier 2 artifact IDs are date-anchored: `{type_slug}-{date}-{title_slug}-{hash}`; tier 3 are date-independent: `{type_slug}-{title_slug}-{hash}` — `hash` is a deterministic 8-hex-char SHA-256 prefix of the full original title, always appended, and disambiguates the empty-slug/truncation/punctuation-collapse collision classes — do not alter this scheme. A write whose generated key already exists is rejected by default (`validation_error`); pass the `overwrite` flag to intentionally replace it
- Client interfaces in `src/cairn_mcp/clients/interfaces.py` use `typing.Protocol` — concrete implementations (`s3.py`, `vectors.py`, `bedrock.py`) and fakes satisfy the structural contract without inheriting from the interface class; never add `ABC` or `abstractmethod` to client code
- Vector client methods use the parameter name `filter_expr` (not `filter`) — never use the bare name `filter` in vector client calls; `filter` is a Python builtin and the rename avoids shadowing it
- `SECTION_CONCURRENCY`, `EMBED_MAX_SECTIONS`, and `EMBED_MIN_SECTION_LENGTH` control write-path embedding behaviour; all three are validated at startup — setting any to an out-of-range value prevents the server from starting

## Non-Negotiable Rules

- Never print to stdout — it corrupts the MCP stdio transport; use `logging.getLogger(__name__)` to write to stderr
- Never bypass the cross-scope gate — read and search tools must always check tier + visibility for foreign-scope artifacts
- Never store artifact content in S3 Vectors metadata — content belongs in S3 only
- Never generate random or UUID artifact keys — keys are fully deterministic from artifact attributes
- All tool public functions delegate to an `_inner` variant wrapped in `try/except Exception` — never let raw exceptions escape to the MCP caller
- The synthesis reference check in `delete_artifact` is scoped to own scope only — foreign-scope synthesis identifiers must never appear in delete warnings

## High-Friction Areas

- **Vector index dimension is immutable**: Once the S3 Vectors index is created, its
  dimension cannot be changed without deleting and recreating the index (losing all
  vectors). A `BEDROCK_EMBEDDING_DIMENSIONS` change after go-live requires a full
  re-index via `reconcile_index`.

- **Scope check must use `startswith(scope + "/")` not `startswith(scope)`**: A bare
  `startswith` allows a scope of `"team-a"` to incorrectly match keys under `"team-abc/"`.
  Every scope guard in every tool uses the `scope + "/"` form; do not abbreviate it.

- **S3 object metadata vs vector metadata encoding differ intentionally**: `tags`
  and `source_artifacts` are stored as comma-joined strings in S3 object metadata
  (required by the S3 API, which only accepts string values) but as `list[str]` in vector
  metadata (enables `$eq` element-in-list filtering). Both representations are correct;
  do not unify them.

- **Protocol-based client interfaces**: `interfaces.py` uses `typing.Protocol`. Concrete
  clients and fakes satisfy the contract structurally — they do not inherit from the
  interface class. Never add `ABC` or `abstractmethod` to client code.

- **`_search_helper.py` is the single source of truth for the re-fetch loop**: Both
  `search.py` and `synthesise.py` delegate to `run_search_loop` in `_search_helper.py`.
  Fix the loop there; do not patch individual tools.

- **Vector scores are `1.0 - distance`, not raw distance**: Search results carry
  `score = 1.0 - cosine_distance`, which equals cosine similarity, so scores are in `[−1, 1]`
  where `1.0` is most similar and `−1.0` is most dissimilar. Do not negate scores or treat
  them as distances; the conversion is already applied before results are returned to callers.

## CI and Quality Gates

Run before pushing:

```bash
uv run pytest tests/unit/ -q -m 'not integration'    # must pass
uv run ruff check src/ tests/                        # must be clean
uv run ruff format --check src/ tests/               # must be clean
uv run mypy src/                                     # must be clean
uv run cairn-mcp                                     # must start without error (requires .env)
```

Integration tests (require real AWS credentials in `.env`):

```bash
uv run pytest tests/integration/ -q
```
