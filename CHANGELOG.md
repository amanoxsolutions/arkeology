# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- `build_scope_filter` moved from `arkeology.tools._search_helper` to
  `arkeology.tools._scope`, joining `is_cross_scope_readable` so that every implementation
  of the cross-scope access gate lives in one module. Its signature changed from
  `build_scope_filter(settings)` to `build_scope_filter(own_scope, read_prefixes)`, keeping
  the gate free of any configuration dependency. Both are private helpers — no MCP tool
  signature, response shape, or stored data shape changes
- the ruff quality gate now covers `scripts/` and `plugins/` in addition to `src/` and
  `tests/`, which had left the repository's non-package Python unlinted
- `.pre-commit-config.yaml` now runs the project's own pinned tooling via `uv run` instead
  of independently-versioned upstream mirrors, which had drifted to ruff 0.11 and mypy 1.x
  while the project ran ruff 0.16 and mypy 2.x
- documented that filtering `list_artifacts(commit_refs=[...])` searches only an artifact's
  most-recent 20 commit refs — the filterable index copy is capped at that many entries, so
  an artifact linked to more commits is not matched on its oldest SHAs even though the
  returned `commit_refs` field still shows the full list. Behaviour is unchanged; the
  window was previously undocumented in the list contract and the runtime schema resource
- the `arkeology://artifacts` resource is now documented as returning `list_artifacts`'
  default scope — own-scope artifacts plus shared tier-3 artifacts from readable foreign
  scopes — rather than own-scope only, which the contract and docstrings had claimed while
  the code always applied the wider gate. Behaviour is unchanged
- the freshness contract now records that a synthesis source failing the cross-scope gate is
  reported as missing, deliberately indistinguishable from a genuinely absent one, because a
  separate "inaccessible" category would leak the existence of foreign tier-2 and hidden
  artifacts. Behaviour is unchanged

### Added
- CI: `.github/workflows/ci.yml` runs the ruff, mypy, pytest, and `npm test` gates on push
  to `main` and on every pull request — the repository's first automated checks
- direct unit tests for `build_scope_filter`, asserting the gate's semantics by evaluating
  the returned filter rather than comparing it literally, plus a test pinning that both
  forms of the gate agree on the same candidate
- a test pinning that `tier` gates identically whether it arrives as an `int` (vector
  metadata) or a stringified int (S3 object metadata), which the read and list paths
  respectively depend on
- a test pinning that the `arkeology://artifacts` resource applies the cross-scope gate
  rather than listing own-scope artifacts only — a foreign-scope tier-3 shared artifact is
  listed, a foreign-scope tier-2 one is not, matching `list_artifacts`' default scope

### Fixed
- the `write_artifact` and `write_artifacts` MCP tools now accept and forward
  `file_extension`, which both module contracts list and both underlying functions
  implement but neither FastMCP wrapper declared — so no MCP caller could set the S3
  key extension on a single write or as a batch default. It was already reachable per
  descriptor inside `write_artifacts`, so this exposes no new capability
- `archive_artifact` double-encoded non-ASCII and `%`-bearing S3 metadata values on every
  archive (a title of `Café review` became `Caf%25C3%25A9 review`): `put_object`
  percent-encoded values for transport but `head_object` returned them still encoded, so
  the archive status re-PUT re-encoded what it had read. `S3ClientImpl.head_object` now
  decodes every value (except the reserved `ETag`), making the transport encoding symmetric
  and owned by the client; the ad-hoc decode sites in `read_artifact`, `reconcile_index`,
  and `archive_artifact`'s failure-log entry are removed as redundant
- corrected the normative contracts under `docs/contracts/` where they misstated the
  implementation: the Studio design-token layer still defined tokens for the removed `prd`
  artifact type and omitted the `vision`, `requirements`, and `--text-h4` tokens actually
  in use; `read_artifact`'s contract claimed a gated foreign artifact is indistinguishable
  from an absent one, which its own governing spec forbids; `health_check`'s contract
  declared all probes read-only despite the write-prefix probe performing a real
  put/get/delete cycle, and omitted the conditional `bedrock_text_model` key;
  `write_artifact`'s contract omitted the `warning` key returned when the durable
  annotation write is unavailable; the S3 data contract mislabelled per-field encoding when
  transport encoding is applied uniformly to every value; the resources contract omitted
  the `ui://` Studio resource and its content-security-policy origin allow-list
