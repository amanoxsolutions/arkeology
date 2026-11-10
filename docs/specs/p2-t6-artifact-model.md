---
type: Spec
id: p2-t6-artifact-model
title: T6 — Artifact Model and Key Generation
description: Feature spec for the pure artifact model module providing deterministic key generation, markdown section parsing, and metadata validation shared by all Phase 2+ tools.
tags: []
status: stable
okf_version: "0.2"
sources:
  - resource: docs/architecture-decisions/adr-2026-05-29-deterministic-artifact-ids.md
    title: Deterministic Slug-Based Artifact Identifiers
    last_modified: 2026-09-29T00:00:00Z
generated:
  by: "axians-architect/unknown"
  at: 2026-05-30T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-10T06:08:45Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
---

# T6 — Artifact Model and Key Generation

## TL;DR

A single pure Python module — no AWS calls — that every Phase 2+ tool imports for three shared
concerns: deterministic artifact key generation, `##`-heading section parsing, and artifact metadata
validation. It gives all tools one consistent metadata schema and one key derivation, so the
idempotency guarantees in FR-08 become testable.

## 1. Problem Statement

All Phase 2 tools share two foundational concerns: a consistent metadata schema for every
artifact, and a deterministic way to derive an S3 key from an artifact's own attributes.
Without this layer, each tool would independently derive keys and validate metadata,
producing divergent behaviour and making the idempotency guarantees in FR-08 untestable.
This task delivers a single pure module — no AWS calls — that every tool imports. Its three user
stories — deterministic keys, section parsing, metadata validation on construction — are all
priority P1.

## 2. Rules — Key generation

### R1 — Same inputs always produce the same artifact key

`generate_artifact_id` is deterministic, with no random component. With tier 2 it derives the key
from `type`, `date` and `title`; with tier 3 it derives it from `type` and `title` only — date is not
a factor. When a developer agent writes a tier 2 code review on 2026-05-30 twice in the same session,
the server produces the same S3 key both times and silently overwrites.

**Example**

- Given tier=2, type="code_review", date="2026-05-30", title="Fix auth bug", when
  `generate_artifact_id` is called twice with identical inputs, then both calls return the exact
  same string.
- Given the same tier 2 inputs and a second call with date="2026-05-31", when
  `generate_artifact_id` is called, then the two returned strings differ.
- Given tier=3, type="adr", title="Use Postgres", when `generate_artifact_id` is called on two
  different dates, then both calls return the exact same string (date is ignored for tier 3).

Source: FR-08

### R2 — Logically distinct inputs do not accidentally share a key

When two calls to `generate_artifact_id` produce the same string, the inputs are logically
identical — there is no accidental collision for distinct inputs that a real-world agent would
produce. A different title with the same type and date (tier 2), or with the same type (tier 3),
produces a different id.

### R3 — Key format is a slug plus a deterministic hash suffix

The key is a slug plus a deterministic hash suffix:

- Tier 2: `{type_slug}-{date}-{title_slug}-{hash}` — e.g., `code-review-2026-05-30-fix-auth-bug-a1b2c3d4`
- Tier 3: `{type_slug}-{title_slug}-{hash}` — e.g., `adr-use-postgres-for-sessions-a1b2c3d4`

`hash` is the first 8 hex characters of a SHA-256 digest of the full, original (un-normalised,
un-truncated) title. It is **always** appended — never only when a collision is detected.

The only titles that produce the same generated key are ones whose raw text is identical — for
tier 2 that is the same-day idempotent retry; for tier 3 that is the intended living-document
update. Either way, a write to an already-existing generated key is rejected unless the caller
passes an explicit `overwrite` flag.

**Why the slug:** debuggability — the S3 console, CloudTrail, and log lines all show a
human-readable prefix; a pure hash key would not be legible without a separate lookup table.

