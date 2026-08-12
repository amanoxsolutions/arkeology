---
type: spec
title: T55 — Write-Path Metadata Size + Charset Validation
description: Validate metadata size budgets (S3 user-metadata aggregate, vector filterable, vector total) and neutralise control characters BEFORE any storage write, so an oversize or malformed write fails fast with a structured error and never produces a partial write that reconcile replays. Bound title length in the model and preserve non-ASCII titles losslessly so read_artifact and search_artifacts always agree.
tags: []
timestamp: 2026-07-03T00:00:00Z
okf_version: "0.1"
feature: p12-t55-metadata-validation
status: ready
phase: 12
task: 55
references:
  - docs/planning-artifacts/prd.md
  - docs/planning-artifacts/plan.md
  - docs/architecture-decisions/adr-2026-07-03-annotation-backed-link-storage.md
  - docs/specs/p12-t46-references-field.md
  - docs/specs/p12-t47-annotation-dual-write.md
authored:
  by: "architect"
  date: "2026-07-03"
revised:
  by: "tech-writer"
  date: "2026-08-12"
---

# T55 — Write-Path Metadata Size + Charset Validation

<!-- SCOPE BLOCK — frozen after approval -->

## TL;DR

Before any S3 or vector write, the write path validates the artifact's
metadata against three byte budgets (S3 user-metadata aggregate; vector filterable; vector total)
and rejects control characters, failing fast with a structured `validation_error` so no partial
write and no self-perpetuating failure-log replay is ever created. It also bounds `title` length in
the `Artifact` model and stores non-ASCII titles losslessly so `read_artifact` and `search_artifacts`
report the identical title. Serves every agent that writes artifacts; nothing durable can be trusted
until oversize/malformed writes fail cleanly. (FR-59, AC-67.)

## Problem Statement

`write_artifact` assembles S3 user-defined object metadata (transmitted as HTTP headers) and vector
metadata, then writes S3 **first** and vectors second. Three defects live in that path:
(1) no pre-write size check — an oversize `title`/`description`/comma-joined list overflows S3's 2 KB
user-metadata cap or S3 Vectors' 2 KB filterable-metadata cap and fails *after* the S3 put, leaving a
deterministic partial write that `reconcile_index` and the failure log replay into the same failure
forever; (2) a control character (e.g. a `\n` in the title) reaches urllib3 as a raw `ValueError`
that escapes the tool; (3) a non-Latin title is NFKD-stripped to `""` in S3 metadata
(`s3.py:24-40`) while vector metadata keeps the real UTF-8 title, so `read_artifact` and
`search_artifacts` return different titles for the same artifact. This lands before/with T46 (adds
`references` to the filterable vector payload) and T47 (moves `commit_refs`/`references` off S3
user-metadata to annotations) because those tasks enlarge exactly the payload this guard measures.

## User Stories

### Story 1 — Oversize metadata rejected before any write (P1)

**Acceptance criteria:**
- Given an artifact whose assembled S3 user-metadata exceeds the S3 aggregate budget, when
  `write_artifact` is called then it returns a structured `validation_error` naming the offending
  budget AND performs no `put_object`, no `put_vectors_batch`, and appends no failure-log entry. (AC-67)
- Given an artifact whose filterable vector metadata exceeds the 2 KB filterable budget (e.g. many
  long `references`/`commit_refs`/`tags`), when written then it is rejected before any write with a
  `validation_error` — no partial write, no reconcile-replay loop is created.
- Given an artifact whose total vector metadata exceeds the 40 KB total budget, when written then it
  is rejected before any write.
- Given a rejected write, when `reconcile_index` later runs, then there is nothing to replay (no S3
  object and no failure-log entry were ever created).

### Story 5 — Budget re-check after the T47 overwrite read-forward merge (P1)

**Added 2026-07-04 (tech-writer).** T47 (`write_artifact`) read-forwards a
tier-3 overwrite's existing `commit_refs` / `references` (union of both durable stores) and
merges them into `vector_metadata` **after** this task's pre-write budget check has already run
against the values supplied to the current call. That merge can enlarge `vector_metadata` beyond
what Story 1's check measured.