- `scripts/validate.py` formatting, which no quality gate had ever checked

## [0.6.0] - 2026-08-28

### Changed
- **Breaking:** the `prd` artifact type is removed and replaced by two new types,
  `vision` and `requirements`, mirroring this project's own migration from a single
  `prd.md` to `vision.md` + `requirements.md`. Callers writing or filtering on
  `type="prd"` must switch to `type="vision"` or `type="requirements"`; existing
  `prd`-typed artifacts are unaffected in storage but no longer match schema
  validation on new writes
- `search_artifacts` and `synthesise_artifacts` responses now include
  `index_corruption_detected: true` when a `VectorDistanceMissingError` — an S3
  Vectors index-corruption signal, distinct from an ordinary transient error — is
  encountered mid-search; the call still returns whatever partial results were
  already collected rather than aborting
- The `AnnotationUnavailableError` message's bucket-type guidance now correctly
  describes directory buckets and Outposts buckets as the two affected bucket
  types, with S3 Express One Zone named as the storage class directory buckets
  use rather than a third, separately-counted bucket type
- **Breaking:** the project is renamed from `cairn-mcp` to `arkeology`, because
  `cairn-mcp` collided with several unrelated existing projects on GitHub and PyPI.
  The Python package, CLI entrypoint, plugin and skill assets, and the MCP resource
  scheme (`cairn://` → `arkeology://`) all change accordingly. Existing installations
  must update their MCP client configuration to point at the new entrypoint; stored
  artifacts and AWS resources are unaffected
- **Breaking:** `references` now has plain replace semantics on write, mirroring the
  supplied frontmatter exactly — an ordinary overwrite sets `references` to the value
  supplied and omitting it clears the field. Previously an overwrite union-merged the
  new value with whatever was already stored, which silently accumulated stale
  reference targets over repeated writes. `commit_refs` is unaffected: it remains a
  union-merge accretive field, since it is a git-derived audit trail rather than a
  claim about current state. Callers relying on the old union-merge behaviour for
  `references` must now resend the full desired list on every write.
- `link_metadata` tool replaces the retired `link_commit` tool — appends
  `commit_refs` and `references` to an artifact's durable S3 annotation copy
  without re-embedding, where `link_commit` only handled `commit_refs`.
  `commit_refs` in vector metadata is capped to the most-recently-appended 20
  entries (the complete list stays in the durable annotation); `references` is
  no longer written to vector metadata at all
- Durable read-modify-write cycles (`write_artifact` overwrite, `link_metadata`,
  `archive_artifact` status re-PUT) are now guarded by ETag compare-and-swap:
  `PutObject` / `PutObjectAnnotation` / `DeleteObjectAnnotation` calls are made
  conditional on the ETag captured at read time, with a bounded retry (~3 attempts)
  on detected concurrent modification before returning a structured `conflict` error,
  instead of silently racing another writer
- `references` returned to a **foreign-scope** reader via `read_artifact` or
  `list_artifacts` is now filtered to targets the reader is actually permitted to
  read (own-scope, or an independently readable tier-3 shared artifact); own-scope
  reads are unaffected and continue to return `references` exactly as stored.
  `list_artifacts` now issues one additional batched query page for this filtering
- Invalid or wrong-type `tier` values on `write_artifact` now return
  `validation_error` instead of `internal_error` (`Artifact.tier` is now
  strict-typed)
- `top_k <= 0` on `search_artifacts` / `synthesise_artifacts` now returns
  `validation_error` instead of being silently accepted
- Typo'd or invalid `type` / `tier` / `status` filter values on `search_artifacts`
  now return `validation_error` instead of silently matching zero results
- Duplicate H2-heading slugs within a single artifact are now disambiguated at write
  time, so `sections_indexed` is accurate and no section's vector silently overwrites
  another's; the same disambiguation is shared between `write_artifact` and
  `reconcile_index`
