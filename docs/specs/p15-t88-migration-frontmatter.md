---
type: Spec
id: p15-t88-migration-frontmatter
title: T88 — Migration Skill for OKF v0.2 Frontmatter
description: The migrating-to-arkeology skill imports documents written by an OKF producer, such as a spec-driven development framework, with their own id, generated, revised, status, type, sources and relationships. Before any write it stops on duplicate or invalid ids. It resolves sources[].resource paths through the target file's own id, and the server rewrites them in content. Verifications are recorded after the write. A source that does not resolve is left unchanged and reported once, to be added later by hand with add_artifact_links. references.py and the skill's drift test follow. Studio's link click and the arkeology://artifact/{id*} resource open bare-id links through T84's resolver.
tags: []
status: draft
okf_version: "0.2"
sources:
  - id: adr
    resource: docs/architecture-decisions/adr-2026-09-25-okf-v02-adoption.md
    title: OKF v0.2 Adoption
    last_modified: 2026-09-29T00:00:00Z
  - id: brainstorming
    resource: docs/brainstorming/brainstorming-2026-09-17-okf-v02-adoption.md
    title: OKF v0.2 Adoption for Arkeology
    last_modified: 2026-09-24T00:00:00Z
  - id: requirements
    resource: docs/planning-artifacts/requirements.md
    title: "Arkeology — Requirements"
    last_modified: 2026-09-24T00:00:00Z
  - id: plan
    resource: docs/planning-artifacts/plan.md
    title: Plan Arkeology
    last_modified: 2026-10-07T13:29:34Z
  - id: adr-xref
    resource: docs/architecture-decisions/adr-2026-07-03-artifact-cross-referencing.md
    title: Artifact Cross-Referencing — First-Class references Field, Migration Rewrite, referenced_by Warning
    last_modified: 2026-09-29T00:00:00Z
  - id: adr-studio
    resource: docs/architecture-decisions/adr-2026-08-12-studio-link-resolution.md
    title: Studio-Side Resolution of arkeology:// Links on the Human Read Surface
    last_modified: 2026-09-25T00:00:00Z
  - id: spec-t77
    resource: docs/specs/p15-t77-open-type-list.md
    title: T77 — Open Type List
    last_modified: 2026-10-13T13:04:34Z
  - id: spec-t78
    resource: docs/specs/p15-t78-create-update-split.md
    title: T78 — Split Writing into create_artifact / update_artifact; Drop overwrite
    last_modified: 2026-10-13T13:02:46Z
  - id: spec-t79
    resource: docs/specs/p15-t79-provenance.md
    title: "T79 — Provenance: generated / revised; Drop date, author_role, timestamp"
    last_modified: 2026-10-13T16:20:20Z
  - id: spec-t80
    resource: docs/specs/p15-t80-revision-history.md
    title: "T80 — Revision-History Annotation + Shared Compare-and-Swap Append Helper"
    last_modified: 2026-10-13T16:40:30Z
  - id: spec-t81
    resource: docs/specs/p15-t81-lifecycle-status-in-force.md
    title: T81 — OKF Lifecycle status and In-Force Default View
    last_modified: 2026-10-13T16:19:13Z
  - id: spec-t83
    resource: docs/specs/p15-t83-verified.md
    title: "T83 — verified Annotation, add_artifact_verification, and the \"Unverified Since Revised\" Flag"
    last_modified: 2026-10-13T17:50:06Z
  - id: spec-t84
    resource: docs/specs/p15-t84-sources-relationships.md
    title: "T84 — sources + relationships in One Structured Annotation; link_metadata → add_artifact_links"
    last_modified: 2026-10-13T17:23:06Z
  - id: spec-t87
    resource: docs/specs/p15-t87-supplied-ids.md
    title: T87 — Producer-Supplied id Becomes Artifact Id
    last_modified: 2026-10-13T16:38:44Z
  - id: contract-migrate
    resource: docs/contracts/modules/arkeology.tools.migrate_artifacts.md
    title: arkeology.tools.migrate_artifacts
    last_modified: 2026-09-15T00:00:00Z
  - id: contract-write
    resource: docs/contracts/modules/arkeology.tools.write.md
    title: arkeology.tools.write
    last_modified: 2026-09-06T00:00:00Z
  - id: contract-write-artifacts
    resource: docs/contracts/modules/arkeology.tools.write_artifacts.md
    title: arkeology.tools.write_artifacts
    last_modified: 2026-09-04T00:00:00Z
  - id: contract-s3
    resource: docs/contracts/data/s3.artifact.md
    title: s3.artifact
    last_modified: 2026-09-07T00:00:00Z
  - id: contract-annotations
    resource: docs/contracts/data/s3-annotations.artifact.md
    title: s3-annotations.artifact
    last_modified: 2026-09-14T00:00:00Z
  - id: contract-read
    resource: docs/contracts/modules/arkeology.tools.read.md
    title: arkeology.tools.read
    last_modified: 2026-09-14T00:00:00Z
  - id: contract-resources
    resource: docs/contracts/modules/arkeology.resources.md
    title: arkeology.resources
    last_modified: 2026-09-04T00:00:00Z
  - id: okf-spec
    resource: https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/main/SPEC.md
    title: Open Knowledge Format — Specification
  - id: spec-t51
    resource: docs/specs/p12-t51-migration-reference-rewrite.md
    title: T51 — Migration Frontmatter Reference Rewriting + arkeology:// Content Rewrite
  - id: spec-t30
    resource: docs/specs/p9-t30-write-artifacts.md
    title: Write Performance Z1 — write_artifacts + migrate_artifacts + P4 Section Truncation
  - id: review-2026-11-15
    resource: .docs/reviews/architecture-review-2026-11-15-arkeology-phases-9-10-12.md
    title: "Architecture review — Arkeology, plan phases 9, 10 and 12"
