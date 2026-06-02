# Plan: cairn-mcp

_Project: cairn-mcp_
_Generated: 2026-05-29_ · _Last updated: 2026-06-02_
_Status: **V1 — Phases 1–8 complete + artifact type vocabulary extended to 14 types (489 unit tests + integration suite passing against live AWS; ruff + mypy clean; Apache 2.0 licensed; production-hardened; moto migration complete; write performance hardened) · Phase 9 (pre-v1 release improvements) in progress**_

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

20. ✅ **Migration skill** — `skills/migrating-to-cairn/SKILL.md` with structured workflow covering both paths (agent-only < 30 files; manifest + script ≥ 30 files); discovery, classification table, metadata enrichment guidance, post-migration AGENTS.md update step; `skills/migrating-to-cairn/scripts/migrate.py` with PEP 723 inline deps — Bedrock description generation, `git log` date recovery, bulk `write_artifact` calls, `--dry-run` mode (JSON preview), structured JSON stdout, idempotent on re-run; `skills/migrating-to-cairn/schema.yaml` documenting CAIRN_IMPORT.yaml manifest format; README table of skills directory paths for Claude Code, Codex, Copilot, and OpenCode (FR-23, NFR-12)
    - Done when: `SKILL.md` covers both workflow paths end-to-end including post-migration AGENTS.md update; `migrate.py --help` documents all flags; `migrate.py --dry-run` with a valid manifest outputs JSON preview without any writes; full manifest run imports all listed artifacts and makes them immediately searchable; re-running the same manifest produces no duplicates; date fallback (no git history) is handled gracefully and logged to stderr
    - **Note**: `migrate.py` calls AWS APIs directly via boto3 (PEP 723 dep) using the same env vars as the server (`ARTIFACT_BUCKET`, `VECTORS_BUCKET`, `VECTORS_INDEX`, `AWS_REGION`, `BEDROCK_EMBEDDING_MODEL`) — it does not import from `cairn_mcp` to avoid a source dependency from the skill bundle into the server package

---

## Phase 5 — Could-have: reconciliation and synthesis freshness

21. ✅ **Reconciliation tool** — failure log replay + full S3 vs vector index orphan scan (including partial-delete orphans); re-index missing entries; remove resolved failure log entries; return structured summary (FR-17)
    - Done when: an orphaned S3 object (present in S3, absent from vector index) is detected and re-indexed; partial-delete orphans are handled identically to write-failure orphans; failure log entries are resolved and cleared; summary identifies each recovered artifact by identifier and title

22. ✅ **Synthesis freshness check tool** — scan all `synthesis` type artifacts; compare synthesis `date` against `date` of each listed `source_artifact`; flag stale (source updated more recently) and orphaned (source archived) entries; return structured report (FR-20)
    - Done when: a synthesis artifact with a source artifact updated after the synthesis date is flagged correctly; an archived source artifact is flagged correctly; all-fresh case returns an empty report; no S3 content fetch required (metadata-only operation)

---

## Phase 6 — Production Hardening (Review Fix Cycle)

Goal: resolve all 76 findings from the full project code review (12 critical, 27 major, 37 minor). No new functionality — correctness, security, and maintainability only.

23. ✅ **Implement all 20 review-fix specs** — credential error hardening, vector score semantics, health probe filter, README IAM fixes, exception chaining, S3/Bedrock hardening, health CredentialError distinction, archive idempotency, list scope filter, shared search helper, test infrastructure consolidation, CredentialError test coverage, integration test isolation, project config fixes, minor foundation/client/tool/test/doc improvements, ABC→Protocol migration, `filter`→`filter_expr` rename, Apache 2.0 licence, repo URL
    - Done when: all 486 unit tests passing; ruff + mypy clean; all 20 specs implemented; full post-implementation review passed clean (0 critical, 0 major, 0 minor)
    - Spec files: `docs/specs/review-fix-01-*.md` through `docs/specs/review-fix-20-*.md`

24. ✅ **V1 integration suite re-run** — full integration test suite re-run against live AWS after Phase 6 hardening; all tests pass; V1 declared clean
    - Done when: `uv run pytest tests/integration/ -q` passes green post-hardening — confirmed 2026-06-01

---

## Phase 7 — Test infrastructure: moto migration

