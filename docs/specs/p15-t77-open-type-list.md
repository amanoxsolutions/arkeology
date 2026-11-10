---
type: Spec
id: p15-t77-open-type-list
title: T77 — Open Type List
description: Opens the artifact type list — any non-empty type is accepted, stored verbatim and matched exactly, the known types become a recommended list of OKF display names, and every synthesis comparison, the generated-id type slug, the reconcile orphan scan and Studio follow.
tags: []
status: draft
okf_version: "0.2"
sources:
  - resource: docs/architecture-decisions/adr-2026-09-25-okf-v02-adoption.md
    title: OKF v0.2 Adoption
    last_modified: 2026-09-29T00:00:00Z
  - resource: docs/brainstorming/brainstorming-2026-09-17-okf-v02-adoption.md
    title: OKF v0.2 Adoption for Arkeology
    last_modified: 2026-09-24T00:00:00Z
  - resource: docs/planning-artifacts/requirements.md
    title: Arkeology — Requirements
    last_modified: 2026-09-24T00:00:00Z
  - resource: docs/planning-artifacts/plan.md
    title: Plan Arkeology
    last_modified: 2026-10-07T13:29:34Z
  - resource: https://github.com/amanoxsolutions/amanox-ai-agents/blob/main/plugins/amanox/skills/authoring-skills/references/okf-frontmatter.md
    title: OKF frontmatter reference of the producer amanox-ai-agents plugin
generated:
  by: "axians-architect/claude-opus-5.5"
  at: 2026-10-13T13:04:34Z
phase: 15
task: 77
---

# T77 — Open Type List

<!-- SCOPE BLOCK — frozen after approval -->

## TL;DR

Arkeology stops rejecting artifact types outside its sixteen-value list: any non-empty `type` is
stored exactly as written and matched exactly, including case, so OKF documents typed
`Attested Computation` or `Code Review` import unchanged (D37). The known types survive as a
recommended list of OKF display names, and everything that compares against a type — the synthesis
checks, the generated-id slug, the reconcile orphan scan, Studio — moves to those names.

## Problem Statement

OKF's `type` is a free-form display string and a conforming consumer must tolerate unknown values.
Arkeology rejects any `type` outside `ARTIFACT_TYPES` at write, at every type filter, and in the
reconcile orphan scan, so a producer document typed `Architecture Review` cannot be stored, and a
stored one could never be re-indexed. The producer `amanox-ai-agents` plugin writes Title Case
types (`Code Review`, `ADR`) where Arkeology's corpus holds snake_case (`code_review`, `adr`); under
exact matching the two would split every type filter. D37 resolves both: open the list, keep the
stored value verbatim, publish the known types as recommended OKF display names, and let the
store migration (T90) rewrite legacy values once.

## User Stories

### Story 1 — An unknown type is stored and found verbatim (P1)

- Given a write with type `Attested Computation`, when it succeeds and is listed with type filter
  `Attested Computation`, then it is returned with `type` exactly `Attested Computation`; filtering
  by `attested computation` does not match it (AC-77).
- Given a list, search or synthesise call with a type no artifact carries (`Sepc`), then the result
  is empty and no error is returned.
- Given a write whose type is empty, whitespace-only or contains a control character, then it is
  rejected with `validation_error` and nothing is written.

### Story 2 — Existing generated ids are unchanged (P1)

- Given a recommended display name and its legacy value (`Code Review`, `code_review`), when an id
  is generated for the same tier, date and title, then both yield the same id — for all sixteen.
- Given type `Attested Computation`, when an id is generated, then it begins `attested-computation-`.

### Story 3 — Synthesis behaviour keys on `Synthesis` only (P1)

- Given an own-scope artifact typed `Synthesis`, then `check_synthesis_freshness` audits it,
  `purge_archived` may cascade it, and `delete_artifact`/`archive_artifact` name it as a referrer.
- Given an artifact still typed legacy `synthesis`, then none of the three treats it as a synthesis.

### Story 4 — Agents and humans see the recommended list (P1/P2)

- Given the `arkeology://schema/types` resource, then it lists every recommended display name with
  usage guidance and states that types outside the list are accepted (FR-18).
- Given Studio showing an artifact of a type not on the list, then its badge shows the type verbatim
  in the default style (FR-48).

