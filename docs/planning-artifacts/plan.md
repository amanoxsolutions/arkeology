# Plan: cairn-mcp

_Project: cairn-mcp_
_Generated: 2026-05-29_ · _Last updated: 2026-05-31_
_Status: **complete — Phases 1–5 complete; T21 ✅ T22 ✅ (431 unit tests + 54 integration tests passing; all tools documented)**_

---

## Notes

- **TDD throughout** — tests written before implementation on every task (NFR-07)
- **Layered architecture from day one** — AWS client interfaces established in Phase 1; all subsequent tasks build on them, never bypassing them (NFR-04)
- **Credential error wrapping is a Phase 1 concern** — all credential-related errors are caught and re-raised as structured MCP error responses at the AWS client layer (FR-12, D2); individual tool tasks inherit this automatically and do not need to re-implement it
- **T18–T20 (Phase 4) can start in parallel with Phase 3** — MCP Resources and migration skill do not depend on Phase 3 being complete; T17 (integration test phase gate) should complete before T19 (setup docs) to ensure documented behaviour is empirically verified
- **Integration tests must clean up after themselves** — once `delete_artifact` is implemented (T12), all integration test teardown fixtures must call `delete_artifact` to remove every artifact written during the test run; existing integration tests for T7–T9 must be updated at the same time as T12 is delivered

---

## Phase 1 — Foundation: runnable server with startup validation

Goal: the server starts, validates all configuration, and fails clearly on any misconfiguration. No tools yet — just the skeleton everything else builds on.

1. ✅ **Bootstrap Python project** — project must be installable and testable from source (NFR-08, NFR-09)
   - Approach: `uv init`, `pyproject.toml`, ruff, mypy, pytest, pre-commit hooks, `.gitignore` including tier 1 artifacts path
   - Done when: `uv run pytest` passes on an empty test suite; `uv run cairn-mcp` starts without error

2. ✅ **FastMCP server skeleton** — stdio transport, structured logging, graceful shutdown; no tools registered yet (NFR-05)
   - Done when: server starts, logs its startup message, and exits cleanly

3. ✅ **AWS client layer** — S3, S3 Vectors, and Bedrock each behind a clean typed interface; HTTPS enforced; all boto3 calls catch credential-related exceptions and re-raise as structured typed errors (NFR-04, NFR-10, FR-12, D2)
   - Approach: one interface + one concrete implementation + one in-memory fake per service; fakes used in all unit tests
   - Done when: each interface has full test coverage via its fake; concrete implementations connect to real AWS in integration tests; a simulated credential failure at any client call produces a structured typed error, never a raw exception

4. ✅ **Configuration model** — all env vars parsed and validated at process start: `AWS_REGION`, `ARTIFACT_BUCKET`, `VECTORS_BUCKET`, `VECTORS_INDEX`, `WRITE_PREFIX`, `READ_PREFIXES`, `BEDROCK_EMBEDDING_MODEL`, `AWS_PROFILE` (optional), `SEARCH_FETCH_TOP_K` (optional, default 25), `SEARCH_MAX_ITERATIONS` (optional, default 3), `SEARCH_DEFAULT_TOP_K` (optional, default 5)
   - Done when: missing required vars raise a clear named error; optional vars parse to typed values with documented defaults; all vars present in configuration reference

5. ✅ **Startup validation sequence** — credentials, `WRITE_PREFIX` read/write, each `READ_PREFIXES` entry read, vector index existence, embedding model ↔ index dimension match; any failure is a hard stop with a distinct actionable error (FR-07, NFR-03)
   - Done when: each of the 5 failure conditions produces a distinct, actionable error message with a clear remediation hint; tests cover every failure path

🔁 **Phase 1 retrospective** — review structure, fakes, and configuration model before building tools on top

---

## Phase 2 — Core value loop: write, search, read

Goal: an agent writes an artifact and immediately finds it via semantic search. This is the minimum viable loop — the reason the server exists.

6. ✅ **Artifact model and key generation** — metadata schema (FR-09), deterministic tier 2 slug (`type-date-title_slug`) and tier 3 slug (`type-title_slug`) (FR-08)
   - Done when: hash function is pure and tested; same inputs always produce the same key; different inputs produce different keys; edge cases (empty feature tags, same-day vs cross-day) tested