Goal: replace hand-rolled in-memory fakes for S3 and S3 Vectors with moto-backed real client implementations. Fixes the score range inconsistency between unit and production and aligns with the project's testing convention.

25. ✅ **Migrate unit tests from hand-rolled fakes to moto** — delete `FakeS3Client` and `FakeVectorsClient`; replace with moto-backed `S3ClientImpl` / `VectorsClientImpl` throughout the unit test suite; patch `S3VectorsBackend.query_vectors` with a cosine similarity extension in `conftest.py`; fix score range from `[0, 2]` (fake) to `[−1, 1]` (cosine similarity, matching production) in all score assertions (FR-mock-conv)
    - Done when: 451 unit tests passing; `FakeS3Client`, `FakeVectorsClient` deleted; `test_fake_s3.py`, `test_fake_vectors.py` deleted; `test_moto_query_vectors_extension.py` added with 6 targeted tests; ruff + mypy clean; AGENTS.md Testing Conventions accurate

---

## Phase 8 — Write Performance

Goal: eliminate the dominant latency bottlenecks in `write_artifact` and `migrate.py`. No new
tools, no breaking changes — pure performance, correctness, and usability improvements.
Specs: `docs/specs/write-perf-p1-*.md` through `docs/specs/write-perf-l1-l2-*.md`.

**Execution order:** T26 first (establishes concurrent embed foundation all others benefit from);
T27 and T28 can proceed in parallel after T26 merges; T29 is independent and can start at any
point.

26. ✅ **P1 — Concurrent embedding + batched put_vectors** *(highest impact)* — replace the serial section `for` loop in `write_artifact` with `asyncio.to_thread` + `asyncio.gather` bounded by `asyncio.Semaphore(SECTION_CONCURRENCY)`; collapse all per-section `put_vector` calls into one `vectors.put_vectors_batch` call per artifact; add `SECTION_CONCURRENCY` config var (default 5); add `put_vectors_batch` to `VectorsClientInterface` and `VectorsClientImpl` (chunk at 500) (NFR-13, NFR-14)
    - Done when: 8-section write makes 8 concurrent embed calls and 1 batch put call (verified by unit test spy); `SECTION_CONCURRENCY=0` rejected at startup; all existing write tests pass; ruff + mypy clean
    - Spec: `docs/specs/write-perf-p1-concurrent-embedding.md`

