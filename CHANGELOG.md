# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-06-03

### Added
- `write_artifacts` bulk write tool for importing multiple artifacts in a single MCP call (T30, FR-25)
- `migrate_artifacts` migration tool for server-side parallel migration with automatic chunking (FR-26)
- `brainstorming` artifact type; vocabulary extended from 9 to 14 types with flexible docs-root discovery
- Concurrent section embedding and batched `put_vectors` calls in `write_artifact` — reduces write latency by up to 80% on multi-section documents (Phase 8)
- Bedrock throttle retry with exponential backoff and jitter
- `SECTION_CONCURRENCY`, `EMBED_MAX_SECTIONS`, and `EMBED_MIN_SECTION_LENGTH` configuration variables for write-path tuning
- OpenCode-specific MCP client configuration example in README

### Changed
- `migrating-to-cairn` skill rewritten with server-side parallel migration paths (Path B concurrent script, Path C sub-agent fan-out)
- Docs-root discovery replaced with two-pass classification in migration skill

### Fixed
- S3 object metadata values sanitised to ASCII to prevent boto3 encoding errors on non-ASCII content
- `READ_PREFIXES` validated at startup to reject template placeholder text
- AWS credential values suppressed from `LOG_LEVEL=DEBUG` output
- Migration parallelism gate added — skill now surfaces concurrency settings before migration starts
- Required field validation added to `write_artifacts`; returns structured `validation_error` on missing fields

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

[0.2.0]: https://github.com/amanoxsolutions/cairn-mcp/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/amanoxsolutions/cairn-mcp/releases/tag/v0.1.0