7. ✅ **Write artifact tool** — S3 PutObject → parse all `##` sections → one Bedrock embed per section (fallback: single embed from title+description+type+features if no sections) → one `S3 Vectors PutVector` per section with key `{artifact_key}#{section_name_slug}` and `artifact_id` in filterable metadata (fallback key = artifact_key); re-write: upsert existing section keys + query by `artifact_id` to delete orphaned section keys for removed sections; tier 2 immutability (FR-13); tier 3 overwrite in place (FR-15); idempotent same-key writes (NFR-06); returns identifier (FR-01)
   - Done when: write → read → search round-trip tested end-to-end; section vectors carry correct `artifact_id`; same-day tier 2 write is idempotent; tier 3 same-type+title overwrites and cleans orphaned section vectors; fallback (no `##` sections) produces single document-level vector; credential errors return structured responses; no raw exceptions reach the caller
   - Integration test checkpoints: PutVector upsert behaviour — docs provide strong evidence (unique key semantics, no `ConflictException` in error list, "write/update/delete" language in overview, no separate UpdateVector API); empirical confirmation in T17; `#` key character — confirmed valid by docs (key is `String` 1–1024, no char pattern restriction; official tutorial uses spaces in keys); empirical confirmation in T17

8. ✅ **Search artifacts tool** — one Bedrock embed of query; re-fetch loop: single combined `S3 Vectors QueryVectors` call per iteration using `$or` filter covering own scope (unrestricted) and foreign scopes (tier 3 + shared only); group section vectors by `artifact_id`; repeat until `top_k` artifacts collected or `SEARCH_MAX_ITERATIONS` reached; metadata + description only in response, no content (NFR-02) (FR-03)
   - Done when: results contain no full content; cross-scope filter enforced and tested; re-fetch loop exits correctly when index is exhausted; `SEARCH_MAX_ITERATIONS` cap respected; zero results distinguished from service error; filter combinations return correct subsets
   - Integration test checkpoint: S3 Vectors `$nin` operator on `artifact_id` — confirmed supported by AWS documentation ([Metadata filtering](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-metadata-filtering.html)); non-empty array required (omit clause on first iteration); empirical confirmation in T17

9. ✅ **Read artifact tool** — S3 GetObject by identifier; cross-scope gate enforced (FR-02, FR-10)
   - Done when: known artifact returns full content; tier 2 artifact from foreign scope is rejected with a clear error; tier 3 shared artifact from foreign scope is accessible

🔁 **Phase 2 retrospective** — validate the write → search → read round-trip end-to-end with a real AWS deployment before proceeding

---

## Phase 3 — Complete tool surface: list, archive, delete, health, reliability

Goal: the server is operationally complete. Agents can list, archive, and delete artifacts; admins can diagnose health. Partial write failures are never silent.

10. ✅ **List artifacts tool** — metadata-only listing with filters (type, feature tags, team, project, tier, status); no semantic ranking; cross-scope gate enforced (FR-04)
    - Done when: filter combinations return correct subsets; archived artifacts excluded by default; active-only filter can be overridden; cross-scope gate tested

11. ✅ **Archive artifact tool** — update `status` in S3 Vectors metadata to inactive; scoped to `WRITE_PREFIX` only; no content modification (FR-05, FR-14)
    - Done when: archived artifact absent from default search and list; archiving a foreign-scope artifact returns a clear rejection; no other metadata or content is modified

12. ✅ **Delete artifact tool** — hard-delete by `artifact_id` with `confirm=True` required; delete vectors first then S3 object; warn-and-proceed if artifact is a synthesis source; scoped to `WRITE_PREFIX` only; partial delete (vectors gone, S3 delete failed) recoverable via reconciliation (FR-21, FR-13, FR-14, AC-19)
    - Done when: deleted artifact not retrievable by ID; deleted artifact absent from search and list results; foreign-scope delete returns clear rejection; synthesis warning returned when applicable; credential errors return structured responses
    - **Also deliver**: update all existing integration tests (T7–T9) to use `delete_artifact` in teardown so test data is cleaned up on every run

