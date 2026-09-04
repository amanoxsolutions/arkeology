# Arkeology

## Overview
Arkeology is a Python MCP server that gives AI agents persistent artifact memory backed by AWS S3
(durable content storage), AWS S3 Vectors (vector embeddings + metadata filtering), and Amazon
Bedrock (embeddings via Titan Text v2). Agents connect via MCP to write, search, and recall
structured artifacts — code reviews, ADRs, implementation notes, specs, session summaries — across
sessions and across team boundaries. It directly resolves the tier 2 artifact gap from the F3.2
research: knowledge produced in one agent session is no longer discarded when the context window
closes. Any agent or workflow that depends on recalled context relies on this server; if it is
unavailable or misconfigured, all persisted memory is inaccessible. The `arkeology_studio`
tool is the human reading entry point — it renders a visual two-pane artifact browser
inline in supporting MCP hosts (Claude Desktop, claude.ai, VS Code Copilot) and falls
back to a plain-text listing on non-supporting hosts. When `arkeology_studio` is active and
the browser UI triggers `read_artifact`, `list_artifacts`, or `search_artifacts` on behalf
of a user interaction, do not summarize, reformat, or interpret the tool result — the
browser UI handles rendering; Claude's role ends after the initial `arkeology_studio` invocation.

## Project
- **Name:** Arkeology
- **Type:** mcp-server
- **Description:** MCP server for persistent artifact memory powered by AWS S3, S3 Vectors, and Bedrock embeddings

## Stack
- **Languages:** python
- **Frameworks:** fastmcp
- **Infrastructure:** none — the server is deployment-agnostic; S3 bucket, S3 Vectors bucket/index, and IAM are provisioned externally
- **Platform:** assumes a POSIX host (Linux/macOS) — `failure_log.py` uses `fcntl` for file locking, disabled gracefully (not a crash) on non-POSIX hosts

## Agent Settings
- **Documentation:** docs/
- **Scratchpad:** .docs/

## Conventions
- **Testing approach:** tdd
- **Mutation testing:** enabled, but **manual and local only** — run on demand, wired to no CI
  job, no pre-commit hook, and no schedule. A full run takes **40+ minutes**, because mutmut
  re-runs the entire unit suite once to map tests to functions before any mutant executes; that
  cost is why it is not a per-commit check. Nothing reminds you, so run it deliberately after
  changing any file named in `only_mutate` (see `[tool.mutmut]` in `pyproject.toml`).

    Do **not** compare the survivor count against a remembered number, and do not record one.
    Most surviving mutants are provably equivalent — the mutated expression cannot change the
    gate's outcome — so a raw count carries no signal, and it decays two independent ways: it
    shifts whenever the mutation Scope changes, and mutmut's mutant names are *positional* per
    function (`__mutmut_21`), so inserting any mutatable expression earlier in a function
    silently renumbers every mutant after it. Instead, read each survivor's diff with
    `mutmut show` and check it against the equivalent-mutant classes already triaged by
    mutated expression (`meta.get("tier", 0)` → `1`, and similar) in the cross-scope-gate
    mutation-survivor issue. A survivor matching none of those classes is the thing worth
    investigating.

    ```bash
    uv run mutmut run          # 40+ min; exits 0 even when mutants survive
    uv run mutmut results      # the survivor list
    uv run mutmut show <name>  # one mutant's diff
    ```

    Run it alone. It writes instrumented bytecode into the real `src/**/__pycache__/`, so
    running it alongside the test suite produces bogus failures in untouched files — see
    High-Friction Areas.
  - **Scope:** the cross-scope access gate — the tier + visibility check applied to foreign-scope
    artifacts in every read, search, and delete path, and every `startswith(scope + "/")` scope guard.
    That whole Scope lives in `_scope.py`, which is what keeps `only_mutate` to two entries; a gate
    implementation added outside it drops out of mutation coverage silently. `_reference_filter.py`
    is the second entry, for its candidate loop rather than for the gate, which it delegates.
  - **Tool:** python — mutmut
- **Integration target:** real AWS (S3, S3 Vectors, Bedrock), with credentials and resource names
  read from `.env`; fixtures are provisioned as an ephemeral run-scoped
  `integration-tests/<run-id>` write/read prefix pair inside the operator's existing buckets,
  never the operator's configured `WRITE_PREFIX`/`READ_PREFIXES`, and are best-effort torn down
  at session end
