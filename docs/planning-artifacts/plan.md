# Plan: cairn-mcp

_Project: cairn-mcp_
_Generated: 2026-05-29_ · _Last updated: 2026-06-09_
_Status: **V1 — Phases 1–8 complete + artifact type vocabulary extended to 14 types (489 unit tests + integration suite passing against live AWS; ruff + mypy clean; Apache 2.0 licensed; production-hardened; moto migration complete; write performance hardened) · Phase 9 (pre-v1 release improvements) in progress — T30 (Z1 write_artifacts + migrate_artifacts) complete (547 unit tests passing); T31 (installing-cairn skill + migration exclusion gate + README reduction) complete — multi-client per-project config implemented (FR-44, AC-49): all four clients support project-scoped config; Copilot CLI shares .mcp.json with Claude Code (v0.0.401+); auto-detect in Step 1; safe-edit for JSON/JSONC/TOML; migration skill exclusion gate wired to cairn-mcp:config block; README reduced to ~370 lines (inc. Quick Install); T32 (reconcile Scenario 3 dangling vectors) complete (557 unit tests passing); T33 (skill distribution via native plugin mechanisms) complete — OpenCode JS plugin, Claude Code plugin, install.sh, Copilot adapter, README Quick Install, scripts/validate.py pre-commit validation (557 unit tests passing; ruff + mypy clean) · Phase 10 (artifact commit references) T34–T37 planned, specs ready**_

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
Specs: `docs/specs/p8-t26-*.md` through `docs/specs/p8-t29-*.md`.

**Execution order:** T26 first (establishes concurrent embed foundation all others benefit from);
T27 and T28 can proceed in parallel after T26 merges; T29 is independent and can start at any
point.

26. ✅ **P1 — Concurrent embedding + batched put_vectors** *(highest impact)* — replace the serial section `for` loop in `write_artifact` with `asyncio.to_thread` + `asyncio.gather` bounded by `asyncio.Semaphore(SECTION_CONCURRENCY)`; collapse all per-section `put_vector` calls into one `vectors.put_vectors_batch` call per artifact; add `SECTION_CONCURRENCY` config var (default 5); add `put_vectors_batch` to `VectorsClientInterface` and `VectorsClientImpl` (chunk at 500) (NFR-13, NFR-14)
    - Done when: 8-section write makes 8 concurrent embed calls and 1 batch put call (verified by unit test spy); `SECTION_CONCURRENCY=0` rejected at startup; all existing write tests pass; ruff + mypy clean
    - Spec: `docs/specs/p8-t26-concurrent-embedding.md`

