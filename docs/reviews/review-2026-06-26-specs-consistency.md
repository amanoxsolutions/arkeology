---
type: code_review
title: "Cross-spec consistency review of docs/specs"
description: "Whole-corpus consistency review of all 50 per-task feature specs in docs/specs — numbering, naming, defaults, type vocabulary, and status alignment against plan.md and the PRD, separating genuine contradictions from intended supersession."
tags: [code-review, cairn-mcp, specs, consistency]
timestamp: 2026-06-26T00:00:00Z
okf_version: "0.1"
status: draft
references:
  - docs/planning-artifacts/plan.md
  - docs/planning-artifacts/prd.md
  - docs/specs/p2-t6-artifact-model.md
  - docs/specs/p7-t25b-extend-artifact-types.md
  - docs/specs/p10-t35-filter-range-operators.md
  - docs/specs/p10-t36-commit-refs-metadata-fields.md
  - docs/specs/p10-t37-propose-commit-links.md
  - docs/specs/p10-t38-link-commit.md
  - docs/specs/p4-t19-setup-documentation.md
  - docs/specs/p11-t43-mcp-app-infrastructure.md
authored:
  by: architect
  date: 2026-06-26
revised:
  by: ""
  date: ""
---

# Cross-spec consistency review of docs/specs

## Description
A full consistency review of all 50 per-task feature specs under `docs/specs/`, checked
against the authoritative current state in `docs/planning-artifacts/plan.md` and `prd.md`.
The corpus was partitioned into five phase-groups (P1, P2–P3, P4–P7, P8–P9, P10–P11),
structured facts were extracted from each spec (config defaults, numeric limits, field/key
names, data encodings, tool signatures, cross-references, status), and cross-cutting claims
were compared. Every concrete defect below was then verified directly against the spec files.

The central discipline of this review: **distinguish genuine contradictions from intended
evolution.** Specs are point-in-time documents and later tasks deliberately supersede earlier
ones (e.g. T29→T30, the `ARTIFACT_CONCURRENCY` removal in T39, the `feature_tags`→`tags`
rename in T41). An apparent disagreement between an early and a late spec is only a defect if
it is *not* a documented supersession. The "Intended Evolution" section records the
correct-by-design cases that were checked and cleared.

## Specs and Planning Artifacts Consulted
- All 50 files in `docs/specs/` (phase-1-overview, p1-t1..t5, p2-t6..t9, p3-t10..t16,
  p4-t17..t20, p5-t21/t22, p7-t25/t25b/t25c, p8-t26..t29, p9-t30..t34, p10-t35..t42,
  p11-t43/t44).
- `docs/planning-artifacts/plan.md` (phase history + supersession notes) and `prd.md`.

## Findings

> **Status (2026-06-26): ALL FINDINGS RESOLVED.** Every defect below is fixed and merged to
> `main` (merge commit on branch `docs/specs-consistency-fixes`). Per-finding status:
>
> | # | Severity | Finding | Status |
> |---|---|---|---|
> | M1 | Major | T35–T38 triple numbering + dangling/ broken references | ✅ Resolved |
> | M2 | Major | T6 vs T25b baseline artifact-type contradiction | ✅ Resolved |
> | M3 | Minor | T19 "all eight types" stale count | ✅ Resolved |
> | M4 | Minor | T43/T44 status not marked done | ✅ Resolved |
> | M5 | Minor | T20 describes removed mechanics, unmarked | ✅ Resolved |
> | M6 | Minor | "checks" terminology / stale 5-check count in T5 | ✅ Resolved |
> | M7 | Minor | plan.md:315 stale `feature_tags` reference (post-T41) | ✅ Resolved |
>
> Resolution detail for each is recorded in **Items Resolved Since This Review** at the bottom.

### Critical
None. No spec defect blocks runtime correctness or causes data loss; the impact of every
finding is documentation navigability and accuracy.

### Major