- `WRITE_PREFIX` validation now matches `READ_PREFIXES`'s strictness — it rejects
  internal whitespace and values that collapse to empty after slash-stripping,
  instead of accepting them
- Metadata filter evaluator's `filter` parameter renamed to `filter_expr`, so it no
  longer shadows the `filter` builtin
- `check_synthesis_freshness` now batches its per-source vector lookups into a
  single query instead of issuing one per unique source
- The write path's section-embedding thread pool is now constructed lazily on
  first use instead of at module import time
- The reverse-reference lookup used by `delete_artifact` / `archive_artifact`
  (checking whether other artifacts still reference the one being acted on) now
  issues one vector-index query instead of two
- `arkeology_studio`'s plain-text fallback listing, used on hosts that cannot render
  the visual browser, is now capped at the 50 most recent artifacts and reports the
  total count, pointing at `list_artifacts` when truncated. Previously it emitted every
  artifact, so the listing grew without bound on large stores
- `reconcile_index`'s orphan scan now skips every own-scope key whose final path
  segment begins with `_arkeology_`, a prefix now reserved for internal probe objects.
  Previously two specific probe names were hard-coded, so the setup skill's annotation
  probe could be reported as an orphaned artifact. No generated artifact id can collide
  with the prefix
- `reconcile_index`'s failure-log replay now tracks a per-entry retry count. An entry
  that fails to re-index 3 times in a row stops being auto-retried and is reported once,
  loudly, in a new `stuck_failures` response field, instead of blending indistinguishably
  into `failed` on every run. Previously a genuinely unfixable entry would be replayed
  identically forever
- `write_artifact`'s Step 8 orphan-vector cleanup now retries a transient
  `delete_vectors` failure inline, bounded with backoff, so it self-heals without
  reaching the durable failure path. If the retry budget is exhausted, the failure
  is logged with the exact orphan vector keys still needing deletion, and
  `reconcile_index` gains a new repair path that recognises this failure kind and
  deletes exactly those keys directly, without re-indexing. `reconcile_index`'s
  response reports these as a `reconciled` entry shaped `orphan_keys_deleted` /
  `source: "orphan_vector_cleanup"` (in place of `sections_indexed`), and they
  participate in the existing `failed`/`stuck_failures` bounding, carrying an
  additional `orphan_keys` field when present
- `link_metadata` and `reconcile_index` now validate metadata size budgets before
  writing (previously only `write_artifact` did), closing a gap where either could
  durably write metadata a fresh `write_artifact` call would reject outright and
  permanently desync the annotation/vector stores. `link_metadata`'s validation of
  supplied `commit_refs`/`references` values now also rejects control characters
  (previously only checked for commas and empty/whitespace-only values)
- **Breaking:** `list_artifacts`' `references=` filter parameter is removed entirely
  — a caller supplying it now gets a `TypeError`, not a silently-empty result.
  `references` stopped being vector-filterable once `commit_refs`/`references`
  vector-metadata hardening shipped, so the parameter could never match anything for
  artifacts written after that. `commit_refs=` filtering is unaffected
- `delete_artifact`'s and `archive_artifact`'s reverse-lookup warning (checking
  whether other artifacts refer to the one being acted on) now only checks
  `source_artifacts` — the `references`-half of that check is dropped, since
  `references` stopped being vector-filterable and could never match anything there
  either. This is a separate, more recent change from the reverse-reference lookup's
  earlier one-query-instead-of-two optimisation documented above
- `migrate_artifacts`' skip-existing check can now report a candidate under a new
  `skipped_unindexed` field (distinct from `skipped_existing`) when its S3 object
  exists but its vectors are missing — a partial-write state previously silently
  treated as "already migrated." Points the operator at `reconcile_index` for
  remediation
- `check_synthesis_freshness(confirm=True)`'s `all_fresh` field now also requires no
  synthesis deletions to have failed, not just no malformed syntheses reported —
  previously it could report `all_fresh: true` while a malformed synthesis was still
  present in S3 because its deletion had failed

