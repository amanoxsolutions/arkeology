---
type: code_review
title: "Full source review of cairn-mcp (src/cairn_mcp)"
description: "Whole-codebase review of the cairn-mcp MCP server — correctness, security, spec alignment, and maintainability across all 36 source files."
tags: [code-review, cairn-mcp, full-review]
timestamp: 2026-06-25T00:00:00Z
okf_version: "0.1"
status: draft
references: []
authored:
  by: developer
  date: 2026-06-25
revised:
  by: developer
  date: 2026-06-29
---

# Full source review of cairn-mcp (src/cairn_mcp)

## Description
A complete review of all 36 Python source files under `src/cairn_mcp/`, grounded in the
per-task feature specs (`docs/specs/`), `AGENTS.md` conventions, and non-negotiable rules.
The review was conducted by partitioning the source into seven logical areas, reviewing each
against its spec, and independently verifying every critical/major finding against the code.

Baseline gates at review time: **653 unit tests pass**, `ruff check` clean, `ruff format`
clean, `mypy` clean, no `print()`/stdout writes anywhere in `src/`.

## Spec and ADRs Consulted
- `docs/specs/` — p1-t2/t3/t4/t5, p2-t6/t7/t8/t9, p3-t10..t16, p5-t21/t22, p8-t26/t27/t28,
  p9-t30/t32, p10-t35..t42, p11-t43/t44
- `AGENTS.md` (conventions + non-negotiable rules), `docs/architecture-decisions/overview.md`

## Files Reviewed
All of `src/cairn_mcp/**.py` (domain/config, clients, all 17 tools, server, startup, resources).

## Findings