## Requirements

- THE SYSTEM SHALL accept any `type` that is non-empty after trimming and free of control
  characters, and SHALL store it in S3 object metadata and vector metadata exactly as supplied —
  no case folding, trimming or character replacement (FR-09, D37).
- WHEN a type is empty, whitespace-only or contains a control character THE SYSTEM SHALL return
  `validation_error` before any storage call. (FR-09 makes `type` required; this is required-field
  and header-safety validation, not a vocabulary check, and never alters an accepted value.)
- WHEN a caller filters list, search or synthesise by `type` THE SYSTEM SHALL match the stored
  value exactly and case-sensitively, and SHALL NOT validate the value against any list (AC-77).
- THE SYSTEM SHALL publish this recommended list of OKF display names, replacing the legacy
  values one for one; T90 uses the same table to rewrite stored values:

  | Legacy | Display | Legacy | Display |
  |---|---|---|---|
  | `adr` | `ADR` | `learning` | `Learning` |
  | `brainstorming` | `Brainstorming` | `plan` | `Plan` |
  | `bug_report` | `Bug Report` | `postmortem` | `Postmortem` |
  | `changelog` | `Changelog` | `requirements` | `Requirements` |
  | `code_review` | `Code Review` | `runbook` | `Runbook` |
  | `decision_note` | `Decision Note` | `session_summary` | `Session Summary` |
  | `implementation_note` | `Implementation Note` | `spec` | `Spec` |
  | `synthesis` | `Synthesis` | `vision` | `Vision` |

  *Rationale:* the ADR names `Code Review` but enumerates no table. Each value applies the
  producer's rule — Title Case words, upper case for abbreviations — so a migrated legacy artifact
  and a newly ingested producer document of the same kind land on one value.
- WHEN an id is generated THE SYSTEM SHALL derive its type component by applying the existing
  title-slug normalisation to the type, with fallback `artifact` when the slug is empty; for every
  row above the display name's slug equals the legacy value with `_` replaced by `-`, so existing
  ids are unchanged (D37). Supplied ids (T87) are out of scope.
- WHEN freshness, the purge cascade or the delete/archive referrer check selects syntheses THE
  SYSTEM SHALL match stored `type` exactly `Synthesis` and nothing else (D37).
  *Rationale — before the store migration has run:* the ADR rewrites legacy values once in the
  store migration and has code follow (§6); it ships no compatibility aliases (§9, D42); and a
  deployment holding artifacts must migrate before or with the upgrade (Consequences). Matching
  `synthesis` too would be exactly the alias and dual path those rule out. Every miss on an
  unmigrated store is non-destructive: freshness audits none and deletes no malformed synthesis,
  purge cascades none, and the delete/archive warning — a convenience — omits them.
- WHEN the reconcile orphan scan classifies an own-scope object THE SYSTEM SHALL treat any object
  whose S3 object metadata carries a non-empty `type` as an artifact, and SHALL skip and report one
  whose `type` is missing or empty. *Rationale:* D36 — the bucket is dedicated, so Arkeology's own
  metadata identifies an artifact; `artifact_id` is a vector-metadata key, absent from object
  metadata, so `type` alone is the test. Under the open list a type-membership test would leave
  any newly typed orphan unindexable forever.
- THE SYSTEM SHALL describe `type` in `arkeology://schema/artifact` as free-form, stored verbatim
  and matched exactly, list the recommended values, and use display names in every example in
  the tiers and query-strategy resources (FR-18). The full OKF rewrite of the schema is T89's.
- THE STUDIO SHALL key its type styles and type-filter options on the recommended display names,
  show any type verbatim as its badge label, and render a type outside the list with the default
  style (FR-48). Filter options are the recommended list only.

## Boundaries

**Always:** store and return `type` byte-for-byte; compare synthesis type through one shared
constant; keep the recommended list the single source the schema resource reads and Studio mirrors.

**Ask First:** adding, removing or renaming a recommended type, or changing the display-name table
— T90 depends on it.

**Never:**
- Normalise, case-fold or trim a stored or filtered `type`, or match case-insensitively (D37).
- Treat a legacy value as an alias of its display name anywhere (`$in` of both, a lookup table at
  read time) — D42 and the no-fallback rule.