- **Contracts location:** docs/contracts/
- **Contract format:** defaults
  - **design:** CSS custom properties in a self-contained HTML reference page, not DTCG — the
    token layer is consumed directly by `src/arkeology/static/arkeology-studio.html`, which is
    plain CSS with no build step to compile DTCG tokens into
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
| `src/arkeology/`                  | MCP server source                                          |
| `src/arkeology/__init__.py`       | Package marker (empty)                                     |
| `src/arkeology/__main__.py`       | Entry point: logging, config, clients, startup, server     |
| `src/arkeology/annotations.py`    | Shared helpers for the annotation-backed durable copy of `commit_refs`/`references` |
| `src/arkeology/artifact.py`       | Artifact model, key generation, section parsing            |
| `src/arkeology/config.py`         | Settings (pydantic-settings, all env vars)                 |
| `src/arkeology/constants.py`      | Centralised string-literal constants: error codes, artifact status values |
| `src/arkeology/errors.py`         | Typed exceptions: ArkeologyError, CredentialError, etc.        |
| `src/arkeology/failure_log.py`    | Failure log helper: append_failure_entry, JSONL format     |
| `src/arkeology/references.py`     | Pure migration reference-resolution helpers (AWS-free, I/O-free) |
| `src/arkeology/resources.py`      | FastMCP resource registrations                             |
| `src/arkeology/server.py`         | FastMCP app, tool registration                             |
| `src/arkeology/startup.py`        | Seven-check startup validation sequence                    |
| `src/arkeology/tools/`            | MCP tool implementations (write, search, read, and more)   |
| `src/arkeology/tools/_scope.py`    | The cross-scope access gate — sole home of both its forms: `is_cross_scope_readable` (in-process predicate) and `build_scope_filter` (server-side vector filter), plus `is_own_scope` |
| `src/arkeology/tools/_search_helper.py` | Shared vector re-fetch loop used by search + synthesise |
| `src/arkeology/tools/_section_pipeline.py` | Shared write-path section embedding pipeline (min-length filter, max-sections cap, truncation) — used by `write.py` and `reconcile.py` |
| `src/arkeology/tools/archive.py`  | archive_artifact MCP tool                                  |
| `src/arkeology/tools/studio.py`   | arkeology_studio MCP tool — UI extension + plain-text fallback |
| `src/arkeology/tools/delete.py`   | delete_artifact MCP tool                                   |
| `src/arkeology/tools/freshness.py`| check_synthesis_freshness MCP tool                         |
| `src/arkeology/tools/health.py`   | health_check MCP tool                                      |
| `src/arkeology/tools/link_metadata.py` | link_metadata MCP tool — backfills `commit_refs`/`references` without re-embedding (was `link_commit.py`) |
| `src/arkeology/tools/list.py`     | list_artifacts MCP tool                                    |
| `src/arkeology/tools/migrate_artifacts.py` | migrate_artifacts MCP tool — bulk migration write with Nova Lite description enrichment |
| `src/arkeology/tools/propose_commit_links.py` | propose_commit_links MCP tool — read-only discovery of unlinked own-scope artifacts |
| `src/arkeology/tools/purge.py`    | purge_archived MCP tool                                    |
| `src/arkeology/tools/read.py`     | read_artifact MCP tool                                     |
| `src/arkeology/tools/reconcile.py`| reconcile_index MCP tool                                   |
| `src/arkeology/tools/search.py`   | search_artifacts MCP tool                                  |
| `src/arkeology/tools/synthesise.py` | synthesise_artifacts MCP tool                            |
| `src/arkeology/tools/write.py`    | write_artifact MCP tool                                    |
| `src/arkeology/tools/write_artifacts.py` | write_artifacts MCP tool — bulk concurrent write bounded by caller-supplied `artifact_concurrency` |
| `src/arkeology/static/arkeology-studio.html` | Self-contained HTML/JS MCP App: single-pane, view-switching browser (list view ↔ detail view) with faceted filter, artifact list, markdown + mermaid rendering, semantic search |
| `src/arkeology/clients/`          | AWS client interfaces, implementations, fakes, filter      |
| `src/arkeology/clients/interfaces.py` | Protocol interfaces for S3, S3 Vectors, Bedrock        |
| `src/arkeology/clients/s3.py`     | Concrete boto3 S3 client, incl. object-annotation put/get/list/delete |
| `src/arkeology/clients/vectors.py`| Concrete boto3 S3 Vectors client                           |
| `src/arkeology/clients/bedrock.py`| Concrete boto3 Bedrock embeddings client                   |
| `src/arkeology/clients/credentials.py` | Credential error code detection helper                |
| `src/arkeology/clients/filter.py` | In-process metadata filter evaluator ($eq, $in, $nin, …)   |
| `src/arkeology/clients/fakes/`    | `FakeBedrockClient` only — S3 and S3 Vectors are mocked via moto |
| `src/arkeology/clients/fakes/fake_bedrock.py` | Deterministic hash-derived embeddings fake for tests |
| `tests/unit/`                     | Unit tests (moto + `FakeBedrockClient`, no real AWS)       |
| `tests/unit/conftest.py`          | moto `query_vectors` extension + shared fixtures (settings, aws_mock, s3_client, vectors_client_*) |
| `tests/unit/clients/test_moto_query_vectors_extension.py` | Verifies the cosine-similarity moto extension |
| `tests/unit/clients/test_s3_annotations.py` | Verifies the S3 object-annotation client methods + moto self-mock extension |
| `tests/integration/`              | Integration tests (real AWS, @pytest.mark.integration)     |
| `docs/planning-artifacts/`        | Vision, requirements, and plan                              |
| `docs/specs/`                     | Per-task feature specs                                     |
| `docs/contracts/`                 | Normative interface contracts — `modules/` (importable Python surface), `data/` (persisted shapes), `design/` (Studio token layer). Authority over the implementation; a disagreement is a contract bug until decided otherwise |
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