13. ✅ **Purge archived tool** — bulk hard-delete of all `status=inactive` artifacts in own scope with `confirm=True` required; cascade-delete any synthesis whose every `source_artifact` is in the purge set; returns summary of purged identifiers (FR-22, AC-20)
    - Done when: all inactive artifacts absent after purge; cascade-deleted synthesis identifiers reported; empty purge set returns a clear no-op response; foreign-scope artifacts never touched

14. ✅ **Health check tool** — independent per-component status: S3, S3 Vectors, Bedrock, `WRITE_PREFIX`, each `READ_PREFIXES` entry (FR-06)
    - Done when: each component reports independently; a single misconfigured component is identifiable without log access; all-healthy case tested alongside each individual failure case

15. ✅ **Partial write failure log** — on S3 success + S3 Vectors failure: write structured entry to local tier 1 failure log before surfacing error; error includes artifact identifier; Bedrock throttle triggers one retry with back-off before error (FR-16, NFR-11)
    - Done when: simulated S3 Vectors failure produces a machine-readable failure log entry and a structured error with the identifier; Bedrock throttle triggers exactly one retry; failure log path is gitignored

16. ✅ **Synthesise artifacts tool** — semantic search + batch `read_artifact` for top-k results; returns bundled full content (identifier, metadata, description, content) per source artifact; agent performs synthesis in-context; agent writes back via `write_artifact` with `type=synthesis`, `tier=3`, `source_artifacts=[...]` (FR-19)
    - Done when: single tool call returns full content from multiple matching artifacts; result includes all required fields; content is bounded by the `top_k` ceiling (100); cross-scope gate applied (same as `search_artifacts`); credential errors return structured responses

🔁 **Phase 3 retrospective** — end-to-end smoke test of all 9 tools before proceeding to documentation *(captured as T17 — run full integration test suite)*

---

## Phase 4 — Self-documentation and adoption *(T18–T20 can start in parallel with Phase 3)*

Goal: any agent can discover the schema at runtime; a new team can adopt the server following only the README and AGENTS.md snippet.

17. ✅ **Run full integration test suite** *(top priority — phase gate for T19 setup docs)* — execute all integration tests for T7–T16 against live AWS credentials; resolve remaining open question Q1 (upsert behaviour); confirm T7/T8 empirical integration checkpoints; update Learnings; close Phase 3 retrospective (NFR-07)
    - Done when: `uv run pytest tests/integration/ -q` passes green; upsert behaviour result recorded in Learnings — if upsert confirmed, no code change needed; if NOT upsert, tier 3 overwrite logic updated to explicit delete-then-re-put section vector pattern, unit and integration tests updated, and suite re-run green; `#` key separator and `$nin` operator confirmed empirically; open question Q1 closed in this plan; Phase 3 retrospective flag removed

18. ✅ **MCP Resources** — expose artifact schema, tier model, visibility and cross-scope model, type catalogue, and query strategy guidance as MCP Resources; always in sync with running server version (FR-18)
    - Done when: a connected agent can query resources and receive accurate, current field definitions, valid values, tier semantics, and query strategy guidance; resources update automatically when schema changes

19. ✅ **Setup documentation and AGENTS.md snippet** — README quick start, full configuration reference with all env vars, minimum IAM policy, AWS provisioning steps (including S3 Vectors index creation with `description` and `source_artifacts` non-filterable slots, and explicit warning that index dimension, distance metric, and non-filterable keys are immutable after creation — a new index must be created on model or dimension change), `mcp-servers.json` example; recommended AGENTS.md snippet covering when to write/search, artifact types, description quality guidance, tier selection, query strategy (start narrow, broaden if needed), when to synthesise and how (NFR-12)
    - Done when: a new team member can provision AWS resources, configure the server, and connect an agent following only the README and AGENTS.md snippet — no prior knowledge of the codebase required

