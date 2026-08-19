---
type: spec
title: T58 — commit_refs Vector-Metadata Cap (20) + references Vector-Metadata Removal + propose_commit_links Multi-Section Fix
description: Stop writing references into S3 Vectors metadata entirely across write.py, link_metadata.py, and reconcile.py — the S3 object annotation copy becomes its sole durable store and sole read surface. commit_refs stays in S3 Vectors metadata, filterable, but capped to the most-recently-appended 20 entries (real-AWS-calibrated; AWS accepts up to 36 entries for this payload shape, rejects 37); the complete, uncapped list remains durable in annotations regardless of the cap. Also fixes a related gap: propose_commit_links.py sources commit_refs from a single, first-occurrence-wins vector per artifact instead of annotations.read_current_link_fields, which the new cap would otherwise silently worsen (older commit refs beyond 20 would drop out of its already-incomplete view too) — by routing it through the same union-of-both-stores helper read.py/list.py already use.
tags: []
timestamp: 2026-08-17T00:00:00Z
okf_version: "0.1"
feature: p12-t58-commit-refs-cap-references-removal
status: ready
phase: 12
task: 58
references:
  - docs/architecture-decisions/adr-2026-08-13-vector-metadata-budget-hardening-and-self-heal.md
  - docs/specs/p12-t57-guard-coverage.md
  - docs/specs/p12-t46-references-field.md
  - docs/specs/p12-t47-annotation-dual-write.md
  - docs/specs/p12-t48-reconcile-from-annotations.md
  - docs/specs/p12-t55-metadata-validation.md
  - docs/learnings.md
  - tests/integration/test_calibration_vector_metadata_budget.py
authored:
  by: "architect"
  date: "2026-08-17"
---

# T58 — `commit_refs` Vector-Metadata Cap (20) + `references` Vector-Metadata Removal + `propose_commit_links` Multi-Section Fix

<!-- SCOPE BLOCK — frozen after approval -->

## TL;DR

This is the operator's locked, structural fix (ADR D2), not a tuning fix: `references` is removed from S3 Vectors metadata entirely — the S3 object annotation copy (ADR-011) becomes its sole durable store and sole read surface. `commit_refs` keeps its load-bearing `$eq` filterability (`list.py`'s `commit_refs=[...]` filter) but its vector-metadata copy is capped to the most-recently-appended **20 entries** — real-AWS-calibrated (AWS accepts up to 36 entries for this payload shape, rejects 37; 20 leaves deliberate headroom, see `docs/learnings.md`, 2026-08-13). The complete, uncapped `commit_refs` list remains durable in annotations regardless of the vector-side cap — the cap is a representation change, never a data-loss or write-rejection event. (ADR D2.)

Folded into the same spec: `propose_commit_links.py` currently decides whether an artifact is "not yet linked" by reading `commit_refs` off a single, first-occurrence-wins vector per artifact, instead of calling `annotations.read_current_link_fields` (the union-of-both-stores helper `read.py`/`list.py` were already fixed to use for the identical bug class). The 20-entry cap this task introduces makes that gap strictly worse: a `propose_commit_links` caller reading a single vector's now-additionally-capped `commit_refs` copy can miss both a value that lives on a different section vector (the pre-existing bug) and a value that has aged out of that vector's capped window (a new way to hit the same symptom). This task routes `propose_commit_links.py` through `read_current_link_fields` so both gaps close together, rather than shipping a cap that measurably worsens a known, already-flagged bug.

## Problem Statement