**Why the hash:** collision safety — a slug-only scheme silently collapses any two titles that
normalise to the same slug onto one key, most destructively for three cases nobody intends to
collide: titles with no Latin/digit content (all fall back to the constant slug `"artifact"`),
titles differing only past the 60-character truncation point, and titles differing only in
punctuation the normalisation strips. Because the hash is taken from the untouched, full original
title, two textually different titles essentially never share a generated key, even when their
slugs collide — their hashes still differ. The ADR's 2026-07-02 revision records the incident and
the full resolution.

Source: adr-2026-05-29-deterministic-artifact-ids

### R4 — `title_slug` normalisation

`title_slug` is derived from the title as follows:

- Lowercase the title.
- Replace any run of non-alphanumeric characters with a single `-`.
- Strip leading and trailing `-`.
- Truncate to 60 characters maximum (keeps the full S3 key well under the 1,024-byte limit even
  with a long prefix).
- If the result is empty after normalisation (e.g., a title of all punctuation), use the fallback
  `"artifact"`.
- Unicode: transliterate accented characters to ASCII equivalents before slugifying (e.g.,
  `é` → `e`); characters with no ASCII equivalent are dropped.

Source: adr-2026-05-29-deterministic-artifact-ids

### R5 — Every generated key is a valid S3 key

A generated key contains no characters that are illegal in S3 object keys, and does not start or
end with `/`. A title containing only whitespace should produce a valid key (not an empty string
key). A title with Unicode characters (e.g. accented characters) must still produce a valid S3 key
(restrict to an ASCII-safe representation).

## 3. Rules — Markdown sections

### R6 — `parse_sections` returns one section per `##` heading

The write tool needs the section list to know how many vectors to generate and what to embed. When
`parse_sections` is called on content with one or more `##` headings, it returns one section per
`##` heading, preserving order, with the heading text and the body text that follows it up to the
next `##` heading or end of content. The section body does not include the `##` heading line
itself; content before the first `##` heading is not included in any section; `###` (H3) and deeper
headings inside a section body are not section boundaries; a `##` heading with trailing whitespace
is normalised.

**Example**

- Given content containing three `##` headings, when `parse_sections` is called, then three
  sections are returned in order, each with its heading text and body content.

### R7 — Content with no `##` headings returns an empty list

When `parse_sections` is called on content with no `##` headings, it returns an empty list, which
signals fallback to document-level embedding.

### R8 — `section_slug` produces a URL-safe lowercase slug

When `section_slug` is called on a heading string, it returns a URL-safe, lowercase slug suitable
for use as a vector key suffix after the `#` separator: lowercase, spaces become `-`,
non-alphanumeric characters replaced with `-`, consecutive `-` collapsed to one, leading/trailing
`-` stripped. An empty heading produces a non-empty fallback slug (e.g., `"section"`).

**Example**

- Given a section heading with mixed case and punctuation, when `section_slug` is called on the
  heading text, then the result is lowercase, non-alphanumeric characters replaced with `-`,
  leading/trailing `-` stripped, consecutive `-` collapsed to one.

## 4. Rules — Artifact metadata validation

### R9 — Description over 280 characters is rejected on construction

A malformed tool call with a description over 280 characters or an unknown type must be rejected
before any AWS call is made. When an `Artifact` is
constructed with a description exceeding 280 characters, a validation error is raised before any
field is stored. A description of exactly 280 characters is valid.

**Example**

- Given a description of 281 characters, when an `Artifact` is constructed, then a validation error
  is raised.

### R10 — Unknown artifact type is rejected

When an `Artifact` is constructed with a type not in the valid type catalogue, a validation error is
raised listing the valid types. The valid artifact types are: `code_review`, `session_summary`,
`implementation_note`, `spec`, `adr`, `bug_report`, `decision_note`, `synthesis`, `brainstorming`.
(The vocabulary was later extended in p7-t25b with `prd`, `plan`, `runbook`, `changelog`,
`postmortem`, and later again with `learning` — see those specs for the current full set.)

### R11 — Tier and visibility must be valid values

