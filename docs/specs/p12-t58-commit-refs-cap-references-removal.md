---
type: Spec
id: p12-t58-commit-refs-cap-references-removal
title: T58 — commit_refs Vector-Metadata Cap (20) + references Vector-Metadata Removal + propose_commit_links Multi-Section Fix
description: "Stop writing references into S3 Vectors metadata entirely across write.py, link_metadata.py, and reconcile.py — the S3 object annotation copy becomes its sole durable store and sole read surface. commit_refs stays in S3 Vectors metadata, filterable, but capped to the most-recently-appended 20 entries (real-AWS-calibrated; AWS accepts up to 36 entries for this payload shape, rejects 37); the complete, uncapped list remains durable in annotations regardless of the cap. Also makes propose_commit_links.py decide eligibility from the artifact's commit_refs annotation, the sole source of truth read.py/list.py use, instead of a single vector's capped copy."
tags: []
status: stable
okf_version: "0.2"
sources:
  - resource: docs/architecture-decisions/adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal.md
    title: Vector Metadata Budget Hardening, Guard Coverage, and Migration Self-Heal
    last_modified: 2026-09-25T00:00:00Z
  - resource: docs/specs/p12-t57-guard-coverage.md
    title: T57 — Guard Coverage in link_metadata.py and reconcile.py + Control-Character Validation Fix
    last_modified: 2026-08-17T00:00:00Z
  - resource: docs/specs/p12-t46-references-field.md
    title: T46 — references First-Class Field on Artifact + write/read/list Surfacing + Filter
    last_modified: 2026-08-17T00:00:00Z
  - resource: docs/specs/p12-t47-annotation-dual-write.md
    title: T47 — Annotation Dual-Write in the Write Path + Tier-3 Overwrite Preservation
    last_modified: 2026-09-06T00:00:00Z
  - resource: docs/specs/p12-t48-reconcile-from-annotations.md
    title: T48 — reconcile_index Rebuilds commit_refs + references from Annotations
    last_modified: 2026-09-06T00:00:00Z
  - resource: docs/specs/p12-t55-metadata-validation.md
    title: T55 — Write-Path Metadata Size + Charset Validation
    last_modified: 2026-08-17T00:00:00Z
  - resource: docs/learnings.md
    title: Learnings
  - resource: tests/integration/test_calibration_vector_metadata_budget.py
  - resource: docs/contracts/data/s3-annotations.artifact.md
    title: s3-annotations.artifact
  - resource: docs/contracts/modules/arkeology.tools.propose_commit_links.md
    title: arkeology.tools.propose_commit_links
  - resource: .docs/reviews/architecture-review-2026-11-15-arkeology-phases-9-10-12.md
    title: "Architecture review — Arkeology, plan phases 9, 10 and 12"
  - resource: docs/architecture-decisions/adr-2026-09-14-malformed-persisted-data-policy.md
    title: How Arkeology Treats Malformed and Ambiguous Persisted Data
  - resource: docs/specs/p3-t10-list-artifacts.md
    title: T10 — List Artifacts Tool
  - resource: docs/contracts/data/s3vectors.artifact.md
    title: s3vectors.artifact
  - resource: docs/contracts/modules/arkeology.tools.write.md
    title: arkeology.tools.write
  - resource: docs/contracts/modules/arkeology.tools.link_metadata.md
    title: arkeology.tools.link_metadata
  - resource: docs/contracts/modules/arkeology.tools.reconcile.md
    title: arkeology.tools.reconcile
  - resource: docs/contracts/modules/arkeology.tools.read.md
    title: arkeology.tools.read
  - resource: docs/contracts/modules/arkeology.tools.list.md
    title: arkeology.tools.list
generated:
  by: "axians-architect/claude-sonnet-5"
  at: 2026-08-17T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-15T20:28:28Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
  - by: "axians-architect/claude-fable-5-2"
    at: 2026-11-15T20:45:07Z
---

# T58 — `commit_refs` Vector-Metadata Cap (20) + `references` Vector-Metadata Removal + `propose_commit_links` Multi-Section Fix