20. ✅ **Migration skill** — `skills/migration/SKILL.md` with structured workflow covering both paths (agent-only < 30 files; manifest + script ≥ 30 files); discovery, classification table, metadata enrichment guidance, post-migration AGENTS.md update step; `skills/migration/scripts/migrate.py` with PEP 723 inline deps — Bedrock description generation, `git log` date recovery, bulk `write_artifact` calls, `--dry-run` mode (JSON preview), structured JSON stdout, idempotent on re-run; `skills/migration/schema.yaml` documenting CAIRN_IMPORT.yaml manifest format; README table of skills directory paths for Claude Code, Codex, Copilot, and OpenCode (FR-23, NFR-12)
    - Done when: `SKILL.md` covers both workflow paths end-to-end including post-migration AGENTS.md update; `migrate.py --help` documents all flags; `migrate.py --dry-run` with a valid manifest outputs JSON preview without any writes; full manifest run imports all listed artifacts and makes them immediately searchable; re-running the same manifest produces no duplicates; date fallback (no git history) is handled gracefully and logged to stderr
    - **Note**: `migrate.py` calls AWS APIs directly via boto3 (PEP 723 dep) using the same env vars as the server (`ARTIFACT_BUCKET`, `VECTORS_BUCKET`, `VECTORS_INDEX`, `AWS_REGION`, `BEDROCK_EMBEDDING_MODEL`) — it does not import from `cairn_mcp` to avoid a source dependency from the skill bundle into the server package

---

## Phase 5 — Could-have: reconciliation and synthesis freshness

21. ✅ **Reconciliation tool** — failure log replay + full S3 vs vector index orphan scan (including partial-delete orphans); re-index missing entries; remove resolved failure log entries; return structured summary (FR-17)
    - Done when: an orphaned S3 object (present in S3, absent from vector index) is detected and re-indexed; partial-delete orphans are handled identically to write-failure orphans; failure log entries are resolved and cleared; summary identifies each recovered artifact by identifier and title

22. ✅ **Synthesis freshness check tool** — scan all `synthesis` type artifacts; compare synthesis `date` against `date` of each listed `source_artifact`; flag stale (source updated more recently) and orphaned (source archived) entries; return structured report (FR-20)
    - Done when: a synthesis artifact with a source artifact updated after the synthesis date is flagged correctly; an archived source artifact is flagged correctly; all-fresh case returns an empty report; no S3 content fetch required (metadata-only operation)

---

## Risks and Open Questions

- **~~S3 Vectors `PutVector` upsert behaviour~~** — **CLOSED (2026-05-31, T17 confirmed)**: `PutVectors` silently overwrites an existing key (upsert confirmed). 44 integration tests passed green; tier 3 overwrite logic is correct as written; no code change required.

---

## Learnings

