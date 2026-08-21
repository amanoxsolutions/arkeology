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

- **Verification: complete. Fixes: complete (2026-08-12).** All four design-gated findings (M3, M4,
  M5, CA-5) and all six clusters (FC-1 through FC-6) are landed. Per-finding status is tracked in the
  `Status` column of each cluster table below, and per-cluster status in each section's `Status` line.
  Two items surfaced during FC-4/FC-6 that this plan does not cover are recorded in the closing
  section rather than left implicit.
- Work now lands directly on `main` (trunk-based, per AGENTS.md), commit-per-cluster — the earlier
  `review-followup-2026-07-06` branch noted below was merged and deleted:
  - `7a697dd` — M3 (ETag compare-and-swap) + M4 (`references` replace / `commit_refs` union).
  - `63e5665` — FC-1 link-storage integrity (M1, M2, M9, M10, M13).
  - `2aa1633` — M5 (cross-scope reference filtering) + CA-5 (synthesise response-size budget).
  - `1d554c2` — FC-2 search/write validation correctness (07-02 #2/#3/#4/#5/#7/#13).
  - `05321c4` — FC-3 client/config/robustness minors (23 of 25 findings; 1 stale, 1 accepted
    limitation — see the FC-3 table).
  Each passed the full quality gate and an independent code review with no defects left open (1126
  unit tests green at `05321c4`). The one other attempted fix — minor #38 — was found not applicable
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
>   references not in frontmatter are ignored (not Arkeology's job). No separate removal primitive needed (removal =
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

These are recorded here as locked; the ADR-011/ADR-012 revisions, requirements.md FR retrofits, and a consolidated
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

**Status: ✅ done** — 23/25 findings fixed in `05321c4`; 1 verified stale, 1 documented as an
accepted, irresolvable ambiguity rather than force-fixed (see below). Full quality gate green
(1126 unit tests), independent review clean after two Major fixes (fcntl platform guard,
write_artifacts.py per-descriptor error sanitisation).

| Finding | Item | Status |
|---------|------|--------|
| 07-02 **#8** | `WRITE_PREFIX` validation weaker than `READ_PREFIXES` (`config.py`) | ✅ done (`05321c4`) — rejects internal whitespace and all-slashes-collapsing-to-empty, mirroring `READ_PREFIXES` |
| 07-02 **#9** | fixed startup probe key → concurrent-server race (`startup.py`) | ✅ done (`05321c4`) — probe key is ULID-suffixed per invocation |
| 07-02 **#10** | check 3 proves only `ListBucket` | ✅ done (`05321c4`) — `_check_read_prefixes` now also probes actual object-read access |
| 07-02 **#11** | check 1 conflates missing bucket vs bad creds | ✅ done (`05321c4`) — `_check_credentials` distinguishes a missing-bucket `ClientError` from a real credentials failure |
| 07-02 **#14** | `coerce_list_field` used in delete but not purge/freshness | ⛔ not applicable — verified stale: `purge.py`'s direct `meta.get(...)` is behaviourally equivalent for native-list vector metadata, `delete.py` never touches list fields directly (routes through `find_referrers`, which already uses `coerce_list_field`) |
| 07-02 **#15** | `zero_results` asymmetry; synthesise silently drops failed reads | ✅ done (`05321c4`) — `synthesise_artifacts` gains `zero_results` (matching `search_artifacts`) and `skipped_count` for dropped per-candidate reads |
| 07-02 **#17** | `get_vectors` `returnData=True` wastes float arrays for metadata-only reads; freshness 1+N | ✅ done (`05321c4`) — `get_vectors(..., include_data=False)` skips `returnData`; freshness batches its per-source lookups |
| 07-02 **#18** | 300-thread executor at import (`write.py`) | ✅ done (`05321c4`) — `_EMBED_EXECUTOR` now lazily constructed on first use via module `__getattr__` (PEP 562) |
| 07-02 **#19** | failure log: no lock/rotation, cwd-relative default path | ✅ done (`05321c4`) — `append_failure_entry` now holds an `fcntl.flock` around the write (POSIX-only, guarded import, degrades gracefully elsewhere); rotation/cwd-relative-path left as documented, operator-configurable limitations |
| 07-02 **#20** | percent-decode mangles legacy `%XX` | ⚠️ accepted limitation, documented not fixed — a legacy literal `%XX` value and one produced by `encode_metadata_value`'s own escaping are byte-for-byte indistinguishable without a persistent per-object encoding-version marker (an ADR-level schema decision, out of scope for this cluster); recorded in `test_artifact.py` and `decode_metadata_value`'s docstring |
| 07-02 **#21** | `_URL_PREFIXES` case-sensitive (`references.py`) | ⛔ not applicable — verified stale: a case-mismatched URL that misses the prefix check falls through to the path-lookup branch, which returns unchanged/`None` at every current call site (no manifest path ever coincidentally matches an uppercase-URL-shaped string) — no observable behaviour difference found |
| 07-02 **#20** (`filter.py`) | `filter` shadows builtin | ✅ done (`05321c4`) — renamed to `filter_expr` throughout (`matches_filter`, `vectors.py`, `conftest.py`'s moto extension) |
| 07-02 **#21** (`filter.py`) | unsupported op raises mid-pagination | ✅ done (`05321c4`) — raises typed `FilterEvaluationError` instead of bare `ValueError` |
| 07-02 **#22** (`filter.py`) | mixed-type comparison `TypeError` | ✅ done (`05321c4`) — `$gte`/`$lte` comparisons now catch mixed-type `TypeError` and re-raise `FilterEvaluationError` |
| 07-02 **#31** (`resources.py`) | newline in description corrupts `arkeology://artifacts` table | ✅ done (`05321c4`) — cell values collapse `\n`/`\r`/`\r\n` alongside the existing `|` escaping |
| 07-02 **#32** (`resources.py`) | typo "Arkeology studio— visual" | ✅ done (`05321c4`) |
| 07-02 **#37** | raw boto messages — bucket/index names — leak to MCP callers | ✅ done (`05321c4`) — sanitised at both the top-level and per-descriptor `write_artifacts` handlers (the latter added during review follow-up) |
| Phase-12 **#15** | `decode_link_list` keeps interior empty segments | ✅ done (`05321c4`) — filters out empty segments after `.split(",")` |
| Phase-12 **#16** | non-UTF-8 annotation → unclassified `UnicodeDecodeError` | ✅ done (`05321c4`) — new typed `NonUtf8PayloadError` raised at both S3 decode sites |
| Phase-12 **#17** | `link_metadata` `annotation_unavailable` discards partial `linked`/`skipped` counts | ✅ done (`05321c4`) — accumulated progress preserved in the response |
| Phase-12 **#18** | `apply_link_annotations` issues 2 pointless deletes per fresh write + warns on annotation-less deployments | ✅ done (`05321c4`) — `write.py`'s fresh-create path skips the call entirely when neither link field was supplied; overwrite path unaffected (FC-2's M4 replace-semantics untouched, independently verified) |
| Phase-12 **#19** | `json.dumps` defaults over-count budget — use `ensure_ascii=False, separators=(",",":")` | ✅ done (`05321c4`) — `ensure_ascii=False` applied (the `separators` half was scoped out during review as a safe, conservative simplification — only makes the estimate more conservative, never under-counts) |
| Phase-12 **#23** | duplicate manifest paths last-win silently | ✅ done (`05321c4`) — new typed `DuplicateManifestPathError` raised on collision instead of silent overwrite |
| Phase-12 **#27** | `find_referrers` = 2 full-index scans per delete/archive — merge to one; ties to Phase-12 #17 | ✅ done (`05321c4`) — merged into one `list_vectors_by_metadata` call via a combined `$or`, in-process branch per candidate's `type`; return-value equivalence independently verified algebraically and empirically |
| Phase-12 **#12** (informational) | `SEARCH_FETCH_TOP_K le=100` — the real QueryVectors topK cap is 10 000 (confirmed by `test_top_k_over_documented_cap_is_rejected`); just annotate the bound's provenance | ✅ done (`05321c4`) — field docstring now states the 100 ceiling is an application-level choice, not an AWS limit |

### FC-4 — Studio UI hardening  *(developer; part enhancement — `static/arkeology-studio.html`)*

**Status: ✅ done (2026-08-12)** — 8/8 findings fixed in `3bc4810`, alongside the studio-side
`arkeology://` link resolution specified by ADR-013. Full quality gate green (1162 unit tests);
client-side behaviour verified with a throwaway jsdom harness against the real pinned `marked` and
`dompurify`, mutation-tested to confirm the checks are not vacuous.

| Finding | Item | Status |
|---------|------|--------|
| **#23** | `tier` unescaped in list rows — `renderList` | ✅ done (`3bc4810`) |
| **#24** | prototype-chain type-map lookups → `Object.create(null)`/`Map` | ✅ done (`3bc4810`) |
| **#25** | pin `marked`/`mermaid` CDN versions like the SDK/DOMPurify | ✅ done (`3bc4810`) |
| **#26** | stale-response race — guard `selectArtifact` with `if (selectedId !== id) return` | ✅ done (`3bc4810`) |
| **#27** | `doSearch` ignores active facet filters — forward `filterType/Tier/Status` | ✅ done (`3bc4810`) |
| **#28** | no pagination for large stores | ✅ done (`3bc4810`) |
| **#29** | theme toggle re-downloads the artifact | ✅ done (`3bc4810`) |
| **#30** | `studio.py` fallback `structured_content` returns the whole unbounded listing | ✅ done (`3bc4810`) |

### FC-5 — Missing tests  *(developer; some need real AWS)*

**Status: ✅ done (2026-08-11)** — 9/9 findings fixed, commit `6060f1d`. 1128 unit tests, 79
integration tests green; ruff/format/mypy clean.

| Finding | Item | Status |
|---------|------|--------|
| **SA-3(a)** | T47 integration: real-AWS write→backfill→overwrite→annotation-survives round-trip (`tests/integration/test_tools_write.py`) | ✅ done |
| **SA-3(b)** | T48 integration: backfill→drop vectors→`reconcile_index` restores both link fields (`tests/integration/test_tools_reconcile.py`) | ✅ done |
| **M14** | unit test for `list_object_annotations` `ContinuationToken` pagination (currently dead code under tests) | ✅ done |
| 07-02 **#35** | `nextToken` multi-page test for `list_vectors_by_metadata` | ✅ done |
| 07-02 **#36** | assert `register_tools` registers the full tool set | ✅ done |
| Phase-12 **#26** | remaining: list-on-missing-object; orphaned-vector-skip (ties to M10) | ✅ done — orphaned-vector-skip test landed with M10 in `63e5665`; list-on-missing-object added |
| 07-02 **#33** | replace the 5 `set_credential_failure` call sites with `mocker.patch.object(..., side_effect=CredentialError)` and delete the deprecated method from `fake_bedrock.py` | ✅ done |
| Phase-12 **#24** | add an autouse fixture to reset `_ANNOTATION_STORE` between tests (`conftest.py`) | ✅ done |
| 07-02 **#34** | replace the brittle `inspect.getsource` substring assertion (`test_tools_migrate_artifacts.py`) | ✅ done |

### FC-6 — Docs / hygiene  *(tech-writer)*

**Status: ✅ done (2026-08-12)** — 12/13 findings fixed, 1 verified already resolved. Landed across
`2adbf84` (spec amendments, probe keys, skill ID drift), `dec9426` (state, taxonomy and citation
hygiene) and `ad91fe3` (FR-51–58 behaviour rewrite). CHANGELOG `[Unreleased]` audited against every
commit since `v0.5.0` and the gaps filled. Full quality gate green (1162 unit tests).

| Finding | Item | Status |
|---------|------|--------|
| Phase-12 **#1** | brainstorming still lists OQ3 pending + retired sweep item | ✅ done (`dec9426`) |
| Phase-12 **#3** | `plan.md` "open — planning" vs "all implemented"; T55 "Spec: to be written" though the spec exists | ✅ done (`2adbf84`) |
| Phase-12 **#4** | T53 Files-to-Touch describes the pre-consolidation symlink layout | ✅ done (`2adbf84`) |
| Phase-12 **#5** | T54/T55 cite gitignored `.docs/` as provenance | ⛔ not applicable — verified already fixed: both specs cite durable paths |
| Phase-12 **#7** | T55 lists `title`/`author_role` in both filterable and non-filterable | ✅ done (`2adbf84`) |
| Phase-12 **#9** | stale `link_commit` comment in `tests/unit/test_tools_read.py` | ✅ done (`dec9426`) |
| Phase-12 **#10** | CHANGELOG `[Unreleased]` empty despite the breaking `link_commit`→`link_metadata` removal | ✅ done (`dec9426`) — must now also cover M3/M4 (`7a697dd`), FC-1 (`63e5665`), M5/CA-5 + new `SYNTHESISE_MAX_RESPONSE_BYTES` setting (`2aa1633`) |
| Phase-12 **#12** | "S3 Express One Zone" double-counts "directory buckets" across README/SERVER-REFERENCE/ADR/credentials.py/requirements.md/brainstorming | ✅ done (`dec9426`) |
| Phase-12 **#14** | FR-51–58 what-not-how violations + FR-54 duplicates ADR-011 §1 → dual-maintenance | ✅ done (`ad91fe3`) |
| Phase-12 **#22** | skills reimplement `generate_artifact_id` twice with no drift test — add a drift test or single-source it | ✅ done (`2adbf84`) |
| Phase-12 **#8** | style residue ("D4" shorthand vs "decision 5") | ✅ done (`dec9426`) |
| **M8** | straddles code+doc: the `setting-up-arkeology` aws-cli probe path has no always-run cleanup, and the probe key isn't excluded by `reconcile.py`'s orphan scan (only `_arkeology_health_probe`/`_arkeology_startup_probe` are). Fix = reserved non-artifact prefix + reconcile exclusion (code) + always-run cleanup instruction (skill) | ✅ done (`2adbf84`) |
| **#13** (concept) | mixed addressing (D3) has no documented consumer — `arkeology://` links render dead in the studio app; specify read-surface treatment (or make the studio resolve `arkeology://` — overlaps FC-4) | ✅ done (`3bc4810`) |

## Suggested order when resumed

1. ✅ **done** — Settle the **design decisions** (M3, M4, M5, CA-5) — architect memo → operator sign-off.
   Implemented in `7a697dd` (M3, M4) and `2aa1633` (M5, CA-5).
2. ✅ **done** — **FC-1** (link-storage integrity), highest value; M4 outcome folded in. `63e5665`.
3. ✅ **done** — **FC-2** (search/write validation). `1d554c2`.
4. ✅ **done** — **FC-3** (robustness minors). `05321c4`.
5. ✅ **done** — **FC-5** (missing tests, incl. both SA-3 real-AWS integration round-trips). `6060f1d`.
6. ✅ **done** — **FC-4** (studio) and **FC-6** (docs). `3bc4810`, `2adbf84`, `dec9426`, `ad91fe3`,
   plus `2bf5e3e` and `3bfb10f` for work these clusters surfaced. **This plan is now closed.**

## Surfaced during FC-4/FC-6, not covered by this plan

Recorded here because they were discovered by this remediation but are outside its findings; each
needs an operator decision rather than silent adoption.

- **`search_artifacts` gained the `status="all"` sentinel** (`3bc4810`), because the studio's status
  facet defaults to it and neither forwarding nor omitting it was honest. The cross-tool convention
  is recorded in ADR-014 and specified in the search and list specs. This is a user-visible widening
  of a tool contract.
- **Dangling review citations were swept repo-wide** (`3bfb10f`) — 297 sites across 84 files, since
  reviews are not guaranteed to be retained. `AGENTS.md` now forbids citing review findings and line
  numbers. Note this plan is the deliberate exception: it is the register *of* findings.
- **requirements.md's what-not-how convention is breached well beyond FR-51–58.** The rewrite of those
  eight (`ad91fe3`) was run as a pilot; every one had a confirmed ADR home. FR-01–FR-50 predate most
  ADRs, so a higher rate of mechanism recorded *only* in requirements.md is expected there, and the
  pilot's cost should not be extrapolated to them. The requirements.md Constraints table prose has the
  same problem.
- **`credentials.py` carries a user-visible error string** that still double-counts the S3 Express
  One Zone / directory-bucket categories corrected everywhere else in `dec9426`. Left unchanged
  because it is a message, not a comment; no test asserts on it.

## Cross-references

- Full per-finding evidence: the five review files' Findings sections + their 2026-07-06 verification notes.
- Related deferred design-first backlog items: **B-5** (hard cross-scope boundary, relates to M5), **B-6** (recency-weighted ranking). See `backlog.md`.
