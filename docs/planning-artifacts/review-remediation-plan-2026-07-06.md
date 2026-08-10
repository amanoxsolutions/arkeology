---
type: plan
title: Review Remediation Plan (2026-07-06)
description: Actionable, pick-up-later plan for the still-open findings across the five 2026-07-02/07-04 reviews, verified against merged main on 2026-07-06 and grouped into fixable clusters plus the design decisions that gate them.
tags: [review, remediation, phase-12]
timestamp: 2026-07-06T00:00:00Z
okf_version: "0.1"
---

# Review Remediation Plan (2026-07-06)

## Purpose & state

Consolidates every **still-open** finding from the five most recent reviews into an ordered,
dependency-aware backlog so a future session can pick it up without re-deriving anything. The
findings were **re-verified against merged `main` (`a4cf881`) on 2026-07-06** by three read-only
agents; only the confirmed-still-valid items are listed here.

- **Verification: complete.** **Fixes: in progress** — all four design-gated findings (M3, M4, M5,
  CA-5), FC-1, and FC-2 are landed; FC-3/FC-4/FC-5/FC-6 remain. Per-finding status is tracked in the
  `Status` column of each cluster table below, and per-cluster status in each section's `Status` line.
- Work now lands directly on `main` (trunk-based, per AGENTS.md), commit-per-cluster — the earlier
  `review-followup-2026-07-06` branch noted below was merged and deleted:
  - `7a697dd` — M3 (ETag compare-and-swap) + M4 (`references` replace / `commit_refs` union).
  - `63e5665` — FC-1 link-storage integrity (M1, M2, M9, M10, M13).
  - `2aa1633` — M5 (cross-scope reference filtering) + CA-5 (synthesise response-size budget).
  - `1d554c2` — FC-2 search/write validation correctness (07-02 #2/#3/#4/#5/#7/#13).
  Each passed the full quality gate and an independent code review with no defects left open (1101
  unit tests green at `1d554c2`). The one other attempted fix — minor #38 — was found not applicable
  (see below). The standalone design-decision spec these four items were implemented against
  (`review-followup-2026-07-06-design-fixes.md`) has since been folded into the per-task specs that
  reference it and retired.
- Working method when resumed: **TDD**, full quality gate before each commit
  (`uv run pytest tests/unit/ -q -m 'not integration'`, `ruff check`, `ruff format --check`,
  `mypy src/`), **commit-per-cluster**, no push until asked. Prior cycles used developer =
  `claude-sonnet-5`, tech-writer = `claude-sonnet-4-6`.

## Source reviews

- `docs/reviews/review-2026-07-02-full-project-review.md` — Critical + 16 Major all resolved; **~37 Minor still open** + CA-5.
- `docs/reviews/review-2026-07-04-phase-12-full-review.md` — **master** for Phase 12; C1–C6 + M6/M11 resolved; **majors + minors still open** below.
- `docs/reviews/review-2026-07-04-t46-t47-t55-write-path.md`, `…-t49-t50-link-metadata-referenced-by.md`, `…-p12-t48-t51-t53-t54-cluster.md` — cluster inputs, fully subsumed by the master (each carries a 2026-07-06 mapping note).

## Already closed since the reviews (for the record — do NOT re-open)

Phase-12 **M7** (invalid IAM `"Comment"`, via M-15), **M12** (ADR-011 D4 tier-2 scoping), **SA-3(c)**
(`test_tools_link_metadata.py`, via M-16); Phase-12 minors **2/6/8/11**; 07-02 minor **#35** partially
(batch-chunk + document-fallback tested; `nextToken` multi-page still open).

**Minor #38 (unparenthesized `except A, B:`) — RECLASSIFIED NOT APPLICABLE / WON'T-FIX.** The repo
declares `requires-python = ">=3.14"` and the mandatory `ruff format` gate *enforces* the
unparenthesized PEP 758 form as canonical for that target; parenthesizing permanently fails
`ruff format --check`. The finding's "breaks pre-3.14 tooling" premise does not apply to a repo that
intentionally requires 3.14+. No change to make.

---

## Design decisions (✅ ALL DECIDED 2026-07-06 — operator sign-off complete)

> **Decisions locked (2026-07-06):**
> - **M3 → FIX via optimistic concurrency (ETag compare-and-swap).** On every durable read-modify-write
>   (`write.py` overwrite, `link_metadata`, `archive` status re-PUT): capture the object ETag on read;
>   `PutObject(IfMatch=ETag₀)` → new ETag₁; annotation writes use `PutObjectAnnotation`/`DeleteObjectAnnotation`
>   with `ObjectIfMatch=ETag₁`. On `412 PreconditionFailed` → bounded CAS retry (re-read → re-merge → re-write,
>   ~3 attempts) → else structured `conflict` error. Vector writes stay unconditional (no S3 Vectors CAS surface
>   exists — verified) and are the recoverable/derived copy, healed by `reconcile_index` from the guarded
>   annotations; on content-change paths the vector write is already serialized by the upstream object CAS.
>   **Accepted residual (document in ADR-011):** two simultaneous `link_metadata` calls modifying the *same field*
>   of the *same artifact* (neither changes the object, so `ObjectIfMatch` can't distinguish them) — narrow;
>   different-field concurrent calls are already safe. Research basis: AWS "Building multi-writer applications on
>   S3 using native controls" (If-Match/ETag optimistic-locking, Scenario 3) + botocore 1.43.36 confirming
>   `PutObject.IfMatch` and `PutObjectAnnotation.ObjectIfMatch`; S3 Vectors `PutVectors` has no conditional param.
> - **M4 → `references` = plain REPLACE mirroring the frontmatter; `commit_refs` stays UNION/accretive.**
>   `references` is set to exactly the (resolved) frontmatter list on every write — additions, removals, and swaps
>   all mirrored; **a write supplying no references CLEARS the field** (operator-confirmed intended). Body-text
>   references not in frontmatter are ignored (not cairn's job). No separate removal primitive needed (removal =
>   edit frontmatter + rewrite). `commit_refs` is a git audit trail, not in the frontmatter, backfilled by
>   `link_metadata` — it must be read-forward/preserved on overwrite. This makes the two fields **asymmetric**,
>   reversing the **D12 "one uniform mechanism"** decision (recorded in **ADR-011 decision 1**, with a
>   companion value-semantics note in ADR-012 — the plan's earlier "ADR-012 D12" phrasing was a
>   misattribution the architect corrected). Fix the C5 "union-of-both is lossless" wording to note
>   `references` intentionally follows the frontmatter and may shrink.
> - **M5 → FILTER references on cross-scope read (option 1).** When `references` are returned to a foreign reader
>   (`read_artifact` and `list_artifacts`), drop any entry the reader could not independently read (i.e. not
>   itself tier-3 shared). Filtering runs only on cross-scope reads (own-scope hot path untouched); `list` batches
>   the tier/visibility lookup with one `$in` query to avoid N×M; missing/unresolvable entry → treat as
>   not-readable → strip. Reopens ADR-012's "closed as not applicable" leakage note. Keeps the server's read
>   surface internally consistent with its own tier/visibility gate.
> - **CA-5 → ADD a response-size (byte) budget to `synthesise_artifacts` (option 1).** Assemble results in rank
>   order until the next would exceed a configurable byte budget, then stop and signal (`truncated: true` +
>   included count). Keep the count as a cheap secondary guard. Default budget generous enough that normal
>   ~10-artifact syntheses never trip it — final number set in the spec. Retrofit FR-19 + NFR-02 wording.

These are recorded here as locked; the ADR-011/ADR-012 revisions, PRD FR retrofits, and a consolidated
implementation spec are authored next (Architect), then the code clusters implement against them.

| ID | Question | Options | Recommendation |
|----|----------|---------|----------------|
| **M3** | Lost-update race on every merge-read-modify-write (`write.py` overwrite read-forward, `link_metadata.py`) — concurrent ops silently drop each other's links; no conditional writes, undocumented. | (a) document a single-writer assumption in ADR-011; (b) add conditional writes (If-Match/versioning). | (a) document — matches current low-concurrency reality; revisit if multi-writer becomes real. |
| **M4** | `references` on overwrite is force-union-merged, so a stale/typo'd reference can never be shed; no removal primitive; conflates audit-trail `commit_refs` (accretion correct) with `references` (a claim about *current* outbound links). | (a) keep union; (b) replace-semantics for `references` on overwrite; (c) add a removal mode to `link_metadata`. | (b)+(c): replace `references` on content overwrite, keep `commit_refs` accretive; add removal to `link_metadata`. Needs ADR-012 revision. |
| **M5** | Cross-team `references` leakage: `validate_references` checks control chars only, so callers can write arbitrary/computable foreign tier-2 ids; and `references` is returned cross-scope on shared tier-3 artifacts, exposing the author team's hidden tier-2 slugs. | (a) accept + document explicitly; (b) validate/resolve entries at write time; (c) filter foreign-unreadable entries from cross-scope reads. | (c) as the real fix (+ (a) as the interim documented acceptance). Re-opens ADR-012 "closed as not applicable". |
| **CA-5** | `synthesise_artifacts` ceiling of 100 full-content artifacts contradicts the bounded-payload principle (NFR-02); default 10 is fine, ceiling is not. | (a) lower the ceiling; (b) add a response-size budget; (c) accept. | (b) response byte budget (keeps the count flexible, bounds the payload). |

---

## Fix clusters (dispatchable once design items above are settled where noted)

**Status legend:** ✅ `done` (landed + independently reviewed clean) · ⬜ `todo` (not started) ·
🚧 `blocked` (needs something unavailable — e.g. live AWS credentials) · ⛔ `wontfix` (verified not
applicable). Update both the per-finding `Status` cell and the cluster `Status` line when work lands.

### FC-1 — Link-storage integrity  *(developer; highest value — silent data-loss / migration no-ops)*

**Status: ✅ done** — 5/5 findings fixed in `63e5665`; full quality gate green, independent review clean.

| Finding | Location | Fix | Status |
|---------|----------|-----|--------|
| **M1** | `tools/write.py` annotation block; `clients/s3.py::put_object_annotation` re-raises non-annotation-unavailable | A transient/non-credential annotation `ClientError` (SlowDown/timeout) escapes to the blanket handler → orphaned S3 object, zero vectors, **no failure-log entry**. Degrade unknown annotation exceptions to warn+continue, or append a failure-log entry (M-4 fixed only the credential branch). | ✅ done (`63e5665`) — unknown annotation `ClientError` now returns `partial_write` + failure-log entry at both the fresh-create and overwrite/CAS call sites |
| **M2** | `annotations.py::encode/decode_link_list`; `artifact.py::validate_commit_refs/validate_references` | Comma in a link-list element diverges the two stores (comma-join encoding). Reject `,` in elements, or switch the annotation payload to a JSON array. | ✅ done (`63e5665`) — literal `,` in any element rejected as `validation_error`; comma-join encoding kept |
| **M9** | `tools/link_metadata.py`; `annotations.py::_read_vector_link_fields` | No value validation (empty/whitespace/comma pass; `[""]` diverges stores) — strip/reject. Annotation-read samples only `keys[0]`; union across all section vectors. (items[0] *write*-collapse already fixed.) | ✅ done (`63e5665`) — values validated up front; vector link read now unions across all section vectors |
| **M10** | `clients/s3.py::put_object_annotation`; `tools/link_metadata.py` loop | `put_object_annotation` lacks the `NoSuchKey→KeyError` map its siblings have → orphaned-vector artifact aborts the whole batch as `internal_error`, all accounting lost. Map + skip-and-count. | ✅ done (`63e5665`) — `NoSuchKey`/404 → `KeyError`; loop skips-and-counts instead of aborting the batch |
| **M13** | `references.py::build_path_to_id_map` | Keys the map on raw `entry["path"]` (no `normalize_reference_path`) → a `./`- or backslash-spelled manifest path matches nothing → migration rewrite silent no-op. Normalize map keys. | ✅ done (`63e5665`) — map keyed on `normalize_reference_path(entry["path"])` |

### FC-2 — Search / write validation correctness  *(developer; small, high-confidence)*

**Status: ✅ done** — 6/6 findings fixed in `1d554c2`; full quality gate green (1101 unit tests),
independent review clean after one Major fix (see below).

| Finding | Location | Fix | Status |
|---------|----------|-----|--------|
| 07-02 **#3** | `tools/write.py` / `write_artifacts.py`; `generate_artifact_id::_require_valid_tier` | String `tier:"2"` → uncaught `ValueError` → `internal_error`. Return `validation_error`. | ✅ done (`1d554c2`) — `Artifact.tier` now `Field(strict=True)`, rejecting non-int (incl. numeric-string and bool) tier values as `validation_error` in both single and batch write paths |
| 07-02 **#4** | `search.py`, `synthesise.py`, `server.py` params | `top_k <= 0` unvalidated → negative slices. Add `ge=1` guard. | ✅ done (`1d554c2`) — explicit floor check on `top_k`/`requested_top_k` before the `min(..., 100)` clamp in both tools, returning `validation_error` |
| 07-02 **#5** | `_search_helper.build_user_filters`, `list.py` | Filter enum values (type/status/tier) unvalidated → typos silently return empty. Validate against `ARTIFACT_TYPES`/status/tier enums → `validation_error`. | ✅ done (`1d554c2`) — new `InvalidFilterValueError` + `VALID_TIERS` constant; `build_user_filters` validates `type`/`tier`, `search.py`/`list.py` validate `status` via `ArtifactStatus(status)` (preserving `list.py`'s `status="all"` sentinel) |
| 07-02 **#7** | `search.py` (`SEARCH_FETCH_TOP_K` × `SEARCH_MAX_ITERATIONS` = 75) | Advertised `top_k=100` unreachable at defaults, no truncation signal. Signal when the loop exhausts below the requested count, or correct the docstring. | ✅ done (`1d554c2`) — `run_search_loop` now returns `(results, fetch_exhausted)`; `search.py` surfaces `fetch_exhausted: True` when the fetch budget (iteration cap, `$nin` cap, or a non-credential mid-loop failure) truncates results before `top_k` is reached, mirroring the `clamped` field convention |
| 07-02 **#13** | `search.py`, `synthesise.py` (`int(meta["tier"])`) | Hard `KeyError` on a vector missing `tier` while `list.py` is defensive (`meta.get("tier", 0)`). Make search/synthesise defensive. | ✅ done (`1d554c2`) — both now use `int(meta.get("tier", 0))`, matching `list.py` |
| 07-02 **#2** | `write.py` vector key `{s3_key}#{section_slug}`; `_section_pipeline.py` | Duplicate H2 headings collapse to one vector key → `sections_indexed` under-reports. Disambiguate duplicate slugs or count pre-dedup. | ✅ done (`1d554c2`) — new `disambiguate_section_slugs()` shared helper in `_section_pipeline.py`, applied in both `write.py` and `reconcile.py` to keep the two vector-key constructions in sync |

### FC-3 — Client / config / robustness minors  *(developer)*

**Status: ⬜ todo** — 0/25 findings fixed. The M5 / CA-5 fold-in noted in the resume order is already done (`2aa1633`), so this cluster is unblocked.

| Finding | Item | Status |
|---------|------|--------|
| 07-02 **#8** | `WRITE_PREFIX` validation weaker than `READ_PREFIXES` (`config.py`) | ⬜ todo |
| 07-02 **#9** | fixed startup probe key → concurrent-server race (`startup.py`) | ⬜ todo |
| 07-02 **#10** | check 3 proves only `ListBucket` | ⬜ todo |
| 07-02 **#11** | check 1 conflates missing bucket vs bad creds | ⬜ todo |
| 07-02 **#14** | `coerce_list_field` used in delete but not purge/freshness | ⬜ todo |
| 07-02 **#15** | `zero_results` asymmetry; synthesise silently drops failed reads | ⬜ todo |
| 07-02 **#17** | `get_vectors` `returnData=True` wastes float arrays for metadata-only reads; freshness 1+N | ⬜ todo |
| 07-02 **#18** | 300-thread executor at import (`write.py`) | ⬜ todo |
| 07-02 **#19** | failure log: no lock/rotation, cwd-relative default path | ⬜ todo |
| 07-02 **#20** | percent-decode mangles legacy `%XX` | ⬜ todo |
| 07-02 **#21** | `_URL_PREFIXES` case-sensitive (`references.py`) | ⬜ todo |
| 07-02 **#20** (`filter.py`) | `filter` shadows builtin | ⬜ todo |
| 07-02 **#21** (`filter.py`) | unsupported op raises mid-pagination | ⬜ todo |
| 07-02 **#22** (`filter.py`) | mixed-type comparison `TypeError` | ⬜ todo |
| 07-02 **#31** (`resources.py`) | newline in description corrupts `cairn://artifacts` table | ⬜ todo |
| 07-02 **#32** (`resources.py`) | typo "cairn studio— visual" | ⬜ todo |
| 07-02 **#37** | raw boto messages — bucket/index names — leak to MCP callers | ⬜ todo |
| Phase-12 **#15** | `decode_link_list` keeps interior empty segments | ⬜ todo |
| Phase-12 **#16** | non-UTF-8 annotation → unclassified `UnicodeDecodeError` | ⬜ todo |
| Phase-12 **#17** | `link_metadata` `annotation_unavailable` discards partial `linked`/`skipped` counts | ⬜ todo |
| Phase-12 **#18** | `apply_link_annotations` issues 2 pointless deletes per fresh write + warns on annotation-less deployments | ⬜ todo |
| Phase-12 **#19** | `json.dumps` defaults over-count budget — use `ensure_ascii=False, separators=(",",":")` | ⬜ todo |
| Phase-12 **#23** | duplicate manifest paths last-win silently | ⬜ todo |
| Phase-12 **#27** | `find_referrers` = 2 full-index scans per delete/archive — merge to one; ties to Phase-12 #17 | ⬜ todo |
| Phase-12 **#12** (informational) | `SEARCH_FETCH_TOP_K le=100` — the real QueryVectors topK cap is 10 000 (confirmed by `test_top_k_over_documented_cap_is_rejected`); just annotate the bound's provenance | ⬜ todo |

### FC-4 — Studio UI hardening  *(developer; part enhancement — `static/cairn-studio.html`)*

**Status: ⬜ todo** — 0/8 findings fixed.

| Finding | Item | Status |
|---------|------|--------|
| **#23** | `tier` unescaped in list rows — `renderList` | ⬜ todo |
| **#24** | prototype-chain type-map lookups → `Object.create(null)`/`Map` | ⬜ todo |
| **#25** | pin `marked`/`mermaid` CDN versions like the SDK/DOMPurify | ⬜ todo |
| **#26** | stale-response race — guard `selectArtifact` with `if (selectedId !== id) return` | ⬜ todo |
| **#27** | `doSearch` ignores active facet filters — forward `filterType/Tier/Status` | ⬜ todo |
| **#28** | no pagination for large stores | ⬜ todo |
| **#29** | theme toggle re-downloads the artifact | ⬜ todo |
| **#30** | `studio.py` fallback `structured_content` returns the whole unbounded listing | ⬜ todo |

### FC-5 — Missing tests  *(developer; some need real AWS)*

**Status: 🚧 partly blocked** — 0/9 findings fixed. The two SA-3 integration round-trips need live AWS
credentials (SSO session was expired on 2026-08-07 — run `aws sso login` before dispatching those);
the remaining 7 are unit-level and can proceed without AWS.

| Finding | Item | Status |
|---------|------|--------|
| **SA-3(a)** | T47 integration: real-AWS write→backfill→overwrite→annotation-survives round-trip (`tests/integration/test_tools_write.py`) | 🚧 blocked — needs live AWS |
| **SA-3(b)** | T48 integration: backfill→drop vectors→`reconcile_index` restores both link fields (`tests/integration/test_tools_reconcile.py`) | 🚧 blocked — needs live AWS |
| **M14** | unit test for `list_object_annotations` `ContinuationToken` pagination (currently dead code under tests) | ⬜ todo |
| 07-02 **#35** | `nextToken` multi-page test for `list_vectors_by_metadata` | ⬜ todo |
| 07-02 **#36** | assert `register_tools` registers the full tool set | ⬜ todo |
| Phase-12 **#26** | remaining: list-on-missing-object; orphaned-vector-skip (ties to M10) | ⬜ todo — orphaned-vector-skip test landed with M10 in `63e5665`; list-on-missing-object still open |
| 07-02 **#33** | replace the 5 `set_credential_failure` call sites with `mocker.patch.object(..., side_effect=CredentialError)` and delete the deprecated method from `fake_bedrock.py` | ⬜ todo |
| Phase-12 **#24** | add an autouse fixture to reset `_ANNOTATION_STORE` between tests (`conftest.py`) | ⬜ todo |
| 07-02 **#34** | replace the brittle `inspect.getsource` substring assertion (`test_tools_migrate_artifacts.py`) | ⬜ todo |

### FC-6 — Docs / hygiene  *(tech-writer)*

**Status: ⬜ todo** — 0/13 findings fixed. Now also owns the CHANGELOG entries for the three landed code
commits (`7a697dd`, `63e5665`, `2aa1633`), which deliberately left `CHANGELOG.md` untouched — see #10.

| Finding | Item | Status |
|---------|------|--------|
| Phase-12 **#1** | brainstorming still lists OQ3 pending + retired sweep item | ⬜ todo |
| Phase-12 **#3** | `plan.md` "open — planning" vs "all implemented"; T55 "Spec: to be written" though the spec exists | ⬜ todo |
| Phase-12 **#4** | T53 Files-to-Touch describes the pre-consolidation symlink layout | ⬜ todo |
| Phase-12 **#5** | T54/T55 cite gitignored `.docs/` as provenance | ⬜ todo |
| Phase-12 **#7** | T55 lists `title`/`author_role` in both filterable and non-filterable | ⬜ todo |
| Phase-12 **#9** | stale `link_commit` comment in `tests/unit/test_tools_read.py` | ⬜ todo |
| Phase-12 **#10** | CHANGELOG `[Unreleased]` empty despite the breaking `link_commit`→`link_metadata` removal | ⬜ todo — must now also cover M3/M4 (`7a697dd`), FC-1 (`63e5665`), M5/CA-5 + new `SYNTHESISE_MAX_RESPONSE_BYTES` setting (`2aa1633`) |
| Phase-12 **#12** | "S3 Express One Zone" double-counts "directory buckets" across README/SERVER-REFERENCE/ADR/credentials.py/PRD/brainstorming | ⬜ todo |
| Phase-12 **#14** | FR-51–58 what-not-how violations + FR-54 duplicates ADR-011 §1 → dual-maintenance | ⬜ todo |
| Phase-12 **#22** | skills reimplement `generate_artifact_id` twice with no drift test — add a drift test or single-source it | ⬜ todo |
| Phase-12 **#8** | style residue ("D4" shorthand vs "decision 5") | ⬜ todo |
| **M8** | straddles code+doc: the `setting-up-cairn` aws-cli probe path has no always-run cleanup, and the probe key isn't excluded by `reconcile.py`'s orphan scan (only `_cairn_health_probe`/`_cairn_mcp_startup_probe` are). Fix = reserved non-artifact prefix + reconcile exclusion (code) + always-run cleanup instruction (skill) | ⬜ todo |
| **#13** (concept) | mixed addressing (D3) has no documented consumer — `cairn://` links render dead in the studio app; specify read-surface treatment (or make the studio resolve `cairn://` — overlaps FC-4) | ⬜ todo |

## Suggested order when resumed

1. ✅ **done** — Settle the **design decisions** (M3, M4, M5, CA-5) — architect memo → operator sign-off.
   Implemented in `7a697dd` (M3, M4) and `2aa1633` (M5, CA-5).
2. ✅ **done** — **FC-1** (link-storage integrity), highest value; M4 outcome folded in. `63e5665`.
3. ✅ **done** — **FC-2** (search/write validation). `1d554c2`.
4. ⬜ **next** — **FC-3** (robustness minors) — the M5 and CA-5 fold-in is already done, so no longer
   gated.
5. 🚧 **FC-5** (tests) — the 7 unit-level items can run now; the two SA-3 integration round-trips need a
   live-AWS run (`aws sso login` first — the session was expired on 2026-08-07).
6. ⬜ **FC-4** (studio) and **FC-6** (docs) — parallelisable, lower risk. FC-6 now also owns the CHANGELOG
   entries for the four landed code commits (M3/M4, FC-1, M5/CA-5, FC-2).

## Cross-references

- Full per-finding evidence: the five review files' Findings sections + their 2026-07-06 verification notes.
- Related deferred design-first backlog items: **B-5** (hard cross-scope boundary, relates to M5), **B-6** (recency-weighted ranking). See `backlog.md`.