- **S3 Vectors boto3 service client name**: `"s3vectors"` (confirmed from botocore service catalogue during Phase 1 T3 implementation)
- **S3 Vectors `GetIndex` output**: returns `{"index": {"dimension": N, ...}}`; dimension field is nested under `index` key, not at root level
- **S3 Vectors `QueryVectors` response**: uses `distance` field (not `score`); for cosine, lower distance = more similar. Converted to `score` via negation in `VectorsClientImpl.query_vectors()`
- **S3 Vectors `list_vectors_by_metadata`**: `ListVectors` API has no server-side metadata filter parameter; implemented as paginated scan + client-side filter. Performance acceptable for Phase 1; consider optimizing in later phases if needed
- **Bedrock Titan Text Embeddings v2 request shape**: `{"inputText": text}` — `dimensions` parameter is optional; response shape: `{"embedding": [...], "inputTextTokenCount": N}`
- **pydantic-settings + mypy strict**: requires `plugins = ["pydantic.mypy"]` in `[tool.mypy]` to avoid spurious "missing required arguments" errors on `Settings()` calls
- **`#` character in S3 Vectors keys**: valid by AWS documentation — key type is `String` with length constraint 1–1024 and **no character pattern restriction**; the official getting-started tutorial uses spaces in keys ("Star Wars", "Jurassic Park"), which is more permissive than `#`; empirical confirmation planned in T17
- **`WRITE_PREFIX` must be non-empty**: empty prefix causes `startswith("")` to always return True, silently bypassing the cross-scope access control gate; default changed to `"artifacts"` and a validator now rejects empty/whitespace values at startup
- **Slug-based artifact IDs over hash-based**: collisions are intentional deduplication; human-readable in S3 console; two titles normalising to the same slug represent the same artifact (idempotency contract)
- **`$or`, `$in`, and `$nin` in S3 Vectors filters**: all confirmed supported by AWS documentation ([Metadata filtering](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-metadata-filtering.html)); `$nin` explicitly listed as "Match none of the values in array" with "Non-empty array of primitives" constraint — non-empty array required (omit the clause on first iteration); `$or` and `$in` enable a single combined query per search iteration rather than one per scope
- **S3 Vectors index configuration is immutable**: dimension, distance metric, index name, and non-filterable metadata keys cannot be changed after index creation — confirmed by AWS documentation ([Vector indexes](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-indexes.html)); a mismatch between the configured embedding model output dimension and the index dimension requires the admin to create a new index; document this as an explicit warning in T19 setup docs
- **S3 Vectors `PutVector` upsert — CONFIRMED empirically (T17, 2026-05-31)**: integration test suite ran 44 tests against live AWS credentials; tier 3 re-write integration tests passed green with zero duplicate vectors; `PutVectors` silently overwrites an existing key — no code change required; Q1 closed as confirmed.
- **`#` character in S3 Vectors keys — CONFIRMED empirically (T17, 2026-05-31)**: write and search integration tests exercised section-vector keys of the form `{artifact_id}#{section_slug}` without any key-format error from the S3 Vectors API; `#` is a valid key character in production.
- **S3 Vectors `$nin` operator — CONFIRMED empirically (T17, 2026-05-31)**: search integration tests exercised the `$nin` filter in re-fetch loop iterations; no filter-validation errors returned from S3 Vectors; the operator works correctly with a non-empty array constraint.
- **T17 integration suite baseline**: 44 tests, 0 failures, runtime ≈ 94 s against live AWS (eu-west-1); all tools covered (write, search, read, list, archive, delete, purge, health, synthesise, client layer).
- **feature_tags vector metadata storage**: stored as `list[str]` in vector metadata (not comma-joined string) so that `{"feature_tags": {"$eq": "tag"}}` filter works correctly; S3 object metadata stores as comma-joined string (S3 only supports string metadata values)
- **Phase 3 top-level exception handler pattern**: all tool public functions delegate to `_<name>_inner` and wrap the await in `try/except Exception` returning `{"error": "internal_error", "message": str(exc)}` — this prevents any unexpected exception from escaping as a raw Python exception to the MCP caller; follow this pattern for Phase 4+
- **Delete synthesis reference check must be scoped**: the `list_vectors_by_metadata` query for synthesis references in `delete_artifact` must include a `scope` filter; without it, foreign-scope synthesis identifiers leak into the `warnings` list
- **Phase 3 implementation complete**: 370 unit tests passing (264 Phase 1+2 + 106 Phase 3 new); 6 new tools registered; integration test teardown updated for T7–T9; failure log module added

- **Phase 5 implementation complete**: 431 unit tests + 54 integration tests passing; 2 new tools registered (`reconcile_index`, `check_synthesis_freshness`); ruff + mypy clean (32 source files)
- **Scope guard must use `startswith(prefix + "/")` in failure log and malformed deletion paths**: foreign-scope entries in the failure log must be skipped before any `head_object` call; malformed synthesis IDs from vector metadata must be validated against `write_prefix + "/"` before vectors or S3 deletion — bare `startswith(prefix)` would match `"team-abc/..."` against `"team-a"` silently
- **`CredentialError` must be imported and handled at every AWS call site in every tool**: not just at the outer `_inner` boundary — each call site needs its own `except CredentialError` guard so the structured error is returned immediately rather than falling through to a generic `Exception` handler
- **`all_fresh` semantics**: `True` iff `stale`, `archived_sources`, `missing_sources`, AND `malformed` are all empty — applies after any deletions triggered by `confirm=True`
- **Source deduplication in freshness**: collect all distinct source IDs across all synthesis artifacts first, then fetch each unique ID exactly once; without deduplication, a shared source referenced by N syntheses would trigger N `list_vectors_by_metadata` calls

## References

- [`docs/planning-artifacts/prd.md`](./prd.md)
- [`docs/brainstorming/brainstorming-artifact-store.md`](../brainstorming/brainstorming-artifact-store.md)
- [`docs/brainstorming/research-artifact-store.md`](../brainstorming/research-artifact-store.md)
- [`docs/brainstorming/brainstorming-delete-artifact-2026-05-30.md`](../brainstorming/brainstorming-delete-artifact-2026-05-30.md)
- [`docs/brainstorming/brainstorming-existing-project-migration-2026-05-30.md`](../brainstorming/brainstorming-existing-project-migration-2026-05-30.md)