**Acceptance criteria:**
- Given a tier-3 overwrite whose supplied `commit_refs`/`references` alone pass the pre-write budget
  check, but whose merge with the read-forwarded union pushes the vector filterable or total budget
  over its limit, when `write_artifact` runs then `check_metadata_budgets` is called a **second
  time** — after the merge, before any `put_object` / `put_vectors_batch` — and the write is rejected
  with a `validation_error`, with no write and no failure-log entry, identical to a Story 1 rejection.
- Given a merge that stays within all three budgets, then the second check passes silently and the
  write proceeds normally.

> **Note (2026-07-06, shipped in `7a697dd`).** `references` now **replaces** rather than merges on
> an overwriting write (see `docs/specs/p12-t46-references-field.md`'s forward-pointer note); only
> `commit_refs` still read-forwards and unions. This narrows, but does not remove, the reason for
> the second check above: `references`'s contribution to `vector_metadata` after the write-path's
> "merge" step is now exactly the value already measured by Story 1's check (a replace cannot grow
> it further), so `commit_refs`'s union-growth is the only remaining way the enlarged
> `vector_metadata` can newly breach a budget between the two checks. The second check must still
> run — re-running it against the full `vector_metadata` (both fields) after the write path computes
> the final value for each is simpler and no less correct than special-casing which field changed.

### Story 2 — Control characters neutralised (P1)

**Acceptance criteria:**
- Given a `title`, `description`, `author_role`, or any `tags`/`source_artifacts`/`references`/
  `commit_refs` element containing a control character (e.g. `\n`, `\t`, `\r`, `\x00`, DEL), when the
  artifact is constructed or written then a structured `validation_error` is returned naming the
  field — never a raw urllib3 `ValueError` or any uncaught exception. (AC-67)

### Story 3 — Title length bounded (P1)

**Acceptance criteria:**
- Given a `title` longer than the model bound, when the `Artifact` is constructed then a clear
  validation error is raised stating the bound and the actual length. (AC-67)
- Given a title at or below the bound, when constructed then no error is raised.

### Story 4 — Non-ASCII title consistency (P1)

**Acceptance criteria:**
- Given an artifact with a non-Latin title (e.g. Japanese, Cyrillic, Arabic), when it is read via
  `read_artifact` and found via `search_artifacts`, then both return the identical original title —
  no silent ASCII-stripping to `""`. (AC-67)
- Given the same artifact, when `reconcile_index` rebuilds its vector metadata from the S3 object,
  then the restored title is still the identical original title (the S3-metadata copy is lossless).
- Given the non-ASCII title, then the generated `artifact_id` is byte-for-byte unchanged from today
  (ADR-005 hash/slug scheme untouched).

## Requirements

- WHEN the `Artifact` model is constructed THE SYSTEM SHALL reject a `title` longer than
  `TITLE_MAX_LENGTH` with a `ValueError` stating the bound and the actual length.
- WHEN the `Artifact` model is constructed THE SYSTEM SHALL reject any string value bound for metadata
  (`title`, `description`, `author_role`, and every element of `tags`, `source_artifacts`,
  `references`, `commit_refs`) that contains a control character (Unicode category `Cc`, i.e. code
  points U+0000–U+001F and U+007F–U+009F) with a `ValueError` naming the field.
- WHEN `write_artifact` has assembled the S3 user-metadata dict and the filterable-and-total vector
  metadata dict, and BEFORE issuing `head_object`/`put_object`/`put_vectors_batch` or appending any
  failure-log entry, THE SYSTEM SHALL validate all three budgets against the **actual serialized
  representations about to be written** and, on any breach, return a structured `validation_error`
  (via the standard `_inner` try/except) and issue no storage write and no failure-log append.