1. **The T35–T38 cluster is numbered three different ways at once, and its references point
   to files that do not exist.** — ✅ **RESOLVED 2026-06-26.**
   The four commit-refs-track specs each carry a filename, a `# Title`, and frontmatter
   `task:`/`feature:` that all disagree:

   | File on disk | `# Title` | frontmatter `task:` | frontmatter `feature:` |
   |---|---|---|---|
   | `p10-t35-filter-range-operators.md` | T23 | 34 | `p10-t34-filter-range-operators` |
   | `p10-t36-commit-refs-metadata-fields.md` | T24 | 35 | `p10-t35-commit-refs-metadata-fields` |
   | `p10-t37-propose-commit-links.md` | T25 | 36 | `p10-t36-propose-commit-links` |
   | `p10-t38-link-commit.md` | T26 | 37 | `p10-t37-link-commit` |

   Consequences that actually break:
   - **`plan.md:317`** cites `docs/specs/p10-t35-commit-refs-metadata-fields.md` as the spec
     for T36 — that file does not exist (the real file is `p10-t36-…`). The plan body is also
     internally inconsistent: line 311 names T35 "filter range operators" but line 317 uses
     the `p10-t35` stem for the commit_refs spec.
   - **Dangling inter-spec references.** `p10-t36/t37/t38` list `references:` to
     `docs/specs/p10-t34-filter-range-operators.md` and
     `docs/specs/p10-t35-commit-refs-metadata-fields.md` — neither exists on disk (actual:
     `t35`, `t36`).
   - The frontmatter `task: 34`/`35` values **collide with Phase 9**, where the plan's T34 is
     `sync-cairn-plugin`.

   T39–T44 are all correctly self-consistent (filename = title = frontmatter), so the
   off-by-one is isolated to T35–T38 and is unambiguously an error, not a scheme.
   **Fix:** align titles, frontmatter `task:`/`feature:`, and the `references:` lists in these
   four files to their filenames (35–38), and correct `plan.md:317`.

2. **Specs disagree on which artifact types form the original baseline set.** — ✅ **RESOLVED 2026-06-26.**
   - **`p2-t6-artifact-model.md:103–104`** enumerates the baseline 9 as `code_review,
     session_summary, implementation_note, spec, adr, bug_report, decision_note, synthesis,
     learning` — it **includes `learning`** and **omits `brainstorming`**. Yet the same spec
     (line 107) admits `learning` was added later.
   - **`p7-t25b-extend-artifact-types.md:152`** enumerates the existing 9 as `adr,
     brainstorming, bug_report, code_review, decision_note, implementation_note,
     session_summary, spec, synthesis` — it **includes `brainstorming`** and treats
     **`learning` as the later 15th type** (2026-06-15).

   Both cannot be the baseline. The final 15-type set (`p7-t25b:268–270`) correctly contains
   *both* `brainstorming` and `learning`, so the runtime `ARTIFACT_TYPES` is fine — but T6's
   enumerated baseline is wrong: it lists a type it concedes was added later and drops one that
   was original. **Fix:** correct T6's baseline list to include `brainstorming` and exclude
   `learning`, showing `learning` only in the forward-note.

### Minor

3. **`p4-t19-setup-documentation.md:104` says "all eight" artifact types.** — ✅ **RESOLVED 2026-06-26.** Wrong against
   every era: T6 (same date) already defined 9, and the vocabulary is now 15. The AGENTS.md
   snippet guidance this drove has since moved into the skills (T31c), so the live impact is
   nil, but the count was never correct. Update to the current count or phrase it
   count-independently ("all artifact types listed in `cairn://schema/types`").

