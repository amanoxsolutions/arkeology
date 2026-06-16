---
type: spec
title: T6 — Artifact Model and Key Generation
description: Feature spec for the pure artifact model module providing deterministic key generation, markdown section parsing, and metadata validation shared by all Phase 2+ tools.
tags: []
timestamp: 2026-05-30T00:00:00Z
okf_version: "0.1"
feature: p2-t6-artifact-model
status: ready
phase: 2
task: 6
references: []
authored:
  by: "architect"
  date: "2026-05-30"
revised:
  by: ""
  date: ""
---

# T6 — Artifact Model and Key Generation

<!-- SCOPE BLOCK — frozen after approval -->

## Problem Statement

All Phase 2 tools share two foundational concerns: a consistent metadata schema for every
artifact, and a deterministic way to derive an S3 key from an artifact's own attributes.
Without this layer, each tool would independently derive keys and validate metadata,
producing divergent behaviour and making the idempotency guarantees in FR-08 untestable.
This task delivers a single pure module — no AWS calls — that every tool imports.

## User Stories

### Story 1 — Same inputs always produce the same artifact key (P1)

A developer agent writes a tier 2 code review on 2026-05-30 twice in the same session. The
server must produce the same S3 key both times and silently overwrite.

**Acceptance criteria:**
- Given tier=2, type="code_review", date="2026-05-30", title="Fix auth bug", when
  `generate_artifact_id` is called twice with identical inputs, then both calls return the
  exact same string.
- Given tier=2, type="code_review", date="2026-05-30", title="Fix auth bug", and a second
  call with date="2026-05-31", when `generate_artifact_id` is called, then the two returned
  strings differ.
- Given tier=3, type="adr", title="Use Postgres", when `generate_artifact_id` is called on
  two different dates, then both calls return the exact same string (date is ignored for tier 3).

### Story 2 — Markdown sections are parsed correctly (P1)

The write tool needs the section list to know how many vectors to generate and what to embed.

**Acceptance criteria:**
- Given content containing three `##` headings, when `parse_sections` is called, then three
  sections are returned each with its heading text and body content.
- Given content with no `##` headings, when `parse_sections` is called, then an empty list
  is returned (signals fallback to document-level embedding).
- Given a section heading with mixed case and punctuation, when `section_slug` is called on
  the heading text, then the result is lowercase, non-alphanumeric characters replaced with
  `-`, leading/trailing `-` stripped, consecutive `-` collapsed to one.

### Story 3 — Artifact metadata is validated on construction (P1)

A malformed tool call with description over 280 characters or an unknown type must be
rejected before any AWS call is made.

**Acceptance criteria:**
- Given a description of 281 characters, when an `Artifact` is constructed, then a
  validation error is raised.
- Given an unknown artifact type, when an `Artifact` is constructed, then a validation error
  is raised listing the valid types.
- Given `tier=4`, when an `Artifact` is constructed, then a validation error is raised.
- Given all required fields valid and optional fields absent, when an `Artifact` is
  constructed, then `feature_tags` defaults to `[]` and `author_role` defaults to `None`.

## Requirements

- WHEN `generate_artifact_id` is called with tier=2 THE SYSTEM SHALL produce a deterministic
  string derived from `type`, `date`, and `title` — no random component.
- WHEN `generate_artifact_id` is called with tier=3 THE SYSTEM SHALL produce a deterministic
  string derived from `type` and `title` only — date is not a factor.
- WHEN two calls to `generate_artifact_id` produce the same string THE SYSTEM SHALL guarantee
  the inputs are logically identical (no accidental collision for distinct inputs that a
  real-world agent would produce).
- WHEN `parse_sections` is called on content with one or more `##` headings THE SYSTEM SHALL
  return one section per `##` heading, preserving order, with heading text and the body text
  that follows it up to the next `##` heading or end of content.
- WHEN `parse_sections` is called on content with no `##` headings THE SYSTEM SHALL return
  an empty list.
- WHEN `section_slug` is called on a heading string THE SYSTEM SHALL return a URL-safe,
  lowercase slug suitable for use as a vector key suffix after the `#` separator.
- WHEN an `Artifact` is constructed with a description exceeding 280 characters THE SYSTEM
  SHALL raise a validation error before any field is stored.
- WHEN an `Artifact` is constructed with a type not in the valid type catalogue THE SYSTEM
  SHALL raise a validation error.

## Boundaries