- WHEN a tier-3 overwriting write's T47 read-forward merges the union-of-both-stores `commit_refs`
  (and, historically, `references`) into `vector_metadata`, enlarging it beyond what was measured
  above, THE SYSTEM SHALL re-run this same budget check against the enlarged `vector_metadata`
  **after the merge and before** any `put_object` / `put_vectors_batch`, and reject on breach with
  the same `validation_error` behaviour — no write, no failure-log entry. (`references` no longer
  read-forwards or merges as of the 2026-07-06 replace-semantics decision — see the note under
  Story 5 above — so only `commit_refs` can enlarge `vector_metadata` beyond the initial
  measurement; the re-check still runs against the full dict for both fields.)
- WHEN computing the S3 aggregate size THE SYSTEM SHALL sum, over the actual s3_metadata dict, the
  UTF-8 byte length of each key plus each (transport-encoded) value, and reject if it exceeds
  `S3_USER_METADATA_MAX_BYTES`.
- WHEN computing the vector filterable size THE SYSTEM SHALL measure only the vector-metadata keys NOT
  listed in `NON_FILTERABLE_METADATA_KEYS`, and reject if the UTF-8 byte length of their JSON
  serialization exceeds `VECTOR_FILTERABLE_METADATA_MAX_BYTES`.
- WHEN computing the vector total size THE SYSTEM SHALL measure the full vector-metadata dict
  (filterable + non-filterable) and reject if its JSON serialization exceeds
  `VECTOR_TOTAL_METADATA_MAX_BYTES`.
- WHEN a metadata value contains non-ASCII characters THE SYSTEM SHALL encode it losslessly and
  reversibly for the S3 user-metadata copy (replacing the lossy NFKD-ASCII-strip in
  `_ascii_safe_metadata`) and SHALL decode it symmetrically wherever the S3-metadata title is read
  back (the `read_artifact` fallback path and `reconcile_index` rebuild), while vector metadata
  continues to hold the raw UTF-8 title.
- WHEN `read_artifact` and `search_artifacts` return a title THE SYSTEM SHALL source it from the same
  charset-safe representation so the two never disagree.
- WHEN the metadata payload is validated THE SYSTEM SHALL NOT alter `generate_artifact_id` behaviour —
  the id is derived from the raw title upstream of any encoding.

## Boundaries

**Always:**
- The size check runs **before** the collision `head_object`, the `put_object`, the vector write, AND
  any failure-log append — a rejected write touches neither S3, vectors, nor the failure log.
- The check runs **twice** on a tier-3 overwrite: once against the values supplied to the current
  call (Story 1, before `head_object`), and again against the enlarged `vector_metadata` after the
  T47 read-forward union-merge (Story 5, before `put_object`/`put_vectors_batch`) — because the merge
  can independently push the vector budgets over their limit even when the supplied values alone did
  not.
- The check is **representation-driven**, not field-list-driven: it measures the actual assembled
  s3_metadata and vector_metadata dicts. This makes it automatically correct across T46/T47 landing in
  any order — once T47 removes `commit_refs`/`references` from s3_metadata (ADR-011), they simply stop
  counting against the S3 budget; because they remain filterable list fields in vector metadata (T46),
  they keep counting against the 2 KB filterable budget. The S3 budget therefore *excludes*
  `commit_refs`/`references` post-T47; the vector filterable budget *includes* them.
- Budget constants and `NON_FILTERABLE_METADATA_KEYS` live in one place (single source of truth,
  mirroring `ARTIFACT_TYPES`/`REFERENCE_FIELDS`); `NON_FILTERABLE_METADATA_KEYS` MUST equal the
  externally-created index's declared non-filterable slots (per PRD Deployment Prerequisites:
  `description`, `source_artifacts`, `title`, `author_role`).
- Control-char policy is **reject, not strip** — see Open Questions rationale.
- Non-ASCII title copy is **lossless-encoded**, not stripped, so reconcile round-trips it.

**Ask First:**
- Nothing — budgets and policy are fixed by this spec.