Tier values are `2` (project-local, append-only) and `3` (shared, living document); any other tier
(1, 4, 0) raises a validation error on construction. Visibility values are `"shared"` and
`"hidden"`; an invalid visibility raises a validation error.

**Example**

- Given `tier=4`, when an `Artifact` is constructed, then a validation error is raised.

### R12 — Optional fields default when absent

Given all required fields valid and optional fields absent, when an `Artifact` is constructed,
`tags` defaults to `[]` and `author_role` defaults to `None`.

### R13 — `source_artifacts` may be empty for a synthesis, or set on a tier 3 artifact, at construction

A `synthesis` type with `source_artifacts=[]` is valid — the list may be empty at construction. An
artifact constructed with tier=3 and `source_artifacts` set is valid (Phase 3 use case, must not be
rejected in Phase 2).

## 5. Boundaries

**Always:**
- This module is pure Python — zero AWS calls, zero imports from `clients/`.
- `generate_artifact_id` must be a plain function, not a method.
- The valid artifact type set (R10) is the single source of truth; tools and MCP Resources in later
  phases import it from here.
- Status values are `"active"` and `"inactive"`.
- The `Artifact` model is an internal data class — it is never serialised directly to MCP output.
  Tools convert it to dicts for responses.

**Ask First:**
- Nothing — all constraints are defined.

**Never:**
- Do not generate random components in the key (UUID, timestamp with sub-second precision).
- Do not parse `#` (H1) headings as sections — only `##` (H2) headings define section boundaries.
- Do not strip or truncate artifact content during section parsing.

## 6. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_artifact.py` | Create | Written first (Red); all cases below |
| `src/arkeology/artifact.py` | Create | Written after tests fail (Green). Document the `title_slug` normalisation rules (R4) and the hash-suffix rule (R3) in the module docstring |

### Contracts

None.

### Testing Approach

**TDD cycle — write `test_artifact.py` first, confirm all tests fail (ImportError), then implement
`artifact.py` until all pass.**

**`test_artifact.py` — unit tests:**

Key generation (R1, R2, R5):
- Tier 2: same type+date+title → same id; different date → different id.
- Tier 2: different title same type+date → different id.
- Tier 3: same type+title, two different dates → same id.
- Tier 3: different title same type → different id.
- Key contains no characters that are illegal in S3 object keys.
- Key does not start or end with `/`.

Key format and `title_slug` normalisation (R3, R4): add a test case for each normalisation rule and
for the hash-suffix rule.

Section parsing (R6, R7):
- Content with zero `##` headings returns empty list.
- Content with one `##` heading returns one section with correct heading and body.
- Content with three `##` headings returns three sections in order.
- Section body does not include the `##` heading line itself.
- Content before the first `##` heading is not included in any section.
- `##` heading with trailing whitespace is normalised.
- `###` (H3) and deeper headings inside a section body are not treated as section boundaries.

Section slug (R8):
- All lowercase.
- Spaces become `-`.
- Non-alphanumeric, non-hyphen characters are removed or replaced with `-`.
- Consecutive `-` collapsed to one.
- Leading/trailing `-` stripped.
- Empty heading produces a non-empty fallback slug (e.g., `"section"`).

Artifact model validation (R9–R13):
- Description >280 chars → validation error.
- Description exactly 280 chars → valid.
- Unknown type → validation error.
- Invalid tier (1, 4, 0) → validation error.
- Invalid visibility → validation error.
- Optional fields (`tags`, `author_role`) default correctly.
- `synthesis` type with `source_artifacts=[]` → valid (list may be empty at construction).

**Edge cases:**
- Title containing only whitespace → should produce a valid key (not an empty string key).
- Title with Unicode characters (e.g. accented characters) → key must still be a valid S3 key
  (restrict to ASCII-safe representation).
- Artifact constructed with tier=3 and `source_artifacts` set → valid (Phase 3 use case, must not
  be rejected in Phase 2).