**Always:**
- This module is pure Python — zero AWS calls, zero imports from `clients/`.
- `generate_artifact_id` must be a plain function, not a method.
- The valid artifact types are: `code_review`, `session_summary`, `implementation_note`,
  `spec`, `adr`, `bug_report`, `decision_note`, `synthesis`, `learning`. This set is the
  single source of truth; tools and MCP Resources in later phases import it from here.
  (The vocabulary was later extended in p7-t25b with `prd`, `plan`, `runbook`, `changelog`,
  `postmortem`, and again with `learning` — see those specs for the current full set.)
- Tier values are `2` (project-local, append-only) and `3` (shared, living document).
- Visibility values are `"shared"` and `"hidden"`.
- Status values are `"active"` and `"inactive"`.
- The `Artifact` model is an internal data class — it is never serialised directly to MCP
  output. Tools convert it to dicts for responses.

**Ask First:**
- Nothing — all constraints are defined.

**Never:**
- Do not generate random components in the key (UUID, timestamp with sub-second precision).
- Do not parse `#` (H1) headings as sections — only `##` (H2) headings define section
  boundaries.
- Do not strip or truncate artifact content during section parsing.

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_artifact.py` | Create | Written first (Red); all cases below |
| `src/cairn_mcp/artifact.py` | Create | Written after tests fail (Green) |

## Testing Approach

**TDD cycle — write `test_artifact.py` first, confirm all tests fail (ImportError), then
implement `artifact.py` until all pass.**

**`test_artifact.py` — unit tests:**

Key generation:
- Tier 2: same type+date+title → same id; different date → different id.
- Tier 2: different title same type+date → different id.
- Tier 3: same type+title, two different dates → same id.
- Tier 3: different title same type → different id.
- Key contains no characters that are illegal in S3 object keys.
- Key does not start or end with `/`.

Section parsing:
- Content with zero `##` headings returns empty list.
- Content with one `##` heading returns one section with correct heading and body.
- Content with three `##` headings returns three sections in order.
- Section body does not include the `##` heading line itself.
- Content before the first `##` heading is not included in any section.
- `##` heading with trailing whitespace is normalised.
- `###` (H3) and deeper headings inside a section body are not treated as section boundaries.

Section slug:
- All lowercase.
- Spaces become `-`.
- Non-alphanumeric, non-hyphen characters are removed or replaced with `-`.
- Consecutive `-` collapsed to one.
- Leading/trailing `-` stripped.
- Empty heading produces a non-empty fallback slug (e.g., `"section"`).

Artifact model validation:
- Description >280 chars → validation error.
- Description exactly 280 chars → valid.
- Unknown type → validation error.
- Invalid tier (1, 4, 0) → validation error.
- Invalid visibility → validation error.
- Optional fields (`feature_tags`, `author_role`) default correctly.
- `synthesis` type with `source_artifacts=[]` → valid (list may be empty at construction).

**Edge cases:**
- Title containing only whitespace → should produce a valid key (not an empty string key).
- Title with Unicode characters (e.g. accented characters) → key must still be a valid S3
  key (restrict to ASCII-safe representation).
- Artifact constructed with tier=3 and `source_artifacts` set → valid (Phase 3 use case,
  must not be rejected in Phase 2).

## Key Generation Format — Decision

**Use the slug approach.** Format:

- Tier 2: `{type}-{date}-{title_slug}` — e.g., `code-review-2026-05-30-fix-auth-bug`
- Tier 3: `{type}-{title_slug}` — e.g., `adr-use-postgres-for-sessions`

**Why slugs, not hashes:**

1. **Collisions are intentional.** Two titles that normalise to the same slug — e.g.,
   `"Fix Auth Bug"` and `"Fix auth bug!"` — represent the same artifact. The normalisation
   acts as a natural deduplication step, which is exactly what the idempotency contract
   requires.
2. **Debuggability.** The S3 console, CloudTrail, and log lines all show human-readable
   keys. No cross-referencing a lookup table to understand what a key refers to.
3. **Scale.** This is a single-team project store. The probability of two genuinely distinct
   artifacts producing the same slug is negligible.

**Normalisation rules for `title_slug`:**
- Lowercase the title.
- Replace any run of non-alphanumeric characters with a single `-`.
- Strip leading and trailing `-`.
- Truncate to 60 characters maximum (keeps the full S3 key well under the 1,024-byte limit
  even with a long prefix).
- If the result is empty after normalisation (e.g., a title of all punctuation), use the
  fallback `"artifact"`.
- Unicode: transliterate accented characters to ASCII equivalents before slugifying (e.g.,
  `é` → `e`); characters with no ASCII equivalent are dropped.

Document these rules in the `artifact.py` module docstring. Add a test case for each rule.

## Open Questions

*(none — all decisions resolved)*