`references` is a filterable list field in vector metadata today (T46), counted against the 2 KB filterable-metadata budget alongside `commit_refs`, `tags`, and every other filterable key. The operator judged `references`'s native `$eq`/`$in` filtering (`list_artifacts(references=[...])`, the `references`-half of the delete/archive reverse-lookup) a nice-to-have, not load-bearing, at the project's current stage — so rather than tuning the byte-budget threshold (which only narrows, not eliminates, the overflow failure mode for a genuinely large list), the operator chose to retire `references` from the vector store outright. `commit_refs` is different: `list_artifacts(commit_refs=[...])` is a shipped, load-bearing filter, so it must stay filterable — but its list is append-only and unbounded (backfilled repeatedly by `link_metadata` over an artifact's lifetime), and the 2026-08-13 real-AWS calibration proved the local byte-budget approximation under-measures AWS's real per-entry accounting for this exact field shape by enough to make an unbounded list a real, repeatable failure mode, not a hypothetical one. A hard, calibrated entry-count cap on the *vector-metadata copy only* closes this permanently, without touching the byte-budget guard itself (T55's constants are unchanged by this task — this is a structural fix, not a threshold tuning) and without losing any data, because the annotation copy stays uncapped.

Three call sites currently write `references` into vector metadata and write an uncapped `commit_refs` into vector metadata: `write.py` (fresh-create Step 3b, and the overwrite CAS loop), `link_metadata.py` (its per-vector batch-write loop), and `reconcile.py` (`_reindex_artifact`'s rebuild). All three must change together, or the split-store contract is inconsistent depending on which path last touched an artifact.

A fourth site, `propose_commit_links.py`, only *reads* `commit_refs` (it makes no writes), but its read is the same "first-vector-only" mistake `read.py` and `list.py` were already fixed for: it dedups `items` by `artifact_id` with first-occurrence-wins, then reads `commit_refs` directly off that one vector's `meta` to decide eligibility, instead of calling `read_current_link_fields` to get the union across every section vector plus the annotation. A multi-section artifact whose `commit_refs` were set on a section vector other than the one that sorts first is silently re-proposed as "not yet linked," even though it already carries `commit_refs` everywhere else in the system. This task's cap makes the failure mode strictly wider — the vector-metadata copy `propose_commit_links.py` reads from is now also entry-capped — so the fix is folded in here rather than left open while this task ships a cap on top of it.

## User Stories

### Story 1 — `references` never appears in vector metadata after any write path (P1)

**Acceptance criteria:**
- Given `write_artifact` is called with a non-empty `references` value (fresh create or overwrite), when the write completes then the S3 object annotation carries the full `references` value, but no `references` key is present in any written vector's metadata.
- Given `link_metadata` is called with a non-empty `references` value, when the call completes then the merged value is written to the S3 annotation, but no `references` key is present in any vector written by `put_vectors_batch`.
- Given `reconcile_index` re-indexes an artifact whose annotation carries `references`, when the rebuild completes then no `references` key is present in the rebuilt vector metadata — the value remains readable only via the annotation.
- Given any of the above, `read_artifact` and `list_artifacts` still return the artifact's correct `references` value — they already source it from `read_current_link_fields` (the union of both durable stores), so removing the vector-side copy has no effect on what a reader sees; the annotation side alone now supplies it. (No change required in `read.py` or `list.py`'s per-entry field sourcing.)

### Story 2 — `commit_refs` vector-metadata copy capped at 20, full list stays in annotations (P1)

**Acceptance criteria:**
- Given an artifact whose full `commit_refs` list (after read-forward/merge) has 21 or more entries, when written by any of the three paths, then the write succeeds — never rejected for entry count alone — and the vector metadata carries only the **most-recently-appended 20** entries.
- Given the same artifact, when its S3 annotation is read (directly, or via `read_current_link_fields`/`read_artifact`), then it carries the **complete, uncapped** `commit_refs` list — nothing is ever dropped from the durable copy.
- Given an artifact whose full `commit_refs` list has 20 or fewer entries, when written, then the vector-metadata copy is identical to the full list — the cap never truncates a list that already fits.
- Given `commit_refs` is empty after merge, when written, then the `commit_refs` key is omitted from vector metadata exactly as today (existing S3-Vectors empty-array rule, unaffected by this task).
- Given `list_artifacts(commit_refs=["<sha>"])` is called for a SHA that falls outside an artifact's most-recent 20 (i.e. it was pushed out of the vector-side window by later appends), then that artifact does **not** appear in the filtered results — this is the accepted, documented capability narrowing of this task (see Consequences below); `read_artifact`'s returned `commit_refs` list is unaffected (still complete, from annotations).

### Story 3 — Existing dual-field, uncapped vector-metadata contract updated (P1)

**Acceptance criteria:**
- Given the existing unit test suite asserts the pre-T58 shape (both `commit_refs` and `references` present and uncapped in vector metadata after write/link/reconcile), when this task lands then those assertions are updated to the new contract — no test is left asserting a shape the implementation no longer produces.

### Story 4 — `propose_commit_links` sources eligibility from the union of both stores, not one vector (P1)

**Acceptance criteria:**
- Given a multi-section artifact whose `commit_refs` were set (via `link_metadata`) on a section vector other than the one `propose_commit_links`' internal dedup currently keeps (i.e. not the first-occurrence vector by whatever order `get_vectors` returns), when `propose_commit_links` runs, then that artifact is correctly excluded from `proposed` (it is already linked) — not silently re-proposed.
- Given an artifact whose full `commit_refs` list (from annotations) has more than 20 entries, so its vector-metadata copy is capped per this task's Story 2, when `propose_commit_links` runs, then the artifact is still correctly excluded from `proposed` — eligibility is decided from the annotation-backed, uncapped union (`read_current_link_fields`), never from a vector's capped copy.
- Given an artifact with genuinely no `commit_refs` in either store, when `propose_commit_links` runs, then it still appears in `proposed` exactly as today — this story changes no passing-case behaviour.
- Given a `CredentialError` while resolving `commit_refs` for a candidate, when `propose_commit_links` runs, then the call returns the existing structured credential-error response, matching how the tool already handles `CredentialError` from its initial `list_vectors_by_metadata`/`get_vectors` calls.

## Requirements

- WHEN `write.py`, `link_metadata.py`, or `reconcile.py` assemble vector metadata to be written THE SYSTEM SHALL NOT set a `references` key on it, under any circumstance — the field is removed from the vector-metadata representation entirely, not merely capped or conditionally included.
- WHEN any of the three paths assemble vector metadata AND the artifact's full (annotation-sourced or freshly supplied) `commit_refs` list is non-empty THE SYSTEM SHALL set the vector-metadata `commit_refs` key to the **last 20 elements** of that full list (`full_list[-20:]`) — never the full list itself, and never fewer than `min(len(full_list), 20)` entries.
- WHEN the full `commit_refs` list is empty THE SYSTEM SHALL omit the `commit_refs` key from vector metadata, exactly as today.
- WHEN any of the three paths write to the durable S3 annotation store (`apply_link_annotations`) THE SYSTEM SHALL continue to pass the **full, uncapped** `commit_refs` and `references` values — the cap applies to the vector-metadata representation only, never to the annotation write.
- WHEN the cap is applied THE SYSTEM SHALL use one shared constant and one shared helper function (added to `src/arkeology/artifact.py`, alongside the existing byte-budget constants) — e.g. `COMMIT_REFS_VECTOR_METADATA_MAX_ENTRIES = 20` and a `cap_commit_refs_for_vectors(commit_refs: list[str]) -> list[str]` helper returning `commit_refs[-COMMIT_REFS_VECTOR_METADATA_MAX_ENTRIES:]` — reused identically by all three call sites, rather than three independently-written slice expressions.
- WHEN the helper's docstring (and the `Artifact.commit_refs` field docstring) is written THE SYSTEM SHALL state explicitly that the vector-metadata copy is a bounded, most-recent-N view and is **not** a completeness guarantee — the annotation-backed copy is the only complete, authoritative representation of `commit_refs`.
- WHEN `reconcile.py`'s `_reindex_artifact` reads `read_current_link_fields` THE SYSTEM SHALL continue to read both `commit_refs` and `references` from it (the union-of-both-stores helper is unchanged — see `annotations.py`'s `_read_vector_link_fields`, which must keep reading a `references` key from vector metadata for backward-read compatibility with vectors written before this task ships, even though no path writes it going forward), but SHALL only place the capped `commit_refs` value into the rebuilt vector metadata.
- WHEN `propose_commit_links.py` has deduplicated its fetched vector items down to one distinct `artifact_id` per candidate (existing `seen_ids` logic, unchanged) THE SYSTEM SHALL determine each candidate's current `commit_refs` by calling `annotations.read_current_link_fields(s3, vectors, artifact_id)` (off the event loop, via `asyncio.to_thread`, mirroring `list.py`'s `_fetch_link_fields` pattern) rather than reading `meta.get("commit_refs")` off the single vector already in hand.
- WHEN resolving `commit_refs` for multiple candidates THE SYSTEM SHALL issue the per-candidate `read_current_link_fields` calls concurrently via `asyncio.gather(..., return_exceptions=True)`, matching `list.py`'s existing pattern for the same helper, rather than one sequential call per candidate.
- WHEN a per-candidate `read_current_link_fields` call raises `CredentialError` THE SYSTEM SHALL return the existing structured credential-error response for the whole call (matching how `propose_commit_links.py` already handles `CredentialError` from `list_vectors_by_metadata`/`get_vectors`).
- WHEN a per-candidate `read_current_link_fields` call raises any other exception THE SYSTEM SHALL degrade that one candidate's `commit_refs` to `[]` (treating it as not-yet-linked) rather than aborting the whole call — mirroring `list.py`'s existing degrade-on-error behaviour for the same helper, since a supplementary-field read failure for one candidate must not hide every other candidate's proposal.
- WHEN `propose_commit_links`'s `s3` parameter is required for this fix THE SYSTEM SHALL change its type from `S3ClientInterface | None = None` to a required `S3ClientInterface` — the server already injects a real `s3` client into every tool call (AGENTS.md: "Tool functions receive settings, s3, vectors, bedrock as injected dependencies"), so this narrows an already-always-satisfied signature rather than changing runtime wiring.