### Security
- Bumped the pinned DOMPurify dependency used by `arkeology_studio`'s browser-side
  sanitisation (both the CDN import in `arkeology-studio.html` and the `package.json`
  devDependency backing the sanitisation regression test) from `3.4.11` to `3.4.13`,
  addressing two moderate-severity advisories in hook and custom-element handling.
  Neither advisory is reachable through the studio's actual usage, which calls
  `DOMPurify.sanitize(html)` with no config object, no custom elements, and no hooks
  registered

### Added
- `search_artifacts` now accepts `status="all"`, the same all-inclusive sentinel
  `list_artifacts` already accepted, returning matches regardless of status. It was
  previously rejected with a `validation_error`, which left a caller holding an
  explicit "any status" filter — such as the studio's status facet, whose default is
  `"all"` — with no correct way to express it. This is a strict widening: omitting
  `status` still defaults to active-only, `"active"` / `"inactive"` are unchanged, and
  any unrecognised value still returns a `validation_error`
- The studio renders `arkeology://artifact/{id}` links in artifact content as
  activatable controls that open the target in its own detail view. Links that cannot
  be resolved — non-artifact `arkeology://` resources, malformed URIs, and the raw
  repository paths migration leaves behind — render as inert text rather than as dead
  or navigable links. Access control is unchanged; the server-side scope gate remains
  the sole authority
- The studio's artifact list now renders 50 rows at a time behind a "Show more"
  control that reports how many of how many artifacts are shown
- `synthesise_artifacts` gained a configurable response-size budget — new
  `SYNTHESISE_MAX_RESPONSE_BYTES` setting (default 1,000,000 bytes / 1 MB), measured
  as the UTF-8 byte length of the result's `content` field. Results assemble in rank
  order and stop before the next result would exceed the budget, adding
  `truncated: true` and `included: N` to the response (both omitted when not
  triggered); a single oversized top result is still included rather than returning
  zero results. The existing 100-result count ceiling remains a secondary guard
- `search_artifacts` response now includes `fetch_exhausted: true` when the
  re-fetch loop's own fetch budget — not the true number of matching artifacts — is
  what limited the result count below `top_k`