No **critical** (merge-blocking, data-loss-on-normal-path, or security-hole) findings.
One reported "critical" was a **false positive** (see note), and one reported "major"
(studio `structured_content`, #7) was **withdrawn as correct-by-design** after author feedback —
the T43/T44 specs were stale and have been corrected. **All seven remaining majors are now resolved**
(2026-06-25, TDD, all gates green): #1, #2, #3, #4, #5, #6 fixed in code; #8 resolved via a
documented T42 waiver (a genuine FastMCP/MCP-SDK limitation). **No open majors or criticals remain.**
**All 23 minor items are now resolved** (2026-06-26 M1–M14, 2026-06-29 M15–M23, TDD, all gates green); several were retired during verification. See § Items Resolved Since Last Review for full details.

### Spec Alignment
- ✅ **FIXED — freshness.py S3 `head_object` fallback violated T22.** The fallback that read S3
  metadata for sources absent from the vector index has been removed: a source with no vector
  results is now reported missing (T22 SHALL), and the audit performs no S3 reads. S3 is still read
  only on the malformed-deletion path (T22-permitted). New test
  `test_missing_source_present_in_s3_but_no_vectors` (source present in S3, absent from index →
  reported missing, `head_object` call_count == 0); the obsolete fallback credential test was
  repurposed to the malformed-deletion path.
- ✅ **FIXED — reconcile.py dropped `commit_refs` and `last_edited_ulid`.** `_reindex_artifact` now
  rebuilds both (mirroring `write_artifact`: `last_edited_ulid` always present; `commit_refs` as
  `list[str]`, omitted when empty), so commit-ref filtering and ULID lookups survive a rebuild (T21).
  New test `test_reindex_preserves_commit_refs_and_last_edited_ulid`.
- ~~**studio.py:64–73 — supporting-host path omits `structured_content` (T43/T44 drift).**~~
  **RESOLVED — not a bug.** Omitting `structured_content` on UI-supporting hosts is intentional:
  it stops the model from re-describing artifacts already rendered in the widget (it has no signal
  the UI displayed them). The iframe loads its own list on mount. The **specs were stale**; T43 and
  T44 were corrected on 2026-06-25 to document this branching behavior and rationale.
- ✅ **RESOLVED (waiver) — resources.py `lastModified` annotation never emitted.** Verified
  against the pinned stack (FastMCP 3.4.2 + MCP SDK): a per-id `lastModified` on the
  `cairn://artifact/{id}` **template** is not expressible — template annotations are static and
  `TextResourceContents` has no `annotations` field. Recorded an explicit waiver in T42 (requirement,
  Story 1 AC, test bullets, and resolved the open question), and documented the retained, unit-tested
  `_artifact_last_modified` helper at its definition + the handler so it is no longer undocumented
  dead code. `audience: ["user"]` is still emitted; content is always fresh.

### Critical
None. (Reported `fake_bedrock.py:109` "Python-2 `except` SyntaxError" is a **false positive**:
`except A, B:` is valid, correct tuple syntax in Python 3.14 / PEP 758 — verified by `ast.parse`,
`py_compile`, and a runtime semantics test showing both exception types are caught. Project
requires Python 3.14. At most a minor readability note.)

### Major
1. ✅ **FIXED — vectors.py get_vectors/delete_vectors unbatched.** `delete_artifact` and
   `purge_archived` called `get_vectors` on the full own-scope key set; past the API caps the S3
   Vectors API raises `ValidationException`. **Resolved:** chunking now lives inside the client
   methods (`get_vectors` at 100, `delete_vectors` at 500 — verified against the AWS S3 Vectors
   limits page, not the agent's guessed 100), so every call site is safe; `list.py`'s redundant
   manual loop and `_GET_VECTORS_BATCH_SIZE` constant were removed. New client-level chunking tests
   in `tests/unit/clients/test_vectors.py` (spy on boto3 to assert chunk counts). Also added an
   empty-keys guard to `get_vectors`.
2. ✅ **FIXED — freshness.py:140–148** — see Spec Alignment.
3. ✅ **FIXED — reconcile.py:62–80** — see Spec Alignment.
4. ✅ **FIXED — `READ_PREFIXES` not slash-normalized while `WRITE_PREFIX` is.** A configured
   `READ_PREFIXES="network/"` became `"network//"` at the call site and silently disabled
   foreign-scope reads/listing. **Resolved:** `validate_read_prefixes` and `read_prefixes_list` now
   strip surrounding slashes per token (internal slashes preserved), matching `WRITE_PREFIX` and the
   stored `scope` metadata. Updated the affected config tests, added
   `test_read_prefixes_strips_surrounding_slashes_keeps_internal`, and corrected the T4 spec
   (requirement + example) so it no longer documents the buggy output.
5. ✅ **FIXED — bulk path bypassed `file_extension` validation.** `write_artifacts` called
   `_write_artifact_inner` directly, so a descriptor `file_extension:"txt"` produced a malformed key
   `...-titletxt` (confirmed by the failing test before the fix). **Resolved:** the `startswith(".")`
   guard moved into `_write_artifact_inner`, so both single and bulk paths enforce it; the duplicate
   in the public wrapper was removed. Added
   `test_write_artifacts_invalid_file_extension_validation_error`; the single-write
   no-AWS-calls test still passes (guard runs before any AWS call).
6. ✅ **FIXED — orphan-cleanup failure masked an already-successful write.** A non-credential
   error in Step 8 (after S3 + new vectors were durably written) escaped to the catch-all →
   `internal_error`, and via `write_artifacts` the artifact was reported `failed` despite being
   fully written. **Resolved:** Step 8 is now wrapped in a best-effort `try/except Exception` that
   logs a warning (with `exc_info`) and returns the standard success dict; `reconcile_index` can
   collect any leftover orphan vectors later. This also resolves the related minor (a cleanup
   `CredentialError` no longer inverts a durable write). Added three tests
   (`test_orphan_cleanup_{list,delete,credential}_failure_does_not_fail_write`).

   <!-- original finding text retained below for traceability -->
   ~~By Step 8 the S3 object and new section vectors are durably written. The cleanup block catches
   only `CredentialError`; any other error from `list_vectors_by_metadata`/`delete_vectors` escapes
   to the catch-all → `internal_error` with no `artifact_id`, and via `write_artifacts` the artifact
   is reported `failed` despite being fully written (orphan vectors also linger). Make cleanup
   best-effort: `try/except Exception`, log a warning, still return success.~~
7. ~~**studio.py:64–73**~~ — **withdrawn; correct by design.** Supporting hosts intentionally omit
   `structured_content` (prevents the model re-rendering content already in the widget). Specs
   T43/T44 were stale and have been corrected; the code is right.
8. ✅ **RESOLVED (waiver) — resources.py lastModified** — see Spec Alignment.

### Minor
- ✅ **M1 FIXED 2026-06-26 — artifact.py:118–144** `parse_sections` splits on `## ` lines inside
  fenced code blocks (wrong section boundaries for code-heavy artifacts).
- ✅ **M2 FIXED 2026-06-26 — artifact.py:65–86** `generate_artifact_id` validates neither `type`
  nor `date`.
- ✅ **M3 FIXED 2026-06-26 — failure_log.py:29** `json.dumps(entry)` can drop a partial-write
  record on a non-serializable value — pass `default=str`.
- ✅ **M4 FIXED 2026-06-26 — config.py** `ConfigurationError` (T4) never added;
  `BEDROCK_EMBEDDING_MODEL`/`BEDROCK_TEXT_MODEL` accept empty strings.
- ~~**vectors.py:231** `list_vectors` hard-codes `maxResults: 1000`~~ — **retired:** 1000 is the
  documented ListVectors per-page maximum (AWS S3 Vectors limits page), so the value is correct.
- ✅ **M5 FIXED 2026-06-26 — interfaces.py:184 / vectors.py:216** `list_vectors_by_metadata` uses
  bare `filter` (noqa) — convention says `filter_expr`.
- ✅ **M6 FIXED 2026-06-26 — s3.py:107** `head_object` maps `403` → `KeyError`, masking
  permission errors as not-found.
- ✅ **M7 FIXED 2026-06-26 — vectors.py:205** `describe_index` redundantly spreads `index_info`
  after pinning `dimension`.
- ✅ **M8 FIXED 2026-06-26 — fake_bedrock.py:106–112** docstring overstates retry parity (no
  sleep/jitter vs real client); **fake_bedrock.py:109** unparenthesized `except A, B:` — valid in
  3.14 but parenthesize for clarity.
- ✅ **M9 FIXED 2026-06-26 — read.py:130–141** non-credential vector error aborts an
  otherwise-successful read (commit_refs are supplementary — degrade to `[]`).
- ✅ **M10 FIXED 2026-06-26 — search.py / read.py** return `source_artifacts` not in the T8/T9
  response contract (additive) — specs T8/T9 retrofitted to document the field.
- ✅ **M11 FIXED 2026-06-26 — write.py:324,353–366** `asyncio.to_thread` default executor caps
  compound concurrency below the nominal `artifact_concurrency × SECTION_CONCURRENCY` — replaced
  with a dedicated `_EMBED_EXECUTOR` (300-worker `ThreadPoolExecutor`).
- ✅ **M12 FIXED 2026-06-26 — write.py:399–403** `partial_write` message doesn't note a
  failure-log entry was written (T15 AC).
- ✅ **M13 FIXED 2026-06-26 — write_artifacts.py:134–173** intra-batch duplicate artifact IDs
  race on orphan cleanup.
- ✅ **M14 FIXED 2026-06-26 — freshness.py:226–230** non-credential partial-delete aborts the
  whole audit instead of reporting `failed` and continuing (T22 Boundary).
- ✅ **M15 FIXED 2026-06-29 — reconcile.py:215–258,305–331** a Phase-1 failed re-index is
  retried as a Phase-2 orphan → duplicate `failed` entry.
- ✅ **M16 FIXED 2026-06-29 — purge.py:166–176** partial-delete response omits already-purged IDs.
- ✅ **M17 FIXED 2026-06-29 — list.py:205** `int(meta["tier"])` (vs `.get("tier",0)` elsewhere)
  can KeyError on legacy vectors.
- ✅ **M18 FIXED 2026-06-29 — link_commit.py:106–109,147** `linked` counted even when `batch` is
  empty; **:48,130** `commit_sha` not validated for emptiness/format.
- ✅ **M19 FIXED 2026-06-29 — propose_commit_links.py:84–86** artifacts with no
  `last_edited_ulid` excluded under `since_ulid` (consistent with frozen requirement — comment
  added to make the intentional behaviour explicit).
- ✅ **M20 FIXED 2026-06-29 — migrate_artifacts.py:175–181** a single Nova Lite failure aborts
  the whole migration — now isolated per-descriptor; **:11–12** docstring mislabels enrichment
  phase as "dry_run" — corrected; **server.py:271–274** `artifact_concurrency` not exposed on the
  MCP `migrate_artifacts` tool — parameter added.
- ✅ **M21 FIXED 2026-06-29 — studio.py:33–97** no `_cairn_studio_inner` (inline try/except meets
  the safety goal but not the documented `_inner` convention / T43 naming).
- ✅ **M22 FIXED 2026-06-29 — health.py:120–121** `write_prefix` key absent on `CredentialError`;
  **:116–123** probe object can leak if `get_object`/`delete_object` fails — `finally` cleanup
  added.
- ✅ **M23 FIXED 2026-06-29 — startup.py:65–78,160–173** non-credential `head_bucket`/
  `describe_index` errors escape to `__main__` as raw tracebacks — now raise
  `StartupValidationError`; **:243–252** check 6 wraps `CredentialError` instead of propagating —
  fixed; **:1–9,38,59** "6/6" vs frozen T5 "5/5" (stale spec) — AGENTS.md updated to
  "Six-check".

### Test coverage
- Integration tests exist for older tools but **not** for `link_commit`, `propose_commit_links`,
  `migrate_artifacts`, `write_artifacts`, `studio`, or the data resources. Unit coverage is
  comprehensive (one test file per tool). Several majors above (e.g. the 100-key batching in
  delete/purge, the bulk `file_extension` bypass) are exactly the cases an integration test at
  scale would have caught.

## Recommendations
1. Fix the two highest-impact silent failures first: the **get_vectors batching** in delete/purge
   (chunk inside the client) and the **reconcile metadata drop** (re-add `commit_refs` +
   `last_edited_ulid`).
2. Resolve the four spec-drift items (freshness fallback, studio `structured_content`, resources
   `lastModified`, READ_PREFIXES normalization) — each either fix the code or record a spec waiver.
3. Make write-path cleanup best-effort and move `file_extension` validation into the inner function.
4. Add integration tests for the six uncovered tools/resources, with at least one >100-key case.
5. Sweep the minor consistency items (error-taxonomy in startup, `.get("tier",0)`, `filter_expr`
   rename, `json.dumps(default=str)`).

## Items Resolved Since Last Review
- 2026-06-29 — **Minors M15–M23 resolved (TDD; 705 unit tests pass, ruff/format/mypy clean).**
  M15: `reconcile.py` `failed_ids` hoisted to outer scope; Phase-2 orphan scan excludes Phase-1
  failures → no duplicate `failed` entries. M16: `purge.py` `partial_delete` response now includes
  already-purged IDs. M17: `list.py` `int(meta["tier"])` → `.get("tier", 0)` — safe for legacy
  vectors. M18: `link_commit.py` empty `batch` no longer counts as `linked`; empty `commit_sha`
  returns `validation_error`. M19: `propose_commit_links.py` comment added to document intentional
  `since_ulid` exclusion. M20: `migrate_artifacts.py` per-descriptor Nova Lite failure isolation;
  "dry_run phase" → "enrichment phase" in docstring; `artifact_concurrency` exposed on MCP tool in
  `server.py`. M21: `studio.py` `_cairn_studio_inner` extracted following `_inner` convention.
  M22: `health.py` `write_prefix` key set on `CredentialError` (was `pass`); `finally` block
  added for probe object cleanup. M23: `startup.py` non-credential `head_bucket`/`describe_index`
  errors now raise `StartupValidationError`; `CredentialError` propagates from check 6; `AGENTS.md`
  updated "Five-check" → "Six-check".
- 2026-06-26 — **Minors M1–M14 resolved (TDD; 692 unit tests pass, ruff/format/mypy clean).**
  M1: `artifact.py` `parse_sections` now fence-aware (headings inside code blocks ignored). M2:
  `generate_artifact_id` validates `type` and `date`. M3: `failure_log.py` `json.dumps(default=str)`
  prevents drops on non-serialisable values. M4: `ConfigurationError` domain exception added;
  `BEDROCK_EMBEDDING_MODEL`/`BEDROCK_TEXT_MODEL` reject empty strings; `load_settings()` factory
  wraps `ValidationError`. M5: `filter` → `filter_expr` in interfaces and vectors client (removes
  Python-builtin shadow). M6: `s3.py` `head_object` 403 now raises `CredentialError` (was
  re-raising as `KeyError`). M7: `vectors.py` `describe_index` returns `dict(index_info)` without
  redundant spread. M8: `fake_bedrock.py` docstring corrected (no sleep/jitter). M9: `read.py`
  non-credential vector error degrades `commit_refs` to `[]` instead of aborting. M10: T8/T9 specs
  retrofitted to document the `source_artifacts` response field. M11: `write.py` `asyncio.to_thread`
  replaced with dedicated `_EMBED_EXECUTOR` (300-worker `ThreadPoolExecutor`). M12: all four
  `partial_write` responses now include the failure-log path (T15 AC). M13: `write_artifacts.py`
  pre-flight duplicate-artifact-ID check added. M14: `freshness.py` malformed-synthesis delete
  failures now add to `delete_failed` and continue (T22 Boundary); `delete_failed` always in
  response.
- 2026-06-25 — **Majors #2, #3, #8 resolved (TDD; 663 unit tests pass, ruff/format/mypy clean).**
  #2: removed the freshness S3 `head_object` fallback — sources absent from the index are reported
  missing and the audit performs no S3 reads (T22); repurposed the obsolete credential test to the
  malformed-deletion path. #3: `reconcile._reindex_artifact` now rebuilds `commit_refs` +
  `last_edited_ulid` mirroring `write_artifact` (T21). #8: `lastModified` emission waived after
  verifying it is not expressible for a template resource in FastMCP 3.4 + the MCP SDK — recorded the
  waiver in T42 and documented the retained, tested `_artifact_last_modified` helper. This closes all
  open majors.
- 2026-06-25 — **Major #6 fixed (TDD; 661 unit tests pass, ruff/format/mypy clean).** Orphan
  cleanup (write.py Step 8) is now best-effort: a failure (credential or otherwise) is logged and
  the write still returns success, instead of inverting a durable write to `internal_error`. Also
  resolves the related orphan-cleanup-CredentialError minor. Three new tests cover list/delete/
  credential cleanup failures.
- 2026-06-25 — **Majors #1, #4, #5 fixed (TDD; 658 unit tests pass, ruff/format/mypy clean).**
  #1: `get_vectors`/`delete_vectors` now chunk inside the client (100 / 500 per verified AWS caps);
  `list.py` manual loop removed. #4: `READ_PREFIXES` surrounding-slash normalization added,
  consistent with `WRITE_PREFIX`; T4 spec corrected. #5: `file_extension` guard moved into
  `_write_artifact_inner` so the bulk path enforces it. Also retired the `maxResults: 1000` minor
  (verified as the documented ListVectors per-page max).
- 2026-06-25 — **Finding #7 (studio `structured_content`) withdrawn.** Confirmed intentional: a
  UI-supporting host deliberately receives no `structured_content` so the model does not
  re-describe artifacts already rendered in the widget. The stale T43/T44 specs were corrected to
  document the host-dependent branching and its rationale (TL;DR, Story 1, Story 2, Requirements,
  test descriptions, implementation notes, and the ToolResult-shape note).