relationships:
  - to: adr-2026-09-25-okf-v02-adoption
    type: implements
  - to: p15-t87-supplied-ids
    type: builds_on
  - to: p15-t84-sources-relationships
    type: builds_on
  - to: p15-t79-provenance
    type: builds_on
  - to: p15-t83-verified
    type: builds_on
generated:
  by: "axians-architect/claude-opus-5.5"
  at: 2026-10-13T18:53:42Z
revised:
  by: "axians-architect/claude-sonnet-5-5"
  at: 2026-11-16T10:12:15Z
---

# T88 — Migration Skill for OKF v0.2 Frontmatter

## TL;DR

`migrating-to-arkeology` imports a document written by an OKF producer — a spec-driven development
framework, for example — with the identity, provenance, lifecycle, type and links its own
frontmatter declares. Before any write, it stops on a duplicate or invalid `id`. It resolves each
`sources[].resource` path through the `id:` the target file declares, and `migrate_artifacts`
rewrites the path in the stored content. A source that does not resolve at import is left unchanged
and reported once; the operator adds it later by hand with `add_artifact_links`. Studio and the
`arkeology://artifact/{id*}` resource open the bare-id links this writes, through T84's resolver
(FR-23, FR-48, FR-52; brainstorming-2026-09-17-okf-v02-adoption D28, D40, D43).

## 1. Problem Statement

Today the migration skill reads a house `references:` list, derives every id from type, title and
date, and recovers a `date`. After T76–T87 the server accepts `id`, `generated`, `status`,
`sources` and `relationships`, and producer documents carry exactly those keys. They no longer
carry `references:`. Run against a producer corpus, the skill therefore throws away each frozen
`id`, records the wrong first-authorship time and resolves no links. T79 and T83 also left
two import questions to this task: what happens to a document's `revised`, and to its `verified`
list. Migration is also the first writer of bare-id links into content. Neither Studio nor the
`arkeology://artifact/{id*}` resource can open them, because both expect a full key.

The six user stories of this spec are kept as labelled examples under the rules they illustrate
(Stories 1 to 4, 6 and 7); all six are P1. The nine decisions taken in this spec keep their
numbers (Decisions 1 to 7, 9 and 10) as labelled **Why** lines on the rules they settle, and the two
answered questions keep theirs (Open Questions item 2, Resolved Questions item 1).

## 2. Rules — Reading frontmatter

### R1 — The migration skill reads frontmatter only through one documented offline snippet, as literal text

The migration skill reads a file's frontmatter only through one documented offline snippet. Its
authoritative, unit-tested implementation is in `references.py`.

- Frontmatter is the block from an opening `---` first line to the next `---` line. This is the
  rule `_frontmatter_end_index` already applies. A file without such a block declares nothing.
- The block is parsed with no implicit typing. Every scalar is the literal text in the file with
  its quotes removed: `id: 001` stays `"001"`, and a timestamp keeps its spelling.
- When the block does not parse as YAML or is not a mapping, the file is reported as unreadable.

**Why (Decision 6 — One snippet, literal text, PyYAML):** `sources` and `relationships` are lists
of mappings, which the stdlib-only fallback cannot parse without becoming a YAML parser. The skill
already runs `uv run` with PyYAML for manifest validation, so the snippet runs under
`uv run --with pyyaml`. Parsing with no implicit typing keeps ids such as `001` and `1.0` exact, and
keeps timestamps as written.

Source: FR-23; brainstorming-2026-09-17-okf-v02-adoption D10, D28

### R2 — The migration skill reads only OKF v0.2 keys

The migration skill reads only OKF v0.2 keys. It never reads the house `references:`, `timestamp:` or
`authored:` keys.

**Why (Decision 7 — House keys are not read):** brainstorming-2026-09-17-okf-v02-adoption D42 ships
no aliases, and brainstorming-2026-09-17-okf-v02-adoption D10 makes converting the documents the
producer's job. First authorship falls back to Git history, which FR-23 permits.

Source: FR-23; brainstorming-2026-09-17-okf-v02-adoption D10, D28

## 3. Rules — Pre-write checks

### R3 — A duplicate or T87-invalid declared id, a missing file or unreadable frontmatter stops the run before the first `migrate_artifacts` call

When a run is about to make its first `migrate_artifacts` call, the skill first reads every file in
the migration: in Step 3.A every confirmed file, in Step 3.B every manifest entry whatever its
`status`. It stops, writes nothing, and names every file involved, when:

- two or more files declare the same `id`, compared exactly (AC-81);
- a declared `id` fails T87's rule, which is reported with T87's message;
- a file is missing, or its frontmatter is unreadable.

Example (Story 3, duplicate or invalid ids stop the run):

- Given two files that both declare `id: plan`, when the skill runs, then it stops before any
  `migrate_artifacts` call and names both files (AC-81). The same happens for a declared id that
  T87 rejects, or a frontmatter block that does not parse.

**Why (Decision 4 — What stops a run):** A duplicate is AC-81. An invalid declared id is checked
here rather than per entry: every file whose `sources` or `relationships` names that id would also
fail T84's id check, so one bad file would fail many. An unreadable block would silently drop the
file's declared `id`.

