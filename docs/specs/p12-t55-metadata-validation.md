---
type: Spec
id: p12-t55-metadata-validation
title: T55 — Write-Path Metadata Size + Charset Validation
description: Validate metadata size budgets (S3 user-metadata aggregate, vector filterable, vector total) and neutralise control characters BEFORE any storage write, so an oversize or malformed write fails fast with a structured error before anything is durable rather than producing a partial write that reconcile replays. Bound title length in the model and preserve non-ASCII titles losslessly so read_artifact and search_artifacts always agree.
tags: []
status: stable
okf_version: "0.2"
sources:
  - resource: docs/planning-artifacts/requirements.md
    title: Arkeology — Requirements
    last_modified: 2026-09-24T00:00:00Z
  - resource: docs/planning-artifacts/plan.md
    title: Plan Arkeology
  - resource: docs/architecture-decisions/adr-2026-07-03-annotation-backed-link-storage.md
    title: Annotation-Backed Durable Storage for Mutable Link Fields (commit_refs + references)
    last_modified: 2026-09-29T00:00:00Z
  - resource: docs/specs/p12-t46-references-field.md
    title: T46 — references First-Class Field on Artifact + write/read/list Surfacing + Filter
    last_modified: 2026-08-17T00:00:00Z
  - resource: docs/specs/p12-t47-annotation-dual-write.md
    title: T47 — Annotation Dual-Write in the Write Path + Tier-3 Overwrite Preservation
    last_modified: 2026-09-06T00:00:00Z
  - resource: docs/architecture-decisions/adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal.md
    title: Vector Metadata Budget Hardening, Guard Coverage, and Migration Self-Heal
  - resource: docs/specs/p12-t58-commit-refs-cap-references-removal.md
    title: T58 — commit_refs Vector-Metadata Cap (20) + references Vector-Metadata Removal + propose_commit_links Multi-Section Fix
  - resource: .docs/reviews/architecture-review-2026-11-15-arkeology-phases-9-10-12.md
    title: "Architecture review — Arkeology, plan phases 9, 10 and 12"
  - resource: docs/architecture-decisions/adr-2026-07-03-artifact-cross-referencing.md
    title: Artifact Cross-Referencing — First-Class references Field, Migration Rewrite, and referenced_by Warning
  - resource: docs/contracts/data/s3-annotations.artifact.md
    title: s3-annotations.artifact
  - resource: docs/contracts/data/s3.artifact.md
    title: s3.artifact
  - resource: docs/contracts/data/s3vectors.artifact.md
    title: s3vectors.artifact
  - resource: docs/contracts/modules/arkeology.tools.write.md
    title: arkeology.tools.write
  - resource: docs/contracts/modules/arkeology.tools.write_artifacts.md
    title: arkeology.tools.write_artifacts
  - resource: docs/contracts/modules/arkeology.tools.read.md
    title: arkeology.tools.read
generated:
  by: "axians-architect/claude-opus-4.8"
  at: 2026-07-03T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-15T20:35:38Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
  - by: "axians-architect/claude-fable-5-2"
    at: 2026-11-15T20:45:07Z
---

# T55 — Write-Path Metadata Size + Charset Validation

## TL;DR

Before any S3 or vector write, the write path validates the artifact's
metadata against three byte budgets (S3 user-metadata aggregate; vector filterable; vector total)
and rejects control characters and any `references` element that is not a full artifact key,
failing fast with a structured `validation_error` before anything is written, so an oversize or
malformed value leaves no partial write and no self-perpetuating failure-log replay — save a breach
on a compare-and-swap retry after an earlier attempt's object write landed, which the write path
reports as a partial write (R2). It also bounds `title` length in
the `Artifact` model and stores non-ASCII titles losslessly so `read_artifact` and `search_artifacts`
report the identical title. Serves every agent that writes artifacts; nothing durable can be trusted
until oversize/malformed writes fail cleanly. (FR-59, AC-67.)

## 1. Problem Statement

