---
type: spec
title: Write Performance P3 — Configurable Section Caps
description: Adds two configurable pre-embedding filters — EMBED_MIN_SECTION_LENGTH to skip short placeholder sections and EMBED_MAX_SECTIONS to cap the total sections indexed — bounding worst-case Bedrock call count without affecting typical structured artifacts.
tags: []
timestamp: 2026-06-02T00:00:00Z
okf_version: "0.1"
feature: p8-t28-section-caps
phase: 8
task: 28
status: implemented
references: []
authored:
  by: "architect"
  date: "2026-06-02"
revised:
  by: ""
  date: ""
---

# Write Performance P3 — Configurable Section Caps

<!-- SCOPE BLOCK — frozen after approval -->

## TL;DR

Documents with an unusually high number of `##` sections — brainstorming dumps, oversized
specs — can generate dozens of Bedrock calls and vector writes even with P1's concurrency.
This spec adds two configurable filters applied before embedding: a minimum section body length
(sections shorter than the threshold are skipped as semantic noise) and a maximum section count
cap (sections beyond the cap are silently dropped from the vector index). Full content remains
in S3 and is always returned by `read_artifact`.

## Problem Statement

The brainstorming session (2026-06-01) identified two defensive bounds (C1, C2) that limit
worst-case embed work without degrading the typical case. A document with 80 sections (a
verbose brainstorming dump) generates 80 Bedrock calls even with P1 — still a meaningful cost.
Very short sections ("TBD", "See above", a single link) add index noise without contributing
search signal. These two one-line filters bound the worst case and clean the index simultaneously.

## User Stories

### Story 1 — Short sections are skipped before embedding (P1)

An operator migrates a document with a section containing only "TBD". That placeholder section
is not embedded and does not appear as a vector in the index. The full document content
(including the TBD section) is still stored in S3 and returned by `read_artifact`.

**Acceptance criteria:**
- Given a document with three sections where one body is 30 characters and
  `EMBED_MIN_SECTION_LENGTH=50`, when `write_artifact` is called, then `bedrock.embed` is
  called twice (not three times) and `sections_indexed == 2`.
- Given a document where all sections are below the threshold, when `write_artifact` is called,
  then the document-level fallback is used (one embed from title + description), not zero embeds.

### Story 2 — Section count is capped at EMBED_MAX_SECTIONS (P1)

An operator migrates a 40-section brainstorming document. Only the first `EMBED_MAX_SECTIONS`
sections are indexed; the rest are silently dropped from the vector index.

**Acceptance criteria:**
- Given a document with 25 sections and `EMBED_MAX_SECTIONS=20`, when `write_artifact` is
  called, then `bedrock.embed` is called 20 times and `sections_indexed == 20`.
- Given a document with 10 sections and `EMBED_MAX_SECTIONS=20`, when `write_artifact` is
  called, then all 10 sections are indexed and `sections_indexed == 10` (cap not triggered).

### Story 3 — Defaults are safe and require no operator action (P1)

The defaults (`EMBED_MAX_SECTIONS=20`, `EMBED_MIN_SECTION_LENGTH=50`) do not affect typical
structured artifacts (ADRs, specs, code reviews) which have 3–15 meaningful sections.

**Acceptance criteria:**
- Given a document with 8 sections each with 200-character bodies and no env vars set, when
  `write_artifact` is called, then all 8 sections are indexed (defaults do not interfere).
- Given a document with 15 sections of 100+ characters each, when defaults are in effect,
  then all 15 are indexed.

## Requirements

- WHEN `EMBED_MIN_SECTION_LENGTH` is absent from the environment THE SYSTEM SHALL default to 50.
- WHEN `EMBED_MAX_SECTIONS` is absent from the environment THE SYSTEM SHALL default to 20.
- WHEN `EMBED_MIN_SECTION_LENGTH` is set to a value less than 0 THE SYSTEM SHALL reject it at
  startup with a clear validation error.
- WHEN `EMBED_MAX_SECTIONS` is set to a value less than 1 THE SYSTEM SHALL reject it at startup
  with a clear validation error.
- WHEN `write_artifact` parses sections THE SYSTEM SHALL discard any section whose body
  (stripped of leading/trailing whitespace) has fewer characters than
  `settings.embed_min_section_length` before passing sections to the embedding step.
- WHEN the filtered section list exceeds `settings.embed_max_sections` THE SYSTEM SHALL retain
  only the first `settings.embed_max_sections` entries and discard the rest.
- WHEN filtering and capping leave zero sections THE SYSTEM SHALL fall back to the
  document-level embed (title + description) — not return an error.
