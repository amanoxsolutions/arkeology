---
type: Spec
id: p15-t89-schema-resource
title: T89 — Schema Resource Rewrite
description: Rewrites the arkeology://schema/artifact resource into a field reference in OKF v0.2 terms. It has one entry per artifact field, each giving the field's meaning, type, where it appears and its OKF mapping, plus a section on the in-force view. The entries resolve the names that mean different things in OKF and in Arkeology. The tiers, visibility and query-strategy resources gain the supplied-id key form, link-field redaction and revision-time recency. Tests check that every field is present and fit its live responses, and do not depend on the prose wording.
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
    title: "Arkeology — Requirements"
    last_modified: 2026-09-24T00:00:00Z
  - resource: docs/planning-artifacts/plan.md
    title: Plan Arkeology
    last_modified: 2026-10-07T13:29:34Z
  - resource: docs/contracts/modules/arkeology.resources.md
    title: arkeology.resources
    last_modified: 2026-09-04T00:00:00Z
  - resource: docs/specs/p15-t76-archived-boolean.md
    title: T76 — Archive Marker status → archived (bool)
    last_modified: 2026-10-13T15:57:36Z
  - resource: docs/specs/p15-t77-open-type-list.md
    title: T77 — Open Type List
    last_modified: 2026-10-13T13:04:34Z
  - resource: docs/specs/p15-t78-create-update-split.md
    title: T78 — Split Writing into create_artifact / update_artifact; Drop overwrite
    last_modified: 2026-10-13T13:02:46Z
  - resource: docs/specs/p15-t79-provenance.md
    title: "T79 — Provenance: generated / revised; Drop date, author_role, timestamp"
    last_modified: 2026-10-13T16:20:20Z
  - resource: docs/specs/p15-t80-revision-history.md
    title: "T80 — Revision-History Annotation + Shared Compare-and-Swap Append Helper"
    last_modified: 2026-10-13T16:40:30Z
  - resource: docs/specs/p15-t81-lifecycle-status-in-force.md
    title: T81 — OKF Lifecycle status and the In-Force Default View
    last_modified: 2026-10-13T16:19:13Z
  - resource: docs/specs/p15-t82-lifecycle-change.md
    title: T82 — Change Lifecycle status Without Re-Embedding
    last_modified: 2026-10-13T17:40:25Z
  - resource: docs/specs/p15-t83-verified.md
    title: "T83 — verified Annotation, add_artifact_verification, and the \"Unverified Since Revised\" Flag"
    last_modified: 2026-10-13T17:50:06Z
  - resource: docs/specs/p15-t84-sources-relationships.md
    title: "T84 — sources + relationships in One Structured Annotation; link_metadata → add_artifact_links"
    last_modified: 2026-10-13T17:23:06Z
  - resource: docs/specs/p15-t85-link-gate-withheld.md
    title: "T85 — Cross-Scope Gate on sources and relationships, with the {withheld: n} Marker"
    last_modified: 2026-10-13T18:07:52Z
  - resource: docs/specs/p15-t86-per-source-freshness.md
    title: "T86 — Per-Source Freshness"
    last_modified: 2026-10-13T18:19:14Z
  - resource: docs/specs/p15-t87-supplied-ids.md
    title: T87 — Producer-Supplied id Becomes the Artifact Id
    last_modified: 2026-10-13T16:38:44Z
  - resource: docs/specs/p15-t88-migration-frontmatter.md
    title: T88 — Migration and Source-Backfill Skills for OKF v0.2 Frontmatter
    last_modified: 2026-10-13T18:53:42Z
  - resource: https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/main/SPEC.md
    title: Open Knowledge Format (OKF) v0.2 specification
relationships:
  - to: adr-2026-09-25-okf-v02-adoption
    type: implements
generated:
  by: "axians-architect/claude-opus-5.5"
  at: 2026-10-13T19:23:58Z
phase: 15
task: 89
---

# T89 — Schema Resource Rewrite

<!-- SCOPE BLOCK — frozen after approval -->

## TL;DR

`arkeology://schema/artifact` becomes a field reference. It has one entry per artifact field, and
each entry gives the field's meaning, type, where it appears and its OKF mapping. A further section
explains the in-force view. Several names mean one thing in OKF and another in Arkeology: `status`,
`tier`, `sources[].id`, `generated.at` and an absent `status`. After this task an agent reading any
of them gets the meaning from the resource instead of guessing. Tests check that every field is
present and fit the live tool responses, and do not depend on the wording (FR-18; ADR-017
`### 8. Tool surface`).

