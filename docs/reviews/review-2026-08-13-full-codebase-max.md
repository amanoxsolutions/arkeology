---
type: code_review
title: "Full codebase review — max effort, 10 angles"
description: "Max-effort whole-codebase review (10 independent finder angles: 5 correctness, 3 cleanup, 1 altitude, 1 CLAUDE.md/AGENTS.md conventions) run sequentially after repeated parallel-agent session-limit failures. Findings appended incrementally, one angle at a time."
tags: [full-review, code-review, correctness, simplification, conventions]
timestamp: 2026-08-13T00:00:00Z
okf_version: "0.1"
status: complete
references: []
authored:
  by: "developer"
  date: "2026-08-13"
revised:
  by: "developer"
  date: "2026-08-13"
---

# Full codebase review — max effort, 10 angles

## Description

Requested: `/code-review max review the full code base`. Two earlier attempts
(parallel orchestration of 9-10 finder sub-agents) both hit the session token
limit mid-run and lost all findings — nothing had been persisted. This run
orchestrates the same 10 finder angles **sequentially, one at a time**, and
appends each angle's verified findings to this document immediately after it
completes, so partial progress survives a future interruption.

Scope: whole codebase (`src/arkeology/`, `tests/`), not a diff — per the
literal user request ("review the full code base"), consistent with prior
full-codebase reviews in this folder.

## Known false positive (do not re-flag)

Earlier parallel runs repeatedly flagged `except X, Y:` (no parentheses) in
`src/arkeology/clients/fakes/fake_bedrock.py:94`, `src/arkeology/tools/archive.py:72`,
`src/arkeology/tools/migrate_artifacts.py:351`, and
`src/arkeology/tools/write_artifacts.py:168` as Python-2-style syntax errors.
This is a false positive: `pyproject.toml` requires `python >=3.14`, and
[PEP 758](https://peps.python.org/pep-0758/) (shipped in 3.14) makes
unparenthesized multi-exception `except` clauses valid syntax, equivalent to
`except (X, Y):`. Confirmed directly: `uv run python -c "import ast; ast.parse(open('src/arkeology/tools/archive.py').read())"`
parses cleanly under the project's actual 3.14 interpreter. The earlier
SyntaxError reports came from checking with a system Python 3.12 interpreter,
which predates PEP 758. Not a real issue — do not fix, do not re-report.

## Angle Findings

### Angle A — line-by-line scan

**A-1 — `read_artifact` sources `commit_refs`/`references` from only the first vector key of a multi-section artifact, silently dropping link fields other tools see.**

`src/arkeology/tools/read.py:141-153` does:

```python
keys = await asyncio.to_thread(vectors.list_vectors_by_metadata, {"artifact_id": {"$eq": artifact_id}})
if keys:
    entries = await asyncio.to_thread(vectors.get_vectors, [keys[0]])
    ...
```

— it fetches only `keys[0]` and never touches the S3 annotation store (no import of
`arkeology.annotations`). But `src/arkeology/annotations.py:205-214`
(`_read_vector_link_fields`, used by `read_current_link_fields` — the helper
`archive.py`, `write.py`, and `link_metadata.py` all route through) documents
exactly this failure mode in its own docstring: *"Unions across ALL of the
artifact's section vectors, not just the first key returned by
`list_vectors_by_metadata` — a multi-section artifact indexes one vector per
section, and a link field ... may live on any one of them, not necessarily
whichever key happens to sort first."*

Failure scenario: a tier-2/3 artifact with multiple `##` sections (the common
case — each section gets its own vector per the write-path section pipeline)
where `commit_refs`/`references` were set via `link_metadata` on a section
vector that doesn't happen to sort first. `read_artifact` returns `[]` (or a
partial list) for `commit_refs`/`references` even though `archive_artifact`,
`propose_commit_links`, and `link_metadata` all correctly see the full set via
`read_current_link_fields`'s cross-vector union. Silent, no error — an agent
calling `read_artifact` gets a wrong (empty/incomplete) answer about an
artifact's linked commits/references.

Confidence: confirmed (verified directly against `read.py`, `annotations.py`,
and a grep confirming `read.py` never imports `arkeology.annotations`).

**[Verified 2026-08-13 — ✅ RESOLVED.** `read.py` now delegates to
`annotations.read_current_link_fields(s3, vectors, artifact_id)` for
`commit_refs`/`references` instead of reading `keys[0]`'s metadata directly,
matching `archive.py`'s established pattern. Fixed by `824534e` on
2026-08-13, alongside B-3 below (same root cause, `list.py`'s equivalent
gap), with new regression tests added to `tests/unit/test_tools_read.py`
covering the divergent-multi-vector-union case.]

No other candidates from this angle survived self-verification.

### Angle B — missing-guard / invariant auditor

**B-1 — `link_metadata` writes the S3 annotation durably, then writes vector metadata with no `check_metadata_budgets` re-validation — a metadata-size overflow permanently desyncs the annotation and vector stores.**

`src/arkeology/tools/link_metadata.py` (`_apply_link_metadata_with_cas`, called
around line 279, and the `vectors.put_vectors_batch(batch)` call at line 307)
never imports or calls `check_metadata_budgets` (`src/arkeology/artifact.py:180`).
Contrast `write.py`, which calls `check_metadata_budgets(encoded_s3_metadata,
vector_metadata)` (lines 405, 538) **before** any `put_object`/`put_vectors_batch`
call specifically so an over-budget write is rejected with a clean
`MetadataTooLargeError` → `validation_error` touching neither store.

Failure scenario: repeated `link_metadata` calls keep growing
`commit_refs`/`references` (each call unions supplied values into the existing
set — see the CAS read-forward-merge comment at line ~268). The S3 annotation
write (larger 2 KB S3 user-metadata budget) succeeds first and durably persists
the merged, now-oversized field. `vectors.put_vectors_batch` then either raises a
raw, unhandled boto3 `ValidationException` (not caught by any of `link_metadata`'s
specific `except` clauses — `KeyError`, `AnnotationUnavailableError`,
`ArtifactConflictError`, `CredentialError` — so it falls through to the generic
`_inner`/`except Exception` → `INTERNAL_ERROR` wrapper) or silently truncates,
while the S3 annotation copy has already durably committed the oversized value.
The annotation store and vector index are now permanently desynced for that
artifact — and per B-2 below, `reconcile_index`'s repair path has the identical
missing guard, so this is not self-healing.

Confidence: confirmed (verified `check_metadata_budgets`/`MetadataTooLargeError`
appear nowhere in `link_metadata.py`; verified the S3-annotation-write-then-vector-write
ordering; verified none of the file's `except` clauses would catch a raw
`ValidationException`).