27. ✅ **P2 — Retry and throttle fix** *(correctness fix)* — remove the duplicate `ThrottlingException` catch-and-retry blocks from `write.py` (redundant with `bedrock.py`'s internal retry; adds up to 5 s per throttled section); add `random.uniform(0, 1)` jitter to the `bedrock.py` retry sleep to prevent thundering-herd when concurrent embeds throttle simultaneously (NFR-11)
    - Done when: a `ThrottlingException` exhausting both `bedrock.py` retries results in exactly 2 `embed` calls total (no third attempt from `write.py`); `asyncio.sleep` is never called from `write.py` on a throttle event; jitter is applied (verified by patching `random.uniform`); ruff + mypy clean
    - Spec: `docs/specs/write-perf-p2-retry-throttle-fix.md`

28. ✅ **P3 — Configurable section caps** *(defensive bound)* — add `EMBED_MAX_SECTIONS` (default 20) and `EMBED_MIN_SECTION_LENGTH` (default 50 chars) config vars; apply as filters in `write.py` immediately after `parse_sections`; fall back to document-level embed if no sections remain; log dropped sections at DEBUG (FR-01, NFR-13)
    - Done when: a section with a 30-char body is not embedded when `EMBED_MIN_SECTION_LENGTH=50`; a 25-section document indexes only 20 vectors when `EMBED_MAX_SECTIONS=20`; full content is still returned by `read_artifact`; `EMBED_MAX_SECTIONS=0` rejected at startup; ruff + mypy clean
    - Spec: `docs/specs/write-perf-p3-section-caps.md`

29. ✅ **L1+L2 — Migration skill parallel writes** *(skill + script)* — restructure SKILL.md into three mutually exclusive bands (1–4 files → Path A sequential; 5–9 files → Path B manifest+script; ≥10 files → Path C parallel sub-agents via `task` tool, batches of 4–5); lower Path B threshold from 30 → 5 files; add `asyncio.gather` + `asyncio.Semaphore(MIGRATE_CONCURRENCY)` to `migrate.py` for concurrent writes; read `MIGRATE_CONCURRENCY` from env (default 3); wrap `main()` with `asyncio.run` (FR-23, NFR-15)
    - Done when: SKILL.md Step 5 clearly describes the two-phase enrichment + parallel-write path for ≥ 10 files with a sub-agent fallback; Path B gate reads "< 5 files" and "≥ 5 files"; `migrate.py --dry-run` on a 5-entry manifest outputs correct JSON preview; `migrate.py` on a 9-entry manifest processes entries concurrently (not strictly ordered in log); `MIGRATE_CONCURRENCY=0` exits with a clear error
    - Spec: `docs/specs/write-perf-l1-l2-migrate-skill.md`
    - **Open question:** Do sub-agents spawned by the `task` tool inherit cairn-mcp MCP connections? Test empirically during implementation; the SKILL.md fallback path (sub-agent returns metadata → main agent writes) must be in place regardless.

---

## Phase 9 — Pre-v1 Release: Improvements and Fixes

Goal: quality-of-life improvements and documentation polish before declaring v1. No new server
tools — skill authoring, README reduction, and any additional fixes identified as v1 blockers.

30. ☐ **Installing-cairn skill** — `skills/installing-cairn/SKILL.md` with 9-step structured
    workflow: (1) parameter collection upfront — region, resource names, embedding dimension,
    IAM principal ARN, IDE choice, team/project names, optional cross-scope read prefixes;
    (2) pre-flight checks — AWS CLI availability, active credentials (`aws sts get-caller-identity`),
    `uv` installed; (3) clone and Python setup; (4) AWS provisioning — S3 artifact bucket (with
    `us-east-1` variant: omit `LocationConstraint`), S3 Vectors bucket, S3 Vectors index (hard
    stop + explicit operator confirmation gate on immutable properties: dimension, distance metric,
    non-filterable key names), Bedrock model access (Console deep link → operator confirms →
    active `bedrock:InvokeModel` validation call with minimal payload to confirm access); (5) IAM
    policy generation — runtime policy and provisioning-only policy blocks emitted with all
    `YOUR-*` placeholders replaced by operator-provided values; (6) `.env` written from collected
    parameters; (7) MCP client config written for chosen IDE (OpenCode, Claude Desktop, Cursor,
    or generic `mcpServers` format); (8) smoke test via `health_check` — all components must
    return `"status": "ok"` before proceeding; (9) AGENTS.md snippet with ADR strategy gate
    (same two-option decision as migration skill). Existing resources detected via `head-bucket` /
    `describe-index` before creation — skipped and reported rather than re-created.
    `skills/installing-cairn/references/agents-snippet.md` extracted to stay within the 500-line
    skill limit. README slimmed: Prerequisites and Installation sections collapsed to pointer
    sentences; AWS Provisioning (4 steps), both IAM policy blocks, MCP client config sections,
    and AGENTS.md snippet + ADR variants all removed — configuration reference table, server
    launch command, and all concept/marketing content retained (~255 lines). (FR-24, NFR-12,
    AC-28, AC-29)
    - Done when: `SKILL.md` covers all 9 steps end-to-end; `references/agents-snippet.md`
      contains the complete AGENTS.md snippet with both ADR variants; `SKILL.md` ≤ 500 lines;
      README shrinks to ~255 lines with no `YOUR-*` placeholder blocks remaining; a new operator
      following the skill reaches a server confirmed healthy by `health_check` returning all-ok

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

- **Phase 6 (review hardening) complete (2026-05-31)**: 486 unit tests passing; all 76 review findings resolved across 20 specs; ruff + mypy clean (33 source files); Apache 2.0 licence added; `interfaces.py` migrated ABC→Protocol; `filter`→`filter_expr` rename; shared `_search_helper.py` extracted; README IAM policy corrected (`s3:ListBucket`, `DeleteIndex` moved to provisioning section); credential error handling hardened across all tools; vector score formula aligned (`1.0 - distance`); integration tests isolated with `unique_run_id` fixture
- **V1 integration suite baseline (2026-06-01)**: full integration test suite re-run against live AWS after Phase 6 hardening; all integration tests pass; cairn-mcp declared V1-ready
- **Vector score range (known limitation)**: ~~`FakeVectorsClient` returned `1.0 + cosine_similarity` ∈ [0, 2] while `VectorsClientImpl` returns `score = 1.0 − cosine_distance` ∈ [−1, 1].~~ **RESOLVED (Phase 7, 2026-06-01)**: fakes deleted; moto extension returns `score = 1.0 − cosine_distance` ∈ [−1, 1], matching production exactly. All absolute score assertions updated.

- **Moto migration complete (2026-06-01)**: `FakeS3Client` and `FakeVectorsClient` deleted; all 12 unit test files migrated to moto-backed `S3ClientImpl` / `VectorsClientImpl`; `query_vectors` moto extension patched onto `S3VectorsBackend` in `conftest.py`; 451 unit tests passing; ruff + mypy clean. Unit test count dropped from 486 to 451 — the 35-test difference accounts for the deleted fake client test files (`test_fake_s3.py`, `test_fake_vectors.py`), partially offset by 6 new extension tests.

- **Artifact type vocabulary extended to 14 types (2026-06-01)**: added `changelog`, `plan`, `postmortem`, `prd`, `runbook` to `ARTIFACT_TYPES` in `artifact.py` (9 → 14); `resources.py` descriptions and tier guidance updated for all 14 types; README type table and tier lists updated; 5 new parametrized test cases added (`test_artifact.py`); migration skill (`skills/migrating-to-cairn/SKILL.md`) updated with docs-root discovery sub-step, subdirectory-pattern table replacing hardcoded `docs/` paths, and Step 7 removal guidance for the 5 new types; `schema.yaml` type comment updated to list all 14 types. Quality gate: 457 unit tests passing, ruff clean, mypy clean. Spec: `docs/specs/extend-artifact-types-and-flexible-docs-root.md`.

- **Phase 8 (write performance) complete (2026-06-02)**: 489 unit tests passing; ruff + mypy clean (31 source files); all 4 tasks delivered: P1 concurrent embedding + batched `put_vectors` (single `put_vectors_batch` call per artifact, `asyncio.Semaphore(SECTION_CONCURRENCY)`), P2 retry/throttle correctness fix (duplicate `write.py` retry removed; `random.uniform` jitter added to `bedrock.py`), P3 configurable section caps (`EMBED_MAX_SECTIONS=20`, `EMBED_MIN_SECTION_LENGTH=50`; length filter before cap; fallback to document-level embed), L1+L2 migration skill restructured into three mutually exclusive bands (1–4 → Path A sequential; 5–9 → Path B script; ≥10 → Path C sub-agents) with concurrent `asyncio.gather` writes in `migrate.py`.

## References

- [`docs/planning-artifacts/prd.md`](./prd.md)
- [`docs/brainstorming/brainstorming-artifact-store.md`](../brainstorming/brainstorming-artifact-store.md)
- [`docs/brainstorming/research-artifact-store.md`](../brainstorming/research-artifact-store.md)
- [`docs/brainstorming/brainstorming-delete-artifact-2026-05-30.md`](../brainstorming/brainstorming-delete-artifact-2026-05-30.md)
- [`docs/brainstorming/brainstorming-existing-project-migration-2026-05-30.md`](../brainstorming/brainstorming-existing-project-migration-2026-05-30.md)
- [`docs/brainstorming/brainstorming-write-performance-2026-06-01.md`](../brainstorming/brainstorming-write-performance-2026-06-01.md)
- [`docs/specs/write-perf-p1-concurrent-embedding.md`](../specs/write-perf-p1-concurrent-embedding.md)
- [`docs/specs/write-perf-p2-retry-throttle-fix.md`](../specs/write-perf-p2-retry-throttle-fix.md)
- [`docs/specs/write-perf-p3-section-caps.md`](../specs/write-perf-p3-section-caps.md)
- [`docs/specs/write-perf-l1-l2-migrate-skill.md`](../specs/write-perf-l1-l2-migrate-skill.md)
- [`docs/brainstorming/brainstorming-installing-cairn-skill-2026-06-02.md`](../brainstorming/brainstorming-installing-cairn-skill-2026-06-02.md)