## Problem Statement

T76–T88 replace most of the artifact model. Each of those tasks edited only its own rows of the
schema resource, so the result lists fields by name and type but does not say what they mean or
how they relate to OKF. FR-18 requires the resource to give "what each field means and how an agent
should interpret it". The brainstorming session recorded the risk in its
`## What Changes?` section, under "Agent-facing schema resource": without this, an agent reads
`status` or `sources[].id` by guesswork. Five names are open to a wrong reading:

- OKF §5.4 treats a missing `status` as `stable`, but the filter `status="stable"` does not match a
  missing value.
- Arkeology's `tier` is its access tier, while OKF §5.3 derives a separate trust tier from
  `verified`.
- `sources[].id` is a footnote label, but it looks like an artifact id.
- OKF §5.2 describes `generated.at` as the "last meaningful change", but Arkeology stores the time
  of first authorship there.
- `last_edited_at` is when the server stored the artifact. For an imported document that is the
  import time, not when the content was revised.

## User Stories

### Story 1 — Every field has an entry an agent can find (P1)

- Given `arkeology://schema/artifact`, then it has exactly one entry for each field in the
  Requirements table, and each entry states the field's meaning, type, where it appears and its OKF
  mapping.
- Given an artifact returned by `read_artifact`, `list_artifacts` (with the revision history
  requested) or `search_artifacts`, then every key on it has an entry, with one exception: the
  search ranking key `score`.

### Story 2 — Overloaded names are disambiguated (P1)

- Given an agent reading `sources[].id`, then the resource says it is a footnote label and not an
  artifact id.
- Given `tier: 3`, then the resource says this is Arkeology's access tier and not OKF's trust tier.
- Given `generated.at`, then the resource says it is the time of first authorship and that
  `revised.at` holds the latest change.
- Given `status: null`, then the resource says OKF reads a missing status as `stable`, that the
  artifact is in force, and that `status="stable"` does not match it.

### Story 3 — An agent asks for the view it means (P1)

- Given the in-force section, then an agent can build the default call, the full-lineage call
  (`archived="all"` with `status="all"`) and the exclude-drafts call, and knows that `supersedes`
  never removes an artifact from the default view.

### Story 4 — A foreign reader understands the marker (P1)

- Given a foreign artifact whose `sources` ends in `{withheld: 2}`, then the resource says two
  entries were removed because they point at artifacts this reader cannot read, and that the
  marker is not a source.

### Story 5 — No removed name is taught (P1)

- Given any of the five schema resources, then none names a name that AC-80 lists as removed.

## Requirements

**Structure** (FR-18)