- Reject a type for not being recommended; the typo guard is an accepted loss (D37).
- Rewrite stored artifacts (T90), rewrite the whole schema resource (T89), or edit README,
  SERVER-REFERENCE, agent snippets or AGENTS.md (T91).
- Add Studio filter options for types outside the recommended list.

AC-80 does not apply: T77 removes no parameter, field or tool name. A legacy type value is still
accepted — as an ordinary free-form type, not as an alias.

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|---|---|---|
| `src/arkeology/constants.py` | Modify | Add the `Synthesis` type value as a public constant (three importers) |
| `src/arkeology/artifact.py` | Modify | Rename `ARTIFACT_TYPES` to `RECOMMENDED_ARTIFACT_TYPES` holding the display names — the rename makes any surviving validator import fail at import time. Remove `_require_valid_type`; `Artifact.validate_type` checks non-empty and control characters only; `generate_artifact_id` slugifies the type. Fix comments that say "mirroring ARTIFACT_TYPES" |
| `src/arkeology/tools/_search_helper.py` | Modify | `build_user_filters`: drop the type check, keep the tier check. `find_referrers`: both synthesis comparisons use the constant. T76 edits the adjacent `status` clause; T84 later rewrites this function and must keep the constant |
| `src/arkeology/tools/freshness.py` | Modify | Synthesis filter in `_check_synthesis_freshness_inner` uses the constant |
| `src/arkeology/tools/purge.py` | Modify | Cascade filter uses the constant (not named in plan.md's entry; same comparison) |
| `src/arkeology/tools/reconcile.py` | Modify | Orphan-scan discriminator in `_process_orphan`; reword the `_PROBE_KEY_MARKER` comment (a slug or a D33 id never starts with `_`, so the invariant holds) and docstrings |
| `src/arkeology/resources.py` | Modify | Schema type row and heading, type catalogue keyed on display names, tiers "Use for" lists, query-strategy examples (`type="ADR"`, `type="Synthesis"`) |
| `src/arkeology/tools/write.py`, `src/arkeology/references.py` | Modify | Docstrings only |
| `src/arkeology/static/arkeology-studio.html` | Modify | Re-key `TYPE_VARS`; delete `TYPE_LABELS` (`typeLabel` returns the type); `sel-type` options become display names. Tokens unchanged |
| `plugins/arkeology/skills/migrating-to-arkeology/SKILL.md` | Modify | Offline id snippet: `type_slug = slugify(type_, "artifact")` and its prose step; classification tables and examples use display names |
| `plugins/arkeology/skills/migrating-to-arkeology/schema.yaml` | Modify | `type` comment: recommended display names, any value accepted |
| `plugins/arkeology/skills/backfilling-references/SKILL.md` | Modify | Same one-line snippet change |

T76 and T78 run in parallel and touch the same filter dicts, `write.py` and the write contract; the
later-landing task applies its edit to the other's result. For T91, AGENTS.md's Working Conventions
line on `ARTIFACT_TYPES` becomes: `RECOMMENDED_ARTIFACT_TYPES` in `artifact.py` is the single source
of truth for the recommended type list (OKF display names), published by the types schema resource
and mirrored by Studio under a drift test; it validates nothing. The id-format line's `type_slug`
and the `constants.py` Repository Structure row change with it.

## Contract Amendments

- `data/s3.artifact.md` — `### generate_artifact_id`: no `ValueError` for type; the type slug is
  the title-slug normalisation with fallback `artifact`; "equal output implies equal inputs"
  becomes equal *slugged* type, so types differing only in case or punctuation share a key and the
  second create is rejected, never overwritten. `## Storage Shape` `type` row and
  `## Compatibility Guarantees`: free-form, verbatim; the key scheme's outputs are unchanged.
- `data/s3vectors.artifact.md` — `## Storage Shape` `type` row: verbatim, exact `$eq`.
- `modules/arkeology.tools.write.md` — `### write_artifact` Errors and Preconditions: `type` is
  rejected only when empty, whitespace-only or carrying a control character.
- `modules/arkeology.tools.list.md`, `.search.md`, `.synthesise.md` — `type` filter is exact,
  case-sensitive and never a `validation_error`.
- `modules/arkeology.resources.md` — `### register_resources`: types content derives from
  `RECOMMENDED_ARTIFACT_TYPES` and states types outside it are accepted.
- `modules/arkeology.tools.reconcile.md` — `### reconcile_index`: artifacts-only invariant and its
  trade-off keyed on a non-empty `type`.
- `modules/arkeology.tools.freshness.md`, `.purge.md`, `.delete.md`, `.archive.md` — a synthesis is
  an artifact whose stored `type` is exactly `Synthesis`.
- `design/arkeology-studio-tokens.html` — type grid labelled with display names; a default-style
  entry for an unrecognised type (`--t3` stripe, `--t3` text on its 16% tint) checked to ≥4.5:1 in
  both themes; "15 types" corrected.

## Testing Approach

TDD: each test file below is written and confirmed failing before the implementation it gates. No
file in the mutation `only_mutate` scope is touched, so no mutation run is required.

1. `tests/unit/test_artifact.py` → `constants.py`, `artifact.py`. Any type accepted and kept
   verbatim (`Attested Computation`, `code_review`, `Sepc`); empty, whitespace-only and
   control-character types rejected; a sixteen-row table pins slug(display) == legacy with `_`→`-`
   (Story 2); a non-ASCII-only type gets the fallback; `ARTIFACT_TYPES` no longer exists and
   `RECOMMENDED_ARTIFACT_TYPES` equals the display-name table. Flip
   `test_generate_artifact_id_invalid_type_raises_value_error` and `test_artifact_unknown_type_invalid`.
2. `tests/unit/test_tools_write.py`, `test_tools_write_artifacts.py` → `write.py`. AC-77 write half:
   S3 and vector metadata both hold `Attested Computation` exactly. `test_validation_invalid_type_no_s3_call`
   and the entry-4 invalid descriptor switch to an empty type.
3. `tests/unit/test_tools_list.py`, `test_tools_search.py`, `test_tools_synthesise.py`,
   `test_tools__search_helper.py` → `_search_helper.py`. AC-77 filter half; the three
   `*_filter_type_typo_returns_validation_error` tests flip to empty results with no error.
4. `tests/unit/test_tools_freshness.py`, `test_tools_purge.py`, `test_tools_delete.py`,
   `test_tools_archive.py` → `freshness.py`, `purge.py`, `find_referrers`. Synthesis fixtures become
   `Synthesis`; one test per behaviour proves a legacy-`synthesis` artifact is not audited, not
   deleted as malformed under `confirm=True`, not cascaded, not named as referrer (Story 3).
5. `tests/unit/test_tools_reconcile.py` → `reconcile.py`. An orphan typed `Attested Computation` is
   re-indexed (replaces `test_orphan_scan_object_with_unknown_type_metadata_skipped`); an empty
   `type` is skipped.
6. `tests/unit/test_resources.py` → `resources.py`. Schema says free-form and accepted; the types
   resource carries every display name with guidance; examples use display names; monkeypatch
   tests retarget the renamed constant (FR-18).
7. `tests/unit/test_skill_artifact_id_drift.py` → both SKILL.md snippets. Add `ID_CASES` rows with
   `Code Review` and `Attested Computation`.
8. `tests/static/studio-type-style.test.js` (new, sliced from the shipped HTML like the existing
   static test) and one drift test in `tests/unit/test_tools_studio.py` → `arkeology-studio.html`.
   Each display name maps to its own token; `Attested Computation`, `code_review` and `constructor`
   get the `--t3` default; labels are verbatim; `TYPE_VARS` keys and `sel-type` options equal
   `RECOMMENDED_ARTIFACT_TYPES` (FR-48, AC-54).

**Integration tests (real AWS), updated in this task:**
- `tests/integration/test_tools_list.py` — new AC-77 test: real S3 Vectors `$eq` is case-sensitive
  and a space-bearing type round-trips S3 object metadata (neither is provable under moto).
- `tests/integration/test_tools_purge.py` `test_purge_synthesis_cascade_deleted` and
  `tests/integration/test_tools_delete.py` `test_delete_synthesis_source_includes_referrers` —
  synthesis type becomes `Synthesis`.
- `tests/integration/test_tools_freshness.py` — the shared synthesis fixture type becomes
  `Synthesis`. `test_freshness_stale_source_detected` already fails on its date-based staleness
  setup and stays failing until T86 rewrites it.

## Open Questions

None.