27. ✅ **P2 — Retry and throttle fix** *(correctness fix)* — remove the duplicate `ThrottlingException` catch-and-retry blocks from `write.py` (redundant with `bedrock.py`'s internal retry; adds up to 5 s per throttled section); add `random.uniform(0, 1)` jitter to the `bedrock.py` retry sleep to prevent thundering-herd when concurrent embeds throttle simultaneously (NFR-11)
    - Done when: a `ThrottlingException` exhausting both `bedrock.py` retries results in exactly 2 `embed` calls total (no third attempt from `write.py`); `asyncio.sleep` is never called from `write.py` on a throttle event; jitter is applied (verified by patching `random.uniform`); ruff + mypy clean
    - Spec: `docs/specs/p8-t27-retry-throttle-fix.md`

28. ✅ **P3 — Configurable section caps** *(defensive bound)* — add `EMBED_MAX_SECTIONS` (default 20) and `EMBED_MIN_SECTION_LENGTH` (default 50 chars) config vars; apply as filters in `write.py` immediately after `parse_sections`; fall back to document-level embed if no sections remain; log dropped sections at DEBUG (FR-01, NFR-13)
    - Done when: a section with a 30-char body is not embedded when `EMBED_MIN_SECTION_LENGTH=50`; a 25-section document indexes only 20 vectors when `EMBED_MAX_SECTIONS=20`; full content is still returned by `read_artifact`; `EMBED_MAX_SECTIONS=0` rejected at startup; ruff + mypy clean
    - Spec: `docs/specs/p8-t28-section-caps.md`

29. ✅ **L1+L2 — Migration skill parallel writes** *(skill + script)* — restructure SKILL.md into three mutually exclusive bands (1–4 files → Path A sequential; 5–9 files → Path B manifest+script; ≥10 files → Path C parallel sub-agents via `task` tool, batches of 4–5); lower Path B threshold from 30 → 5 files; add `asyncio.gather` + `asyncio.Semaphore(MIGRATE_CONCURRENCY)` to `migrate.py` for concurrent writes; read `MIGRATE_CONCURRENCY` from env (default 3); wrap `main()` with `asyncio.run` (FR-23, NFR-15)
    - Done when: SKILL.md Step 5 clearly describes the two-phase enrichment + parallel-write path for ≥ 10 files with a sub-agent fallback; Path B gate reads "< 5 files" and "≥ 5 files"; `migrate.py --dry-run` on a 5-entry manifest outputs correct JSON preview; `migrate.py` on a 9-entry manifest processes entries concurrently (not strictly ordered in log); `MIGRATE_CONCURRENCY=0` exits with a clear error
    - Spec: `docs/specs/p8-t29-migrate-skill.md`
    - **Open question:** Do sub-agents spawned by the `task` tool inherit cairn-mcp MCP connections? Test empirically during implementation; the SKILL.md fallback path (sub-agent returns metadata → main agent writes) must be in place regardless.

---

## Phase 9 — Improvements and Fixes

Goal: quality-of-life improvements and documentation polish before declaring v1, plus the v0.3.0 artifact commit-references feature.

30. ✅ **Z1 — `write_artifacts` + `migrate_artifacts` bulk tools** *(priority 1 — unblocks correct migration performance)* — add two new MCP tools:
    - **`write_artifacts`** (FR-25): accepts a list of artifact descriptors (same fields as `write_artifact`; `description` required); processes all concurrently via `asyncio.gather` + `asyncio.Semaphore(ARTIFACT_CONCURRENCY)`, default 3; section-level concurrency (P1, `SECTION_CONCURRENCY`) applied within each artifact; partial failures recorded per-artifact in response list without aborting the batch; add `ARTIFACT_CONCURRENCY` config var (int, default 3, ≥ 1).
    - **`migrate_artifacts`** (FR-26): accepts a list of artifact descriptors with `description` optional; for each descriptor missing a description, generates one concurrently via Bedrock Nova Lite (bounded by semaphore, reusing `ARTIFACT_CONCURRENCY` — no separate `DESCRIPTION_CONCURRENCY` needed); generated descriptions clipped to 280 chars (`dry_run=False` = silent clip + DEBUG log; `dry_run=True` = return clipped in enriched list for agent review; same rule applies to agent-provided descriptions that already exceed 280 chars); `dry_run=True` returns enriched descriptor list without writing; `dry_run=False` generates descriptions then delegates to `write_artifacts`; add `BEDROCK_TEXT_MODEL` config var (string, default `amazon.nova-lite-v1:0`); add 6th startup health check validating Nova Lite accessibility when `BEDROCK_TEXT_MODEL` is configured.
    - **P4 — `EMBED_MAX_SECTION_LENGTH`** (FR-01): add `EMBED_MAX_SECTION_LENGTH` config var (int, default 24,000 chars; 0 = disabled); sections exceeding the limit are truncated before the embedding call (not skipped); truncation applies to embedding input only — S3 content is never modified; log at DEBUG; default 24,000 chars targets ≈ 6,000–8,000 tokens depending on content type (code ~3 chars/token ≈ 8,000 tokens; prose ~4 chars/token ≈ 6,000 tokens) — comfortably under Titan's 8,192-token hard limit across content types.
    - **migrate.py eliminated**: delete `skills/migrating-to-cairn/scripts/migrate.py` and the `scripts/` directory entirely; all Bedrock and write logic lives in the server.
    - **SKILL.md simplified**: remove all sub-agent/task-tool references; two paths — agent-only (< 5 files: agent classifies + generates descriptions in-context + calls `write_artifacts` once) and manifest + `migrate_artifacts` (≥ 5 files: agent classifies into CAIRN_IMPORT.yaml with git dates → calls `migrate_artifacts(dry_run=True)` to preview → reviews → calls `migrate_artifacts(dry_run=False)` to write); CAIRN_IMPORT.yaml as progress tracker enabling partial-failure retry; ≤ 500 lines; cross-IDE compatible (no IDE-specific tool references).
    - Update plan.md, PRD, and brainstorming docs.
    - Done when: `write_artifacts` on a 10-entry list processes entries concurrently (verified by log order); any failed entry appears in the response with an error field while successful entries report `written=True`; `ARTIFACT_CONCURRENCY=0` exits with a clear error at startup; `migrate_artifacts` with `dry_run=True` returns enriched descriptors with generated descriptions and writes nothing; descriptions in the enriched list are clipped to 280 chars; `migrate_artifacts` with `dry_run=False` writes all artifacts and makes them immediately searchable; `BEDROCK_TEXT_MODEL` startup check fires when configured; a section body exceeding `EMBED_MAX_SECTION_LENGTH` is truncated before embedding but the full body is returned unchanged by `read_artifact`; `EMBED_MAX_SECTION_LENGTH=0` disables truncation; `skills/migrating-to-cairn/scripts/` directory absent; SKILL.md ≤ 500 lines and references no IDE-specific tool; full round-trip: agent classifies → `migrate_artifacts(dry_run=True)` → `migrate_artifacts(dry_run=False)` → `list_artifacts` confirms all entries
    - Spec: `docs/specs/p9-t30-write-artifacts.md` (status: **approved + complete** — 547 unit tests passing; SKILL.md 354 lines; scripts/ deleted; ruff + mypy clean; integration tests pending live AWS run)
    - **New config vars**: `ARTIFACT_CONCURRENCY` (int, default 3, ≥ 1); `BEDROCK_TEXT_MODEL` (string, default `None` — operator opt-in); `EMBED_MAX_SECTION_LENGTH` (int, default 24,000, ≥ 0; 0 = disabled); combined `ARTIFACT_CONCURRENCY × SECTION_CONCURRENCY ≤ 15` rule of thumb (safe Bedrock quota ceiling)
    - **Supersedes**: L1+L2 spec (`p8-t29-migrate-skill.md`) — both made redundant by server-side parallelism; spec marked `status: superseded`

31. ✅ **Installing-cairn skill** — `skills/installing-cairn/SKILL.md` with 6-step structured
    workflow that assumes all required AWS resources are already provisioned externally:
    (1) parameter collection upfront — region, existing S3 bucket name, existing S3 Vectors
    bucket and index names, embedding model, AWS profile, IDE choice, team/project names,
    optional cross-scope read prefixes; (2) pre-flight checks — AWS CLI availability, active
    credentials (`aws sts get-caller-identity`), `uv` installed, S3 bucket reachable
    (`head-bucket`), Vectors index reachable (`describe-index`), Bedrock model accessible
    (`invoke-model`); (3) clone and Python setup; (4) MCP client config — write the
    cairn-mcp server entry including all required env vars directly into the correct
    configuration file for the chosen MCP client (see multi-client table below); show entry
    and ask explicit permission before writing; merge into existing file without touching
    other entries; display entry for manual addition if operator declines; no `.env` file is
    written at any step; (5) smoke test via `health_check` — all components must return
    `"status": "ok"` before proceeding; (6) permanent exclusion configuration —
    two-part step: (A) ADR strategy (git-only vs cairn-mcp-only): if git-only, auto-detect
    ADR folder from common directory names; confirm with operator or ask for path if not
    found; add confirmed path to `local_only_paths` and `adr` to `local_only_types`; (B) ask
    for any additional folders or files that should never go into cairn-mcp; for each path,
    infer artifact type from the migration skill's path-pattern table and confirm with
    operator. Write `<!-- cairn-mcp:config -->` block to AGENTS.md; write narrative snippet
    from `references/agents-snippet.md`. Re-running updates config block in place. No IAM
    policy generation at any step — the README provides a static reference policy with
    YOUR-* placeholders that operators use as a template. (FR-24, FR-44, NFR-12, AC-28,
    AC-29, AC-40, AC-42, AC-49)
    - **Multi-client per-project config (FR-44, AC-49)**: the skill supports all four
      MCP clients — Claude Code, opencode, GitHub Copilot CLI, and OpenAI Codex. For
      clients that support a project-scoped config file (Claude Code `.mcp.json`/`.mcp.jsonc`,
      opencode `opencode.json`, Codex `.codex/config.toml`), the skill writes
      the cairn-mcp entry into that project-level file. GitHub Copilot CLI uses `.mcp.json`
      at the workspace root (shared with Claude Code, supported since v0.0.401), so all four
      clients receive a project-scoped entry. Config files are
      always edited (JSON/JSONC: parse → insert → write; TOML: append section), never
      replaced or overwritten. opencode uses `environment` as the env-vars key (not `env`);
      all other clients use `env`. For Codex, note the "trusted projects only" requirement
      for project-scoped config. opencode's merge is additive at the server-name level —
      project config adds new server names without disturbing global entries (empirically
      confirmed). The skill checks for `opencode.json`; creates `opencode.json` (no dot
      prefix — officially documented name) if neither exists.
    - **Also delivers**: update `skills/migrating-to-cairn/SKILL.md` — remove Step 2c ADR
      strategy gate entirely; add pre-flight check at top of Step 2: if no `cairn-mcp:config`
      block found in AGENTS.md → hard stop ("run `installing-cairn` first"); if block found →
      read `local_only_paths` (excluded at scan time) and `local_only_types` (excluded after
      classification). (FR-23, AC-41)
    - Done when: `SKILL.md` covers all 6 steps including Step 4 multi-client table with all
      four clients; the four client configs are shown with their correct format (JSON, JSONC,
      TOML), correct env key (`environment` for opencode, `env` for all others), and correct
      file path (project-level for all four clients, including Copilot CLI via `.mcp.json`
      shared with Claude Code); the safe-edit requirement is explicit
      in Step 4 (parse-insert-write for JSON/JSONC; append-section for TOML); `opencode.json`
      (no dot prefix) is used when creating new opencode project configs; `references/agents-snippet.md`
      contains the complete AGENTS.md snippet; `SKILL.md` ≤ 500 lines; README shrinks
      to ~255 lines with no `YOUR-*` placeholder blocks remaining; a new operator following
      the skill reaches a server confirmed healthy by `health_check` returning all-ok; the
      `cairn-mcp:config` block written to AGENTS.md is valid YAML inside the HTML comment
      with all four keys; re-running the skill replaces the block in place; migration skill
      Step 2c is absent; migration skill halts on missing config block; migration skill scan
      respects `local_only_paths` and classification respects `local_only_types`
    - Specs: `docs/specs/p9-t31a-installing-cairn-skill.md` (requires revision — add
      multi-client per-project config per FR-44, AC-49, and
      `docs/brainstorming/brainstorming-2026-06-08-multi-team-multi-project-config.md`),
      `docs/specs/p9-t31b-migration-skill-exclusion-gate.md`,
      `docs/specs/p9-t31c-readme-reduction.md`

32. ✅ **Reconcile Phase 3 — dangling vector pruning** *(priority 2)* — extend `reconcile_index` with a third phase that detects and deletes vector index entries whose backing S3 object no longer exists. Dangling vectors arise when an S3 object is deleted externally (outside cairn-mcp) while its vector index entries remain; they surface in search and list results with valid-seeming metadata but cause `read_artifact` to return a not-found error. Phase 3 reuses data already collected in Phase 2 at zero additional API cost: `indexed_artifact_ids − set(own_keys)` identifies all dangling artifact IDs; their vector keys are already grouped from the existing `indexed_keys_raw` listing and are deleted. Phase 3 always runs automatically — no new parameters, consistent with Phases 1+2 which also auto-repair without confirmation. Response schema gains three additive fields: `dangling_artifacts_found` (int), `dangling_vectors_pruned` (int), `dangling_artifacts` (list[str]). Existing callers that ignore unknown keys are unaffected.
    - Done when: an artifact whose S3 object was deleted externally while its vector entries remain is detected by Phase 3 and its vector entries are removed; `dangling_artifacts_found` and `dangling_vectors_pruned` report correct counts; `dangling_artifacts` lists affected IDs; clean state (no dangling vectors) reports all zeros in the new fields; own-scope gate enforced — foreign-scope vector entries never pruned; credential error during vector deletion returns structured error; Phase 2 orphan scan and Phase 3 dangling prune both execute within a single `reconcile_index` call
    - Spec: `docs/specs/p9-t32-reconcile-phase3-dangling-vectors.md` (status: complete)

33. ✅ **Skill distribution via native plugin mechanisms** — wire `installing-cairn` and `migrating-to-cairn` into engineers' AI tools using the same plugin pattern as the shared engineering plugin project. No new server code — purely repo-level files and a bash script. Independent of all other Phase 9 tasks; can be worked at any point.
    - **OpenCode JS plugin (FR-33)**: `package.json` at repo root (`name: cairn-mcp`, `type: module`, `main: .opencode/plugins/cairn.js`); `.opencode/plugins/cairn.js` ESM module (~50 lines) using the `config` hook to push `skills/` into `config.skills.paths`; path resolved relative to plugin file via `import.meta.url` so it works from Bun's cache regardless of clone location; errors in the hook logged to stderr, never thrown.
    - **Claude Code plugin (FR-34, FR-35, FR-36)**: `.claude-plugin/marketplace.json` registering the repo as a private marketplace source; `plugins/cairn-mcp/.claude-plugin/plugin.json` (name: `cairn`, giving the `cairn:` slash command namespace); `plugins/cairn-mcp/skills/installing-cairn` and `plugins/cairn-mcp/skills/migrating-to-cairn` as symlinks to `../../../skills/<name>`; `plugins/cairn-mcp/skills/plugin-sync/SKILL.md` (~22 lines, Claude Code-specific: runs `git -C ~/.claude/plugins/cairn-mcp pull` + `/reload-plugins`; notes server requires a separate update); no agents directory.
    - **Install script (FR-37, FR-38, FR-39, FR-40, FR-42)**: `install.sh` at repo root; detects `claude`, `opencode`, `copilot` on PATH; OpenCode section prints the `git+ssh://` plugin snippet (does not patch `opencode.jsonc` directly); Claude Code section runs `claude plugin marketplace add` + `claude plugin install cairn@cairn-mcp` and merges `Bash(git -C * pull)` pre-approval into `~/.claude/settings.json`; no `@`-import to `~/.claude/CLAUDE.md` (cairn-mcp AGENTS.md is server-specific context, not global engineering conventions); no agent symlinks loop (cairn-mcp has no agents); idempotent; bash only / WSL Ubuntu on Windows; always prints session-refresh instructions.
    - **Copilot adapter (FR-41)**: inside `install.sh`; detects `copilot` on PATH as the Copilot-specific signal (not `gh`); checks `gh` and `gh skill` as prerequisites; loops over `skills/*/` calling `gh skill install "$REPO_DIR" <skill-name> --from-local --agent github-copilot --scope user --force`; stops immediately on any failure, prints error and docs link; no fallback path.
    - **README quick-install section (FR-43)**: adds a "Quick install" section before the full server setup instructions; documents the one-line OpenCode plugin snippet (SSH primary, HTTPS alternative) and the two-command Claude Code install; brief note that `cairn:` coexists with other plugin namespaces without collision.
    - Done when: adding the plugin line to `opencode.jsonc` and restarting OpenCode makes `installing-cairn` and `migrating-to-cairn` discoverable via the `skill` tool (AC-43); `claude plugin install cairn@cairn-mcp` makes `/cairn:installing-cairn`, `/cairn:migrating-to-cairn`, `/cairn:plugin-sync` available as slash commands (AC-44); `./install.sh` on a machine with all three tools wires each and prints session-refresh instructions (AC-45); running the script twice produces no duplicate entries or errors (AC-46); `/cairn:plugin-sync` pulls and reloads without permission prompts (AC-47); partial-tool install skips absent tools cleanly (AC-48); `plugin-sync` skill absent from shared `skills/` directory; no Python source changes; ruff + mypy clean
    - Brainstorming: `docs/brainstorming/brainstorming-2026-06-08-skill-distribution.md`
    - Spec: `docs/specs/p9-t33a-opencode-js-plugin.md`, `docs/specs/p9-t33b-claude-code-plugin.md`, `docs/specs/p9-t33c-install-script.md`, `docs/specs/p9-t33d-copilot-adapter.md`, `docs/specs/p9-t33e-readme-quick-install.md` (status: complete)

---

### Phase 10 — Artifact Commit References

Goal: close the traceability gap between artifacts and git commits. Agents can associate any
written artifact with a commit SHA after the fact — without re-embedding — and discover
which session artifacts still need linking. The write-time ULID timestamp enables efficient
time-range discovery scoped to the current session.

**Execution order:** T34 is an independent prerequisite (filter.py only); T35 depends on
T34 and must complete before T36 and T37; T36 and T37 can be worked in parallel once T35
merges. This track is independent of T31, T32, and T33 — no shared files.

34. ☐ **Filter range operators ($gte / $lte)** *(prerequisite — filter.py only; no tool changes)* — add `$gte` and `$lte` inclusive string-comparison operators to `filter.py`; update module docstring (FR-30)
    - Done when: `matches_filter(meta, {"field": {"$gte": v}})` returns `True` iff `meta["field"] >= v`; `$lte` symmetric; absent field → `False`; combined `$and` interval works; `$gt` / `$lt` (strict) raise `ValueError`; all existing operator tests pass; ruff + mypy clean
    - Spec: `docs/specs/p10-t34-filter-range-operators.md`

35. ☐ **`commit_refs` and `last_edited_ulid` metadata fields** *(core data model)* — add `commit_refs: list[str]` to `Artifact`; generate `last_edited_ulid` via `python-ulid` on every `write_artifact` call; store both fields in S3 object metadata and vector metadata following the `feature_tags` encoding pattern (comma-joined string in S3, `list[str]` in vectors, key omitted when empty in vectors); include `last_edited_ulid` in `write_artifact` response; expose both fields in `list_artifacts` (with `commit_refs` filter parameter) and `read_artifact` responses; legacy artifacts (missing fields) return `None` — no error (FR-28, FR-29)
    - Done when: `write_artifact` response includes `last_edited_ulid`; `read_artifact` and `list_artifacts` return both fields; `commit_refs` filter in `list_artifacts` returns correct subset; empty `commit_refs` stores `""` in S3 and omits key from vector metadata; legacy artifacts return `None` for `last_edited_ulid` and `[]` for `commit_refs`; ruff + mypy clean
    - Spec: `docs/specs/p10-t35-commit-refs-metadata-fields.md`
    - **New dependency**: `python-ulid` added to `pyproject.toml`

36. ☐ **`propose_commit_links` tool** *(read-only discovery)* — scan own-scope artifacts in the vector index optionally bounded by `last_edited_ulid >= since_ulid`; deduplicate by `artifact_id`; filter client-side for artifacts with absent or empty `commit_refs`; return candidate list with human-readable timestamps; no writes (FR-31)
    - Done when: tool called with `since_ulid` returns only own-scope artifacts written at or after that timestamp with no `commit_refs`; called without `since_ulid` returns all unlinked own-scope artifacts; foreign-scope artifacts never included; empty result returns `{"proposed": [], "commit_sha": "..."}` not an error; credential errors return structured responses; ruff + mypy clean
    - Spec: `docs/specs/p10-t36-propose-commit-links.md`

37. ☐ **`link_commit` tool + AGENTS.md post-commit protocol** *(write, no re-embed)* — for each confirmed `artifact_id`: `list_vectors_by_metadata` → `get_vectors` → merge `commit_sha` into `commit_refs` (append + deduplicate) → `put_vectors_batch` with same float32 embeddings and updated metadata; scope-gate rejects foreign-scope IDs (counted in `skipped`); generate `next_since_ulid` after all artifacts processed; return `{linked, skipped, commit_sha, next_since_ulid}`; add AGENTS.md post-commit protocol snippet to installing-cairn skill (FR-32)
    - Done when: `link_commit` appends SHA to all section vectors without Bedrock call; existing SHA not duplicated; foreign-scope IDs skipped and counted; `next_since_ulid` returned; two successive calls produce monotonically non-decreasing cursors; Bedrock `embed` never called (verified by spy); credential errors return structured responses; AGENTS.md snippet includes session-start ULID capture, post-commit proposal, confirmation, linking, and cursor-advance steps; known reconcile limitation documented in module docstring; ruff + mypy clean
    - Spec: `docs/specs/p10-t37-link-commit.md`
    - **Known limitation (V1)**: commit references are stored in vector metadata only; `reconcile_index` will drop them on any reconcile run — documented in spec and module docstring; S3 `copy_object` update deferred to a future milestone

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

- **Artifact type vocabulary extended to 14 types (2026-06-01)**: added `changelog`, `plan`, `postmortem`, `prd`, `runbook` to `ARTIFACT_TYPES` in `artifact.py` (9 → 14); `resources.py` descriptions and tier guidance updated for all 14 types; README type table and tier lists updated; 5 new parametrized test cases added (`test_artifact.py`); migration skill (`skills/migrating-to-cairn/SKILL.md`) updated with docs-root discovery sub-step, subdirectory-pattern table replacing hardcoded `docs/` paths, and Step 7 removal guidance for the 5 new types; `schema.yaml` type comment updated to list all 14 types. Quality gate: 457 unit tests passing, ruff clean, mypy clean. Spec: `docs/specs/p7-t25b-extend-artifact-types.md`.

- **Phase 8 (write performance) complete (2026-06-02)**: 489 unit tests passing; ruff + mypy clean (31 source files); all 4 tasks delivered: P1 concurrent embedding + batched `put_vectors` (single `put_vectors_batch` call per artifact, `asyncio.Semaphore(SECTION_CONCURRENCY)`), P2 retry/throttle correctness fix (duplicate `write.py` retry removed; `random.uniform` jitter added to `bedrock.py`), P3 configurable section caps (`EMBED_MAX_SECTIONS=20`, `EMBED_MIN_SECTION_LENGTH=50`; length filter before cap; fallback to document-level embed), L1+L2 migration skill restructured into three mutually exclusive bands (1–4 → Path A sequential; 5–9 → Path B script; ≥10 → Path C sub-agents) with concurrent `asyncio.gather` writes in `migrate.py`.

- **L1+L2 superseded by Z1 (2026-06-03)**: Post-implementation review revealed two structural problems with the L1+L2 approach. (1) L1 assumed sub-agents spawned via the `task` tool receive independent cairn-mcp MCP connections — empirical evidence (persistent performance problems) indicates sub-agents share the parent's stdio pipe, serializing all write_artifact calls and collapsing write parallelism to zero. (2) migrate.py duplicated the write path and was never updated with P1's concurrent section embedding — the script's write_artifact() still uses the old sequential for-loop, making it 2× slower per artifact than calling the MCP server with P1. Both problems trace to the same root cause: bypassing MCP required duplicating write logic, and duplicated code does not inherit fixes. Z1 (write_artifacts + migrate_artifacts MCP tools) resolves all three problems: moves all document-level and section-level parallelism inside a single MCP call; eliminates the transport bottleneck; eliminates duplication by moving description generation server-side into migrate_artifacts. migrate.py is deleted entirely — the skill ships SKILL.md + schema only, with no bundled scripts, and is fully cross-IDE compatible (OpenCode, Claude Code, Codex, Copilot). See brainstorming-write-performance-2026-06-01.md Sessions 2026-06-03 Part 1 and Part 2 for full analysis.

- **T31 — opencode project config filename is `opencode.json` (no dot prefix)**: `opencode.json` at the workspace root is the officially documented project-level config. `.opencode.json` (dot-prefixed) is NOT reliably picked up — it was silently ignored in a real installation test where the startup log showed only the three global config files loading and never the project file. Do not create `.opencode.json`; create `opencode.json`. The dot-prefix variant may be detected if already present from an earlier mistaken setup but must never be written by the installing-cairn skill.

- **T31 — opencode MCP config merge is additive at the server-name level**: A project-level `opencode.json` that introduces a server name not present in the global config adds it to the merged set without disturbing existing global servers. Confirmed empirically: a project config containing only `cairn` merged with a global config containing `mcp_aws`, `mcp_iac`, and `mcp_awscw` — all four servers were active in the session.

- **T31 — opencode must be started from the project directory to load project config**: opencode only reads a project-level `opencode.json` when started from the directory that contains it (or a subdirectory that traverses up to find it). Starting from any other directory silently skips the project config — only global configs load, with no error or warning. Skills that configure project-level MCP entries must explicitly tell the operator to restart the MCP client from the project directory.

- **T31 — Copilot CLI supports per-project `.mcp.json` since v0.0.401**: GitHub Copilot CLI added workspace-level `.mcp.json` support in v0.0.401 (≈ February 2026). The official docs page was not updated at time of discovery — the feature was found via GitHub issue comments. `.mcp.json` at the workspace root is shared between Claude Code and Copilot CLI; both use the `mcpServers` top-level key. `servers` (VS Code Copilot Chat's key) is NOT recognised by Copilot CLI. Copilot CLI also reads `~/.copilot/mcp-config.json` as a merge layer — this is a client behaviour, not something the installing-cairn skill writes.

- **T31 — MCP skill agents default to global config paths when not explicitly anchored**: Without an instruction that specifies the exact file path derived from the current working directory, an agent configuring an MCP client will default to the globally-known config path it learned during training (e.g., `~/.config/opencode/opencode.json` instead of the project-local `opencode.json`). Installing skills must resolve and name the absolute target path — including a concrete example such as `/home/alice/myproject/opencode.json` — before the agent touches any file. A reference table alone is insufficient.

- **T31 — opencode uses `environment` (not `env`) and array `command`**: opencode's MCP server config uses `environment` as the env-vars key and requires `command` as a JSON array (e.g. `["uv", "run", ...]`). Every other supported MCP client (Claude Code, Copilot CLI, Codex) uses `env`. VS Code + Copilot Chat additionally uses `servers` as the top-level key instead of `mcpServers`. These differences must be prominently flagged in any skill that generates MCP config entries.

- **T31 — `BEDROCK_TEXT_MODEL` is required for migration Step 3.B (> 10 files)**: Without `BEDROCK_TEXT_MODEL` configured, `migrate_artifacts(dry_run=True)` cannot generate descriptions and the agent improvises a non-standard path — skipping the preview review step and batching calls directly to `dry_run=False`. Always configure `BEDROCK_TEXT_MODEL: amazon.nova-lite-v1:0` alongside `BEDROCK_EMBEDDING_MODEL` in the MCP server env block. The installing-cairn skill now collects this parameter explicitly.

- **T32 — Reconcile Scenario 3 (dangling vector pruning) complete (2026-06-09)**: 557 unit tests passing; ruff + mypy clean (33 source files); 8 new unit tests + 1 new integration test; `vectors_by_artifact` grouping unified into a single pass over `indexed_keys_raw` (was a separate `set()` pass in Scenario 2 — now a dict build that also gives Scenario 3 its key lists at zero extra cost); `dangling_artifact_ids = set(vectors_by_artifact.keys()) − set(own_keys)` drives `delete_vectors` calls; three new response fields (`dangling_artifacts_found`, `dangling_vectors_pruned`, `dangling_artifacts`) are additive — existing callers unaffected.

- **T33 — Plugin distribution: known implementation gotchas (derived from post-delivery fixes to the reference implementation; record here before speccing T33)**:

  - **`git+ssh://` URL format**: the correct npm git+ssh format uses a forward slash after the hostname: `git+ssh://git@github.com/org/repo.git`. The SCP-like colon form (`git+ssh://git@github.com:org/repo.git`) is valid for bare git but is an **invalid URL in Node.js** — it throws `ERR_INVALID_URL`. The OpenCode plugin silently never installs with the colon form: no entry in `~/.config/opencode/node_modules/`, config hook never fires, no skills appear.

  - **YAML description quoting for `gh skill install`**: any SKILL.md whose `description` frontmatter value contains the two-character sequence `: ` (colon-space) **must** be wrapped in double quotes. Python's `yaml.safe_load` is lenient and parses plain scalars with `: ` without complaint. The Go YAML parser used by `gh skill install` is strict and rejects them. This caused silent failures for affected skills. Solution: pre-validate all SKILL.md files at commit time with a `scripts/validate.py` check (or equivalent) that flags unquoted descriptions containing `: `.

  - **`gh skill install` required flags — all four are mandatory**:
    - `--from-local`: installs from the local clone, not via 32+ remote GitHub API calls; works offline; uses exactly the cloned version.
    - `--agent github-copilot`: without this, the command prompts interactively for agent selection and hangs in a terminal script.
    - `--scope user`: installs to `~` (user-level); without it, scope defaults vary and skills may not be globally available.
    - `--force`: overwrites on re-run without prompting; required for idempotency.

  - **Copilot detection signal**: use `command -v copilot` (not `command -v gh`) in `install.sh` to detect GitHub Copilot. `gh` is GitHub's general-purpose CLI used by all developers for PRs, issues, and releases — its presence on PATH says nothing about which AI coding tool is installed. `gh` and `gh skill` are then checked as internal prerequisites inside the Copilot section, not in the top-level detection block.

  - **`marketplace.json` required fields**: the minimal valid `marketplace.json` for Claude Code requires `$schema`, `name`, `owner: {name: ...}`, and `plugins[].source` using a relative path (`"./plugins/cairn-mcp"`). A bare `path` field (without the `source` key) is not valid. Missing `owner` or `$schema` causes the marketplace registration to fail silently.

  - **`plugin.json` must omit `version`**: including a static `version` field in `plugins/cairn-mcp/.claude-plugin/plugin.json` pins the plugin to that version string and prevents users from receiving updates via `claude plugin update`. Omitting `version` causes Claude Code to use the commit SHA, treating every push as a new version automatically.

  - **OpenCode session-refresh message**: print both SSH and HTTPS plugin lines verbatim in the final summary section of `install.sh` — not only earlier in the OpenCode section where they scroll off before the engineer reaches the bottom. Engineers need the plugin line where they are ready to act on it.

- **T33 — Plugin distribution complete (2026-06-10)**: `package.json` + `.opencode/plugins/cairn.js` (OpenCode JS plugin, idempotent `config` hook); `.claude-plugin/marketplace.json` + `plugins/cairn-mcp/` tree (Claude Code plugin, symlinks to root `skills/`, `plugin-sync` skill); `install.sh` (detects `opencode`/`claude`/`copilot`, idempotent, fail-hard on `gh skill install` errors, session-refresh section always printed); `scripts/validate.py` (SKILL.md description quoting gate); `.pre-commit-config.yaml` updated; `CONTRIBUTING.md` created; README Quick Install section added. 557 unit tests passing; ruff + mypy clean.

## References

- [`docs/planning-artifacts/prd.md`](./prd.md)
- [`docs/brainstorming/brainstorming-artifact-store.md`](../brainstorming/brainstorming-artifact-store.md)
- [`docs/brainstorming/research-artifact-store.md`](../brainstorming/research-artifact-store.md)
- [`docs/brainstorming/brainstorming-delete-artifact-2026-05-30.md`](../brainstorming/brainstorming-delete-artifact-2026-05-30.md)
- [`docs/brainstorming/brainstorming-existing-project-migration-2026-05-30.md`](../brainstorming/brainstorming-existing-project-migration-2026-05-30.md)
- [`docs/brainstorming/brainstorming-write-performance-2026-06-01.md`](../brainstorming/brainstorming-write-performance-2026-06-01.md)
- [`docs/specs/p8-t26-concurrent-embedding.md`](../specs/p8-t26-concurrent-embedding.md)
- [`docs/specs/p8-t27-retry-throttle-fix.md`](../specs/p8-t27-retry-throttle-fix.md)
- [`docs/specs/p8-t28-section-caps.md`](../specs/p8-t28-section-caps.md)
- [`docs/specs/p8-t29-migrate-skill.md`](../specs/p8-t29-migrate-skill.md)
- [`docs/brainstorming/brainstorming-2026-06-02-installing-cairn-skill.md`](../brainstorming/brainstorming-2026-06-02-installing-cairn-skill.md)
- [`docs/brainstorming/brainstorming-2026-06-08-multi-team-multi-project-config.md`](../brainstorming/brainstorming-2026-06-08-multi-team-multi-project-config.md)
- [`docs/specs/p9-t31a-installing-cairn-skill.md`](../specs/p9-t31a-installing-cairn-skill.md)
- [`docs/specs/p9-t31b-migration-skill-exclusion-gate.md`](../specs/p9-t31b-migration-skill-exclusion-gate.md)
- [`docs/specs/p9-t31c-readme-reduction.md`](../specs/p9-t31c-readme-reduction.md)
- [`docs/brainstorming/brainstorming-reconcile-dangling-vectors-2026-06-03.md`](../brainstorming/brainstorming-reconcile-dangling-vectors-2026-06-03.md)
- [`docs/specs/p9-t32-reconcile-phase3-dangling-vectors.md`](../specs/p9-t32-reconcile-phase3-dangling-vectors.md)
- [`docs/brainstorming/brainstorming-2026-06-06-artifact-commit-refs.md`](../brainstorming/brainstorming-2026-06-06-artifact-commit-refs.md)
- [`docs/specs/p10-t34-filter-range-operators.md`](../specs/p10-t34-filter-range-operators.md)
- [`docs/specs/p10-t35-commit-refs-metadata-fields.md`](../specs/p10-t35-commit-refs-metadata-fields.md)
- [`docs/specs/p10-t36-propose-commit-links.md`](../specs/p10-t36-propose-commit-links.md)
- [`docs/specs/p10-t37-link-commit.md`](../specs/p10-t37-link-commit.md)
- [`docs/brainstorming/brainstorming-2026-06-08-skill-distribution.md`](../brainstorming/brainstorming-2026-06-08-skill-distribution.md)
- [`docs/specs/p9-t33a-opencode-js-plugin.md`](../specs/p9-t33a-opencode-js-plugin.md)
- [`docs/specs/p9-t33b-claude-code-plugin.md`](../specs/p9-t33b-claude-code-plugin.md)
- [`docs/specs/p9-t33c-install-script.md`](../specs/p9-t33c-install-script.md)
- [`docs/specs/p9-t33d-copilot-adapter.md`](../specs/p9-t33d-copilot-adapter.md)
- [`docs/specs/p9-t33e-readme-quick-install.md`](../specs/p9-t33e-readme-quick-install.md)