- **`requirements.md` describes what, never how** — no env var names, file names, paths, CLI flags, or formula strings anywhere in a Functional/Non-Functional/Acceptance-Criteria requirement; describe observable behaviours and constraints only (the Constraints table's Technology category is the deliberate exception — naming a specific technology, budget, schedule, or regulatory boundary is that table's whole job)
- All new tool functions go in `src/arkeology/tools/<name>.py`; register on `_app` in `server.py` via `register_tools()`
- Tool functions receive `settings`, `s3`, `vectors`, `bedrock` as injected dependencies — never import clients directly
- `ARTIFACT_TYPES` in `artifact.py` is the single source of truth for valid artifact types — never duplicate it elsewhere
- All metadata stored in S3 object metadata is string-valued; lists (`tags`, `source_artifacts`) are comma-joined
- Vector metadata stores `tags` as `list[str]` (enables `$eq` element-in-list filtering); S3 object metadata stores them as a comma-joined string — these are intentionally different representations
- Scope check always uses `artifact_id.startswith(scope + "/")` — never bare `startswith(scope)` (prevents false prefix matches where a scope `"team-a"` would incorrectly match `"team-abc/..."`)
- Tier 2 artifact IDs are date-anchored: `{type_slug}-{date}-{title_slug}-{hash}`; tier 3 are date-independent: `{type_slug}-{title_slug}-{hash}` — `hash` is a deterministic 8-hex-char SHA-256 prefix of the full original title, always appended, and disambiguates the empty-slug/truncation/punctuation-collapse collision classes — do not alter this scheme. A write whose generated key already exists is rejected by default (`validation_error`); pass the `overwrite` flag to intentionally replace it
- Client interfaces in `src/arkeology/clients/interfaces.py` use `typing.Protocol` — concrete implementations (`s3.py`, `vectors.py`, `bedrock.py`) and fakes satisfy the structural contract without inheriting from the interface class; never add `ABC` or `abstractmethod` to client code
- Vector client methods use the parameter name `filter_expr` (not `filter`) — never use the bare name `filter` in vector client calls; `filter` is a Python builtin and the rename avoids shadowing it
- `SECTION_CONCURRENCY`, `EMBED_MAX_SECTIONS`, and `EMBED_MIN_SECTION_LENGTH` control write-path embedding behaviour; all three are validated at startup — setting any to an out-of-range value prevents the server from starting
- **Backlog (`B-` items) are a live work queue, not a history log.** When a `B-` item is completed, delete its entire row from `docs/planning-artifacts/backlog.md` and remove all cross-references to it in specs, ADRs, the review register, and `plan.md`. Pending-language (`⏳ Option A/B`, `code fix pending`) becomes dangling noise once an item is done; there is no value in keeping resolved rows.
- **A dedicated `docs/specs/` file is required only for a task that introduces new or changed behaviour** — a new tool, parameter, response field, or user-visible contract that needs a frozen scope to implement against. A task that is pure code hygiene (extracting duplicated logic into a shared helper, applying an already-established pattern more consistently, renaming for clarity) with zero behavioural change needs no new spec file — `plan.md`'s own task entry, if it names the concrete signatures/call sites, is sufficient scope of record, and the code + its tests + docstrings become the authority once it lands. Writing a spec for every fix produces spec sprawl and authority ambiguity (which of several specs governs code that several fixes have since touched) for no corresponding benefit — reserve specs for changes that actually need a frozen contract.