**Never:**
- Do not fix the search `$nin` exclusion-list growth issue or any other unrelated finding — out of
  scope for this task.
- Do not change `generate_artifact_id` / the ADR-005 hash-slug scheme; this is a metadata-copy fix,
  orthogonal to AC-64 identifier disambiguation.
- Do not move `commit_refs`/`references` storage (that is T47/ADR-011) — only measure them where they
  land.
- Do not let any raw exception escape to the MCP caller.

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Byte Budgets and Classification

Sources: S3 user-defined object metadata 2 KB aggregate cap (ADR-011, verified 2026-07-02, and AWS S3
user-guide); S3 Vectors filterable ≤ 2 KB and total ≤ 40 KB per vector
(https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-limitations.html, retrieved
2026-07-03).

| Constant | Value (nominal) | Scope |
|---|---|---|
| `TITLE_MAX_LENGTH` | 256 chars | coarse model-level sanity bound (headline-length; the byte budgets are the authoritative whole-payload guard) |
| `S3_USER_METADATA_MAX_BYTES` | 2048 | sum of UTF-8 bytes of each key + transport-encoded value in the s3_metadata dict |
| `VECTOR_FILTERABLE_METADATA_MAX_BYTES` | 2048 | JSON UTF-8 bytes of vector-metadata keys NOT in `NON_FILTERABLE_METADATA_KEYS` |
| `VECTOR_TOTAL_METADATA_MAX_BYTES` | 40960 | JSON UTF-8 bytes of the full vector-metadata dict |

`NON_FILTERABLE_METADATA_KEYS = ("description", "source_artifacts", "title", "author_role")` — matches the index declaration.
All other vector-metadata keys (`artifact_id`, `scope`, `type`, `team`, `project`, `tier`, `date`,
`status`, `visibility`, `last_edited_ulid`, `tags`, `references`,
`commit_refs`) are filterable and count against the 2 KB filterable budget — so `references`/
`commit_refs` are the fields that most threaten it, which is why T55 must precede T46/T47. The
constants are the single tuning point if integration testing shows AWS's internal accounting differs
from the JSON/byte approximation.