`write_artifact` assembles S3 user-defined object metadata (transmitted as HTTP headers) and vector
metadata, then writes S3 **first** and vectors second. Three defects live in that path:
(1) no pre-write size check — an oversize `title`/`description`/comma-joined list overflows S3's 2 KB
user-metadata cap or S3 Vectors' 2 KB filterable-metadata cap and fails *after* the S3 put, leaving a
deterministic partial write that `reconcile_index` and the failure log replay into the same failure
forever; (2) a control character (e.g. a `\n` in the title) reaches urllib3 as a raw `ValueError`
that escapes the tool; (3) a non-Latin title is NFKD-stripped to `""` in S3 metadata
(by `s3.py`'s metadata sanitiser) while vector metadata keeps the real UTF-8 title, so `read_artifact` and
`search_artifacts` return different titles for the same artifact. This lands before/with T46 and
T47 (which move `commit_refs`/`references` off S3 user-metadata to annotations, leaving a capped
`commit_refs` copy in vector metadata) because those tasks change exactly the payload this guard
measures. The same check also runs in `link_metadata` and `reconcile_index` before their vector
writes (`p12-t57-guard-coverage`).
All five user stories of the earlier format — oversize metadata rejected before any write, the
budget re-check after the T47 overwrite read-forward merge, control characters neutralised, title
length bounded, and non-ASCII title consistency — are P1.

## 2. Rules — Pre-write budget check

### R1 — Oversize metadata is rejected before any write

When `write_artifact` has assembled the S3 user-metadata dict and the filterable-and-total vector
metadata dict, and BEFORE it issues `head_object`/`put_object`/`put_vectors_batch` or appends any
failure-log entry, it validates all three byte budgets (S3 user-metadata aggregate; vector
filterable; vector total) against the **actual serialized representations about to be written**.
On any breach it returns a structured `validation_error` naming the offending budget (via the
standard `_inner` try/except) and issues no storage write and no failure-log append.

**Example**

- Given an artifact whose assembled S3 user-metadata exceeds the S3 aggregate budget, when
  `write_artifact` is called, then it returns a structured `validation_error` naming the offending
  budget AND performs no `put_object`, no `put_vectors_batch`, and appends no failure-log entry.
- Given an artifact whose filterable vector metadata exceeds the 2 KB filterable budget (e.g. many
  long `tags`), when written, then it is rejected before any write with a
  `validation_error` — no partial write, no reconcile-replay loop is created.
- Given an artifact whose total vector metadata exceeds the 40 KB total budget, when written, then it
  is rejected before any write.
- Given a rejected write, when `reconcile_index` later runs, then there is nothing to replay (no S3
  object and no failure-log entry were ever created).

Source: AC-67 — the S3 user-metadata aggregate part

### R2 — The budget check runs a second time after the T47 overwrite read-forward merge

T47 (`write_artifact`) reads an overwriting write's existing `commit_refs` forward from the
object's annotation and merges it into `vector_metadata` **after** the pre-write budget check has
already run against the values supplied to the current call; `references` is replaced, not read
forward, so `commit_refs` is the only field the merge can enlarge. When that merge enlarges
`vector_metadata` beyond what was measured, `write_artifact` calls `check_metadata_budgets` a
**second time** against the enlarged `vector_metadata` — **after the merge and before** that
compare-and-swap attempt's `put_object` / `put_vectors_batch`. A breach there has one of the two
outcomes `arkeology.tools.write` § write_artifact gives it, keyed on durability: while no attempt's
`put_object` has landed, the same `validation_error` as the pre-write check, with no write and no
failure-log entry; on a retry after an earlier attempt's `put_object` landed, `partial_write` with a
failure-log entry. A merge that stays within all three budgets passes the second check silently and
the write proceeds normally. The re-check runs against the full assembled dict, not only the field
that changed.

**Examples**

- Given an overwrite whose supplied `commit_refs` alone pass the pre-write budget check, but whose
  merge with the read-forwarded `commit_refs` pushes the vector filterable or total budget over its
  limit on the first attempt, when `write_artifact` runs, then `check_metadata_budgets` is called a
  second time — after the merge, before any `put_object` / `put_vectors_batch` — and the write is
  rejected with a `validation_error`, with no write and no failure-log entry, identical to a
  pre-write rejection.
- Given an overwrite whose first attempt's `put_object` landed and whose annotation write then
  conflicted, when the retry's re-merged check breaches a budget, then the write returns
  `partial_write` with a failure-log entry, not `validation_error`.

Source: (tech-writer, 2026-07-04); the `references` part: ADR-011 decision 4

## 3. Rules — Byte Budgets and Classification

### R3 — The three byte budgets

The pre-write check measures each budget as follows and rejects the write when the measured size
exceeds the budget's constant.

| Constant | Value (nominal) | What is measured |
|---|---|---|
| `S3_USER_METADATA_MAX_BYTES` | 2048 | over the actual s3_metadata dict, the sum of the UTF-8 byte length of each key plus each (transport-encoded) value |
| `VECTOR_FILTERABLE_METADATA_MAX_BYTES` | 2048 | only the vector-metadata keys NOT listed in `NON_FILTERABLE_METADATA_KEYS`: the UTF-8 byte length of their JSON serialization |
| `VECTOR_TOTAL_METADATA_MAX_BYTES` | 40960 | the full vector-metadata dict (filterable + non-filterable): the UTF-8 byte length of its JSON serialization |

The nominal values above use KiB. The local JSON/byte measure under-counts AWS's real accounting
for some payload shapes — AWS rejected a `commit_refs` payload this measure put at 2,037 bytes — and
the constants are not tightened to compensate: the vector payload is kept well inside the limit
structurally instead, `references` never being in vector metadata and the `commit_refs` copy being
capped at 20 entries (`p12-t58-commit-refs-cap-references-removal` R1, R4). These constants are the
backstop that rejects whatever still overflows.

Source: S3 user-defined object metadata 2 KB aggregate cap: ADR-011 (verified 2026-07-02), AWS S3 user-guide; S3 Vectors filterable ≤ 2 KB and total ≤ 40 KB per vector: https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-limitations.html (retrieved 2026-07-03); the under-count and the structural answer: adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal D2

### R4 — Filterable and non-filterable vector-metadata keys

`NON_FILTERABLE_METADATA_KEYS = ("description", "source_artifacts", "title", "author_role")` —
matches the index declaration. All other vector-metadata keys (`artifact_id`, `scope`, `type`,
`team`, `project`, `tier`, `date`, `status`, `visibility`, `last_edited_ulid`, `tags`,
`commit_refs`) are filterable and count against the 2 KB filterable budget — so the list fields
`tags` and `commit_refs` are the ones that most threaten it. `references` is not a vector-metadata
key at all. `title` and `author_role` are listed only as non-filterable.

Source: the `title`/`author_role` part: correction (tech-writer, 2026-08-12)

## 4. Rules — Field validation in the Artifact model

### R5 — Title length is bounded

When the `Artifact` model is constructed with a `title` longer than `TITLE_MAX_LENGTH` (256 chars),
it raises a `ValueError` — a clear validation error stating the bound and the actual length. A title
at or below the bound raises no error. `TITLE_MAX_LENGTH` is a coarse model-level sanity bound
(headline-length; the byte budgets are the authoritative whole-payload guard).

Source: AC-67 — the over-bound part

### R6 — Control characters are rejected, not stripped

When the `Artifact` model is constructed, any string value bound for metadata — `title`,
`description`, `author_role`, and every element of `tags`, `source_artifacts`, `references`,
`commit_refs` — that contains a control character (Unicode category `Cc`, i.e. code points
U+0000–U+001F and U+007F–U+009F; e.g. `\n`, `\t`, `\r`, `\x00`, DEL) is rejected with a `ValueError`
naming the field. When such an artifact is constructed or written, a structured `validation_error`
is returned naming the field — never a raw urllib3 `ValueError` or any uncaught exception.

**Why:** these are short human-authored identity fields where a control char is a mistake or
injection; silent stripping would mutate the stored value and, for `title`, directly undermine the
requirement that the title round-trip identically (a stripped title is a new divergence). Reject is
consistent with fail-fast and gives the caller a clear, actionable signal.

Source: AC-67 — the structured `validation_error` part

### R10 — A `references` element that is not a full key is rejected

When the `Artifact` model is constructed, every element of `references` must contain the scope
separator `/`, as every full artifact key does (`s3-annotations.artifact` § Storage Shape states the
form). An element without one is rejected with a `ValueError` naming the field and the element, and
the write returns a structured `validation_error` with nothing written — no `put_object`, no
annotation write, no vector write, no failure-log entry. The check is of form only: it does not look
the key up, so a well-formed key naming no artifact is accepted.

**Example**

- Given `write_artifact(..., references=["adr-use-postgres-abc12345"])`, when the write runs, then
  it returns `validation_error` naming `references` and that element, and nothing is written.
- Given `write_artifact(..., references=["team-a/payments/adr-use-postgres-abc12345.md"])`, when the
  write runs, then it proceeds as any other write.
- Given a `write_artifacts` or `migrate_artifacts` descriptor carrying the bare element, then that
  descriptor's own result carries the `validation_error` and every other descriptor is written.

**Why:** a stored reference is useful only when it equals another artifact's key exactly. Without
the check, a bare identifier is stored silently as a link that matches nothing — a link built from
it leads to "not found", and a reader of the artifact in another scope has it dropped as
unresolvable — and the write gives no sign. The scope separator is the cheapest check that catches
it: it needs no lookup.

Source: adr-2026-07-03-artifact-cross-referencing D2

## 5. Rules — Non-ASCII title consistency

### R7 — The S3-metadata copy of a non-ASCII value is lossless

When a metadata value contains non-ASCII characters, it is encoded losslessly and reversibly for the
S3 user-metadata copy (replacing the lossy NFKD-ASCII-strip in `_ascii_safe_metadata`) and decoded
symmetrically wherever the S3-metadata title is read back (the `read_artifact` fallback path and the
`reconcile_index` rebuild), while vector metadata continues to hold the raw UTF-8 title and is the
authoritative display source. The developer picks the concrete encoding (e.g. percent-encoding of
the UTF-8 bytes — recommended over RFC 2047 for simplicity); it must be ASCII/header-safe and
reversible. The encoded form inflates non-ASCII values (~3× worst case), which the S3 budget check
correctly measures because it measures the encoded representation.

**Example**

- Given an artifact with a non-Latin title, when `reconcile_index` rebuilds its vector metadata from
  the S3 object, then the restored title is still the identical original title (the S3-metadata copy
  is lossless).

**Why:** vector-only-authoritative alone is insufficient because `reconcile_index` rebuilds vector
metadata *from* the S3 object — a lossy S3 copy would reintroduce the divergence after any
reconcile.

Source: None

### R8 — `read_artifact` and `search_artifacts` report the identical title

When `read_artifact` and `search_artifacts` return a title, they source it from the same
charset-safe representation, so the two never disagree.

**Example**

- Given an artifact with a non-Latin title (e.g. Japanese, Cyrillic, Arabic), when it is read via
  `read_artifact` and found via `search_artifacts`, then both return the identical original title —
  no silent ASCII-stripping to `""`.

Source: AC-67 — the non-Latin read/search part

### R9 — The artifact id is unaffected

Validating the metadata payload does not alter `generate_artifact_id` behaviour — the id is derived
from the raw title upstream of any encoding. Given a non-ASCII title, the generated `artifact_id` is
byte-for-byte unchanged from today (ADR-005 hash/slug scheme untouched).

Source: ADR-005

## 6. Boundaries

**Always:**
- The size check runs **before** the collision `head_object`, the `put_object`, the vector write, AND
  any failure-log append — a write rejected while nothing is durable touches neither S3, vectors,
  nor the failure log. The one breach that follows a landed `put_object` — the re-check on a
  compare-and-swap retry — returns the `partial_write` of `arkeology.tools.write` § write_artifact
  (R2).
- The check runs **twice** on an overwriting write: once against the values supplied to the current
  call (R1, before `head_object`), and again against the enlarged `vector_metadata` after the
  T47 `commit_refs` read-forward merge (R2, before that attempt's `put_object`/`put_vectors_batch`)
  — because the merge can independently push the vector budgets over their limit even when the
  supplied values alone did not.
- The check is **representation-driven**, not field-list-driven: it measures the actual assembled
  s3_metadata and vector_metadata dicts, so it counts whatever each store holds. `commit_refs` and
  `references` are in s3_metadata nowhere (ADR-011) and count against no S3 budget; the capped
  `commit_refs` copy counts against the 2 KB filterable budget; `references`, in vector metadata
  nowhere, counts against neither vector budget.
- Budget constants and `NON_FILTERABLE_METADATA_KEYS` live in one place (single source of truth,
  mirroring `ARTIFACT_TYPES`); `NON_FILTERABLE_METADATA_KEYS` MUST equal the
  externally-created index's declared non-filterable slots (per the requirements.md Constraints table:
  `description`, `source_artifacts`, `title`, `author_role`).
- Control-char policy is **reject, not strip** — see the rationale under R6.
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

## 7. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_artifact.py` | Modify | Title over `TITLE_MAX_LENGTH` rejected; control char in each metadata-bound field rejected; a `references` element without `/` rejected naming the element, a full key accepted (R10); non-Latin title accepted and preserved — Red first |
| `src/arkeology/artifact.py` | Modify | Add `TITLE_MAX_LENGTH`, the three byte-budget constants, `NON_FILTERABLE_METADATA_KEYS` (single source of truth); add title max-length + control-char field validators; add the scope-separator check to `validate_references` (R10), which `link_metadata` reaches through its delegated validation (`p12-t57-guard-coverage` R7); add a pure `check_metadata_budgets(s3_metadata, vector_metadata) -> None` helper raising a typed error |
| `src/arkeology/errors.py` | Modify | Add `MetadataTooLargeError(ArkeologyError)` (and reuse for charset if desired) so `write._inner` maps it to `validation_error` |
| `tests/unit/test_tools_write.py` | Modify | Oversize S3 / oversize filterable / oversize total each rejected before any `put_object`/`put_vectors_batch`/failure-log append (spy asserts zero calls); control char → `validation_error` not raw exception — Red first |
| `src/arkeology/tools/write.py` | Modify | Build the filterable+total vector_metadata dict *before* the collision/put step; call `check_metadata_budgets` before `head_object`; ensure the branch returns `validation_error` and skips all writes and the failure-log append; call `check_metadata_budgets` a second time after the T47 overwrite read-forward union-merge enlarges `vector_metadata`, before `put_object`/`put_vectors_batch`, returning `validation_error` while nothing is durable and `partial_write` with a failure-log entry on a retry after a landed `put_object` (R2) |
| `tests/unit/test_clients_s3.py` | Modify | Lossless round-trip of a non-ASCII value through encode→decode; header-safe output — Red first |
| `src/arkeology/clients/s3.py` | Modify | Replace NFKD-ASCII-strip in `_ascii_safe_metadata` with lossless reversible transport encoding; add the symmetric decoder |
| `tests/unit/test_tools_read.py` | Modify | `read_artifact` returns the true non-ASCII title (decoded / vector-sourced) — Red first |
| `src/arkeology/tools/read.py` | Modify (flag) | Ensure the title returned matches `search_artifacts` — source from vector metadata or decode the S3 copy; confirm which path currently reads the stripped value |
| `src/arkeology/tools/reconcile.py` | Modify (flag) | Decode the S3-metadata title when rebuilding vector metadata so the round-trip stays lossless (verify reconcile reads title from S3 object metadata) |
| `tests/integration/test_tools_write.py` | Modify (flag) | Real-AWS: oversize rejected pre-write; non-ASCII title round-trips through read + search |

### Contracts

- `docs/contracts/data/s3.artifact.md` § check_metadata_budgets, § encode_metadata_value, § decode_metadata_value and § generate_artifact_id — the three-budget guard and when it runs, the lossless transport encoding of metadata values, and the id derived upstream of it (R1–R3, R7, R9).
- `docs/contracts/data/s3vectors.artifact.md` § Storage Shape — the non-filterable keys and the two vector budgets (R3, R4).
- `docs/contracts/data/s3-annotations.artifact.md` § Storage Shape — the full-key form a `references` element must have (R10).
- `docs/contracts/modules/arkeology.tools.write.md` § write_artifact — `validation_error` for a budget breach, a control character or a `references` element without a scope separator, and the budget re-run after the overwrite merge with its two outcomes, keyed on whether a `put_object` has landed (R1, R2, R6, R10).
- `docs/contracts/modules/arkeology.tools.write_artifacts.md` § write_artifacts — a rejected descriptor isolated in its own result (R10).
- `docs/contracts/modules/arkeology.tools.read.md` § read_artifact — the decoded title that cannot disagree with `search_artifacts` (R8).

### Testing Approach

**TDD cycle — test file before the implementation file it gates:**

1. **`test_artifact.py` → `artifact.py`** — over-long title rejected with the bound in the message;
   control char in `title`/`description`/`author_role`/list elements rejected; a `references`
   element without `/` rejected with the element named, a full key accepted; non-Latin title
   accepted; `check_metadata_budgets` raises `MetadataTooLargeError` at each of the three budgets and
   passes just under each.
2. **`test_clients_s3.py` → `s3.py`** — `encode(decode(x)) == x` for non-ASCII; encoded output is
   header-safe (ASCII, no control chars); ASCII values pass through unchanged where feasible.
3. **`test_tools_write.py` → `write.py`** — oversize-S3, oversize-filterable, oversize-total each
   rejected with `validation_error` and **zero** `put_object`/`put_vectors_batch`/failure-log calls
   (`mocker.spy`); control char → `validation_error` (no raw exception); a normal write still
   succeeds unchanged; `references=["adr-use-postgres-abc12345"]` → `validation_error` with the
   same zero-writes assertion (R10); a tier-3 overwrite whose read-forward union-merge (T47) pushes the vector
   budget over its limit is rejected by the post-merge re-check (R2) with the same
   zero-writes assertion; the same breach on a compare-and-swap retry after the first attempt's
   `put_object` landed (inject an `ArtifactConflictError` on the first annotation write) returns
   `partial_write` with one failure-log entry (R2).
4. **`test_tools_read.py` → `read.py`** (and reconcile) — non-ASCII title returned identically by
   read and search; reconcile rebuild preserves it.
5. **Integration** — real-AWS pre-write rejection and non-ASCII round-trip.

Use `aws_mock`, `s3_client`, `vectors_client_*` fixtures; `FakeBedrockClient` for embeddings.