Source: FR-23, FR-73, AC-81; brainstorming-2026-09-17-okf-v02-adoption D28, D33; ADR-017 `### 5`, "Case-only duplicate ids"

### R4 — Ids that differ only in letter case continue only on the operator's explicit confirmation

When two or more declared ids differ only in letter case, the skill lists them and continues only on
the operator's explicit confirmation.

Example (Story 3, continued):

- Given `Spec-A` and `spec-a` declared by two files, then the skill lists them and continues only on
  the operator's explicit confirmation.

**Why (Decision 4, continued):** Case-only ids are legal (FR-08), but ADR-017 names this check as
the guard against them. That is why they need confirmation rather than causing a stop.

Source: FR-23, FR-73, AC-81; brainstorming-2026-09-17-okf-v02-adoption D28, D33; ADR-017 `### 5`, "Case-only duplicate ids"

## 4. Rules — Descriptor fields

### R5 — Each descriptor key comes from the frontmatter as this table states

| Descriptor key | Source |
|---|---|
| `id` | Frontmatter `id`, verbatim. Omitted when not declared, so the server generates one (T87) |
| `type` | Frontmatter `type`, verbatim, proposed in the classification table. The filename and path rules apply only to files without one. The tier comes from the table row that names the type, otherwise from Pass 3 judgment. The operator may correct any row |
| `generated` | `by`: frontmatter `generated.by`, otherwise `process:migrating-to-arkeology`. `at`: the entry's `generated_at` |
| `revised` | Frontmatter `revised`, verbatim (see "Imported `revised`") |
| `status` | Frontmatter `status`, verbatim. Any value except the three OKF values fails that entry on the server with T81's message. The skill reports it and never maps or drops it |
| `relationships` | Frontmatter list, verbatim |
| `sources` | Frontmatter list after resolution (below) |

Example (Story 1, a producer document keeps its identity and provenance):

- Given `docs/adr/okf.md` declaring `id: ADR-005.okf-adoption`, `type: ADR`, `status: stable`,
  `generated: {by: "axians-architect/x", at: 2026-03-01T10:00:00Z}` and
  `revised: {by: "human:ana", at: 2026-04-02T08:00:00Z}`. When it is migrated, then it is stored at
  `{WRITE_PREFIX}/ADR-005.okf-adoption.md`. `read_artifact` returns that type, status, `generated`
  and `revised`, and `revision_history` is those two entries in that order (FR-73;
  brainstorming-2026-09-17-okf-v02-adoption D28, D35, D37).

Source: FR-23, FR-26, FR-73; brainstorming-2026-09-17-okf-v02-adoption D9, D22, D28, D35, D37

### R6 — `generated_at` is the first available of the declared time, a filename date, the first commit or today, unless the operator edits it

`generated_at` (manifest field in Step 3.B, held in memory in Step 3.A) is taken from the first
available of:

1. the frontmatter `generated.at`, verbatim;
2. a `YYYY-MM-DD` in the filename;
3. the file's first commit, for **both** tiers;
4. today.

Every value except the first is written as `<day>T00:00:00Z`. An operator edit to `generated_at`
takes precedence.

Example (Story 1, continued):

- Given a file with no frontmatter and no date in its name, when it is migrated, then its id is
  generated (T87). Its `generated.at` is the file's first-commit day at `T00:00:00Z` and
  `generated.by` is `process:migrating-to-arkeology` (FR-23;
  brainstorming-2026-09-17-okf-v02-adoption D9).

**Why (Decision 7, continued):** The first commit replaces the tier-3 last-commit rule, because
`generated` means first authorship (brainstorming-2026-09-17-okf-v02-adoption D9). Tier-3 ids are
date-independent, so no id changes.

Source: FR-23, FR-26, FR-73; brainstorming-2026-09-17-okf-v02-adoption D9, D22, D28, D35, D37

### R7 — The skill never puts `verified` in a descriptor

The skill never puts `verified` in a descriptor, because T83 redirects it.

Source: FR-23, FR-26, FR-73; brainstorming-2026-09-17-okf-v02-adoption D9, D22, D28, D35, D37

## 5. Rules — Imported `revised`

### R8 — A `migrate_artifacts` descriptor's `revised` is validated, written at create and seeds the history

When a `migrate_artifacts` descriptor carries `revised`, the system requires both `by` and `at` and
validates them with T79's provenance-block resolver, with no clock fallback. It then writes
`revised` at create alongside `generated` and seeds `revision_history` with `[generated, revised]`.
An invalid block fails only that entry, with `validation_error` naming the field.

**Why (Decision 1 — Import carries `revised`, T79 hand-off):** The alternative is to import
`generated` only. A source's effective time would then be its first authorship, earlier than every
baseline a producer-written citation captured. Every imported citation would read as fresh, so all
staleness that existed in Git before import would be lost. Studio would order every imported living
document by its creation date, and T83's flag could never be raised until a first update. Importing
`revised` keeps every baseline comparing exactly as it did in Git. FR-69's "absent until the first
update" is read as governing Arkeology-originated writes. T80 recommends that T90 writes a
carried-over `revised` in the same way. The exception is limited to `migrate_artifacts`, and agent
creates still cannot set `revised` (Open Questions, item 2).

**Open Questions item 2 — Resolved 2026-10-13 — FR-69 reworded.** The operator accepted importing
`revised`; FR-69 now reads "absent until the first update, unless the artifact is imported with the
document's existing latest revision". *Original question:* FR-69 wording. Decision 1 imports
`revised` at create. FR-69 says `revised` is "absent until the first update". *Recommended:* clarify
the row through `writing-requirements`, for example "absent until the first update, unless imported
with the document's existing revision". If the operator prefers the literal reading instead, drop
"Imported `revised`" and its tests. Imported citations then lose all pre-import staleness, as
Decision 1 describes.