4. **`p11-t43-mcp-app-infrastructure.md` is `status: draft` while `plan.md` marks T43 ✅
   done.** — ✅ **RESOLVED 2026-06-26.** Its sibling `p11-t44` is `status: ready`. Either the spec was never promoted or the
   field is stale. Promote to `ready` (the 2026-06-25 full-codebase review already corrected
   T43's content for the `structured_content` branching, so the spec is effectively final).

5. **`p4-t20-migration-skill.md` still describes now-removed mechanics and is not marked
   superseded.** — ✅ **RESOLVED 2026-06-26.** It documents the `<30 / ≥30` file-count split and the `migrate.py` script,
   both of which were replaced (thresholds reworked in T25c/T29, then `migrate.py` deleted in
   T30). T29 is correctly marked `status: superseded`; T20 is the one major spec describing
   deleted machinery without that marker. Add a supersession note pointing at T25c/T30.

6. **Terminology collision around "checks".** — ✅ **RESOLVED 2026-06-26** (fixed the stale 5-check count in `p1-t5`; the two check-sequences are now disambiguated). `p9-t31a` describes the setting-up-cairn skill's
   **5 CLI pre-flight checks** (creds, `uv`, S3 bucket, vectors index, bedrock); `p9-t30`
   describes the server's **6th startup check** (Nova Lite / `BEDROCK_TEXT_MODEL`). These are
   two unrelated sequences that happen to share the word "check" and the numbers 5/6. Not a
   contradiction, but a reader can conflate them — worth one clarifying clause in each spec.

7. **(Non-issue, recorded for completeness) `p2-t8-search-artifacts.md` does not restate the
   numeric defaults** for `SEARCH_MAX_ITERATIONS` (3), `SEARCH_FETCH_TOP_K` (25),
   `SEARCH_DEFAULT_TOP_K` (5). It references them by name; `p1-t4-configuration-model.md` is
   the single source of truth. No action needed.

## Intended Evolution (verified correct — not defects)
These look like cross-phase contradictions but are documented, deliberate supersession. Each
was checked and is clean:
- **`migrate.py` / `MIGRATE_CONCURRENCY`** — added in T29, deleted/obsoleted in T30; T29 is
  marked `status: superseded`. ✓
- **`ARTIFACT_CONCURRENCY`** — config var added in T30, removed from `Settings` and converted
  to a per-call parameter (cap 15, floor→default 3, `warning` field) in T39, which states the
  removal explicitly. ✓
- **`feature_tags` → `tags`** — renamed in T41. **Correction (2026-06-26):** an earlier draft
  of this note claimed pre-T41 specs still use `feature_tags`. That is **false** — every spec
  (including the Phase-2 originals and the pre-rename Phase-10 commit-refs specs) already uses
  `tags`; the rename was applied across the spec corpus. `feature_tags` now survives *only*
  where it documents the rename's "from" name (T41 itself; plan.md lines 303/339/340) — which
  must keep it — plus one genuine stale leak (plan.md:315), tracked as M7 below. ✓
- **Migration file-count thresholds** — `<30 / ≥30` (T20) → `1–9 / ≥5 / ≥10` (T29) →
  server-side, no skill threshold (T30). Each supersedes the prior. (See Minor #5 re: T20's
  missing marker.) ✓
- **Reconcile "phases"** — T21 defined 2 phases; T32 added Phase 3 (dangling-vector pruning)
  purely additively. ✓
- **Vector score range `[0,2]` → `[−1,1]`** — corrected intentionally by the T25 moto
  migration; the live AGENTS.md reflects `[−1,1]`. ✓

## Recommendations (priority order)
1. **M1 first** — it produces broken links in `plan.md` and across four specs. Renumber
   titles/frontmatter/references in `p10-t35..t38` to match filenames; fix `plan.md:317`.
2. **M2** — correct the T6 baseline type enumeration so the two specs agree on history.
3. Minor sweep: T19 "eight" (3), promote T43 out of draft (4), mark T20 superseded (5), add
   the one-line check-terminology clarifications (6).
4. Consider a short "spec numbering & status" convention note in `AGENTS.md` so the T35–T38
   class of drift (filename vs title vs frontmatter) is caught earlier.

## Items Resolved Since This Review
- 2026-06-26 — **Minor #7 (M7) fixed** *(surfaced by author question about retrofitting the
  `feature_tags`→`tags` rename).* Investigation showed the spec corpus was **already**
  retrofitted to `tags` (Phase-2 originals and the pre-rename Phase-10 commit-refs specs all
  use `tags`; `feature_tags` appears nowhere in `src/`, `AGENTS.md`, `skills/`, or `prd.md`).
  The only non-rename-documenting survivor was `plan.md:315`, which described `commit_refs` as
  "following the `feature_tags` encoding pattern" — changed to `tags`. Deliberately retained:
  `p10-t41-rename-feature-tags-to-tags.md` and `plan.md:303/339/340`, where `feature_tags` is
  the rename's "from" name and removing it would erase the record of the change. Also corrected
  the inaccurate "clean boundary" bullet in the Intended Evolution section.