## Boundaries

**Always:**
- The byte-budget constants (`VECTOR_FILTERABLE_METADATA_MAX_BYTES`, `VECTOR_TOTAL_METADATA_MAX_BYTES`, `S3_USER_METADATA_MAX_BYTES`) are **unchanged** by this task — this is a structural representation fix (remove one field, cap another), not a threshold tuning (ADR D2, rejected Option A).
- The 20-entry cap and the 36/37-entry calibration boundary are **payload-shape-specific, not universal constants** — they were measured against today's specific filterable-metadata field mix and must be re-calibrated (a fresh run of `tests/integration/test_calibration_vector_metadata_budget.py`) if the set of filterable vector-metadata keys ever changes. Document this alongside the new constant, mirroring the existing warning in `docs/learnings.md`.
- The cap is applied at the **last** step before each path's vector write, using the already-fully-merged/read-forwarded `commit_refs` value — never applied earlier, and never applied to the value passed to the annotation write.
- T57's guard-coverage check (`check_metadata_budgets`) still runs in all three paths, unaffected by this task — it now simply measures a smaller payload (post-cap, post-removal) and continues to function as a defense-in-depth backstop for other filterable fields (e.g. `tags`), not as the mechanism that closes this specific overflow (ADR Consequences).
- `annotations.py`'s `read_current_link_fields`/`_read_vector_link_fields` keep reading a `references` key out of vector metadata (never assume it is absent) — a vector written before this task ships may still carry a stale `references` value, and the union-read must not lose it until that artifact is next reconciled or rewritten.
- `propose_commit_links.py`'s per-candidate `read_current_link_fields` calls are additional round trips beyond its existing single batched `list_vectors_by_metadata` + `get_vectors` fetch — the same accepted cost `list.py` and `read.py` already carry for the identical fix (a blocking S3 + vector round trip per distinct artifact_id, run off the event loop and in parallel via `asyncio.gather`, no new bounded-concurrency setting — the same proportionate-for-page-size reasoning `list.py`'s own comment already documents applies here).