**[2026-08-17 — ✅ RESOLVED.** Root-caused and designed in `adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal.md` (Accepted), which also folds in a real-AWS calibration finding (`commit_refs` cap of 20, see `docs/learnings.md`). `docs/specs/p12-t57-guard-coverage.md` (Phase 12 T57) threads `check_metadata_budgets` into `link_metadata.py`'s CAS loop before the annotation write — an oversize payload is now rejected up front instead of durably desyncing the annotation and vector stores. `docs/specs/p12-t58-commit-refs-cap-references-removal.md` (Phase 12 T58) closes the structural root cause: `references` is removed from vector metadata entirely (annotation-only), `commit_refs` in vector metadata is capped to the most-recently-appended 20 entries (annotation copy stays complete), so the list can no longer grow past what the budget tolerates. Both landed on `main`, `plan.md` T57/T58 now `✅`.]

**B-2 — `reconcile_index`'s own repair path (`_reindex_artifact`) has the same missing `check_metadata_budgets` guard, making an over-budget artifact un-reconcilable and stuck in an infinite failure-log replay loop.**

`src/arkeology/tools/reconcile.py` never imports `check_metadata_budgets`.
`_reindex_artifact` (lines ~60-155) assembles `vector_metadata` (including the
`read_current_link_fields`-merged `commit_refs`/`references` at line 94) and
calls `vectors.put_vector(...)` directly (lines 146, 160) with no budget
validation — unlike `write.py`, which validates the equivalent assembled
representation before every write.

Failure scenario: `reconcile_index` is the designated recovery mechanism for
both the failure-log replay (lines ~260-294) and the orphan scan. Per
`write.py`'s own Step 3c/4a comments, `check_metadata_budgets` exists
specifically to prevent "the deterministic partial-write / reconcile-replay
loop." Because `_reindex_artifact` skips it, an artifact whose merged metadata
exceeds the S3 Vectors filterable (2 KB) or total (40 KB) budget makes
`vectors.put_vector` raise a raw exception, caught by the surrounding
`except Exception as exc: failed.append(...)` (lines 264-267, 293-295) — which
means `resolved_ids` never gains that artifact_id, so the failure-log entry
survives the "retain only unresolved" rewrite (line 297) and is retried,
identically, on every future `reconcile_index` run. This is the exact
infinite-replay failure mode `check_metadata_budgets` was built to prevent
(per its own docstring), reintroduced on reconcile's own re-indexing path.

Confidence: confirmed (verified no `check_metadata_budgets` import/call in
`reconcile.py`; verified the `except Exception` → `failed` → retained-in-log
path).

**[2026-08-17 — ✅ RESOLVED.** Same ADR as B-1 (`adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal.md`, Accepted). `docs/specs/p12-t57-guard-coverage.md` (Phase 12 T57) threads `check_metadata_budgets` into `_reindex_artifact` before `vectors.put_vector`, so reconcile can no longer durably write an over-budget rebuild; `docs/specs/p12-t62-bounded-reconcile-retry.md` (Phase 12 T62) additionally caps the infinite-replay failure mode described here at `CAS_MAX_ATTEMPTS` (3) attempts, reporting stuck entries once in a new `stuck_failures` response field instead of retrying forever. Both landed on `main`, `plan.md` T57/T62 now `✅`.]

**B-3 — `list_artifacts` sources `commit_refs`/`references`/`tags`/`source_artifacts` from a single arbitrary (first-occurrence) vector per artifact, not the cross-store union `archive.py`/`write.py`/`link_metadata.py` use — same failure class as A-1, for the list/studio-browser path.**

`src/arkeology/tools/list.py:168-189` dedups `items` (one entry per section
vector) by `artifact_id` with first-occurrence-wins (`seen_ids`), then Step 6
(`list.py:209-214`) reads `commit_refs`/`references`/`tags`/`source_artifacts`
straight off that single vector's `meta`, never through
`annotations.read_current_link_fields`.

Failure scenario: under normal operation every section vector of an artifact
carries identical metadata (write.py reuses one `vector_metadata` dict across
all section vectors; `link_metadata`'s batch update touches all vector keys
uniformly), so this only diverges after a partial write/CAS race leaves one
section vector's metadata stale relative to the others — the same class of
race `write.py`'s CAS retry and `reconcile.py`'s failure-log replay exist to
handle. When it does diverge, `list_artifacts` (and the `arkeology_studio`
list view built on it) can display stale/missing `commit_refs`/`references`
for an artifact whose durable annotation copy or other section vectors already
hold the correct value.

Confidence: plausible (mechanism confirmed by reading the code; requires a
partial-write/race precondition to produce a user-visible divergence, so
marked lower-severity than A-1/B-1/B-2).

**[Verified 2026-08-13 — ✅ RESOLVED.** `list.py` now computes the
cross-scope-gated `commit_refs`/`references` union via
`annotations.read_current_link_fields` once per distinct `artifact_id`
(concurrency-bounded via `asyncio.gather`, mirroring `write.py`'s
`SECTION_CONCURRENCY` pattern) instead of reading a single arbitrary
vector's metadata. `tags`/`source_artifacts` were left untouched — they
are written identically across all section vectors in one batched write and
are outside adr-2026-07-03-annotation-backed-link-storage.md's dual-store model, so they cannot diverge the way
`commit_refs`/`references` can under a partial-write/CAS race. This
required making `s3` a required (not optional-unused) parameter of
`list_artifacts`/`arkeology_studio`, with ripple-through changes to
`studio.py`, `server.py`, and `resources.py`. Fixed by `824534e` on
2026-08-13, alongside A-1 above, with new regression tests added to
`tests/unit/test_tools_list.py` and `tests/unit/test_tools_studio.py`.]

### Angle C — cross-file contract tracer

**C-1 — `VectorDistanceMissingError` (a deliberate hard-fail meant to surface S3 Vectors index corruption) is swallowed by `_search_helper.py`'s blanket `except Exception:` and reported identically to an ordinary transient network blip.**

`src/arkeology/clients/vectors.py:163-166` raises `VectorDistanceMissingError`
specifically so a missing `distance` field is never silently treated as
perfect similarity ("must never be treated as perfect similarity — silently
breaks ranking — hard error", per its own comment and the exception's
docstring in `errors.py:240-247`: *"Raise instead of defaulting."*). But the
sole production caller, `run_search_loop` in
`src/arkeology/tools/_search_helper.py:231-245`, catches `CredentialError`
specifically and then falls through to a generic `except Exception:` that logs
a warning, sets `fetch_exhausted`, and returns whatever partial results were
already collected — the exact same handling as a transient boto3
throttle/timeout.

Failure scenario: it does not corrupt ranking (the raise already prevents the
result from being scored) but it does destroy observability — an operator or
caller of `search_artifacts`/`synthesise` cannot distinguish "fewer results
because of ordinary network flakiness" from "fewer results because the vector
index is returning malformed data missing `distance`, indicating deeper index
corruption," even though the exception exists precisely to make that second
case visible.

Confidence: confirmed.

**C-2 — `archive.py`'s partial-failure log entries store the still-percent-encoded title, while `write.py`'s equivalent entries store the plain decoded title — same failure log, inconsistent encoding per writer.**

`src/arkeology/tools/archive.py:78` (`_record_partial_archive_failure`) reads
`s3_meta.get("title", "")` where `s3_meta` comes directly from
`s3.head_object()` (`src/arkeology/clients/s3.py:127-138`), which returns raw
S3 user-metadata with no decoding applied. Non-ASCII values are percent-encoded
on write via `encode_metadata_value` (`artifact.py:102`) and must be reversed
with `decode_metadata_value` (`artifact.py:122`) to recover the original text —
`archive.py` never calls it here. `write.py`'s equivalent failure-log calls
(e.g. line 169) instead pass the plain, human-readable `title` function
parameter, never the encoded S3 value.

Failure scenario: an artifact titled e.g. "Café review" that fails partway
through `archive_artifact` gets a failure-log `"title"` of `"Caf%C3%A9 review"`;
the same title failing partway through `write_artifact` gets `"Café review"` —
in the same `.arkeology_failures.jsonl` file. Cosmetic only (replay logic keys
off `artifact_id`, not `title`), but an operator triaging the failure log sees
inconsistently garbled titles depending on which tool produced the entry.

Confidence: confirmed.

**C-3 — `S3ClientInterface`/`BedrockClientInterface` Protocol docstrings understate the exceptions their concrete implementations actually raise (documentation-contract drift, not a runtime bug).**

Several `Raises:` blocks in `src/arkeology/clients/interfaces.py` are
incomplete relative to the concrete `S3ClientImpl`/`BedrockClientImpl`:
- `put_object_annotation`/`get_object_annotation`/`list_object_annotations`/`delete_object_annotation`
  (interfaces.py:152, 169, 184, 210) document only `ArtifactConflictError`/`KeyError`/`CredentialError`,
  but `S3ClientImpl` (s3.py:200, 224, 245, 285) also raises
  `AnnotationUnavailableError` (adr-2026-07-03-annotation-backed-link-storage.md decision 5) from all four.
- `get_object`/`get_object_annotation` (interfaces.py:56, 159) omit
  `NonUtf8PayloadError`, which `S3ClientImpl` raises on `UnicodeDecodeError`
  (s3.py:120, 221).
- `BedrockClientInterface.embed`/`invoke_text_model` (interfaces.py:328)
  document only `CredentialError`, but `BedrockClientImpl._invoke`
  (bedrock.py:60-96) re-raises the raw `botocore.exceptions.ClientError`
  unchanged once its single transient-error retry is exhausted — AGENTS.md
  itself confirms this is intended ("persistent throttling surfaces error"),
  but the Protocol never says so.

Every current caller already imports and handles the undocumented exceptions
correctly (or relies on the tool-level blanket `except Exception` per the
`_inner` convention), so nothing is functionally broken today. Flagged because
`interfaces.py` is AGENTS.md's declared single source of truth for client
contracts — a reviewer or a future implementation written strictly against
the Protocol's documented `Raises:` sections would miss required exception
handling.

Confidence: confirmed (documentation-accuracy finding, not a functional bug —
lowest severity of this angle's findings).

### Angle D — Python/asyncio/boto3 pitfall specialist

**D-1 — Seven tool modules call synchronous boto3 S3/S3-Vectors client methods directly inside `async def` bodies with no `asyncio.to_thread`, blocking the single event loop — breaking an otherwise-consistent codebase convention.**

`read.py`, `list.py`, `search.py`, `synthesise.py`, `freshness.py`,
`reconcile.py`, and the Bedrock-embed calls in `write.py`/`migrate_artifacts.py`
all correctly route blocking boto3 calls through `asyncio.to_thread` (e.g.
`read.py:126,141,145`, explicitly commented "Off the event loop — blocking
boto3 calls"). The following do not, and call `s3.*`/`vectors.*` directly
(verified by grep — zero `asyncio.to_thread` occurrences in any of these
files):

- `src/arkeology/tools/write.py:445,502,543,639,807,874,911,914` — the primary write hot path (`_write_artifact_inner`).
- `src/arkeology/tools/purge.py:99,110,126,136,179,192,202` — per-artifact deletion loop, unbounded iteration count.
- `src/arkeology/tools/archive.py:149,167,172,240,260,265,335,337,345` — including the CAS retry loop (up to 3 attempts, each fetching full object content via `get_object`).
- `src/arkeology/tools/delete.py:101,118,125,133`.
- `src/arkeology/tools/link_metadata.py:87,90,253,261,307` — CAS retry loop, up to `CAS_MAX_ATTEMPTS` (3) synchronous round-trips per artifact_id.
- `src/arkeology/tools/propose_commit_links.py:99,104`.
- `src/arkeology/tools/migrate_artifacts.py:360` (`s3.head_object` inside a per-descriptor existence-check loop; note this file's Bedrock calls at line 254 are correctly offloaded).

(`health.py` has the same gap but is already a separately-tracked, documented
exception per `bedrock.py`'s own comment — not a new finding here.)

Failure scenario: any of these tools blocks the MCP server's single asyncio
event loop for the full network round-trip of each synchronous S3/S3-Vectors
call. Concretely: a `write_artifact` call (or `purge_archived` iterating many
artifacts, or an `archive`/`link_metadata` call retrying its CAS loop under
contention) stalls every other concurrently in-flight MCP request — e.g. a
`search_artifacts` or `health_check` call from a different agent/session —
until the blocking call returns. This is the same class of bug already
called out for `health.py` (an accepted, documented exception per
`bedrock.py`'s comment); the other seven files have no equivalent
documentation and appear to be an unintentional inconsistency rather than a
deliberate exception.

Confidence: confirmed (grepped every listed file directly; confirmed
`S3ClientImpl`/`VectorsClientImpl` are plain synchronous classes with no
async-offloading wrapper applied at injection in `__main__.py`/`server.py`,
so these calls genuinely run on the event-loop thread).

Ruled out by this angle after investigation (no bug found): mutable default
arguments (none present); `asyncio.gather`/`Semaphore` usage in
`write.py`/`write_artifacts.py`/`migrate_artifacts.py` (correctly released via
`async with`, `return_exceptions=True` with explicit post-gather inspection);
the Bedrock throttle-retry loop in `bedrock.py` (bounded, jittered, correctly
classified transient-vs-fatal); the annotation CAS retry bound
(`CAS_MAX_ATTEMPTS`, correct ETag re-read per attempt); S3/S3-Vectors
pagination (`list_vectors_by_metadata`'s `nextToken` loop is correct);
`datetime.now()` usage (always UTC-qualified); closure-captured loop
variables (loop variables are always passed as function parameters, never
captured by reference).

### Angle E — wrapper/delegation correctness

**E-1 — One of three `CredentialError` handlers in `write.py`'s overwrite CAS retry loop omits `artifact_id` from its response, unlike its two sibling handlers in the same loop iteration.**

`src/arkeology/tools/write.py:548` — `except CredentialError as exc: return
credential_error_response(exc)` (which returns only `{"error": ...,
"message": ...}`, per `tools/_errors.py:17-26`) — sits between two other
`CredentialError` handlers in the very same retry loop (lines 503-507 around
the `head_object` re-read, and 514-518 around `read_current_link_fields`)
that both return a bespoke dict adding `"artifact_id": s3_key`.

Failure scenario: credentials expiring in the narrow window between the
loop's `head_object`/`read_current_link_fields` calls and the immediately
following `s3.put_object` call (real on an `overwrite=True` write under CAS
contention) produces a response missing `artifact_id`, while the same
expiry occurring a few lines earlier/later in the identical loop iteration
includes it. `write_artifacts.py`'s batch path returns this dict verbatim
per descriptor, so a batch caller keying off `result["artifact_id"]` to
attribute a failure to a specific write hits a missing field for this one
code path only.

Confidence: confirmed.

**E-2 — `migrate_artifacts.py` builds its `CredentialError` response inline instead of calling the shared `credential_error_response()` helper every other tool module uses, and never imports it.**

`src/arkeology/tools/migrate_artifacts.py:364` —
`return _with_warning({"error": ErrorCode.CREDENTIAL_ERROR, "message": str(exc)})`
— constructs the dict by hand; the file has no `from arkeology.tools._errors
import credential_error_response` at all, unlike every other `tools/*.py`
module. `_errors.py`'s own docstring states the helper exists precisely "so
the many uniform call sites stay in sync automatically."

Failure scenario: no live bug today (the inline dict is currently identical
in shape), but this one call site is not wired into the single source of
truth — a future shape change to `credential_error_response` (e.g. adding a
field, per the pattern `write.py`'s bespoke handlers already show is
sometimes needed) will silently miss this site, and `migrate_artifacts.py`'s
credential-error responses will drift from every other tool's.

Confidence: confirmed.

**E-3 — `freshness.py` reimplements the cross-scope readability predicate inline instead of delegating to `_reference_filter.py`'s `resolve_readable_targets`, which its own comment cites as the pattern being mirrored.**

`src/arkeology/tools/freshness.py:129,167-174` hand-codes "own-scope always
readable; foreign-scope readable only if `tier == 3` and `visibility ==
"shared"`" — byte-for-byte the same rule `resolve_readable_targets`
(`_reference_filter.py:16-46`) implements and that `read_artifact`/
`list_artifacts` delegate to, per that function's docstring ("so the
readability rule is defined in exactly one place"). Note:
`resolve_readable_targets` returns only a `set[str]` of readable IDs, not
full metadata — `freshness.py` needs per-source `date`/`status`/`tier`
alongside the gate decision, so a direct call would require a second round
trip; the inline duplication may be a deliberate one-round-trip
optimisation rather than an oversight.

Failure scenario: none today (logic is currently equivalent). If the
cross-scope predicate in `resolve_readable_targets` is ever changed,
`freshness.py`'s copy won't receive the fix, and stale-synthesis detection
would silently apply a different (wrong) access rule than
`read_artifact`/`list_artifacts` for the same visibility check.

Confidence: plausible (real drift risk, but possibly an intentional
performance trade-off rather than a bug — flagging for a decision, not
asserting it's wrong as-is).

No other candidates from this angle survived self-verification (checked:
every public tool function's `_inner` delegation pattern is intact across
all of `tools/*.py`; `run_search_loop` is called identically by `search.py`
and `synthesise.py`; `write.py`/`reconcile.py` call
`prepare_sections_for_embedding` with equivalent arguments;
`FakeBedrockClient` structurally satisfies every method real callers use;
`wrap_credential_errors` is applied consistently in `s3.py`/`vectors.py`/`bedrock.py`
with no bypassing call site found).

### Angle F — reuse / DRY cleanup

**F-1 — The cross-scope readability predicate ("own-scope always readable; foreign-scope readable iff tier==3 and visibility=='shared'") is independently hand-rolled in four places instead of one.**

`_reference_filter.py`'s `resolve_readable_targets()` (lines 16-46) already
centralizes this exact three-clause condition for the `references`-field
filtering use case, but the artifact-level version of the same predicate is
separately reimplemented in `list.py:183-186`, `freshness.py:171-174`
(labeled E-3 above as mirroring this pattern), and the single-artifact form
in `read.py:112-119` (`int(meta["tier"]) != 3 or meta.get("visibility") !=
"shared"`).

Cost: this predicate is the entire cross-scope security gate — AGENTS.md:
"Never bypass cross-scope gate." Four independent copies means any future
tightening/loosening of the rule must be applied in four places to stay
consistent; missing one leaves that tool silently diverging on what it
considers cross-scope-readable. Recommend extracting the boolean predicate
itself (e.g. `is_cross_scope_readable(meta, artifact_id, own_scope,
read_prefixes) -> bool`) into a shared module, with `list.py`, `freshness.py`,
`read.py`, and `resolve_readable_targets` all calling it.

Confidence: confirmed (verified all four sites independently implement the
identical three-clause condition).

**[2026-08-19 — ✅ RESOLVED.** Extracted into `is_cross_scope_readable(meta, artifact_id, own_scope, read_prefixes)` in the new `src/arkeology/tools/_scope.py`, used consistently by `read.py`, `list.py`, `freshness.py`, and `_reference_filter.py::resolve_readable_targets`. Phase 12 T63, `plan.md` now `✅`; landed alongside I-3 in the same task.]

**F-2 — Hand-rolled boto3 `Error`/`Code` extraction repeated at 11 call sites across the client layer.**

`code = exc.response.get("Error", {}).get("Code", "")` appears verbatim in
`s3.py` (8×: lines 101, 122, 140, 203, 227, 248, 288, plus one more),
`vectors.py:47`, `bedrock.py:87`, and `credentials.py:104,111`. Cost: a
future botocore response-shape quirk (e.g. a missing `"Error"` key) must be
handled correctly in 11 places instead of one; a typo'd default in one copy
silently changes behavior for that call only. `credentials.py` is already
the shared client-error-classification module — recommend a single
`_error_code(exc: botocore.exceptions.ClientError) -> str` helper there.

Confidence: confirmed (grep count matches exactly: 11 occurrences).

**F-3 — The `list_vectors_by_metadata` → `get_vectors` two-step fetch idiom is hand-rolled independently at ~10 call sites, with inconsistent empty-`keys` short-circuit handling.**

The pattern appears in `purge.py` (3×), `delete.py:118`, `archive.py`
(167-172, 335-337), `link_metadata.py:253-261`, `propose_commit_links.py:99-104`,
`read.py:142-145`, `write.py:911`, `list.py:150-160`, `freshness.py` (84-99,
143-152, 239), and `reconcile.py:323` — alongside the already-shared copies
inside `_search_helper.py:344-347` and `_reference_filter.py:66-71`. Sites
already disagree on whether to short-circuit when `keys` is empty (e.g.
`purge.py` returns early; several others call `get_vectors` unconditionally).
Recommend a small `fetch_vectors_by_metadata(vectors, filter_expr, *,
include_data=False)` helper alongside the existing `_search_helper.py`/
`_reference_filter.py` module.

Confidence: confirmed.

**[2026-08-19 — ✅ RESOLVED.** Extracted into `fetch_vectors_by_metadata(vectors, filter_expr, *, include_data=False)` in `src/arkeology/tools/_search_helper.py`, used consistently across all ~10 call sites (`archive.py`, `list.py`, `purge.py`, `propose_commit_links.py`, `_reference_filter.py`, `freshness.py`, `find_referrers`), with the empty-`keys` short-circuit unified. Phase 12 T63, `plan.md` now `✅`. `write.py`'s one `list_vectors_by_metadata` call is list-then-*delete*, not list-then-get, so it's out of scope for this helper and was correctly left untouched.]

**F-4 — Artifact "summary" response dict is built field-by-field, byte-for-byte identically, in both `list.py` and `search.py`.**

`list.py:218-235` and `search.py:204-221` each construct the same ~14-key
literal dict from vector metadata. Cost: adding a new artifact metadata
field requires remembering to update both dict-literals; missing one
produces a field present in `list_artifacts` but silently absent from
`search_artifacts` (or vice versa). Recommend a shared
`build_artifact_summary(meta, artifact_id, tags_val, source_artifacts_val)`
with each caller layering its own extra keys on top.

Confidence: confirmed.

**F-5 — `top_k` validation-and-clamp logic duplicated between `search.py` and `synthesise.py`.**

Both `search.py:118-125,230-232` and `synthesise.py:95-101,209-211`
independently implement the identical `top_k <= 0` rejection message, the
`min(top_k, 100)` clamp, and the `clamped`/`effective_top_k` response
annotation. Recommend a shared `clamp_top_k()` helper, matching how
`_search_helper.py` already centralizes the analogous type/tier validation
for the same two tools.

Confidence: confirmed.

**F-6 — `last_edited_ulid` → `last_edited_at` ISO-timestamp derivation duplicated verbatim in `search.py` and `propose_commit_links.py`.**

`search.py:194-201` and `propose_commit_links.py:133-140` contain the
identical try/except-around-`ULID.from_str(...).datetime.isoformat()` block,
including the same warning message on malformed input. Minor by itself, but
a fix to the malformed-ULID handling (e.g. narrowing the `except Exception`)
must be made twice to stay in sync. Recommend extracting a one-line-call
`derive_last_edited_at()` helper near `coerce_list_field`.

Confidence: confirmed.

**F-7 — The CAS (compare-and-swap) retry loop skeleton is hand-rolled independently in `archive.py`, `link_metadata.py`, and `write.py`.**

Each implements its own `for attempt in range(CAS_MAX_ATTEMPTS): ... except
ArtifactConflictError: continue` cycle around a read-merge-write operation.
`CAS_MAX_ATTEMPTS` itself is already centralized in `annotations.py`, but the
loop control-flow is not. Loop *bodies* differ substantially (status flip +
annotation re-apply vs. annotation merge vs. content+metadata merge), so
full extraction may not be worth it yet — flagged for awareness; a fourth
CAS site appearing would be the trigger to extract a generic
`run_cas_retry(attempts, body_fn)`.

Confidence: plausible (real but lower-priority than F-1..F-6 given the
bodies genuinely differ).

No test-fixture duplication of note was found in `tests/unit/conftest.py`
(`_make_vectors_client`/`_make_settings` already properly factored).

### Angle G+H — simplification & efficiency

**G-1 — `write.py`: five duplicated "log partial-write, then return `CredentialError` dict" blocks.**

`write.py` already has `_record_partial_write()` (a shared helper for the
generic-`Exception`-after-S3-success case), but the structurally identical
`CredentialError`-after-S3-success case has no equivalent helper — it's
hand-rolled five times:

```python
_log_partial_write_failure(settings, artifact_id=s3_key, title=title, artifact_type=type,
                            tier=tier, date=date, failure_step="...", reason=str(exc))
return {"error": ErrorCode.CREDENTIAL_ERROR, "message": str(exc), "artifact_id": s3_key}
```

at `write.py:576-590`, `687-701`, `770-784`, `809-819`, `849-859`. A
`_record_partial_write_credential_error(settings, *, artifact_id, title, ...,
failure_step, exc)` helper (mirroring `_record_partial_write`) would
collapse all five call sites to one-liners.

Confidence: confirmed (all five sites verified).

**G-2 — `propose_commit_links.py` reimplements `coerce_list_field` instead of reusing it.**

`_search_helper.py:coerce_list_field()` is already the shared helper for
"vector metadata list-or-comma-string" coercion, used by `search.py`,
`list.py`, and `freshness.py`. `propose_commit_links.py:121-127`
reimplements the identical logic inline instead of importing it:

```python
raw_commit_refs = meta.get("commit_refs")
if isinstance(raw_commit_refs, list):
    commit_refs_val = raw_commit_refs
elif raw_commit_refs:
    commit_refs_val = [r for r in str(raw_commit_refs).split(",") if r]
else:
    commit_refs_val = []
```

This is exactly `coerce_list_field(meta, "commit_refs")`. One-line fix.

Confidence: confirmed.

**G-3 — `artifact_concurrency` clamp logic + constants duplicated verbatim across two files.**

`_ARTIFACT_CONCURRENCY_DEFAULT = 3` / `_ARTIFACT_CONCURRENCY_MAX = 15` and
the clamp-with-warning `if > MAX / elif < 1 / else` block (near-identical
warning text) are defined independently in `write_artifacts.py:51-52,128-148`
and `migrate_artifacts.py:75-76,209-224`. `migrate_artifacts.py` even
forwards its already-clamped `effective` value into `write_artifacts`, which
then re-derives/re-validates the same bound. A shared
`_clamp_concurrency(value, default, max_)` in a common module would remove
the duplicate constants and duplicate branching — the same pattern as the
`top_k` clamp duplication already flagged in F above (search.py/synthesise.py),
but a separate pair of files/constants.

Confidence: confirmed.

**H-1 — Sequential per-artifact processing where independent items could run concurrently.**

`write_artifacts.py` is the only tool that processes a batch of independent
artifacts with bounded concurrency (`asyncio.Semaphore` + `asyncio.gather`).
Every other multi-item tool loop processes items strictly one-at-a-time via
blocking round trips in a plain `for` loop, despite the operations being
logically independent per artifact:

- `reconcile.py` — failure-log replay loop (`249-298`), orphan-scan loop
  (`340-366`), and dangling-vector-prune loop (`379-404`) each
  `await asyncio.to_thread(...)` sequentially per artifact.
- `link_metadata.py:244-357` — loops `artifact_ids` one at a time, each
  doing several blocking S3/vector calls.
- `purge.py:175-209` — deletes `all_to_delete` one artifact at a time.
- `freshness.py:229-296` — malformed-synthesis deletion loop, one artifact
  at a time.
- `migrate_artifacts.py:332-374` — Step 5 skip-existing check calls
  `s3.head_object` per descriptor sequentially.

A bounded-concurrency helper matching `write_artifacts.py`'s pattern
(semaphore-gated `asyncio.gather`) applied to these loops would cut
wall-clock time roughly by the concurrency factor for any non-trivial batch,
at no correctness cost (each item's outcome is already independent/isolated
in these tools).

Confidence: plausible (mechanism confirmed at all cited line ranges; actual
wall-clock benefit depends on typical batch sizes in production usage, which
wasn't measured).

**[2026-08-19 — ✅ RESOLVED.** `write_artifacts.py`'s `asyncio.Semaphore` + `asyncio.gather` pattern applied to `purge.py`, `freshness.py`, `migrate_artifacts.py` (Step 5), `reconcile.py` (all three phases), and `link_metadata.py`'s main loop. Phase 12 T63, `plan.md` now `✅`. Reviewed accepted trade-off, documented inline at each site: converting an abort-on-first-`CredentialError` sequential loop to bounded concurrency means the abort no longer stops at a deterministic prefix — low-risk, since the credential-error response never reported partial progress in either version and every completed item stays individually correct. `reconcile.py`'s call sites here are T62's already-restructured Phase 1/2/3 loops, not this finding's original (pre-T62) line ranges.]

**H-2 — `reconcile.py`: duplicated fetch-and-reindex sequence between Phase 1 and Phase 2.**

Phase 1 (`reconcile.py:270-292`) and Phase 2 (`340-362`) both do:
`get_object` → `_reindex_artifact` → append `{"artifact_id", "title",
"sections_indexed", "source"}` to `reconciled`, differing only in whether
`head_object` was already fetched and the `source` label (`"failure_log"`
vs. `"orphan_scan"`). Worth factoring into one
`_fetch_and_reindex(artifact_id, raw_meta, source, ...)` helper.

Confidence: confirmed.

**[2026-08-19 — ✅ RESOLVED.** Factored into a shared `_fetch_and_reindex(artifact_id, raw_meta, source, ...)` helper exactly as recommended, in Phase 12 T62 (`docs/specs/p12-t62-bounded-reconcile-retry.md`), commit `8be95b8`. Already reflected in B-2's resolved note and the aggregate cleanup-backlog count above — this entry was missing its own inline marker.]

**H-3 — `delete_artifact`: two independent vector-index lookups run sequentially.**

`delete.py` — Step 4 `find_referrers(...)` (`112`) and Step 5
`vectors.list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}})`
(`118`) are independent read-only queries against the vector index (neither
depends on the other's result), yet run one after another. They could be
issued concurrently (`asyncio.gather`), saving one round trip of latency on
every delete call.

Confidence: confirmed.

### Angle I — altitude (right-depth fixes)

**I-1 — The `description` field's 280-character maximum is a bare literal duplicated in two places with no shared constant, unlike `title`'s equivalent limit.**

`artifact.py:519-520` (`Artifact.validate_description`) hardcodes `if len(v)
> 280: raise ValueError(...)`. `migrate_artifacts.py:74` independently
defines `_MAX_DESCRIPTION_LENGTH = 280` and uses it to clip Nova-Lite-generated
descriptions before they are ever validated by the `Artifact` model. The
codebase already has the correct pattern for this exact situation one field
over: `TITLE_MAX_LENGTH = 256` (`artifact.py:67`) is a named module constant
`validate_title` references (`artifact.py:527-528`) — `description`'s limit
never got the same treatment, even though it is the one length limit
actually consumed by a second module.

Cost: the two `280`s are currently in sync by coincidence, not by
construction. If `Artifact.validate_description`'s threshold is ever tuned,
`migrate_artifacts.py`'s clip constant silently goes stale — Nova Lite
output gets clipped to a length that no longer matches what the `Artifact`
model actually accepts, producing confusing `validation_error` failures for
entries `migrate_artifacts` itself believed it had already made safe. Fix:
promote a `DESCRIPTION_MAX_LENGTH` constant next to `TITLE_MAX_LENGTH` in
`artifact.py`; have `migrate_artifacts.py` import it instead of
re-declaring `280`.

Confidence: confirmed.

**I-2 — `propose_commit_links.py` sources `commit_refs` from a single, first-occurrence-wins vector per artifact — a third independent instance of the "first-vector-only" bug class already flagged (and partly fixed) for `read.py` and `list.py`.**

`propose_commit_links.py:109-125` dedups `items` by `artifact_id` with
`seen_ids` first-occurrence-wins, then reads `commit_refs` directly off
that one vector's `meta` to decide whether the artifact is eligible for
proposal — it never calls `annotations.read_current_link_fields`, the
helper `annotations.py:205-214` documents as necessary precisely because "a
link field... may live on any one of [a multi-section artifact's
vectors], not necessarily whichever key happens to sort first."
`archive.py`, `write.py`, and `link_metadata.py` all correctly route
through that shared cross-vector union; `read.py` and `list.py` were just
fixed to do the same in commit `824534e` (see A-1/B-3 above) — this is the
same class of bug, present a third time, in a fourth tool, still open.

Failure scenario: a multi-section artifact whose `commit_refs` were set
(via `link_metadata`) on a section vector other than the one that sorts
first is silently re-proposed by `propose_commit_links` as "not yet
linked," even though it already carries `commit_refs` everywhere else in
the system — the inverse symptom of A-1 (over-proposal vs. dropped-field),
same root cause. Given `read.py` and `list.py` were just fixed for exactly
this reason, `propose_commit_links.py` is the natural next call site for
the same `read_current_link_fields` fix.

Confidence: confirmed.

**[2026-08-19 — ✅ RESOLVED.** `propose_commit_links.py` now sources each candidate's `commit_refs` via `annotations.read_current_link_fields` (the same union-of-both-stores helper `read.py`/`list.py` use), concurrently across candidates via `asyncio.gather`/`asyncio.to_thread`. Folded into Phase 12 T58 (`docs/specs/p12-t58-commit-refs-cap-references-removal.md`), since T58's `commit_refs` vector-metadata cap would otherwise have silently worsened this exact bug. `plan.md` T58 now `✅`.]

**I-3 — The mandatory `artifact_id.startswith(scope + "/")` scope check has no shared function; it is manually re-typed at ten-plus call sites across eight tool modules, with no structural guard against a future omitted `"/"`.**

`delete.py:90`, `read.py:82,84`, `list.py:184,188`, `archive.py:138`,
`link_metadata.py:246`, `purge.py:117`, `freshness.py:167,171,230`,
`reconcile.py:253`, and `_reference_filter.py:56,78` each independently
write `artifact_id.startswith(<scope> + "/")` (or the `own_scope + "/"` /
`p + "/"` variant). All sites are correct today — but AGENTS.md itself
calls this out as the single highest-friction correctness rule in the
codebase: *"Scope check always uses `artifact_id.startswith(scope + "/")`
— never bare `startswith(scope)`... Every scope guard in every tool uses
`scope + "/"` form; do not abbreviate it."* That warning exists precisely
because the mistake is easy to make, and there is currently no function
whose signature makes it structurally impossible — the invariant lives
only in the discipline of a dozen separate call sites remembering to
append `"/"` correctly, not inside a single `is_own_scope(artifact_id,
scope) -> bool` helper.

Cost: the next call site is one dropped `+ "/"` away from reopening exactly
the cross-scope false-prefix-match hole AGENTS.md dedicates a paragraph to
(`"team-a"` incorrectly matching `"team-abc/..."`), and nothing in the type
system, tests, or code structure would catch it before the mistake reaches
a scope-security decision.

Confidence: plausible (real gap, but no current call site is actually
wrong — the cost is entirely about the next one).

**[2026-08-19 — ✅ RESOLVED.** Extracted into `is_own_scope(artifact_id, scope) -> bool` in the new `src/arkeology/tools/_scope.py`, used consistently across `delete.py`, `read.py`, `list.py`, `archive.py`, `link_metadata.py`, `purge.py`, `reconcile.py`, `freshness.py`, and `_reference_filter.py`. New tests (`tests/unit/test_tools__scope.py`) explicitly pin the exact false-prefix-match case this finding names (`"team-a"` vs `"team-abc/..."`). Phase 12 T63, `plan.md` now `✅`; landed alongside F-1 in the same task.]

**I-4 — `link_metadata.py` reimplements `Artifact.validate_commit_refs`/`validate_references`'s per-element constraint by hand instead of calling it, and the reimplementation has already drifted from the real rule: it never checks for control characters.**

`link_metadata.py:112-131` (`_validate_supplied_link_values`) checks each
supplied `commit_refs`/`references` element for (a) empty/whitespace-only
and (b) containing a comma, and its own docstring claims this is "matching
the same per-element constraints `Artifact.validate_commit_refs` /
`validate_references` enforce on write." But the real constraints, at
`artifact.py:555-567`, are `_require_no_control_chars` +
`_require_no_comma` — control characters, not emptiness. The two checks
are not the same rule: `link_metadata.py`'s version rejects empty strings
the `Artifact` model would silently accept, and — the real gap — never
rejects control characters, which the `Artifact` model rejects on every
other write path (`title`, `description`, `author_role`, `tags`, and
`commit_refs`/`references` themselves when set via `write_artifact`).

Failure scenario: a caller supplies a `commit_refs`/`references` element
containing a control character via `link_metadata`.
`_validate_supplied_link_values` passes it through (no control-char
check), it gets merged via `_merge_link_field` and durably written via the
S3 annotation and `vectors.put_vectors_batch` — bypassing `Artifact`'s
control-char invariant entirely, because `link_metadata.py` never
constructs an `Artifact` instance for the merged result. Nothing
downstream re-validates it either: `write.py`'s overwrite CAS loop reads
the value forward via `read_current_link_fields` and merges it into
`final_commit_refs` without re-running `Artifact` validation on the
existing (read-forward) component — only the newly-supplied `refs` for
that call go through `Artifact(...)` construction. `reconcile.py`'s
`_reindex_artifact` likewise reads and re-writes the value raw. The
control-character invariant `artifact.py:139-142`'s own docstring treats
as unconditional ("a mistake or injection... reject, not strip") has
exactly one bypass door, and it exists because the gate was hand-copied
instead of shared.

Confidence: confirmed (verified `_validate_supplied_link_values`'s two
checks against `Artifact.validate_commit_refs`/`validate_references`'s
actual two checks directly — they diverge on both ends: one check each is
present that the other lacks).

**[2026-08-19 — ✅ RESOLVED.** `_validate_supplied_link_values` now delegates the control-character and comma checks to `Artifact.validate_commit_refs`/`validate_references` directly instead of a hand-rolled parallel implementation. Folded into Phase 12 T57 (`docs/specs/p12-t57-guard-coverage.md`), which was already reopening `link_metadata.py`'s per-attempt validation dispatch for the guard-coverage fix. `plan.md` T57 now `✅`.]

**I-5 — Root cause of F-1 above: `_reference_filter.py` only exposes the set-returning form of the cross-scope readability predicate (`resolve_readable_targets(candidate_ids) -> set[str]`), not a single-artifact boolean form — so every new single-artifact caller is structurally forced to reimplement the three clauses inline rather than call a shared function.**

This is the mechanism-level reason F-1's four-way duplication recurs:
`resolve_readable_targets` was built for filtering a `references` list and
cannot be called for one artifact ID without paying for a batched vector
round trip it doesn't need. A single-artifact gate check (`read.py`) or a
per-item filter (`list.py`, `freshness.py`) has no boolean function to
call, so each one reimplements the three clauses inline — not out of
carelessness, but because the module surface only offers one shape.

Cost beyond F-1's already-flagged drift risk: the next tool needing "is
this one artifact readable from here" will, by construction of the
current module surface, add a fifth hand-rolled copy rather than a call
site. Fix: add `is_cross_scope_readable(meta, artifact_id, own_scope,
read_prefixes) -> bool` alongside the existing set-returning helper in
`_reference_filter.py`, so `resolve_readable_targets` itself can be
rewritten in terms of it too.

Confidence: plausible (correctly identifies why F-1 recurs, but is a
design-surface argument rather than a new observed bug).

**[2026-08-19 — ✅ RESOLVED.** `is_cross_scope_readable(meta, artifact_id, own_scope, read_prefixes) -> bool` added to the new `src/arkeology/tools/_scope.py`, exactly as recommended; `_reference_filter.py::resolve_readable_targets` now composes it internally rather than duplicating the three clauses. Phase 12 T63 (same fix as F-1), `plan.md` now `✅`.]

**I-6 — `migrate_artifacts.py`'s skip-existing pre-check builds a candidate S3 key from a hand-built `file_extension` without the same `"."`-prefix validation `write.py` enforces, so the two paths can silently probe different keys for the same descriptor.**

`migrate_artifacts.py:357` builds `ext = str(descriptor.get("file_extension")
or ".md")` and probes `s3.head_object(candidate_key)` with no check that
`ext` starts with `"."` — unlike `write.py:316-321`, where an `ext` not
starting with `"."` is explicitly rejected with `validation_error` before
any key is built, specifically (per its own comment) "so the bulk
write_artifacts path... cannot produce a malformed S3 key (e.g.
`...-titletxt`)."

Failure scenario: a descriptor supplies a malformed `file_extension` (e.g.
`"txt"` instead of `".txt"`). The skip-existing pre-check silently probes
a key like `{prefix}/{slug}txt` (which will essentially never already
exist) rather than surfacing the malformed input, always routes that
descriptor to `to_write_indices`, and only the eventual `write_artifacts` →
`write.py` delegation applies the real validation and rejects it. No data
corruption (the final write still rejects it correctly), but the
"`file_extension` must start with `.`" invariant is enforced in only one
of the two places that construct a key from it — the existence pre-check
spends a `head_object` round trip probing a key the write path itself
would refuse to construct.

Confidence: confirmed.

### Angle J — CLAUDE.md / AGENTS.md conventions

Exhaustive grepping across `src/arkeology/` for AGENTS.md's explicit rules
(bare `print()`, `startswith(scope)` without `+ "/"`, bare `filter=`
shadowing, `uuid`/random key generation, `ABC`/`abstractmethod` on client
code, duplicated `ARTIFACT_TYPES`, content stored in vector metadata,
foreign-scope leakage in delete-synthesis warnings) found no violations —
every one of those rules is followed correctly everywhere in the codebase.
This angle instead surfaced two novel correctness bugs while reading the
code under those rules; recorded here since they weren't found by any
other angle.

**J-1 — `reconcile_index` cannot actually collect the "leftover orphan vectors" that `write_artifact`'s Step 8 comment promises it will.**

`write.py:906-908` documents Step 8's failure mode as recoverable: *"Log and
proceed; `reconcile_index` can collect any leftover orphan vectors later."*
But the promise doesn't hold — the `except Exception:` block at
`write.py:915-922` only does `logger.warning(...)`; it never calls
`_record_partial_write`/`_log_partial_write_failure`, so no failure-log
entry is written. `reconcile.py`'s three repair mechanisms — Phase 1
failure-log replay (`44-163`, only replays entries present in
`.arkeology_failures.jsonl`), Phase 2 orphan scan (`312-338`, finds S3 keys
missing from the vector index, not stale extra vectors), and the
dangling-vector prune (`368-404`, prunes vectors whose S3 object no longer
exists) — none of the three is a scan for "an existing artifact's vector
index has stale pre-overwrite section vectors alongside the current ones."

Failure scenario: an `overwrite=True` write on an existing multi-section
artifact where the new section vectors are written successfully but Step
8's `vectors.delete_vectors(orphan_keys)` call transiently fails (e.g. a
brief credential hiccup). The stale section vectors from the prior version
are now permanently un-collectible by any documented recovery path —
`reconcile_index` silently does nothing for them — contradicting the code
comment's explicit claim, and permanently polluting search results for that
artifact with duplicate/stale section content.

Confidence: confirmed (verified all three `reconcile.py` phases plus the
`write.py:915-922` except block directly).

**J-2 — `check_synthesis_freshness(confirm=True)` can report `all_fresh: True` while a malformed synthesis artifact still exists, undeleted.**

`freshness.py:294` unconditionally sets `malformed_reported = []` after the
`confirm=True` deletion loop, regardless of whether any individual
deletion actually failed (tracked separately in `delete_failed`, appended
to at `248`, `262`, `287`). `all_fresh` (`309-311`) only inspects
`malformed_reported`, never `delete_failed` — the two lists are
verifiably disjoint by construction.

Failure scenario: `check_synthesis_freshness(confirm=True)` runs against a
malformed synthesis whose vector deletion succeeds but whose S3
`delete_object` call fails (e.g. transient S3 error at `freshness.py:280`)
— the artifact is appended to `delete_failed`, `continue`d past, and never
added to `deleted`. The response still reports `"malformed": []` and
`"all_fresh": true`, even though the malformed synthesis artifact is still
present in S3 (now vector-orphaned but not deleted). A caller that gates
follow-up logic on `all_fresh` gets a false "all clean" signal; the only
way to notice the leftover artifact is to separately inspect
`delete_failed`, which nothing in the tool's contract requires callers to
check when `all_fresh` is already `True`.

Confidence: confirmed (verified `delete_failed` and `malformed_reported`
are disjoint accumulator lists and `all_fresh`'s boolean expression omits
`delete_failed` entirely).

## Summary

32 findings across 10 angles: 26 confirmed directly against source, 6
plausible (real mechanism, lower-certainty impact or partly-intentional
tradeoff — B-3 was confirmed-mechanism/plausible-impact before it was
fixed). 2 findings (A-1, B-3) were fixed mid-review by commit `824534e`
and are marked resolved in place above; the remaining 30 are open.

**Highest-severity open findings (data integrity / silent-corruption class):**

- **B-1 / B-2** — missing `check_metadata_budgets` guard on the
  `link_metadata` and `reconcile_index` write paths can permanently desync
  the S3-annotation and vector stores for an artifact, with no self-healing
  path (B-2 made B-1 non-recoverable). *Resolved — guard coverage (T57),
  bounded reconcile retry (T62), and the split-store/cap structural fix
  (T58) are all done, see the inline notes above.*
- **I-4** — `link_metadata.py`'s hand-rolled validation omits the
  control-character check `Artifact` enforces everywhere else, giving
  `commit_refs`/`references` exactly one bypass door for an invariant the
  model treats as unconditional. *Resolved by T57 — `link_metadata.py` now
  delegates to `Artifact.validate_commit_refs`/`validate_references`
  directly instead of a hand-rolled parallel check.*
- **J-1** — `write_artifact`'s Step 8 orphan-cleanup failure path doesn't
  write a failure-log entry, so `reconcile_index` can never actually
  recover the "leftover orphan vectors" the code comment promises it will.
- **J-2** — `check_synthesis_freshness(confirm=True)` can report
  `all_fresh: True` while a malformed synthesis artifact is still
  undeleted, because `delete_failed` isn't consulted by the `all_fresh`
  calculation.
- **C-1** — `VectorDistanceMissingError`, a deliberate hard-fail for index
  corruption, is swallowed by the same blanket `except Exception:` used for
  ordinary transient network errors — corruption and transient blips become
  indistinguishable to the caller.
- **I-2** (+ **A-1**/**B-3**, now fixed) — the "first-vector-only"
  `commit_refs`/`references` sourcing bug class, still open in
  `propose_commit_links.py` after being fixed in `read.py`/`list.py`.
  *Resolved by T58 — `propose_commit_links.py` now sources `commit_refs`
  via `read_current_link_fields`, the same union-of-both-stores helper
  `read.py`/`list.py` use.*

**Convention/architecture findings worth acting on even though no live bug exists today:**

- **F-1 / I-5** — the cross-scope readability predicate is hand-rolled in
  four+ places with no shared boolean function to call, and AGENTS.md
  explicitly calls this predicate the entire cross-scope security gate.
  *Resolved by T63 — see inline notes above.*
- **I-3** — the `startswith(scope + "/")` scope-check pattern that AGENTS.md
  dedicates a paragraph to has no shared function either; correct today at
  every site, one dropped `"/"` away from reopening a security hole at the
  next site. *Resolved by T63 — see inline note above.*
- **D-1** — 7 tool modules skip `asyncio.to_thread` around blocking boto3
  calls, contradicting an otherwise-consistent codebase convention.

**Cleanup backlog (F, G, H — reuse/simplification/efficiency):** originally
13 findings, mostly small hand-rolled duplications of existing shared
helpers (`coerce_list_field`, `credential_error_response`, the boto3
`Error`/`Code` extraction idiom, the `list_vectors_by_metadata` →
`get_vectors` idiom, `top_k` clamping, artifact-summary dict construction,
CAS retry skeletons) plus one concrete efficiency win applicable in five
files (H-1: bounded-concurrency batch processing, already proven out in
`write_artifacts.py`). **F-1, F-3, H-1, and H-2 are now resolved (Phase 12
T62/T63)** — see the inline notes above; **9 remain open** (F-2, F-4
through F-7, G-1 through G-3, H-3), none describing currently-broken
behavior.

No violations of AGENTS.md's explicit, checkable rules (stdout printing,
bare `startswith(scope)`, `filter=` shadowing, UUID/random keys,
`ABC`/`abstractmethod` on client code, `ARTIFACT_TYPES` duplication,
content in vector metadata, foreign-scope leakage in delete warnings) were
found anywhere in `src/arkeology/` — Angle J's exhaustive grep-based sweep
came back clean on all of them.