- `synthesise_artifacts` response now includes `zero_results` (matching
  `search_artifacts`'s existing convention) and `skipped_count`, the latter
  reporting per-candidate content-read failures that were previously dropped
  silently
- Vector client's `get_vectors` supports `include_data=False` for metadata-only
  reads, skipping the underlying vector-float payload

### Fixed
- A `read_artifact` failure in the studio now shows the server's own error message with
  the detail view open, instead of a blank body
- The `setting-up-arkeology` skill's annotation probe now always removes its probe
  object, reporting the exact key and removal command if cleanup fails. Previously an
  `AccessDenied` during the probe could strand the object in the bucket
- Unknown/transient `ClientError`s during annotation writes on `write_artifact` no
  longer escape as `internal_error`; the S3 content is already durable, so the
  failure is now logged and surfaced as `partial_write`, matching existing
  `CredentialError` handling
- `commit_refs` / `references` values containing a literal comma are now
  rejected up front on write and on `link_metadata`, instead of silently diverging
  between the comma-joined S3 annotation encoding and the native `list[str]` vector
  metadata encoding
- `put_object_annotation` now maps `NoSuchKey` / 404 the same way its sibling S3
  methods do; `link_metadata`'s batch loop now skips and counts orphaned-vector
  artifacts (vector index entries whose underlying S3 object no longer exists)
  instead of aborting the whole batch with `internal_error`
- Migration reference-rewrite path now normalises manifest path keys before
  matching, fixing a silent no-op on `./`- or backslash-spelled paths
- `search_artifacts` / `synthesise_artifacts` now default missing vector `tier`
  metadata to `0` instead of raising `KeyError`
- Startup's write-prefix probe now uses a unique key per invocation instead of a
  fixed one, so concurrent server starts against the same prefix no longer race on
  the same S3 object
- Startup's read-prefix check now verifies actual object-read access, not just
  `ListBucket`, catching an IAM misconfiguration (list-but-not-read) at startup
  instead of on the first `read_artifact` call
- Startup's credentials check now distinguishes a missing/misnamed bucket from an
  actual credentials failure, instead of reporting both under a misleading
  "re-authenticate" message
- A fresh artifact write with no `commit_refs` / `references` supplied no longer
  issues two pointless annotation-delete calls
- `link_metadata` now preserves partial `linked` / `skipped` progress in its
  response when an annotation-unavailable condition cuts a batch short, instead of
  discarding it
- The local failure log is now guarded against concurrent-writer corruption with a
  `flock`-based lock, gracefully degrading on non-POSIX platforms
- Raw AWS/boto error text no longer leaks into `write_artifacts` error responses,
  on both the top-level and per-artifact error paths
- An unsupported filter operator or a mixed-type comparison (e.g. an int field
  compared against a string operand) now raises a typed, catchable error instead
  of a bare `ValueError` / `TypeError` that could abort a paginated query mid-way
  and discard already-collected results
- `decode_link_list` now drops empty segments produced by a malformed
  comma-joined payload (e.g. a double comma) instead of including them as
  empty-string list entries
- A non-UTF-8 S3 object or annotation payload now raises a typed, classified
  error instead of a bare `UnicodeDecodeError`
- Metadata byte-budget validation now measures true UTF-8 size for non-ASCII
  content (CJK, Arabic, etc.) instead of the inflated size of `json.dumps`'s
  default ASCII-escaped representation, which could reject a value that actually
  fit within budget
- A migration manifest with two entries that normalise to the same path now
  raises instead of silently letting the second entry overwrite the first
- `migrate_artifacts`' skip-existing pre-check now rejects a candidate whose
  `file_extension` does not start with `.` up front, with the same
  `validation_error` shape as `write_artifact`'s own guard. Previously a
  malformed value silently built an unreachable candidate key and was deferred
  to `write_artifacts`' own validation
- A newline embedded in an artifact's title or description no longer corrupts the
  `arkeology://artifacts` markdown table's row structure
- Investigated and left unchanged: the `coerce_list_field` inconsistency flagged
  for `delete_artifact` / `purge_archived` / `check_synthesis_freshness` is not a
  real bug — vector metadata natively stores lists, so the direct access already
  in use is behaviourally equivalent
- Documented as an accepted limitation rather than fixed: a metadata value
  written before the transport-encoding scheme existed (v0.5.0-era) that happens
  to contain a literal `%XX`-shaped substring cannot be reliably distinguished on
  read from an intentionally-encoded value without a persistent per-object
  encoding-version marker — a schema-level decision out of scope for this fix
- `write_artifact`'s overwrite compare-and-swap retry loop's `CredentialError`
  response on the conditional `put_object` call now includes `artifact_id`,
  matching its two sibling `CredentialError` handlers in the same loop iteration

## [0.5.0] - 2026-06-29

### Added
- `arkeology_studio` MCP tool — two-pane visual artifact browser rendered as an MCP App in
  supporting hosts (Claude Desktop, claude.ai, VS Code Copilot); falls back to a
  structured artifact listing on non-supporting hosts
- `purge_archived` best-effort bulk partial-failure: non-credential failures on individual
  artifacts are collected in a `failed` list without aborting the purge; `CredentialError`
  during the deletion phase aborts early and reports the artifacts purged so far in
  `purged_ids`

### Changed
- `ErrorCode` and `ArtifactStatus` StrEnum constants extracted to `constants.py`,
  replacing ~75 scattered string literals across the codebase
- Config range constraints migrated from imperative `@field_validator` to declarative
  `Field(ge=…, le=…)` in `Settings`
- `wrap_credential_errors(service)` context manager introduced in `credentials.py`;
  all three AWS client implementations use it, removing per-method `except` boilerplate
- `build_user_filters` and `coerce_list_field` helpers extracted to `_search_helper.py`;
  used by `search_artifacts`, `list_artifacts`, and `reconcile_index`
- `_SCHEMA_RESOURCES` table-driven loop replaces five identical `@app.resource`
  registrations in `resources.py`
- All dependencies pinned with compatible-release operator (`~=`)

### Fixed
- `reconcile_index` now preserves `commit_refs` and `last_edited_ulid` fields when
  re-indexing artifacts
- `check_synthesis_freshness` reports sources missing from the vector index directly;
  removes the unreliable S3 fallback
- `write_artifact` enforces `file_extension` on bulk-write paths and performs
  best-effort orphan cleanup on partial write failures
- `READ_PREFIXES` config value now normalises surrounding slashes on load
- `get_vectors` and `delete_vectors` now chunk requests to the S3 Vectors API cap
  (≤ 100 keys per call), preventing `ValidationException` on large artifact sets
- Minor code quality fixes across tools and clients (codebase review 2026-06-25)

## [0.4.0] - 2026-06-23

### Added
- `arkeology://artifact/{id}` and `arkeology://artifacts` MCP data resources — human-browsable
  resources backed by existing `read_artifact` and `list_artifacts` logic; carry
  `audience: ["user"]` annotations and apply the same cross-scope gate as the tools;
  browsable in MCP Inspector and Claude Desktop
- `learning` artifact type — fifteenth first-class type (tier 3, date-independent ID)
  backing the `capturing-learnings` skill's living `learnings.md`
- `propose_commit_links` tool — discovers own-scope artifacts with no `commit_refs`,
  optionally bounded to artifacts written at or after a session-start ULID (`since_ulid`)
- `link_commit` tool — appends a commit SHA to vector metadata of confirmed own-scope
  artifacts without re-embedding
- `commit_refs` optional field — list of git commit SHAs; accepted by `list_artifacts`
  as a filter and returned by `read_artifact` and `list_artifacts`
- `last_edited_ulid` system-generated field — ULID assigned at every `write_artifact`
  call; suitable for use as `since_ulid` in `propose_commit_links`
- `$gte` and `$lte` string comparison operators in the metadata filter evaluator;
  enable range queries on string-valued metadata fields

### Changed
- `feature_tags` field renamed to `tags` across all tools, metadata, and resources (T41)
- All dependencies upgraded to latest versions
- Minimum Python version raised from 3.12 to 3.14

### Fixed
- `list_artifacts` now batches `GetVectors` calls in chunks of ≤100 — deployments
  with more than 100 artifacts were getting a `ValidationException` from the S3
  Vectors API

## [0.3.1] - 2026-06-11

### Added
- `artifact_concurrency` optional per-call parameter on `write_artifacts` and
  `migrate_artifacts` (default 3, ceiling 15); values outside [1, 15] are clamped
  with a top-level `"warning"` field rather than rejected; removes the
  `ARTIFACT_CONCURRENCY` env var

### Fixed
- `setting-up-arkeology` skill: installation now requires a single MCP client restart
  instead of two — AGENTS.md is written before the restart so both files are picked
  up in one reload
- `setting-up-arkeology` skill: removed the "When to write artifacts" section from the
  generated AGENTS.md snippet, which was triggering spurious `session_summary` writes
  at the end of skill-driven operations
- `migrating-to-arkeology` skill: dot-prefix directories (e.g. `.docs/`) are now surfaced
  in the 2b discovery scan; the blanket `.docs/` exclusion is removed
- `migrating-to-arkeology` skill: ARKEOLOGY_IMPORT.yaml is no longer printed to the terminal;
  operators are directed to open the file in their editor

## [0.3.0] - 2026-06-10

### Added
- `setting-up-arkeology` skill — guided per-project Arkeology configuration for OpenCode, Claude Code, GitHub Copilot, and Claude Desktop
- `sync-arkeology-plugin` skill — updates the Arkeology plugin in place for any supported AI coding tool without manual config edits
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
- `migrating-to-arkeology` skill rewritten with server-side parallel migration paths (Path B concurrent script, Path C sub-agent fan-out)

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
- `migrating-to-arkeology` skill for migrating existing project documentation into Arkeology
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

[0.3.0]: https://github.com/amanoxsolutions/arkeology/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/amanoxsolutions/arkeology/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/amanoxsolutions/arkeology/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/amanoxsolutions/arkeology/releases/tag/v0.1.0
