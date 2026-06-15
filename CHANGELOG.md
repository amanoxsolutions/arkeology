# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `learning` artifact type — a fifteenth first-class type (tier 3, date-independent ID)
  backing the `capturing-learnings` skill's living `learnings.md`; accepted by
  `write_artifact`, listed in the `cairn://schema/artifact` and `cairn://schema/types`
  resources, and classified by the `migrating-to-cairn` skill (Pass 1 filename rules
  `learnings` / `learning` / `lessons-learned`; Pass 2 path segments `**/learnings` /
  `**/lessons-learned`)
- `propose_commit_links` tool — read-only tool that discovers own-scope artifacts with no
  `commit_refs`, optionally bounded to artifacts written at or after a session-start ULID
  (`since_ulid`); returns a proposed list for agent review before linking
- `link_commit` tool — appends a commit SHA to the vector metadata of confirmed own-scope
  artifacts without re-embedding; returns `{linked, skipped, commit_sha, next_since_ulid}`
- `commit_refs` optional field on artifacts — list of git commit SHAs linked via `link_commit`;
  accepted by `list_artifacts` as a filter and returned by `read_artifact` and `list_artifacts`
- `last_edited_ulid` system-generated field — ULID assigned at every `write_artifact` call and
  returned in the write response; monotonically increasing, suitable for use as `since_ulid` in
  `propose_commit_links` to bound discovery to the current session
- `$gte` and `$lte` string comparison operators in the in-process metadata filter evaluator
  (`filter.py`); enable range queries on string-valued metadata fields (e.g. ULID-based filtering)
- `python-ulid` runtime dependency for ULID generation in `write_artifact`

### Changed
- Minimum Python version raised from 3.12 to 3.14; `.python-version`, `pyproject.toml` `requires-python`, and `[tool.mypy] python_version` updated accordingly

## [0.3.1] - 2026-06-11

### Added
- `artifact_concurrency` optional per-call parameter on `write_artifacts` and
  `migrate_artifacts` (default 3, ceiling 15); values outside [1, 15] are clamped
  with a top-level `"warning"` field rather than rejected; removes the
  `ARTIFACT_CONCURRENCY` env var

### Fixed
- `setting-up-cairn` skill: installation now requires a single MCP client restart
  instead of two — AGENTS.md is written before the restart so both files are picked
  up in one reload
- `setting-up-cairn` skill: removed the "When to write artifacts" section from the
  generated AGENTS.md snippet, which was triggering spurious `session_summary` writes
  at the end of skill-driven operations
- `migrating-to-cairn` skill: dot-prefix directories (e.g. `.docs/`) are now surfaced
  in the 2b discovery scan; the blanket `.docs/` exclusion is removed
- `migrating-to-cairn` skill: CAIRN_IMPORT.yaml is no longer printed to the terminal;
  operators are directed to open the file in their editor

## [0.3.0] - 2026-06-10

### Added
- `setting-up-cairn` skill — guided per-project cairn-mcp configuration for OpenCode, Claude Code, GitHub Copilot, and Claude Desktop
- `sync-cairn-plugin` skill — updates the cairn-mcp plugin in place for any supported AI coding tool without manual config edits
- Native plugin support for OpenCode, Claude Code, and GitHub Copilot via `install.sh` and `marketplace.json`
- `reconcile_index` Scenario 3 — dangling vector pruning: removes vector entries with no corresponding S3 object

## [0.2.0] - 2026-06-03

### Added
- `write_artifacts` bulk write tool for importing multiple artifacts in a single MCP call (T30, FR-25)
- `migrate_artifacts` migration tool for server-side parallel migration with automatic chunking (FR-26)
- Concurrent section embedding and batched `put_vectors` calls in `write_artifact` — reduces write latency by up to 80% on multi-section documents (Phase 8)
- Bedrock throttle retry with exponential backoff and jitter
- `SECTION_CONCURRENCY`, `EMBED_MAX_SECTIONS`, and `EMBED_MIN_SECTION_LENGTH` configuration variables for write-path tuning