- WHEN sections are dropped by either filter THE SYSTEM SHALL log a DEBUG message indicating
  the number of sections dropped and the reason (length filter or cap).
- WHEN `write_artifact` returns THE SYSTEM SHALL include in `sections_indexed` only the
  sections actually embedded and indexed (dropped sections are not counted).

## Boundaries

**Always:**
- Filtering is applied to the parsed section list in `write.py` immediately after
  `parse_sections(content)` and before the embed step. The filter is not applied inside
  `parse_sections` — section parsing remains a pure function with no configuration dependency.
- Both filters apply to the section path only. The document-level fallback path (no `##`
  sections, or all sections filtered out) is unchanged.
- Dropped sections remain in S3 content and are always returned by `read_artifact`. Only the
  vector index entry is omitted.
- Length filter runs first; cap runs second. This means the cap applies to sections that
  passed the minimum-length check, not to the raw parsed list.

**Ask First:**
- Whether the cap should apply to sections that pass the length filter (recommended, above) or
  to the raw parsed list before the length filter.

**Never:**
- Do not change `parse_sections` — it must remain a pure function with no settings dependency.
- Do not raise an error when sections are dropped — silently drop and log at DEBUG level.
- Do not store `EMBED_MAX_SECTIONS` or `EMBED_MIN_SECTION_LENGTH` in artifact metadata —
  these are server-side controls only.

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_config.py` | Modify | Add tests for new config vars (written first — Red) |
| `tests/unit/test_tools_write.py` | Modify | Add section cap and min-length filter tests (written first — Red) |
| `src/arkeology/config.py` | Modify | Add `EMBED_MAX_SECTIONS` (int, default 20, ≥ 1) and `EMBED_MIN_SECTION_LENGTH` (int, default 50, ≥ 0) with validators; add `embed_max_sections` and `embed_min_section_length` properties |
| `src/arkeology/tools/write.py` | Modify | After `sections = parse_sections(content)`, apply length filter then cap; log dropped sections at DEBUG; fall back to document-level embed if no sections remain after filtering |

## Testing Approach

**TDD cycle A (config):** update `test_config.py` first (Red) → add fields to `config.py`
(Green).

**TDD cycle B (write tool):** update `test_tools_write.py` first (Red) → implement filtering
in `write.py` (Green).

---

**`tests/unit/test_config.py` — new tests:**

- `test_embed_max_sections_default` — Settings without env var → `embed_max_sections == 20`.
- `test_embed_max_sections_custom` — `EMBED_MAX_SECTIONS=5` → `embed_max_sections == 5`.
- `test_embed_max_sections_zero_invalid` — `EMBED_MAX_SECTIONS=0` → `ValidationError`.
- `test_embed_min_section_length_default` — Settings without env var →
  `embed_min_section_length == 50`.
- `test_embed_min_section_length_zero_valid` — `EMBED_MIN_SECTION_LENGTH=0` → valid (disables
  the filter).
- `test_embed_min_section_length_negative_invalid` — `EMBED_MIN_SECTION_LENGTH=-1` →
  `ValidationError`.

**`tests/unit/test_tools_write.py` — new tests:**

Length filter:
- `test_short_section_skipped` — doc with 3 sections (bodies: 10, 200, 200 chars);
  `EMBED_MIN_SECTION_LENGTH=50`; assert `embed` called twice, `sections_indexed == 2`.
- `test_all_sections_short_falls_back_to_document` — doc with 2 sections both under 50 chars;
  assert document-level embed is used (one `embed` call, `sections_indexed == 1`).
- `test_min_length_zero_skips_no_sections` — `EMBED_MIN_SECTION_LENGTH=0`; all sections pass.

Cap:
- `test_sections_capped_at_max` — doc with 25 sections; `EMBED_MAX_SECTIONS=20`; assert
  `embed.call_count == 20` and `sections_indexed == 20`.
- `test_sections_under_cap_not_truncated` — doc with 10 sections; `EMBED_MAX_SECTIONS=20`;
  assert `embed.call_count == 10`.

Combined:
- `test_length_filter_then_cap` — doc with 30 sections, 5 of which are short; with
  `EMBED_MIN_SECTION_LENGTH=50` and `EMBED_MAX_SECTIONS=20`; assert 20 sections indexed
  (25 pass filter, then capped at 20).
- `test_all_filtered_then_capped_falls_back` — `EMBED_MAX_SECTIONS=0` is invalid; use
  `EMBED_MIN_SECTION_LENGTH` that filters everything → document-level fallback.

## Open Questions

*(none — all decisions resolved per brainstorming session 2026-06-01)*