- THE SYSTEM SHALL serve `arkeology://schema/artifact` as markdown with three parts:
  - a conventions section;
  - one entry per field in the table below, each headed by a level-3 heading whose whole text is
    the field name in backticks (`` ### `status` ``);
  - a section on the in-force view.

  No other level-3 heading in this resource SHALL take that form.
- Each field entry SHALL carry four labelled parts: `Meaning:`, `Type:`, `Appears in:` and `OKF:`.
  - `Type` states the shape and whether the field is required, optional or set by the server.
  - `Appears in` names the tools that accept the field and the tools that return it.
- Sub-keys of `sources` and `relationships` SHALL be described inside their parent's entry, not as
  entries of their own.
- THE SYSTEM SHALL keep `artifact_schema_content` pure, identical across calls and deployments, and
  free of AWS access. It SHALL read the recommended type list live from
  `RECOMMENDED_ARTIFACT_TYPES` (T77).
- Every reference to OKF SHALL cite a section (`§5.1`) or be written out as "OKF GitHub issue #N".

**Conventions section** (D19, D35; OKF §7)

- Every `by` is an OKF §7 actor (`<producer>/<version>`, `human:<id>` or `process:<id>`) and is
  stored verbatim.
- Every `at` is ISO 8601 with a UTC offset, and Arkeology writes it as `YYYY-MM-DDTHH:MM:SSZ`.
- `sources[].last_modified` is kept exactly as it was supplied.
- Timestamps are compared as parsed instants, never as strings.
- Metadata comes only from tool parameters. The server never parses the content's frontmatter to
  fill a field.

**Field entries** (FR-18, FR-09). An entry may add detail, but it SHALL NOT contradict the cited
spec. Each row lists what the entry SHALL make clear.

| Field | The entry SHALL make clear | OKF mapping | Traces to |
|---|---|---|---|
| `artifact_id` | The full key `<scope>/<id><extension>` that every tool takes and returns. It never changes, including on update and retitle. A bare id inside a link is relative to the artifact that holds the link. To follow one, call `read_artifact` with the bare id and set `linked_from` to the holder's `artifact_id`. `arkeology://artifact/{id*}` resolves a bare id against the reader's own scope | None (store key) | D28, FR-75, AC-83; T78, T84, T88 |
| `id` | Optional, and only on create (the single, bulk and migrate tools). It is used verbatim as the bare id, with no suffix, case kept, and never repaired. Form: 1–128 characters from `A-Z a-z 0-9 . _ -`, letter or digit first and last, no `..`. When omitted, the id is generated as the tiers resource describes. Ids that differ only in case are different artifacts. Unrelated to `sources[].id` | Not an OKF v0.2 key; an extension key under §4.1 | D28, D33, FR-73, AC-76; T87 |
| `type` | Required and free-form. Stored and matched exactly, including case. Unknown values are accepted. The entry lists the recommended display names and points to `arkeology://schema/types`. Cannot change on update | §4.1 `type`, which consumers must tolerate when unknown | D37, FR-09, AC-77, AC-84; T77 |
| `team`, `project` (two entries) | Required free text naming the owner. Filterable. Cannot change on update | None | FR-09, AC-84 |
| `tier` | `2` means project-local and never readable from another scope. `3` means permanent and shareable. Cannot change on update. This is Arkeology's access tier, not OKF's trust tier: a reader derives the trust tier from `verified`, and Arkeology never computes or changes it | None; distinct from the §5.3 trust tiers | FR-09, FR-10, D41 |
| `visibility` | `shared` or `hidden`. Only a tier-3 `shared` artifact is readable from another scope | None | FR-10 |
| `title` | Required. May change on update; `artifact_id` stays the same | §4.1 `title` (recommended in OKF, required here) | FR-09, AC-83 |
| `description` | Required, at most 280 characters | §4.1 `description` | FR-09 |
| `tags` | Optional list of strings. Filterable | §4.1 `tags` | FR-09 |
| `archived` | Boolean, always present. Only `archive_artifact` sets it, and an update carries it forward. No tool unsets it, and `purge_archived` deletes archived artifacts. It is the store's archive marker, not a lifecycle state. Filter values: `false` (the default), `true`, `"all"` | None; kept apart from §5.4 | D21, FR-05, FR-14; T76 |
| `status` | `draft`, `stable`, `deprecated`, or `null` when none was given. The writer sets it on create or update; an update replaces it when it passes `status`, keeps it when it omits `status`, and removes it when it passes `status: null`. `set_artifact_status` changes it alone, and `null` there clears it; this neither re-embeds nor moves `revised`. OKF reads `null` as `stable`, and a `null` artifact is in force, but the filter `status="stable"` matches only a stored `stable`. Never taken from the content's frontmatter | §5.4 `status` | D22–D24, FR-67, FR-68, AC-69, AC-71; T81, T82 |
| `generated` | `{by, at}`, always present: who first wrote the artifact and when. Required on create, with `by` required and `at` optional (the server clock when omitted). Written once and never rewritten. A generated tier-2 id anchors on the UTC day of `generated.at`. Read `generated.at` as first authorship, not as last change. OKF v0.2 words it differently in §5.1 and §5.2, and Arkeology follows §5.1 (OKF GitHub issue #28) | §5.2 `generated`, read as §5.1 describes it | D9, D32, D35, FR-69, AC-72; T79 |
| `revised` | `{by, at}` of the latest content revision, or `null` before the first update. Required on `update_artifact`. Moves only on content writes: never on link backfill, archive, lifecycle change, verification or reconciliation. A document imported by `migrate_artifacts` may arrive with its existing `revised`. Content recency is `revised.at`, or `generated.at` when `revised` is `null` | Not an OKF v0.2 key; the latest-revision block that the OKF GitHub issue #28 thread converged on | D19, D35, FR-69, AC-72; T79, T88 |
| `revision_history` | `{by, at}` list, oldest first, with one entry per create or update and no length cap. `read_artifact` always returns it. `list_artifacts` returns it only when called with `include_revision_history=true` | None; entries use §7 actors | D26, D30, D34, FR-72, AC-75; T80 |
| `verified` | `{by, at}` list in the order recorded, or `[]`. Added only by `add_artifact_verification`, never on create or update; this neither re-embeds nor moves `revised`. Returned by `read_artifact` only. The latest verification is the one with the greatest `at`, which is not necessarily the last entry. A reader derives OKF's trust tier from this list: no entries means unverified, only non-`human:` actors means machine-confirmed, and any `human:` actor means human-reviewed | §5.2 `verified`, §5.3 | D41, D44, D45, FR-70, AC-73; T83 |
| `unverified_since_revised` | Boolean, returned by `read_artifact` only. True only when `verified` is non-empty, `revised` is present, and the latest `verified.at` is earlier than `revised.at`. Advisory: it changes no tier and no other field | None; leaves the §5.3 tier alone | D41, D45, FR-71, AC-74; T83 |
| `sources` | What the artifact was built from (derivation). Each entry is `{resource, last_modified?, id?, title?}`, and any `author`, `usage_count` or `usage_window` is kept as supplied. Sub-keys: `resource` is `arkeology://artifact/` followed by a bare id or a full key. A bare id is relative to this artifact's scope and implies `.md`, so another extension must be cited by full key. Otherwise `resource` is a URL, an unresolved path or a scope descriptor, stored as given and never followed. `last_modified` is a snapshot of the source's revision time when this artifact was written, not a live copy. When it is omitted for a readable Arkeology source, it is filled from that source's current `revised.at`, or `generated.at` if never revised. A source is stale when its current time is later than its `last_modified`. `check_synthesis_freshness` reports stale sources, and reports a source it cannot judge under `unchecked_sources` with reason `no_baseline` or `unreadable_timestamp`. `id` is a footnote label that joins body citations (`[^label]`) to the entry. It is never an artifact id, so do not resolve it. `title` is a display label. An update replaces the whole list, and omitting it clears the list. `add_artifact_links` adds entries keyed by `resource` and keeps the first one. Returned by `read_artifact`, `list_artifacts` and the create and update responses. Never a filter. A foreign reader gets entries pointing at artifacts it cannot read removed, with one `{withheld: n}` entry appended that carries the count. That entry has no `resource` and is not a source | §5.1 `sources`; the marker follows the OKF GitHub issue #32 proposal | D17–D19, D40, D43, D47, D48, FR-20, FR-51, FR-53, AC-18, AC-56, AC-57, AC-78; T84–T86 |
| `relationships` | Typed claims about other artifacts (association, not derivation). Each entry is `{to, type}`, and any per-edge `generated` or `verified`, or unknown key, is kept as supplied. `to` is a bare id (relative to this artifact's scope) or a full key, never a URI or a path. `type` is a case-sensitive string, for example `supersedes`, `builds_on` or `amends`. Edges are outbound only. A missing target is not an error. `supersedes` records lineage only: it never removes its target from the in-force view, and only the target's own `status: deprecated` does that. The update, return, filter and `{withheld: n}` rules are the same as for `sources`, except that `add_artifact_links` keys entries on `to` and `type` together | Not an OKF v0.2 key; an extension key shaped by the OKF GitHub issue #16 proposal | D13, D17, D25, D47, FR-51, AC-70, AC-78; T84, T85 |
| `commit_refs` | Git commit SHAs. They accumulate and are never removed: an update and `add_artifact_links` both merge. `read_artifact` and `list_artifacts` return the full list. The `commit_refs` filter applies AND semantics and sees only each artifact's 20 most recent | Outside OKF's scope | FR-09, AC-57, C-07; T84 |
| `content` | The markdown body as written, frontmatter included, stored verbatim. Returned by `read_artifact`, `synthesise_artifacts` and `arkeology://artifact/{id*}`. Where frontmatter and a field disagree, the field is the store's record. A foreign reader gets the `sources:` and `relationships:` frontmatter blocks redacted with the same marker. An own-scope reader gets the bytes as stored | §4 concept document | D49, FR-10, AC-78; T81, T83, T85 |
| `last_edited_ulid` | Opaque server token that changes only on create and update. Pass it as `if_match` to `update_artifact`, which then fails with `conflict` if the artifact has changed since. Pass it as `since_ulid` to `propose_commit_links`. It is not provenance and is not comparable with `revised.at` | None | D19, FR-75, AC-86; T78, T79 |
| `last_edited_at` | On search, synthesise and `propose_commit_links` results: when Arkeology stored the latest create or update, derived from `last_edited_ulid` (`null` if it cannot be parsed). This is storage time, so for an imported document it is the import time. Judge recency by `revised.at` or `generated.at` instead | None | D19; T79 |

**In-force view section** (FR-04, FR-67; D23–D25)

- In force means `status` is not `deprecated` and `archived` is `false`. An artifact in `draft`, or
  with no status, is in force.
- The in-force view is the default for `search_artifacts`, `list_artifacts`,
  `synthesise_artifacts` and `arkeology://artifacts`. `read_artifact` and
  `arkeology://artifact/{id*}` apply no view.
- `archived` takes `false` (the default), `true` or `"all"`.
- `status`, when omitted, applies the in-force lifecycle rule. `"all"` drops that rule, and `draft`,
  `stable` or `deprecated` match exactly.
- `exclude_drafts=true` drops drafts from the result, and is rejected together with
  `status="draft"`.
- Full lineage is `archived="all"` with `status="all"`.
- Whether an artifact is in force depends only on its own `status` and `archived`. A `supersedes`
  edge never excludes anything.

**The other schema resources** (FR-18)

- `tiers_schema_content` SHALL state that a supplied `id` replaces both generated formats. The key
  is then `<WRITE_PREFIX>/<id><extension>`, verbatim, with no hash and no date anchor (D28, D32;
  T87).
- `visibility_schema_content` SHALL state that the gate also applies inside link fields. For a
  foreign reader, entries in `sources` and `relationships`, and in the matching frontmatter blocks
  of returned content, that point at artifacts the reader cannot read are removed, and one
  `{withheld: n}` entry is added per list (D47–D49; T85).
- `query_strategy_content` SHALL tell agents to judge recency by `revised.at`, or `generated.at`
  when `revised` is `null`, rather than `last_edited_at`. Its line describing the artifact resource
  SHALL describe the field reference.
- `_SCHEMA_RESOURCES` SHALL describe `arkeology://schema/artifact` as the field reference: meaning,
  type, where each field appears, its OKF mapping, and the in-force view.
- None of the five resources SHALL name, as a code span, any name that AC-80 lists as removed:
  `references`, `source_artifacts`, `author_role`, `date`, `timestamp`, `link_metadata`,
  `write_artifact`, `write_artifacts`, `overwrite`, `active` or `inactive`.

### Decisions taken in this spec

**One heading per field, four labelled parts.** An agent can find a field by its name, and a test
can collect the set of headings without depending on any prose. A single table was rejected because
the meanings FR-18 asks for do not fit in table cells. One resource per field family was rejected
because the contract fixes five URIs and nothing needs more.

**What counts as a field.** A field is anything a create or update tool accepts, or anything
`read_artifact`, `list_artifacts`, `search_artifacts` or `synthesise_artifacts` returns for each
artifact, plus `last_edited_at`. Keys that describe one call rather than one artifact are excluded,
because the tool descriptions own them: `score`, `skipped_malformed_count`, `truncated`,
`included`, and the freshness report lists. `unchecked_sources` appears only to explain
`last_modified`. The in-force view is a query rule, not a field, so it gets a section.

**Removed names are not documented.** The AC-80 rejection already names the replacement, and the
**Breaking** CHANGELOG entry (T91) carries the mapping. A list of old names in the resource would
grow with every release and keep dead names in every agent's context.

**Recency moves from `last_edited_at` to `revised.at`.** `last_edited_at` is when the server stored
the artifact, so every imported document would look freshly edited. OKF §5.2 says consumers use
the content's change time "to tell a recent edit from a stale fact". In Arkeology that time is
`revised.at`, falling back to `generated.at`, which is the same order Studio uses (T79) and the
same effective time freshness uses (T86).

**Completeness is checked against live responses.** FR-18 says "always-current". In practice that
breaks when a later task adds a response key and leaves the resource alone, and a hand-kept test
list cannot notice. One test therefore compares real response keys against the headings.

## Boundaries

**Always:**
- Describe the target state.
- Spell every field, parameter and tool name exactly as the tools do.
- Read the type list live.
- Keep every resource pure and AWS-free.

**Ask First:**
- Adding, removing or renaming a schema resource URI.
- Changing the `` ### `name` `` heading form, which agents and tests depend on.
- Documenting any removed name.

**Never:**
- State behaviour that T76–T88 do not define. The resource describes; it decides nothing.
- Add per-scope, per-configuration or live data to a schema resource.
- Change any tool, response, contract-defined semantics or data resource.
- Edit README, SERVER-REFERENCE, AGENTS.md or the setup skill's agents snippet (T91).

AC-80 does not apply to this task: T89 removes no parameter, field or tool name.

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|---|---|---|
| `tests/unit/test_resources.py` | Modify | Replace the required/optional-field tests with the tests below. Keep T77's type tests |
| `src/arkeology/resources.py` | Modify | Rewrite `artifact_schema_content`. Add one paragraph each to `tiers_schema_content` and `visibility_schema_content`. Change the recency step and the artifact line in `query_strategy_content`. Change the artifact description in `_SCHEMA_RESOURCES` |

No other source file changes. `tests/unit/test_data_resources.py` is not affected.

## Contract Amendments

- `modules/arkeology.resources.md`, `### register_resources`, Invariants:
  - `arkeology://schema/artifact` holds exactly one `` ### `name` `` entry per artifact field, as
    defined under "What counts as a field" above.
  - Each entry carries `Meaning:`, `Type:`, `Appears in:` and `OKF:`.
  - Every key of a `read_artifact` response, of a `list_artifacts` entry and of a
    `search_artifacts` entry other than `score` has an entry.
  - No schema resource names an AC-80 removed name.
  - A change that adds, removes or renames an artifact field amends its entry in the same change.
  - Add this spec to the contract's `sources`.

No other contract changes.

## Testing Approach

TDD: test file first, confirmed failing, then `resources.py`. No acceptance criterion cites FR-18,
so every test below proves FR-18 and plan.md's T89 Done condition. Tests match field, parameter,
tool and enum names as backtick code spans, and every other token as a plain substring, so prose
can change freely. No
file in the mutation `only_mutate` scope is touched, so no mutation run is needed.

1. `tests/unit/test_resources.py` → `src/arkeology/resources.py`:
   - **Field set.** The `` ### `name` `` headings parsed from `artifact_schema_content()` equal the
     test-owned set of the 23 names in the Requirements table, exactly (Story 1).
   - **Four parts.** Each entry's section, which runs to the next heading, contains `Meaning:`,
     `Type:`, `Appears in:` and `OKF:`.
   - **Key tokens per entry.** A test-owned table maps each field to tokens its section must
     contain. The interpretive ones (Stories 2 and 4) are:

     | Field | Tokens |
     |---|---|
     | `status` | the three values, `set_artifact_status`, `§5.4` |
     | `archived` | `archive_artifact`, `"all"` |
     | `generated` | `§5.2`, `§5.1`, `revised` |
     | `verified` | `add_artifact_verification`, `§5.3`, `human:` |
     | `revision_history` | `include_revision_history` |
     | `sources` | `resource`, `last_modified`, `id`, `title`, `withheld`, `footnote`, `unchecked_sources`, `§5.1` |
     | `relationships` | `to`, `type`, `supersedes`, `withheld`, `#16` |
     | `tier` | `verified` |
     | `last_edited_ulid` | `if_match`, `since_ulid` |
     | `artifact_id` | `linked_from` |
     | `type` | every name in `RECOMMENDED_ARTIFACT_TYPES` |
     | `description` | `280` |
     | `commit_refs` | `20` |

   - **In-force view (Story 3).** The resource contains `exclude_drafts`, `"all"`, `deprecated` and
     `supersedes`.
   - **Conventions.** The resource contains `§7`, `human:` and `process:`.
   - **Removed names (Story 5).** For each of the five content functions, no code span starts with
     an AC-80 name followed by a non-identifier character.
   - **Other resources.** The tiers content mentions the supplied-id key (`{id}`). The visibility
     content mentions `withheld`. The query-strategy content mentions `revised.at`.
   - **Drift against live responses (Story 1).** Using the conftest moto fixtures and
     `FakeBedrockClient`, as `tests/unit/test_data_resources.py` does:
     - create one artifact;
     - every key of the `read_artifact` response is a heading;
     - every key of its `list_artifacts(include_revision_history=True)` entry is a heading;
     - every key of its `search_artifacts` entry other than `score` is a heading.
   - The registration test (five URIs) and T77's types tests stay unchanged.

**Integration tests:** none read a schema resource, so none break.

**Review (Done condition):** before marking the task done, check the rendered resource field by
field against ADR-017 `## Decision` and the cited specs, and record the result in the PR.

## Open Questions

1. **Resolved 2026-10-13 — keep the import clause.** The operator accepted importing `revised` and FR-69 was reworded to match. *Original question:* the import clause of `revised`. The `revised` entry says a document imported
   by `migrate_artifacts` may arrive with its `revised`, following T88's Decision 1. T88's Open
   Question 2, on how literally to read FR-69, is still open. If it is decided the literal way,
   delete that one clause; nothing else in the entry changes.