### Changed
- `migrating-to-cairn` skill rewritten with server-side parallel migration paths (Path B concurrent script, Path C sub-agent fan-out)

### Fixed
- `READ_PREFIXES` validated at startup to reject template placeholder text
- AWS credential values suppressed from `LOG_LEVEL=DEBUG` output
- Migration parallelism gate added — skill now surfaces concurrency settings before migration starts
- Required field validation added to `write_artifacts`; returns structured `validation_error` on missing fields

## [0.1.1] - 2026-06-01

### Added
- `brainstorming` artifact type
- Artifact type vocabulary extended from 9 to 14 types: `prd`, `plan`, `runbook`, `changelog`, and `postmortem`
- OpenCode-specific MCP client configuration example in README

### Changed
- Migration skill document classification replaced fragile docs-root detection with a two-pass system — filename rules fire first, followed by path-segment rules matching at any depth

### Fixed
- S3 object metadata values sanitised to ASCII to prevent boto3 encoding errors on non-ASCII content

## [0.1.0] - 2026-06-01

### Added
- FastMCP server skeleton with stdio transport and structured logging to stderr
- AWS client layer — S3, S3 Vectors, and Amazon Bedrock each behind a typed `Protocol` interface; all boto3 calls catch and re-raise credential errors as structured `CredentialError` exceptions
- Configuration model (`pydantic-settings`) with environment variable validation and five-check startup validation sequence
- Artifact model with deterministic key generation (date-anchored tier 2, date-independent tier 3) and section parsing
- `write_artifact` tool — embeds sections at write time via Amazon Bedrock Titan Text Embeddings v2 and stores content in S3
- `search_artifacts` tool — vector similarity search with metadata filtering (`$eq`, `$in`, `$nin`, `$and`, `$or`)
- `read_artifact` tool — full content retrieval from S3 by artifact ID with cross-scope visibility checks
- `list_artifacts` tool — filtered artifact listing by scope, type, status, and feature tags
- `archive_artifact` and `purge_archived` tools — two-phase soft delete lifecycle
- `delete_artifact` tool — hard delete with synthesis reference guard (scoped to own scope only)
- `health_check` tool — validates all three AWS service connections and reports configuration
- Partial write failure log — JSONL-format append log for embed and vector write failures
- `synthesise_artifacts` tool — LLM-ready cross-artifact synthesis with source tracing and freshness metadata
- `reconcile_index` tool — scans S3 prefix and re-indexes any artifacts with no corresponding vector entry
- `check_synthesis_freshness` tool — detects synthesis artifacts whose source artifacts have changed since last synthesis
- MCP resources for artifact type vocabulary and scope discovery
- `migrating-to-cairn` skill for migrating existing project documentation into cairn-mcp
- Full integration test suite against live AWS (S3, S3 Vectors, Bedrock) with automatic teardown
- Configurable `BEDROCK_EMBEDDING_DIMENSIONS` (default 1024)
- In-process metadata filter evaluator enabling client-side filtering when S3 Vectors filter is not supported

### Changed
- Visibility value renamed from `confidential` to `hidden`

### Fixed
- Vector metadata excludes empty list fields to avoid S3 Vectors schema validation errors
- Bedrock embed API called with correct `dimensions` parameter
- `WRITE_PREFIX` validated to require a non-empty value; defaults to `artifacts`

### Security
- Credential-related boto3 exceptions caught at the AWS client layer and re-raised as structured typed errors; never exposed as raw stack traces to MCP callers

[0.3.0]: https://github.com/amanoxsolutions/cairn-mcp/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/amanoxsolutions/cairn-mcp/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/amanoxsolutions/cairn-mcp/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/amanoxsolutions/cairn-mcp/releases/tag/v0.1.0