Source: FR-20, FR-69, FR-72; brainstorming-2026-09-17-okf-v02-adoption D19, D35

### R9 — `revised` on `create_artifact` or a `create_artifacts` descriptor is rejected, naming `update_artifact`

When `create_artifact`, or a `create_artifacts` descriptor, carries `revised`, the system returns
`validation_error` naming `update_artifact`, for the call or for that entry. `revised` reaches a
create only through `migrate_artifacts`.

Source: FR-20, FR-69, FR-72; brainstorming-2026-09-17-okf-v02-adoption D19, D35

### R10 — A `skipped_existing` artifact's stored `revised` is never touched

A `skipped_existing` artifact is never re-imported, so its stored `revised` is never touched.

Source: FR-20, FR-69, FR-72; brainstorming-2026-09-17-okf-v02-adoption D19, D35

## 6. Rules — Source resolution

### R11 — A URL or `arkeology://` `resource` is left unchanged

For each frontmatter `sources` entry, the skill leaves an `http(s)://` or `arkeology://`
`resource` unchanged.

Source: FR-52, AC-58; brainstorming-2026-09-17-okf-v02-adoption D40, D43

### R12 — A path that names a manifest entry declaring an `id` resolves to `arkeology://artifact/<id>`

For any other `resource`, the skill joins `./` and `../` paths against the citing file's directory
and applies today's bounded normalisation. When the result is the path of a manifest entry whose
file declares an `id`, the skill:

- sets `resource` to `arkeology://artifact/<id>`;
- adds `{original resource text: id}` to the descriptor's `resolved_sources_map`.