## Non-Negotiable Rules

- Never cite line numbers, review finding numbers when referencing any project file — for Markdown documents (ADRs, specs, and the like) reference the document by name and, where possible, its `##` (H2) section heading; for source-code files reference the file by name and, where possible, the class or function that contains the referenced code. Both document and code line-anchors drift as content is added or removed above the reference, creating recurring maintenance churn. The same applies to aggregate counts of `backlog.md` rows ("137 backlog rows", "12 DW items") cited in any other document — `backlog.md` is a live work queue whose rows are deleted the moment a `B-` item closes (see Working Conventions), so a cited total drifts the same way a line anchor does; reference the specific `B-` IDs involved instead of a total.
- Never print to stdout — it corrupts the MCP stdio transport; use `logging.getLogger(__name__)` to write to stderr
- Never bypass the cross-scope gate — read and search tools must always check tier + visibility for foreign-scope artifacts
- Never store artifact content in S3 Vectors metadata — content belongs in S3 only
- Never generate random or UUID artifact keys — keys are fully deterministic from artifact attributes
- All tool public functions delegate to an `_inner` variant wrapped in `try/except Exception` — never let raw exceptions escape to the MCP caller
- The synthesis reference check in `delete_artifact` is scoped to own scope only — foreign-scope synthesis identifiers must never appear in delete warnings

## High-Friction Areas

- **Never run `mutmut run` concurrently with the test suite in the same checkout, and clear
  `__pycache__` afterwards**: a mutmut run writes its *instrumented* bytecode into the real
  `src/**/__pycache__/`, not only into `mutants/`. A stale instrumented `.pyc` is visibly larger
  than a clean one (6,486 bytes vs a 5,256-byte `_scope.py` source) and makes the imported
  function disagree with its own file — `inspect.getsource` shows correct code while the callable
  returns the mutated result. This presents as a large batch of inexplicable failures in
  *unmodified* test files, and the access-control tests fail first because the gate is what is
  being mutated. Recovery:

    ```bash
    find src tests -name __pycache__ -type d -exec rm -rf {} +
    ```

  Suspect this before suspecting your own change whenever tests fail in files you did not touch.

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

## Quality Gates

**There is no CI.** This repository has no `.github/workflows/` and nothing runs automatically on
push, on pull request, or on a schedule. Every gate below is enforced by you remembering to run
it.

`.pre-commit-config.yaml` gives you a fast local pre-filter. **Install it once per clone** — the
hooks do nothing until you do:

```bash
uv run pre-commit install
```

Every hook runs the project's own pinned tooling via `uv run` (`language: system`), never an
independently-versioned upstream mirror, so a hook and its gate below can never disagree about
tool versions or typing stubs — `pyproject.toml` is the single source of truth for both. It is
still **not a substitute** for the list below: `pytest` (~4 min) and `npm test` are deliberately
absent, because a hook slow enough to invite `--no-verify` is worse than no hook.

Run the full list by hand before pushing:

```bash
uv run pytest tests/unit/ -q -m 'not integration'    # must pass
uv run ruff check src/ tests/ scripts/ plugins/      # must be clean
uv run ruff format --check src/ tests/ scripts/ plugins/  # must be clean
uv run mypy src/                                     # must be clean
uv run arkeology                                     # must start without error — needs a .env,
                                                     # which is NOT in the repo, so a fresh clone
                                                     # cannot run this gate until one is created
npm test                                             # must pass (arkeology-studio.html link-sanitisation guard)
```

The ruff scope is deliberately `src/ tests/ scripts/ plugins/` and **not** `.`: ruff formats
Python code blocks embedded in Markdown, so `.` would rewrite code samples inside archival
brainstorming documents, specs, and reviews. It is also deliberately not just `src/ tests/`,
which is what previously let `scripts/validate.py` — the pre-commit validator itself — sit
unformatted without any gate noticing.

Integration tests (require real AWS credentials in `.env`):

```bash
uv run pytest tests/integration/ -q
```