- 2026-06-26 — **Minor #5 (M5) fixed.** Set `p4-t20-migration-skill.md` to
  `status: superseded` (matching how T29 is marked) and added a prominent "SUPERSEDED —
  historical record only" note mapping each now-removed mechanic to its replacement:
  classification → p7-t25b/p7-t25c; `<30/≥30` paths → p8-t29 then p9-t30 (server-side bulk
  tools); `migrate.py` + `schema.yaml` → deleted in p9-t30; exclusion handling → p9-t31b/t31a.
  Populated the previously-empty `references:` with those five superseding specs (all verified
  to resolve). Original spec text retained verbatim for provenance.
- 2026-06-26 — **Minor #6 (M6) fixed.** Root cause confirmed: the sixth startup check
  (text-model accessibility / `BEDROCK_TEXT_MODEL`) was added later by T30, after the Phase-1
  spec was written — so the stale doc was `p1-t5-startup-validation-sequence.md`, which still
  described a "five-check" sequence with `Check x/5` / `5/5` messages while the running
  `startup.py` (and AGENTS.md) already do six (`Check x/6`, `6/6`). Fixed: added a
  "later evolution" forward-note pointing to p9-t30 for the 6th check's spec; updated the
  frontmatter description, the order list, and the requirement/boundary count language; and
  changed all per-check log-message denominators and the success line from `/5` to `/6` to
  match the code. Left T5's own implementation-block scope at "checks 1→5" (the 6th's code and
  tests are T30's deliverable, not T5's). Verified: no `/5`/"five-check" runtime references
  remain; `p9-t31a`'s separate "5 CLI pre-flight checks" were correctly left untouched (a
  different sequence). No code change — the implementation was already correct.
- 2026-06-26 — **Minor #3 (M3) fixed.** `p4-t19-setup-documentation.md:104` no longer says
  "all eight types"; the AGENTS.md-snippet requirement now reads "artifact type selection
  guidance for all artifact types (the full catalogue lives in `cairn://schema/types`)" —
  count-independent, so it cannot go stale as the vocabulary grows. No residual "eight" in T19.
- 2026-06-26 — **Minor #4 (M4) fixed.** Per author confirmation that both are done, set
  `status: complete` on `p11-t43-mcp-app-infrastructure.md` (was `draft`) and
  `p11-t44-browser-ui.md` (was `ready`), matching the established done-status used elsewhere
  (p9-t30/t31b/t32/t33) and the plan's ✅ marking.
- 2026-06-26 — **M2 fixed.** Corrected T6's baseline type enumeration
  (`p2-t6-artifact-model.md:103–104`): swapped the wrongly-listed `learning` for the
  originally-present `brainstorming`, so the baseline 9 is `code_review, session_summary,
  implementation_note, spec, adr, bug_report, decision_note, synthesis, brainstorming` —
  now identical to T25b's "existing 9". The forward-note (line 107) still records the +5
  extension (`prd, plan, runbook, changelog, postmortem`) and `learning` as the later
  15th addition. Both specs now agree that the final set contains both `brainstorming` and
  `learning`, with `learning` added later. No stale "nine"/count word remains in T6.
- 2026-06-26 — **M1 fixed.** Aligned the T35–T38 commit-refs-track specs so each file's
  `# Title`, frontmatter `task:`, and `feature:` match its filename (35→`p10-t35`
  filter-range-operators, 36→commit-refs-metadata-fields, 37→propose-commit-links,
  38→link-commit). Repointed every dangling inter-spec `references:` entry
  (`p10-t34`/`p10-t35-commit-refs`/`p10-t36-propose`) to the correct on-disk stems, fixed the
  three in-body cross-references (T25/T26→T37/T38; T26→T38; T25→T37), and corrected the broken
  `plan.md:317` link (`p10-t35-commit-refs-metadata-fields.md` → `p10-t36-…`). Verified: no
  residual `p10-t34`/old-`T23–T26` stems remain, and every `docs/specs/` reference in the four
  specs and the plan's Phase-10 links now resolves to an existing file.