Example (Story 2, sources resolve through the target's own `id:`):

- Given A listed before B in the migration. A's `sources` has a label-`b` entry with
  `resource: docs/specs/new-name.md` and no `last_modified`, a URL entry, and an entry pointing at
  an excluded path. B lives at `docs/specs/new-name.md` but declares `id: old-name`. When the
  migration runs:
  - A's first source becomes `arkeology://artifact/old-name` in both the structured field and the
    stored frontmatter, with label `b` and its title unchanged and `last_modified` set to B's
    `revised.at`;
  - the URL and excluded-path entries are byte-identical;
  - A's `relationships` equal its frontmatter list (AC-58).

Source: FR-52, AC-58; brainstorming-2026-09-17-okf-v02-adoption D40, D43

### R13 — A target that is not a manifest entry, or declares no `id`, leaves the entry unchanged and reported once

When the result names no manifest entry (an excluded, never-migrated or missing target) or a target
that declares no `id`, the skill leaves the entry unchanged and lists it once in the migration
report with that reason. A source left unresolved is added later by hand with
`add_artifact_links`.

**Why (Decision 3 — A target without `id:` does not resolve):** FR-52 resolves a source by the id
the target declares. Under brainstorming-2026-09-17-okf-v02-adoption D10 the producer's OKF
migration gives every document an `id:` before import. Falling back to a generated id would bring
back the title-derived map that ADR-017 rejects as "wrong across file renames".

Source: FR-52, AC-58; brainstorming-2026-09-17-okf-v02-adoption D40, D43; p12-t51-migration-reference-rewrite R6

### R14 — Resolution never reads an excluded path or uses `sources[].id`, and keeps every other key and the entry order

The skill never reads an excluded path and never uses `sources[].id` to resolve. It keeps every
other key and the order of entries.

Source: FR-52, AC-58; brainstorming-2026-09-17-okf-v02-adoption D40, D43

### R15 — A resolved entry with no `last_modified` gets the target descriptor's effective time

When a resolved entry has no `last_modified`, the skill sets it to the effective time on the
target's own descriptor: `revised.at`, otherwise `generated.at`.

**Why (Decision 5 — The skill fills `last_modified`):** In one batch, writes run concurrently.
T84's server-side fill would therefore depend on whether the target already existed, and FR-52
requires the result not to depend on order. The target's own descriptor holds the value it is
imported with, which is brainstorming-2026-09-17-okf-v02-adoption D40's "current revision time".

Source: FR-52, AC-58; brainstorming-2026-09-17-okf-v02-adoption D40, D43

### R16 — Resolution depends only on the manifest and the declared ids

Resolution depends only on the manifest and the ids the files declare, so write order and session
never change its result.

Source: FR-52, AC-58; brainstorming-2026-09-17-okf-v02-adoption D40, D43

## 7. Rules — Content rewrite in `migrate_artifacts`

### R17 — `migrate_artifacts` accepts the transient key `resolved_sources_map` in place of `resolved_references_map`

The system accepts a transient descriptor key `resolved_sources_map` in place of
`resolved_references_map`. It applies the map in both `dry_run` modes, before the existence check
and the delegation, and then pops it. The key is never stored or returned.

**Why (Decision 9 — The map key is renamed):** It now drives `sources:`, and keeping the name
`references` would misdescribe it. A stale caller also sends `references`, which T84 already
rejects.

Source: FR-52, AC-58

### R18 — Inside the block-style `sources:` list, only matching `resource:` values are rewritten; every other frontmatter byte stays

Inside the frontmatter's block-style `sources:` list, the system rewrites every `resource:` value
whose text, quotes removed, equals a map key to `arkeology://artifact/<id>`, keeping its quoting.
This applies whether the key sits on the entry's `- ` line or on a later line.

Every other frontmatter byte stays unchanged. That includes label `id:`, `title:` and
`last_modified:` lines, the `relationships:` block and a top-level `resource:` key.

Source: FR-52, AC-58

### R19 — Body links are rewritten as today; a flow-style `sources: [...]` list is not rewritten in content

Body markdown links are rewritten exactly as today. A flow-style `sources: [...]` list is not
rewritten in content. This existing limitation is kept, and the structured field is still
resolved.

Source: FR-52, AC-58

## 8. Rules — Imported verifications

### R20 — After each write step and on every resumed run, each declared verification not yet recorded is added once

After each write step, and on every resumed run, the skill processes each migration entry that has
an `artifact_id` and whose file declares `verified`, as follows:

- call `read_artifact` once;
- for each frontmatter entry, in file order, that is not already recorded, call
  `add_artifact_verification` once. An entry is already recorded when one with the same `by` and
  the same instant exists.

Example (Story 4, verifications arrive after the write):

- Given a file declaring two `verified` entries, when it is migrated, then `read_artifact` returns
  both. Re-running the migration records nothing further (FR-70; T83).

**Why (Decision 2 — Verifications through a post-write pass, T83 hand-off):** As T83 recommends,
every entry goes through `add_artifact_verification`. The tool appends rather than merges, so the
skill makes the pass idempotent by checking first against `read_artifact`. No extra manifest state
is needed, and a run that fails partway is resumed by running the pass again.

Source: FR-70; brainstorming-2026-09-17-okf-v02-adoption D41, D44, D46

### R21 — A `validation_error` is reported and the pass continues; any other error stops the pass with a per-file report

When the tool returns `validation_error`, the skill reports the file and the entry and continues.
On any other error it stops the pass and reports, per file, which entries were and were not
recorded. A re-run records only the missing ones.

Source: FR-70; brainstorming-2026-09-17-okf-v02-adoption D41, D44, D46

### R22 — Each manifest entry gains the `artifact_id` from its result, whether written or skipped

Each manifest entry gains the `artifact_id` from its result, whether written or skipped.

Source: FR-70; brainstorming-2026-09-17-okf-v02-adoption D41, D44, D46

## 9. Rules — Removed name

### R27 — A `migrate_artifacts` descriptor carrying `resolved_references_map` fails that entry, naming `resolved_sources_map`

When a `migrate_artifacts` descriptor carries `resolved_references_map`, the system fails that
entry with `validation_error` naming `resolved_sources_map`.

Example (Story 6, the renamed descriptor key is rejected):

- Given a `migrate_artifacts` descriptor carrying `resolved_references_map`, then that entry fails
  with `validation_error` naming `resolved_sources_map` (AC-80;
  brainstorming-2026-09-17-okf-v02-adoption D42).

Source: AC-80; brainstorming-2026-09-17-okf-v02-adoption D42

## 10. Rules — Following bare-id links

**Resolved Questions item 1 — Bare-id links on read surfaces.** *Original question:* T88 is the
first writer of `arkeology://artifact/<bare id>` into stored content (AC-58). The
`arkeology://artifact/{id*}` resource and Studio expected a full key, so those links would not open.
T84 left this open, and T85 declined it. *Resolution (2026-10-13, Phase 15
coordinator):* plan.md's T88 entry now routes Studio's link click and the resource through T84's
resolver (FR-48). This is specified under "Following bare-id links", Story 7 and Decision 10.

### R28 — `read_artifact`'s optional `linked_from` resolves a bare id through T84's resolver before the gate, and returns the resolved key

`read_artifact` accepts an optional `linked_from`, the full key of the artifact whose content holds
the link. When it is supplied, the system does three things in order:

1. resolve `artifact_id` through T84's resolver, with `linked_from` as the carrier;
2. run the existing scope check and cross-scope gate on the resolved key;
3. return the resolved key as `artifact_id`.

A full-key `artifact_id` resolves to itself.

**Why (Decision 10 — Studio sends the carrier, and the resource uses the reader's own scope):**
Studio knows the carrier, because it is the artifact open in the view. Sending it and letting the
server resolve keeps two rules intact: the Studio link-resolution ADR's
brainstorming-2026-09-17-okf-v02-adoption D1 (Studio derives nothing) and T84's single resolver. A
parameter on `read_artifact` is the smallest server path: no new tool, and the gate already sits
there. It is named `linked_from` because it states where the link was found.

Source: FR-10, FR-46, FR-48, AC-51; brainstorming-2026-09-17-okf-v02-adoption D28; adr-2026-08-12-studio-link-resolution D1 and D4

### R29 — A `linked_from` with no `/` returns `validation_error` before any storage call

When `linked_from` contains no `/`, the system returns `validation_error` naming `linked_from`,
before any storage call.

Source: FR-10, FR-46, FR-48, AC-51; brainstorming-2026-09-17-okf-v02-adoption D28; adr-2026-08-12-studio-link-resolution D1 and D4

### R30 — Without `linked_from`, behaviour is unchanged: a bare `artifact_id` returns `access_denied`

When `linked_from` is omitted, behaviour is unchanged: a bare `artifact_id` lies in no accessible
scope and returns `access_denied`.

Source: FR-10, FR-46, FR-48, AC-51; brainstorming-2026-09-17-okf-v02-adoption D28; adr-2026-08-12-studio-link-resolution D1 and D4

### R31 — `linked_from` grants no access

`linked_from` grants no access. A caller could pass the resolved key directly, and either way the
gate decides on that key.

Source: FR-10, FR-46, FR-48, AC-51; brainstorming-2026-09-17-okf-v02-adoption D28; adr-2026-08-12-studio-link-resolution D1 and D4

### R32 — Studio sends the decoded id unchanged with the open artifact's key as `linked_from`, adopts the returned key, and decides nothing itself

When Studio activates an `arkeology://artifact/` link in a detail view, the system calls
`read_artifact` with the decoded id unchanged and with `linked_from` set to the key of the artifact
open in that view. A list-row click sends no `linked_from`.

Once the response arrives, the view uses the returned `artifact_id` for its scope pill, its list
highlight and its next followed link.

Studio derives nothing from the id and checks nothing before the call, and shows a server error
verbatim (ADR brainstorming-2026-09-17-okf-v02-adoption D1, D4). Link classification and
sanitisation are unchanged.

Examples (Story 7, bare-id links open where readers follow them):

- Given a migrated A whose content links to `arkeology://artifact/old-name` (B's declared id). When
  a reader activates that link in Studio's view of A, then B opens, resolved against A's scope. A
  link inside B then resolves against B (FR-48; brainstorming-2026-09-17-okf-v02-adoption D28).
- Given a foreign shared artifact `P/a.md` whose content links to bare `t2`, a tier-2 artifact in P.
  When a reader follows that link in Studio, then the view shows `read_artifact`'s `access_denied`
  message verbatim. Nothing is decided in Studio itself (FR-10;
  adr-2026-08-12-studio-link-resolution D4).

Source: FR-10, FR-46, FR-48, AC-51; brainstorming-2026-09-17-okf-v02-adoption D28; adr-2026-08-12-studio-link-resolution D1 and D4

### R33 — The `arkeology://artifact/{id*}` resource resolves a bare id against the server's own scope

When `arkeology://artifact/{id*}` is read with an `id` that contains no `/`, the system resolves it
through the same resolver with the server's own scope as the carrier, giving
`{WRITE_PREFIX}/{id}.md`. It then reads the resolved key through `read_artifact`, as today. A full
key is unchanged, and the template stays `{id*}`.

Example (Story 7, continued):

- Given a host reads `arkeology://artifact/old-name`, then B's content is returned (AC-51).

**Why (Decision 10, continued):** A resource URI carries only the id, so the resource cannot know
which artifact held the link. It resolves against the reader's own scope, which is where migration
writes every bare id (AC-58), so every migrated link opens. A bare link inside a foreign artifact
therefore resolves into the reader's own scope. At worst that gives a wrong target or `not_found`,
never extra access, because the gate runs on the resolved key. T84 warns against resolving against
the reader's prefix, but that concerns list redaction, where a foreign entry would pass
unredacted. A resource read returns only what the reader may already read.

Source: FR-10, FR-46, FR-48, AC-51; brainstorming-2026-09-17-okf-v02-adoption D28; adr-2026-08-12-studio-link-resolution D1 and D4

## 11. Rules — Skill surface

### R34 — The migration skill uses only Phase 15 names

The migration skill uses only Phase 15 names: `add_artifact_links` (in its commit-refs Step 5),
`create_artifact`, and no `status="active"` or `references`.

Source: brainstorming-2026-09-17-okf-v02-adoption D42, D46, D51

### R35 — The migration skill does not compute generated ids

The migration skill does not compute generated ids. Its offline id snippet and its
"Determining `write_prefix`" step are deleted.

Source: brainstorming-2026-09-17-okf-v02-adoption D42, D46, D51

## 12. Boundaries

**Always:**
- Run the pre-write checks over the whole migration before the first `migrate_artifacts` call.
- Pass declared values verbatim, and let the server reject what it rejects. Never repair a value.
- Leave content rewriting to `migrate_artifacts`. The agent never edits content.
- Resolve a bare id only on the server, and only through T84's resolver.
- Keep the `public` / `_inner` pattern with `try/except Exception`, and log to stderr only.

**Ask First:**
- Resolving a target without `id:` by its generated id.
- Accepting `revised` on `create_artifact` or `create_artifacts`.
- Rewriting flow-style `sources:` in content.
- Resolving bare ids in `read_artifact` without `linked_from`, or in any other tool.

**Never:**
- In Studio, derive a key from a link, or check scope, tier or existence (Studio link-resolution
  ADR, brainstorming-2026-09-17-okf-v02-adoption D1 and D4).
- Read an excluded path, or use `sources[].id` to resolve or rewrite anything.
- Resolve, normalise or rewrite `relationships`.
- Map a lifecycle `status`, or read `references:`, `timestamp:` or `authored:`.
- Change `_scope.py`, `annotations.py` or `_reference_filter.py`. Migrate stored artifacts (T90).
  Rewrite the schema resource (T89). Edit README, SERVER-REFERENCE, CHANGELOG, AGENTS.md or the
  setting-up skill's snippet (T91).

## 13. For the developer agent

### Files to Touch

T88 lands after T84 and T87 and edits the code that T76–T87 leave.

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_references_resolution.py` | Rewrite | Frontmatter reader, pre-write checks, path→declared-id map, source resolution with fill |
| `src/arkeology/references.py` | Modify | Delete `extract_references_list`, its manual fallback and regexes, and `ManifestEntry`. Delete the `generate_artifact_id` use in `build_path_to_id_map`, which now maps each normalised path to its declared id (duplicate paths still raise `DuplicateManifestPathError`). Add the reader (`yaml.BaseLoader`), the pre-write check (calls T87's validator in `artifact.py`) and a sources resolver. Rename `rewrite_content_references` to `rewrite_content_sources`, retargeted to `resource:` lines in `sources:`. Update the module docstring |
| `tests/unit/test_references_content_rewrite.py` | Modify | Retarget to `sources:` |
| `tests/unit/test_skill_artifact_id_drift.py` | Modify | Keep the file name, because `pyproject.toml`'s `also_copy` comment names it |
| `plugins/arkeology/skills/migrating-to-arkeology/SKILL.md` | Modify | Frontmatter snippet; pre-write check step; descriptor table; source resolution, reporting each unresolved source once (R13); Step 3.C verification pass; `generated_at` chain; delete the id snippet, `write_prefix` step and `references:` sections; Step 5 → `add_artifact_links` |
| `plugins/arkeology/skills/migrating-to-arkeology/schema.yaml` | Modify | `date` → `generated_at`; add `artifact_id`; tier-3 comment no longer says "overwrites in place" (T78) |
| `tests/unit/test_tools_migrate_artifacts.py` | Modify | Replace the T56 `resolved_references_map` tests |
| `src/arkeology/tools/migrate_artifacts.py` | Modify | `resolved_sources_map` step; old-key rejection; validate and forward `revised` |
| `tests/unit/test_tools_write_artifacts.py`, `test_tools_write.py` | Modify | `revised` redirect; import create |
| `src/arkeology/tools/write_artifacts.py` | Modify | Descriptor `revised` fails the entry unless the call comes from `migrate_artifacts`. *Uncertain:* the internal channel (a keyword on the inner function is suggested) |
| `src/arkeology/tools/write.py` | Modify | The create inner function takes an optional import `revised`, writes it, and seeds history `[generated, revised]` |
| `tests/unit/test_tools_read.py` | Modify | `linked_from` cases |
| `src/arkeology/tools/read.py` | Modify | Optional `linked_from`: resolve through T84's resolver before the scope check, and return the resolved key |
| `tests/unit/test_data_resources.py` | Modify | Bare-id resource read |
| `src/arkeology/resources.py` | Modify | `_artifact_resource` resolves a bare id with the own scope as carrier. Docstrings no longer say `id` is always the full key |
| `tests/static/studio-link-follow.test.js` | Create | Slices the shipped functions with `extractBlock`, as `studio-link-sanitisation.test.js` does. Runs under `npm test` |
| `src/arkeology/static/arkeology-studio.html` | Modify | `activateArtifactLink` passes the open artifact's key. `selectArtifact` takes an optional carrier, sends it as `linked_from`, and adopts the returned `artifact_id`; its stale-response guard compares against the requested id. The `artifactTarget` comment no longer says "full S3 key" |
| `tests/unit/test_server.py`, `src/arkeology/server.py` | Modify | `create_artifact` redirect row for `revised` (T78's table). `read_artifact` gains `linked_from: str \| None = None` and forwards it. The `migrate_artifacts` docstring names the new descriptor keys |

### Contracts

Make these on top of the T78–T87 amendments, and before writing the tests:

- **`modules/arkeology.tools.migrate_artifacts.md`**:
  - Add descriptor `resolved_sources_map`, which is missing from the contract today: its rewrite
    rule, both `dry_run` modes, popped before delegation.
  - Add descriptor `revised` (import only, `by` and `at` required, seeds `[generated, revised]`).
  - `resolved_references_map` fails its entry.
  - "No pre-existing artifact … modified" stays unchanged.
- **`modules/arkeology.tools.write.md`**, `### create_artifact`: `revised` is rejected, naming
  `update_artifact`.
- **`modules/arkeology.tools.write_artifacts.md`**, `### create_artifacts`: descriptor `revised` fails
  its entry, except on the internal path `migrate_artifacts` uses.
- **`data/s3.artifact.md`**, `## Compatibility Guarantees`: `revised` is absent at create except on a
  migration import, and afterwards moves only on an update.
- **`data/s3-annotations.artifact.md`**: create seeds `revision_history` with `[generated]`, or with
  `[generated, revised]` for an import that carries `revised`.
- **`modules/arkeology.tools.read.md`**, `### read_artifact`:
  - optional `linked_from`, resolved through T84's resolver before the scope check;
  - the returned `artifact_id` is the resolved key;
  - `validation_error` for a `linked_from` with no `/`;
  - the gate is unchanged.
- **`modules/arkeology.resources.md`**, `### register_data_resources`, the `{id*}` invariant:
  - `id` is either a full key or a bare id;
  - a bare id resolves to `{WRITE_PREFIX}/{id}.md` through T84's resolver;
  - the cross-scope-gate invariant applies to the resolved key;
  - `{id*}` stays.
- No Studio or design contract changes. Neither `arkeology.tools.studio.md` nor
  `design/arkeology-studio-tokens.html` specifies link-click behaviour.
  `### register_ui_resource` names only the `npm test` sanitisation guard, which still applies.
- The Studio link-resolution ADR's revision asks for brainstorming-2026-09-17-okf-v02-adoption D1's
  "full S3 key" wording to be revisited once links carry bare ids. T88 makes that happen, so update
  the wording alongside these amendments. No decision changes:
  brainstorming-2026-09-17-okf-v02-adoption D1's "Studio derives nothing" still holds.
- `references.py` has no contract and gets none. As today, its docstrings and unit tests are the
  authority.

### Testing Approach

**TDD order** (each test file confirmed red before the implementation file it gates):

1. `tests/unit/test_references_resolution.py` → `references.py`.
   - Reader:
     - `id: 001`, `id: 1.0` and timestamps come back as literal strings;
     - no block, or an unclosed `---`, means nothing declared;
     - invalid YAML or a non-mapping block is unreadable.
   - **AC-81**: two files declaring `plan` produce one duplicate naming both paths.
   - An invalid id is reported with T87's message. A missing file is an error. `Spec-A` and `spec-a`
     are a case-only group, not an error.
   - **AC-58**, resolution:
     - a renamed target, a target later in the manifest and a `../` path all resolve to the
       declared id;
     - a URL, an excluded or never-migrated path, an id-less target and an `arkeology://` entry
       stay unchanged;
     - a label equal to another file's id resolves nothing;
     - an absent `last_modified` gets the target's `revised.at`, or its `generated.at`;
     - a present one, other keys and the entry order are kept;
     - shuffling the manifest gives the same output.
2. `tests/unit/test_references_content_rewrite.py` → `rewrite_content_sources`.
   - A `resource:` on the `- ` line and on a continuation line are both rewritten, with quotes kept.
   - Label, title and `last_modified` lines stay byte-identical. So does a `relationships:` block
     whose `to:` equals a map key, and a top-level `resource:`.
   - URLs, fenced code and flow style are untouched. A body link is rewritten, with its anchor note.
   - A second run changes nothing.
3. `tests/unit/test_skill_artifact_id_drift.py` → the migration skill's SKILL.md.
   - Delete the id and `references:` cases and `test_punctuation_collapse_cases_share_a_slug`, since
     the skill no longer computes ids.
   - Run the skill's frontmatter snippet over temporary files built from one case table: producer
     block, literal scalars, invalid ids, unreadable block, missing file, duplicate, case-only
     group.
   - Assert the output equals the `references.py` helper's output.
4. `tests/unit/test_tools_migrate_artifacts.py` → `migrate_artifacts.py`.
   - `resolved_sources_map` rewrites content in both `dry_run` modes and never leaks into results.
   - **AC-80**: `resolved_references_map` fails only its entry, naming `resolved_sources_map`.
   - **AC-58 end to end**: descriptors built through `references.py` for Story 2, run with
     `dry_run=False`. `read_artifact` on A shows the resolved source, with its label, title and
     filled baseline, plus rewritten content, untouched URL and excluded entries, and
     `relationships` equal to the input.
   - Imported `revised`:
     - it is stored canonically and the history is `[generated, revised]`;
     - a missing `at` or a bare-role `by` fails the entry;
     - a re-run that skips an existing artifact leaves its `revised` unchanged.
5. `tests/unit/test_tools_write_artifacts.py`, `test_tools_write.py` → `write_artifacts.py`,
   `write.py`. A `create_artifacts` descriptor carrying `revised` fails naming `update_artifact`. A
   plain create still writes no `revised` (T79's test stays).
6. `tests/unit/test_tools_read.py` → `read.py`.
   - An own-scope carrier with a bare id reads B and returns B's full key.
   - Carrier `P/a.md` with `t2` resolves to `P/t2.md`. A tier-2 target there gives `access_denied`,
     and a tier-3 shared one is readable.
   - A full key with `linked_from` is unchanged.
   - A `linked_from` with no `/` gives `validation_error` with no storage call (spy).
   - A bare id without `linked_from` gives `access_denied`, as today.
7. `tests/unit/test_data_resources.py` → `resources.py`.
   - `arkeology://artifact/old-name` returns `{WRITE_PREFIX}/old-name.md`'s content.
   - An absent bare id returns the `not_found` error body.
   - **AC-51**'s foreign tier-2 full key still returns the gate error.
8. `tests/static/studio-link-follow.test.js` → `arkeology-studio.html`, run with `npm test`.
   - Activating a bare link in K's view calls `read_artifact` with
     `{artifact_id: "old-name", linked_from: K}`.
   - A row click sends `artifact_id` only.
   - After the response, a nested link sends the returned key as `linked_from`.
   - A server error is rendered verbatim.
   - `studio-link-sanitisation.test.js` passes unchanged.
9. `tests/unit/test_server.py` → `server.py`, through `fastmcp.Client(_app)`.
   - `create_artifact` called with `revised` returns `validation_error` naming `update_artifact`,
     and the inner function is not awaited.
   - The `read_artifact` schema lists an optional string `linked_from`, and the tool forwards it.
10. The skill and `schema.yaml` are covered by step 3 and by the manual checks below.

**Manual checks** (each on a fixture repository, against a deployment holding no artifacts under its
write prefix):

- **AC-81**: two files declare `id: plan`. The skill stops, names both, makes no `migrate_artifacts`
  call, and `list_artifacts` is still empty.
- **Story 4**: a file with two `verified` entries. After migration `read_artifact` shows both, and
  after a second run still exactly two.
- **Story 7**: on the AC-58 fixture, open A in Studio inside a supporting host, click B's link, and
  B opens. Reading `arkeology://artifact/<B's id>` from the host returns B.

**Integration tests this change breaks:** none.
`tests/integration/test_tools_migrate_artifacts.py` sends neither map key nor `revised`, and its
T79 and T84 descriptor changes land with those tasks. `read_artifact`'s new parameter is optional,
so `tests/integration/test_tools_read.py` is unaffected. No integration test is added. The new
server behaviour is a content rewrite, plus metadata keys and an annotation that T79, T80 and T84
already exercise against real AWS, plus a key resolution that happens before any AWS call.

**Mutation testing.** T88 changes no file in `only_mutate`. If the history seed has to touch
`annotations.py` after all, run `uv run mutmut run` alone, clear `__pycache__`, and triage the
survivors as AGENTS.md describes.
