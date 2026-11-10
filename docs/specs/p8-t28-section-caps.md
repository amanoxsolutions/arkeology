---
type: Spec
id: p8-t28-section-caps
title: Write Performance P3 — Configurable Section Caps
description: Adds two configurable pre-embedding filters — EMBED_MIN_SECTION_LENGTH to skip short placeholder sections and EMBED_MAX_SECTIONS to cap the total sections indexed — bounding worst-case Bedrock call count without affecting typical structured artifacts.
tags: []
status: stable
okf_version: "0.2"
generated:
  by: "axians-architect/unknown"
  at: 2026-06-02T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-09T13:29:44Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
---

# Write Performance P3 — Configurable Section Caps

## TL;DR

Documents with an unusually high number of `##` sections — brainstorming dumps, oversized
specs — can generate dozens of Bedrock calls and vector writes even with P1's concurrency.
This spec adds two configurable filters applied before embedding: a minimum section body length
(sections shorter than the threshold are skipped as semantic noise) and a maximum section count
cap (sections beyond the cap are silently dropped from the vector index). Full content remains
in S3 and is always returned by `read_artifact`.

## 1. Problem Statement

The brainstorming session (2026-06-01) identified two defensive bounds that limit
worst-case embed work without degrading the typical case. A document with 80 sections (a
verbose brainstorming dump) generates 80 Bedrock calls even with P1 — still a meaningful cost.
Very short sections ("TBD", "See above", a single link) add index noise without contributing
search signal. These two one-line filters bound the worst case and clean the index simultaneously.

All three user stories this spec states are P1: short sections are skipped before embedding,
section count is capped at `EMBED_MAX_SECTIONS`, and the defaults are safe and require no
operator action.

## 2. Rules — Section filters

### R1 — Short sections are skipped before embedding

When `write_artifact` parses sections, it discards any section whose body (stripped of
leading/trailing whitespace) has fewer characters than `settings.embed_min_section_length`
before passing sections to the embedding step. Such a section is not embedded and does not
appear as a vector in the index.

**Example**

- Given an operator migrates a document with a section containing only "TBD", when
  `write_artifact` is called, then that placeholder section is not embedded and does not appear
  as a vector in the index, and the full document content (including the TBD section) is still
  stored in S3 and returned by `read_artifact`.
- Given a document with three sections where one body is 30 characters and
  `EMBED_MIN_SECTION_LENGTH=50`, when `write_artifact` is called, then `bedrock.embed` is called
  twice (not three times) and `sections_indexed == 2`.

Source: —

### R2 — The section count is capped at `EMBED_MAX_SECTIONS`

When the filtered section list exceeds `settings.embed_max_sections`, `write_artifact` retains
only the first `settings.embed_max_sections` entries and discards the rest: only the first
`EMBED_MAX_SECTIONS` sections are indexed, and the rest are silently dropped from the vector
index.

**Example**

- Given a document with 25 sections and `EMBED_MAX_SECTIONS=20`, when `write_artifact` is
  called, then `bedrock.embed` is called 20 times and `sections_indexed == 20`.
- Given a document with 10 sections and `EMBED_MAX_SECTIONS=20`, when `write_artifact` is
  called, then all 10 sections are indexed and `sections_indexed == 10` (cap not triggered).

Source: —

### R3 — No remaining sections falls back to the document-level embed

When filtering and capping leave zero sections, `write_artifact` falls back to the
document-level embed (title + description) — it does not return an error.

**Example**

- Given a document where all sections are below the threshold, when `write_artifact` is called,
  then the document-level fallback is used (one embed from title + description), not zero
  embeds.

Source: —

### R4 — Dropped sections are logged at DEBUG

When sections are dropped by either filter, `write_artifact` logs a DEBUG message indicating the
number of sections dropped and the reason (length filter or cap).

Source: —

### R5 — `sections_indexed` counts only indexed sections

When `write_artifact` returns, `sections_indexed` includes only the sections actually embedded
and indexed (dropped sections are not counted).

Source: —

## 3. Rules — Configuration

### R6 — Defaults and validation of the two settings

| Setting | Absent from the environment | Rejected at startup with a clear validation error when |
|---|---|---|
| `EMBED_MIN_SECTION_LENGTH` | defaults to 50 | set to a value less than 0 |
| `EMBED_MAX_SECTIONS` | defaults to 20 | set to a value less than 1 |

Source: —

### R7 — The defaults leave typical structured artifacts untouched

The defaults (`EMBED_MAX_SECTIONS=20`, `EMBED_MIN_SECTION_LENGTH=50`) do not affect typical
structured artifacts (ADRs, specs, code reviews) which have 3–15 meaningful sections, and require
no operator action.

**Example**

- Given a document with 8 sections each with 200-character bodies and no env vars set, when
  `write_artifact` is called, then all 8 sections are indexed (defaults do not interfere).
- Given a document with 15 sections of 100+ characters each, when defaults are in effect, then
  all 15 are indexed.

Source: —

## 4. Boundaries

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

## 5. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_config.py` | Modify | Add tests for new config vars (written first — Red) |
| `tests/unit/test_tools_write.py` | Modify | Add section cap and min-length filter tests (written first — Red) |
| `src/arkeology/config.py` | Modify | Add `EMBED_MAX_SECTIONS` (int, default 20, ≥ 1) and `EMBED_MIN_SECTION_LENGTH` (int, default 50, ≥ 0) with validators; add `embed_max_sections` and `embed_min_section_length` properties |
| `src/arkeology/tools/write.py` | Modify | After `sections = parse_sections(content)`, apply length filter then cap; log dropped sections at DEBUG; fall back to document-level embed if no sections remain after filtering |

### Contracts

None.

### Testing Approach

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