> **Corrected 2026-08-12 (tech-writer).** The "all other keys" sentence above previously also
> listed `title` and `author_role`, which are non-filterable — it contradicted the
> `NON_FILTERABLE_METADATA_KEYS` tuple immediately above it and would have led a reader to count
> both keys against the wrong budget. Both are now listed only as non-filterable. Verified against
> the shipped `src/arkeology/artifact.py` (`NON_FILTERABLE_METADATA_KEYS`) and the
> `vector_metadata` dict assembled in `_write_artifact_inner` in
> `src/arkeology/tools/write.py`: the
> filterable enumeration above now matches the shipped keys exactly.

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_artifact.py` | Modify | Title over `TITLE_MAX_LENGTH` rejected; control char in each metadata-bound field rejected; non-Latin title accepted and preserved — Red first |
| `src/arkeology/artifact.py` | Modify | Add `TITLE_MAX_LENGTH`, the three byte-budget constants, `NON_FILTERABLE_METADATA_KEYS` (single source of truth); add title max-length + control-char field validators; add a pure `check_metadata_budgets(s3_metadata, vector_metadata) -> None` helper raising a typed error |
| `src/arkeology/errors.py` | Modify | Add `MetadataTooLargeError(ArkeologyError)` (and reuse for charset if desired) so `write._inner` maps it to `validation_error` |
| `tests/unit/test_tools_write.py` | Modify | Oversize S3 / oversize filterable / oversize total each rejected before any `put_object`/`put_vectors_batch`/failure-log append (spy asserts zero calls); control char → `validation_error` not raw exception — Red first |
| `src/arkeology/tools/write.py` | Modify | Build the filterable+total vector_metadata dict *before* the collision/put step; call `check_metadata_budgets` before `head_object`; ensure the branch returns `validation_error` and skips all writes and the failure-log append; call `check_metadata_budgets` a second time after the T47 overwrite read-forward union-merge enlarges `vector_metadata`, before `put_object`/`put_vectors_batch` |
| `tests/unit/test_clients_s3.py` | Modify | Lossless round-trip of a non-ASCII value through encode→decode; header-safe output — Red first |
| `src/arkeology/clients/s3.py` | Modify | Replace NFKD-ASCII-strip in `_ascii_safe_metadata` with lossless reversible transport encoding; add the symmetric decoder |
| `tests/unit/test_tools_read.py` | Modify | `read_artifact` returns the true non-ASCII title (decoded / vector-sourced) — Red first |
| `src/arkeology/tools/read.py` | Modify (flag) | Ensure the title returned matches `search_artifacts` — source from vector metadata or decode the S3 copy; confirm which path currently reads the stripped value |
| `src/arkeology/tools/reconcile.py` | Modify (flag) | Decode the S3-metadata title when rebuilding vector metadata so the round-trip stays lossless (verify reconcile reads title from S3 object metadata) |
| `tests/integration/test_tools_write.py` | Modify (flag) | Real-AWS: oversize rejected pre-write; non-ASCII title round-trips through read + search |

## Testing Approach

**TDD cycle — test file before the implementation file it gates:**

1. **`test_artifact.py` → `artifact.py`** — over-long title rejected with the bound in the message;
   control char in `title`/`description`/`author_role`/list elements rejected; non-Latin title
   accepted; `check_metadata_budgets` raises `MetadataTooLargeError` at each of the three budgets and
   passes just under each.
2. **`test_clients_s3.py` → `s3.py`** — `encode(decode(x)) == x` for non-ASCII; encoded output is
   header-safe (ASCII, no control chars); ASCII values pass through unchanged where feasible.
3. **`test_tools_write.py` → `write.py`** — oversize-S3, oversize-filterable, oversize-total each
   rejected with `validation_error` and **zero** `put_object`/`put_vectors_batch`/failure-log calls
   (`mocker.spy`); control char → `validation_error` (no raw exception); a normal write still
   succeeds unchanged; a tier-3 overwrite whose read-forward union-merge (T47) pushes the vector
   budget over its limit is rejected by the post-merge re-check (Story 5) with the same
   zero-writes assertion.
4. **`test_tools_read.py` → `read.py`** (and reconcile) — non-ASCII title returned identically by
   read and search; reconcile rebuild preserves it.
5. **Integration** — real-AWS pre-write rejection and non-ASCII round-trip.

Use `aws_mock`, `s3_client`, `vectors_client_*` fixtures; `FakeBedrockClient` for embeddings.

## Open Questions

- **Control chars: reject (chosen) vs strip.** Chosen **reject** with a structured `validation_error`.
  Rationale: these are short human-authored identity fields where a control char is a mistake or
  injection; silent stripping would mutate the stored value and, for `title`, directly undermine the
  Story-4 requirement that the title round-trip identically (a stripped title is a new divergence).
  Reject is consistent with fail-fast and gives the caller a clear, actionable signal. (Resolved.)
- **Non-ASCII S3 copy: lossless encoding (chosen) vs vector-only authoritative title.** Chosen
  **lossless reversible encoding** (e.g. percent-encoding of the UTF-8 bytes) of the S3-metadata copy,
  with vector metadata as the authoritative display source. Vector-only-authoritative alone is
  insufficient because `reconcile_index` rebuilds vector metadata *from* the S3 object — a lossy S3
  copy would reintroduce the divergence after any reconcile. The developer picks the concrete encoding
  (percent-encoding recommended over RFC 2047 for simplicity); it must be ASCII/header-safe and
  reversible. Note the encoded form inflates non-ASCII values (~3× worst case), which the S3 budget
  check correctly measures because it measures the encoded representation. (Resolved.)
- **Budget nominal units (KiB vs decimal).** Nominal values above use KiB; if integration testing
  shows AWS rejects earlier, tighten the single-source constants. (Deferred to integration.)