## TL;DR

This is the operator's locked, structural fix
(adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal D2), not a tuning fix: `references`
is removed from S3 Vectors metadata entirely — the S3 object annotation copy (ADR-011) becomes its
sole durable store and sole read surface. `commit_refs` keeps its load-bearing `$eq` filterability
(`list.py`'s `commit_refs=[...]` filter) but its vector-metadata copy is capped to the
most-recently-appended **20 entries** — real-AWS-calibrated (AWS accepts up to 36 entries for this
payload shape, rejects 37; 20 leaves deliberate headroom, see `docs/learnings.md`, 2026-08-13). The
complete, uncapped `commit_refs` list remains durable in annotations regardless of the vector-side
cap — the cap is a representation change, never a data-loss or write-rejection event.
(adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal D2.) It also makes
`propose_commit_links.py` decide eligibility from the artifact's `commit_refs` annotation — the sole
source of truth, read with `annotations.read_link_annotations` — instead of a single vector's capped
`commit_refs` copy.

## 1. Problem Statement

A link list held in vector metadata is a filterable field, counted against the 2 KB filterable-metadata budget alongside `tags` and every other filterable key. The operator judged `references`'s native `$eq`/`$in` filtering (`list_artifacts(references=[...])`, the `references`-half of the delete/archive reverse-lookup) a nice-to-have, not load-bearing, at the project's current stage — so rather than tuning the byte-budget threshold (which only narrows, not eliminates, the overflow failure mode for a genuinely large list), the operator chose to retire `references` from the vector store outright. `commit_refs` is different: `list_artifacts(commit_refs=[...])` is a shipped, load-bearing filter, so it must stay filterable — but its list is append-only and unbounded (backfilled repeatedly by `link_metadata` over an artifact's lifetime), and the 2026-08-13 real-AWS calibration proved the local byte-budget approximation under-measures AWS's real per-entry accounting for this exact field shape by enough to make an unbounded list a real, repeatable failure mode, not a hypothetical one. A hard, calibrated entry-count cap on the *vector-metadata copy only* closes this permanently, without touching the byte-budget guard itself (T55's constants are unchanged by this task — this is a structural fix, not a threshold tuning) and without losing any data, because the annotation copy stays uncapped.

Three call sites assemble vector metadata carrying the link fields: `write.py` (fresh-create Step 3b, and the overwrite CAS loop), `link_metadata.py` (its per-vector batch-write loop), and `reconcile.py` (`_reindex_artifact`'s rebuild). All three apply the same two rules, or the split-store contract is inconsistent depending on which path last touched an artifact.

A fourth site, `propose_commit_links.py`, only *reads* `commit_refs` (it makes no writes) to decide whether an artifact is "not yet linked". Reading it off one section vector per artifact misses both a value that lives on a different section vector and a value that has aged out of that vector's 20-entry window, so a linked artifact would be re-proposed after every commit. It therefore reads the artifact's `commit_refs` annotation — the sole, complete source of truth that `read.py` and `list.py` read — so the cap cannot change its answer.

All four user stories of the earlier format — `references` never appears in vector metadata after
any write path; `commit_refs` vector-metadata copy capped at 20, full list stays in annotations;
existing dual-field, uncapped vector-metadata contract updated; `propose_commit_links` sources
eligibility from the annotation, not one vector — are P1.

## 2. Rules — `references` removed from vector metadata

### R1 — No write path sets `references` in vector metadata

When `write.py`, `link_metadata.py`, or `reconcile.py` assemble vector metadata to be written, they
never set a `references` key on it, under any circumstance — the field is removed from the
vector-metadata representation entirely, not merely capped or conditionally included. The S3 object
annotation copy (ADR-011) becomes its sole durable store and sole read surface.

**Example**

- Given `write_artifact` is called with a non-empty `references` value (fresh create or overwrite),
  when the write completes, then the S3 object annotation carries the full `references` value, but
  no `references` key is present in any written vector's metadata.
- Given `link_metadata` is called with a non-empty `references` value, when the call completes, then
  the merged value is written to the S3 annotation, but no `references` key is present in any vector
  written by `put_vectors_batch`.
- Given `reconcile_index` re-indexes an artifact whose annotation carries `references`, when the
  rebuild completes, then no `references` key is present in the rebuilt vector metadata — the value
  remains readable only via the annotation.

Source: adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal D2; the sole-store part: ADR-011

### R2 — Readers still return the correct `references` value

After any of the writes above, `read_artifact`, and `list_artifacts` when the caller asks for link
fields (p3-t10-list-artifacts R11), still return the artifact's correct `references` value — they
read it from the S3 object annotation
(`annotations.read_link_annotations`), the field's sole read surface, so the vector side carrying no
copy has no effect on what a reader sees.

Source: None

### R3 — The rebuild reads both fields from the annotation but writes back only the capped `commit_refs`

When `reconcile.py`'s `_reindex_artifact` rebuilds an artifact, it reads both `commit_refs` and
`references` from the object's annotation with `annotations.read_link_annotations` — never from the
vector metadata it is replacing — and places only the capped `commit_refs` value into the rebuilt
vector metadata.

Source: p12-t48-reconcile-from-annotations R1, R3

## 3. Rules — `commit_refs` vector-metadata cap

### R4 — The vector-metadata copy of `commit_refs` is capped at the most-recently-appended 20 entries

When any of the three paths assemble vector metadata AND the artifact's full (annotation-sourced or
freshly supplied) `commit_refs` list is non-empty, the vector-metadata `commit_refs` key is set to
the **last 20 elements** of that full list (`full_list[-20:]`) — never the full list itself, and
never fewer than `min(len(full_list), 20)` entries. When the full `commit_refs` list is empty, the
`commit_refs` key is omitted from vector metadata, exactly as today. `commit_refs` keeps its
load-bearing `$eq` filterability (`list.py`'s `commit_refs=[...]` filter). The cap is
real-AWS-calibrated (AWS accepts up to 36 entries for this payload shape, rejects 37; 20 leaves
deliberate headroom, see `docs/learnings.md`, 2026-08-13); it is a representation change, never a
data-loss or write-rejection event.

**Example**

- Given an artifact whose full `commit_refs` list (after read-forward/merge) has 21 or more entries,
  when written by any of the three paths, then the write succeeds — never rejected for entry count
  alone — and the vector metadata carries only the **most-recently-appended 20** entries.
- Given an artifact whose full `commit_refs` list has 20 or fewer entries, when written, then the
  vector-metadata copy is identical to the full list — the cap never truncates a list that already
  fits.
- Given `commit_refs` is empty after merge, when written, then the `commit_refs` key is omitted from
  vector metadata exactly as today (existing S3-Vectors empty-array rule, unaffected by this task).

Source: adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal D2; the 20-entry number: OQ2 (closed by real-AWS calibration)

### R5 — The annotation write always carries the full, uncapped lists

When any of the three paths write to the durable S3 annotation store (`apply_link_annotations`),
they continue to pass the **full, uncapped** `commit_refs` and `references` values — the cap applies
to the vector-metadata representation only, never to the annotation write.

**Example**

- Given an artifact whose full `commit_refs` list has 21 or more entries, when its S3 annotation is
  read (directly, or via `read_link_annotations`/`read_artifact`), then it carries the
  **complete, uncapped** `commit_refs` list — nothing is ever dropped from the durable copy.

Source: adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal D2

### R6 — A `commit_refs` filter does not match a SHA outside the most-recent 20

When `list_artifacts(commit_refs=["<sha>"])` is called for a SHA that falls outside an artifact's
most-recent 20 (i.e. it was pushed out of the vector-side window by later appends), that artifact
does **not** appear in the filtered results — this is the accepted, documented capability narrowing
of this task (see Consequences below); `read_artifact`'s returned `commit_refs` list is unaffected
(still complete, from annotations).

Source: adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal D2

### R7 — One shared constant and one shared helper apply the cap

When the cap is applied, one shared constant and one shared helper function are used (added to
`src/arkeology/artifact.py`, alongside the existing byte-budget constants) — e.g.
`COMMIT_REFS_VECTOR_METADATA_MAX_ENTRIES = 20` and a
`cap_commit_refs_for_vectors(commit_refs: list[str]) -> list[str]` helper returning
`commit_refs[-COMMIT_REFS_VECTOR_METADATA_MAX_ENTRIES:]` — reused identically by all three call
sites, rather than three independently-written slice expressions. Routing the cap through a single
shared helper follows the project's existing single-source-of-truth convention.

Source: None

### R8 — The docstrings say the vector-metadata copy is not complete

The helper's docstring (and the `Artifact.commit_refs` field docstring) states explicitly that the
vector-metadata copy is a bounded, most-recent-N view and is **not** a completeness guarantee — the
annotation-backed copy is the only complete, authoritative representation of `commit_refs`.

Source: None

## 4. Rules — `propose_commit_links` eligibility

### R9 — `propose_commit_links` decides eligibility from the annotation

When `propose_commit_links.py` has deduplicated its fetched vector items down to one distinct
`artifact_id` per candidate (existing `seen_ids` logic, unchanged), it determines each candidate's
current `commit_refs` by reading the candidate's annotation with
`annotations.read_link_annotations(s3, artifact_id)` (off the event loop, via `asyncio.to_thread`,
mirroring `list.py`'s pattern) rather than reading `meta.get("commit_refs")` off the single vector
already in hand. When resolving `commit_refs` for multiple candidates, it issues the per-candidate
reads concurrently via `asyncio.gather(..., return_exceptions=True)`, matching `list.py`'s existing
pattern, rather than one sequential call per candidate.

**Example**

- Given a multi-section artifact whose `commit_refs` were set (via `link_metadata`) on a section
  vector other than the one `propose_commit_links`' internal dedup currently keeps (i.e. not the
  first-occurrence vector by whatever order `get_vectors` returns), when `propose_commit_links` runs,
  then that artifact is correctly excluded from `proposed` (it is already linked) — not silently
  re-proposed.
- Given an artifact whose full `commit_refs` list (from annotations) has more than 20 entries, so its
  vector-metadata copy is capped at 20, when `propose_commit_links` runs, then the artifact is still
  correctly excluded from `proposed` — eligibility is decided from the uncapped annotation, never
  from a vector's capped copy.
- Given an artifact with no `commit_refs` annotation, when `propose_commit_links` runs, then it
  still appears in `proposed` exactly as today — no passing-case behaviour changes.

Source: None

### R10 — A failed per-candidate read fails the whole call; no candidate is degraded to "not yet linked"

When a per-candidate `read_link_annotations` call fails, `propose_commit_links` proposes nothing and
returns one structured error for the whole call, with the code `arkeology.tools.propose_commit_links`
§ propose_commit_links lists under Errors: `credential_error` for a `CredentialError`,
`annotation_unavailable` when the annotation store is unavailable or access to it is denied, and
`internal_error` for any other failure, a throttled read and a not-found the client could not
classify included. A candidate whose read failed is never treated as having empty `commit_refs`:
`commit_refs` is an append-only trail with no removal operation, so a candidate proposed on the
strength of a failed read and then linked would claim that commit permanently. The one outcome that
does not fail the call is a read answering that the candidate's object is gone: that candidate is
left out of `proposed`, silently and uncounted, since a deleted artifact cannot be linked.

**Example**

- Given two candidates, one already linked to an earlier commit and whose annotation read is
  throttled on this call, when `propose_commit_links` runs, then it returns
  `{"error": "internal_error", "message": ...}` and no `proposed` list.
- Given a candidate whose annotation read raises `AnnotationUnavailableError`, when
  `propose_commit_links` runs, then it returns `{"error": "annotation_unavailable", ...}`.
- Given a candidate whose object was deleted after its vectors were listed, when
  `propose_commit_links` runs, then the call succeeds and that candidate is not in `proposed`.

Source: adr-2026-09-14-malformed-persisted-data-policy D5, D6

### R11 — `propose_commit_links`'s `s3` parameter becomes required

`propose_commit_links`'s `s3` parameter, required for this fix, changes type from
`S3ClientInterface | None = None` to a required `S3ClientInterface` — the server already injects a
real `s3` client into every tool call (AGENTS.md: "Tool functions receive settings, s3, vectors,
bedrock as injected dependencies"), so this narrows an already-always-satisfied signature rather than
changing runtime wiring.

Source: None

## 5. Rules — Existing test-suite contract

### R12 — No test is left asserting the old dual-field, uncapped vector-metadata shape

Where the existing unit test suite asserts the pre-T58 shape (both `commit_refs` and `references`
present and uncapped in vector metadata after write/link/reconcile), those assertions are updated to
the new contract — no test is left asserting a shape the implementation no longer produces.

Source: None

## 6. Boundaries

**Always:**
- The byte-budget constants (`VECTOR_FILTERABLE_METADATA_MAX_BYTES`,
  `VECTOR_TOTAL_METADATA_MAX_BYTES`, `S3_USER_METADATA_MAX_BYTES`) are **unchanged** by this task —
  this is a structural representation fix (remove one field, cap another), not a threshold tuning
  (adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal D2, rejected Option A).
- The 20-entry cap and the 36/37-entry calibration boundary are **payload-shape-specific, not universal constants** — they were measured against today's specific filterable-metadata field mix and must be re-calibrated (a fresh run of `tests/integration/test_calibration_vector_metadata_budget.py`) if the set of filterable vector-metadata keys ever changes. Document this alongside the new constant, mirroring the existing warning in `docs/learnings.md`.
- The cap is applied at the **last** step before each path's vector write, using the already-fully-merged/read-forwarded `commit_refs` value — never applied earlier, and never applied to the value passed to the annotation write.
- T57's guard-coverage check (`check_metadata_budgets`) still runs in all three paths, unaffected by this task — it now simply measures a smaller payload (post-cap, post-removal) and continues to function as a defense-in-depth backstop for other filterable fields (e.g. `tags`), not as the mechanism that closes this specific overflow (ADR Consequences).
- No path reads either link field back from vector metadata: the S3 object annotation is the sole read surface for both (`s3-annotations.artifact` § read_link_annotations), and a failed annotation read raises rather than returning `[]`.
- `propose_commit_links.py`'s per-candidate annotation reads are additional round trips beyond its existing single batched `list_vectors_by_metadata` + `get_vectors` fetch — the same accepted cost `read.py` carries, and `list.py` carries when the caller asks for link fields (one annotation read per distinct artifact_id, run off the event loop and in parallel via `asyncio.gather`, no new bounded-concurrency setting — the same proportionate-for-page-size reasoning `list.py`'s own comment already documents applies here).

**Ask First:**
- Nothing — the split-store decision, the 20-entry cap, and the "annotation is sole store for
  `references`" contract are all locked, operator-approved decisions
  (adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal D2, OQ2 closed by real-AWS
  calibration). The propose_commit_links fix shape (read the annotation per candidate, mirroring
  `list.py`'s existing per-candidate fetch pattern) has no open design choice either.

**Never:**
- Do not write `references` into vector metadata under any code path, including `reconcile.py`'s rebuild — the rebuild reads `references` from the annotation, but the value is never written to the vector side.
- Do not cap `references` instead of removing it — the adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal D2 table considered and rejected "cap both fields" (Option B) specifically because it produces silent false negatives on `references`'s `$eq` filtering, a completeness regression the operator explicitly rejected.
- Do not tighten `VECTOR_FILTERABLE_METADATA_MAX_BYTES`/`VECTOR_TOTAL_METADATA_MAX_BYTES` as part of
  this task — that is a different, rejected alternative
  (adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal D2 Option A).
- Do not cap the value written to the S3 annotation — the annotation copy of `commit_refs` must always be the full, uncapped list; only the vector-metadata copy is capped.
- Do not duplicate the cap constant or slice expression in three files — use the single shared helper in `artifact.py`.
- Do not leave `propose_commit_links.py` reading `commit_refs` off a single vector's `meta` — that is precisely the bug this story closes; the dedup-by-`artifact_id` step (`seen_ids`) stays (it is still needed to build one candidate entry per artifact), only the source of the `commit_refs` eligibility check changes.

## 7. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_artifact.py` | Modify | Tests for `cap_commit_refs_for_vectors` — ≤20 entries unchanged, >20 entries returns last 20, empty list returns empty — Red first |
| `src/arkeology/artifact.py` | Modify | Add `COMMIT_REFS_VECTOR_METADATA_MAX_ENTRIES = 20` and `cap_commit_refs_for_vectors(...)` next to the existing budget constants; update `Artifact.commit_refs`/`Artifact.references` field docstrings to note the vector-metadata cap and removal respectively |
| `tests/unit/test_tools_write.py` | Modify | Tests: `references` never in written vector metadata (fresh + overwrite); `commit_refs` >20 entries → vector metadata carries last 20, annotation carries full list — Red first |
| `src/arkeology/tools/write.py` | Modify | Remove the `if references: vector_metadata["references"] = references` assignment (Step 3b) entirely; wrap both `commit_refs` vector-metadata assignments (Step 3b fresh path, and the CAS-loop overwrite path) in `cap_commit_refs_for_vectors(...)`; annotation write (`apply_link_annotations`, both call sites) keeps using the uncapped `final_commit_refs`/`final_references` unchanged |
| `tests/unit/test_tools_link_metadata.py` | Modify | Tests: `references` never in `put_vectors_batch` payload; `commit_refs` capped at 20 in vector metadata, full merged list in annotation — Red first |
| `src/arkeology/tools/link_metadata.py` | Modify | In the per-item batch loop, replace the `references` set/pop block with an unconditional `meta.pop("references", None)`; wrap the `commit_refs` assignment in `cap_commit_refs_for_vectors(merged_commit_refs)` |
| `tests/unit/test_tools_reconcile.py` | Modify | Tests: rebuilt vector metadata never carries `references`; `commit_refs` capped at 20 when the annotation-sourced list exceeds it — Red first |
| `src/arkeology/tools/reconcile.py` | Modify | Remove the `if references_list: vector_metadata["references"] = references_list` assignment; wrap the `commit_refs_list` assignment in `cap_commit_refs_for_vectors(...)`; import the new helper from `arkeology.artifact` |
| `tests/unit/test_tools_list.py`, `tests/unit/test_tools_read.py` | Modify (flag) | Update any existing assertion that expected `references` in vector metadata or an uncapped `commit_refs` vector-metadata copy to the new contract; the *returned* `references`/`commit_refs` field values (annotation-sourced) are unaffected and need no assertion changes |
| `tests/integration/test_tools_write.py`, `tests/integration/test_tools_link_metadata.py`, `tests/integration/test_tools_reconcile.py` | Modify (flag) | Real-AWS: confirm a >20-entry `commit_refs` write succeeds and is capped in the index; confirm `references` never reaches the index |
| `tests/unit/test_tools_propose_commit_links.py` | Modify | Tests: multi-section artifact whose `commit_refs`-bearing vector is not the first-occurrence one → correctly excluded from `proposed`; artifact whose full `commit_refs` exceeds the 20-entry vector-metadata cap → correctly excluded from `proposed` (eligibility from annotation, not the capped vector copy); artifact with no `commit_refs` annotation → still included; `CredentialError` during resolution → `credential_error`; `AnnotationUnavailableError` → `annotation_unavailable`; any other read failure → `internal_error` and no `proposed` list; object gone → call succeeds without that candidate — Red first |
| `src/arkeology/tools/propose_commit_links.py` | Modify | Import `read_link_annotations` from `arkeology.annotations`; change `s3` parameter to required `S3ClientInterface` (drop `\| None = None` and the `_ = s3` no-op); replace the `raw_commit_refs = meta.get("commit_refs")` block with a per-`artifact_id` `asyncio.to_thread(read_link_annotations, s3, artifact_id)` call, gathered concurrently via `asyncio.gather(..., return_exceptions=True)` across all deduplicated candidates; any failed read fails the call with its code (R10), and an object-gone candidate is dropped |

### Contracts

- `docs/contracts/data/s3vectors.artifact.md` § cap_commit_refs_for_vectors, § Storage Shape and § Compatibility Guarantees — the shared 20-entry cap, `references` never present, and the capped copy as a derived index whose calibration a change of filterable keys invalidates (R1, R4, R6–R8).
- `docs/contracts/data/s3-annotations.artifact.md` § apply_link_annotations, § read_link_annotations and § Compatibility Guarantees — the full uncapped annotation write, and the annotation as the sole read surface for both fields (R2, R3, R5, R9).
- `docs/contracts/modules/arkeology.tools.write.md` § write_artifact — the write path's vector metadata: no `references`, at most 20 `commit_refs` (R1, R4, R5).
- `docs/contracts/modules/arkeology.tools.link_metadata.md` § link_metadata — the backfill's vector metadata: no `references`, at most 20 `commit_refs` (R1, R4, R5).
- `docs/contracts/modules/arkeology.tools.reconcile.md` § reconcile_index — the rebuild reading both fields from the annotation and writing back only the capped `commit_refs` (R1, R3, R4).
- `docs/contracts/modules/arkeology.tools.read.md` § read_artifact — both link fields returned from the annotation, complete (R2, R5, R6).
- `docs/contracts/modules/arkeology.tools.list.md` § list_artifacts — the `commit_refs` filter over the capped window, and the link fields returned from the annotation under `include_links` (R2, R6).
- `docs/contracts/modules/arkeology.tools.propose_commit_links.md` § propose_commit_links — eligibility from the annotation, concurrent per-candidate reads, the error codes, the gone-object drop and the required `s3` (R9–R11).

### Testing Approach

**TDD cycle — test file before the implementation file it gates:**

1. **`test_artifact.py` → `artifact.py`** — `cap_commit_refs_for_vectors` unit tests for the boundary (exactly 20 unchanged, 21 → last 20, 0 → `[]`).
2. **`test_tools_write.py` → `write.py`** — fresh write and overwrite (read-forward) paths: `references` supplied but absent from vector metadata (present in annotation, via spy/fixture read); `commit_refs` with >20 entries after merge → vector metadata has exactly the last 20, annotation has the full list.
3. **`test_tools_link_metadata.py` → `link_metadata.py`** — same two assertions via `link_metadata`'s batch-write path.
4. **`test_tools_reconcile.py` → `reconcile.py`** — an artifact whose annotation carries >20 `commit_refs` entries and a non-empty `references` → after reconcile, rebuilt vector metadata has the capped `commit_refs` and no `references` key.
5. **Regression pass** — run the full existing Phase 12 unit suite and update every assertion that encoded the old (uncapped, dual-field) vector-metadata shape.
6. **`test_tools_propose_commit_links.py` → `propose_commit_links.py`** — seed a multi-section artifact whose `commit_refs` live on a section vector that does not sort first among its keys; call `propose_commit_links`; assert the artifact is excluded from `proposed`. Separately, seed an artifact whose annotation-backed `commit_refs` has more than 20 entries (so its vector-metadata copy is capped per R4); assert it is still excluded from `proposed`. Assert an artifact with no `commit_refs` annotation still appears in `proposed`. For a per-candidate read on an already-linked candidate, assert a `CredentialError` returns `credential_error`, an `AnnotationUnavailableError` returns `annotation_unavailable`, and any other exception returns `internal_error` — each with no `proposed` list; and assert an `ObjectNotFoundError` leaves the call successful with that candidate absent from `proposed`.

Use `aws_mock`, `s3_client`, `vectors_client_*` fixtures; `FakeBedrockClient` for embeddings. The 20-entry cap boundary itself needs no real-AWS call to unit-test (it is a local slice, not a byte measurement) — the calibration that justified the number is already captured in `tests/integration/test_calibration_vector_metadata_budget.py` (adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal D2, OQ2 closed) and is not re-run by this task.