**Ask First:**
- Nothing — the split-store decision, the 20-entry cap, and the "annotation is sole store for `references`" contract are all locked, operator-approved decisions (ADR D2, OQ2 closed by real-AWS calibration). The propose_commit_links fix shape (route through `read_current_link_fields`, mirroring `list.py`'s existing per-candidate fetch pattern) has no open design choice either — it is the same fix already applied twice elsewhere in this codebase for the identical bug class.

**Never:**
- Do not write `references` into vector metadata under any code path, including `reconcile.py`'s rebuild (a naive read of "restore both fields from the union" would re-introduce it — `read_current_link_fields` still *reads* the union for `references`, but the value must never be re-written to the vector side).
- Do not cap `references` instead of removing it — the ADR's D2 table considered and rejected "cap both fields" (Option B) specifically because it produces silent false negatives on `references`'s `$eq` filtering, a completeness regression the operator explicitly rejected.
- Do not tighten `VECTOR_FILTERABLE_METADATA_MAX_BYTES`/`VECTOR_TOTAL_METADATA_MAX_BYTES` as part of this task — that is a different, rejected alternative (ADR D2 Option A).
- Do not cap the value written to the S3 annotation — the annotation copy of `commit_refs` must always be the full, uncapped list; only the vector-metadata copy is capped.
- Do not duplicate the cap constant or slice expression in three files — use the single shared helper in `artifact.py`.
- Do not leave `propose_commit_links.py` reading `commit_refs` off a single vector's `meta` — that is precisely the bug this story closes; the dedup-by-`artifact_id` step (`seen_ids`) stays (it is still needed to build one candidate entry per artifact), only the source of the `commit_refs` eligibility check changes.

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

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
| `tests/unit/test_tools_propose_commit_links.py` | Modify | Tests: multi-section artifact whose `commit_refs`-bearing vector is not the first-occurrence one → correctly excluded from `proposed`; artifact whose full `commit_refs` exceeds the 20-entry vector-metadata cap → correctly excluded from `proposed` (eligibility from annotation, not the capped vector copy); artifact with no `commit_refs` in either store → still included; `CredentialError` during resolution → structured credential-error response — Red first |
| `src/arkeology/tools/propose_commit_links.py` | Modify | Import `read_current_link_fields` from `arkeology.annotations`; change `s3` parameter to required `S3ClientInterface` (drop `\| None = None` and the `_ = s3` no-op); replace the `raw_commit_refs = meta.get("commit_refs")` block with a per-`artifact_id` `asyncio.to_thread(read_current_link_fields, s3, vectors, artifact_id)` call, gathered concurrently via `asyncio.gather(..., return_exceptions=True)` across all deduplicated candidates, degrading a non-`CredentialError` failure to `commit_refs=[]` for that one candidate |

## Testing Approach

**TDD cycle — test file before the implementation file it gates:**

1. **`test_artifact.py` → `artifact.py`** — `cap_commit_refs_for_vectors` unit tests for the boundary (exactly 20 unchanged, 21 → last 20, 0 → `[]`).
2. **`test_tools_write.py` → `write.py`** — fresh write and overwrite (read-forward) paths: `references` supplied but absent from vector metadata (present in annotation, via spy/fixture read); `commit_refs` with >20 entries after merge → vector metadata has exactly the last 20, annotation has the full list.
3. **`test_tools_link_metadata.py` → `link_metadata.py`** — same two assertions via `link_metadata`'s batch-write path.
4. **`test_tools_reconcile.py` → `reconcile.py`** — an artifact whose annotation carries >20 `commit_refs` entries and a non-empty `references` → after reconcile, rebuilt vector metadata has the capped `commit_refs` and no `references` key.
5. **Regression pass** — run the full existing Phase 12 unit suite and update every assertion that encoded the old (uncapped, dual-field) vector-metadata shape.
6. **`test_tools_propose_commit_links.py` → `propose_commit_links.py`** — seed a multi-section artifact whose `commit_refs` live on a section vector that does not sort first among its keys; call `propose_commit_links`; assert the artifact is excluded from `proposed`. Separately, seed an artifact whose annotation-backed `commit_refs` has more than 20 entries (so its vector-metadata copy is capped per Story 2); assert it is still excluded from `proposed`. Assert an artifact with no `commit_refs` in either store still appears in `proposed`, and that a `CredentialError` raised from the per-candidate fetch produces the existing structured credential-error response.

Use `aws_mock`, `s3_client`, `vectors_client_*` fixtures; `FakeBedrockClient` for embeddings. The 20-entry cap boundary itself needs no real-AWS call to unit-test (it is a local slice, not a byte measurement) — the calibration that justified the number is already captured in `tests/integration/test_calibration_vector_metadata_budget.py` (D2, OQ2 closed) and is not re-run by this task.

## Open Questions

*(none — the split-store shape, the 20-entry number, and the removal of `references` are all locked, operator-approved decisions per ADR D2. The one implementation judgment this spec makes explicit — routing the cap through a single shared helper in `artifact.py` rather than three independent slice expressions — follows the project's existing single-source-of-truth convention and is not itself an open design question. The propose_commit_links fix shape mirrors `list.py`'s existing per-candidate `read_current_link_fields` fetch pattern exactly, so it carries no open design question either.)*
