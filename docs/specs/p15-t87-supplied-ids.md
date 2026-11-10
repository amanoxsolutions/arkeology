---
type: Spec
id: p15-t87-supplied-ids
title: T87 — Producer-Supplied id Becomes the Artifact Id
description: create_artifact, and each create_artifacts or migrate_artifacts descriptor, accepts an optional writer-supplied id that becomes the bare artifact id verbatim under the key {WRITE_PREFIX}/{id}{file_extension}. It is case-preserved, never slugified and gets no hash suffix. An id outside D33's form is rejected and never repaired, and generated ids are unchanged when no id is supplied. The cross-scope gate, every scope guard and reconcile's probe marker are unaffected by construction. AGENTS.md's deterministic-keys rules carry the amendment.
tags: []
status: draft
okf_version: "0.2"
sources:
  - id: adr
    resource: docs/architecture-decisions/adr-2026-09-25-okf-v02-adoption.md
    title: OKF v0.2 Adoption
    last_modified: 2026-09-29T00:00:00Z
  - id: adr-ids
    resource: docs/architecture-decisions/adr-2026-05-29-deterministic-artifact-ids.md
    title: Deterministic Slug-Based Artifact Identifiers
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
  - id: contract-s3
    resource: docs/contracts/data/s3.artifact.md
    title: s3.artifact
    last_modified: 2026-09-07T00:00:00Z
  - id: contract-write
    resource: docs/contracts/modules/arkeology.tools.write.md
    title: arkeology.tools.write
    last_modified: 2026-09-06T00:00:00Z
  - id: contract-write-artifacts
    resource: docs/contracts/modules/arkeology.tools.write_artifacts.md
    title: arkeology.tools.write_artifacts
    last_modified: 2026-09-04T00:00:00Z
  - id: contract-migrate
    resource: docs/contracts/modules/arkeology.tools.migrate_artifacts.md
    title: arkeology.tools.migrate_artifacts
    last_modified: 2026-09-15T00:00:00Z
  - id: aws-s3vectors-key
    resource: https://docs.aws.amazon.com/AmazonS3/latest/API/API_S3VectorBuckets_PutInputVector.html
    title: PutInputVector (S3 Vectors) — vector key length 1–1024
relationships:
  - to: adr-2026-09-25-okf-v02-adoption
    type: implements
  - to: adr-2026-05-29-deterministic-artifact-ids
    type: implements
  - to: p15-t78-create-update-split
    type: builds_on
  - to: p15-t79-provenance
    type: builds_on
  - to: p15-t77-open-type-list
    type: builds_on
generated:
  by: "axians-architect/claude-opus-5.5"
  at: 2026-10-13T16:38:44Z
phase: 15
task: 87
---

# T87 — Producer-Supplied `id` Becomes the Artifact Id

<!-- SCOPE BLOCK — frozen after approval -->

## TL;DR

`create_artifact` gains an optional `id`, and so does each `create_artifacts` and `migrate_artifacts`
descriptor. When a caller supplies it, the string is the artifact id byte for byte, and the key is
`{WRITE_PREFIX}/{id}{file_extension}`. The frozen filename stems and `relationships[].to` values
written by the producer `amanox-ai-agents` plugin then name the same document in Git and in
Arkeology, with no translation step (D28). An id outside D33's form is rejected and never repaired.
A caller that supplies no `id` gets exactly the id it got before.

## Problem Statement

Every id is generated today from type, date and title, then slugified and hash-suffixed. The producer
`amanox-ai-agents` plugin now writes a frozen `id:` into every document and names other documents by
it in `relationships[].to`. A generated id never equals that name, so every move between the Git
corpus and Arkeology needs a lookup. Upstream, path-derived links were measured wrong 43 times
(ADR-017 `## Alternatives Considered`, "Identity and types"). AGENTS.md and the deterministic
artifact ids ADR allow only the generated scheme. That ADR's accepted
`## Revision — 2026-09-25 (accepted 2026-10-13)` amends this, and the code and AGENTS.md now have to
follow (FR-73; D28).

## User Stories

### Story 1 — A supplied id is the artifact id (P1)
- Given `id="ADR-005.okf-adoption"`, when `create_artifact` succeeds, then it returns `artifact_id`
  `{WRITE_PREFIX}/ADR-005.okf-adoption.md`. The S3 object, every vector key prefix and every vector's
  `artifact_id` metadata carry exactly that key, and `read_artifact` on it returns the content
  (AC-76).
- Given the same `id` with `file_extension=".txt"`, then the key ends `ADR-005.okf-adoption.txt`.
- Given no `id`, then the returned key is the one `generate_artifact_id` produces for the same inputs
  (FR-08).
- Given an artifact created with a supplied id, when `update_artifact` retitles it by `artifact_id`,
  then the key is unchanged (FR-15, FR-75).

### Story 2 — An invalid id is rejected, never repaired (P1)
- Given an id that contains `/` or `..`, is longer than 128 characters, starts or ends with a
  non-alphanumeric character, or contains any character outside `[A-Za-z0-9._-]`, when it is
  created, then the call returns `validation_error` with the message below, and no storage call is
  made (AC-76; D33).

### Story 3 — Uniqueness is enforced at the storage layer (P1)
- Given an artifact stored under supplied id X, when another create supplies X with any title, tier
  or day, then the call returns `validation_error` naming `update_artifact`, and the original is
  unchanged (FR-08, FR-13, C-05).
- Given a stored generated id G, when a create supplies `id=G`, or a generated create lands on a key
  that a supplied id already holds, then it is rejected the same way.
- Given `Spec-A` is stored, when `spec-a` is created, then it succeeds and two artifacts exist (D33;
  FR-08).

### Story 4 — Bulk and migration honour it (P1)
- Given `create_artifacts` descriptors that carry `id`, then each entry is keyed by its own id. When
  two descriptors resolve to one key, whether supplied, generated or one of each, the later one fails
  with `validation_error` naming the first index. An invalid id fails only its own entry.
- Given `migrate_artifacts` re-run over descriptors that carry `id`, then an entry whose supplied key
  already exists is reported under `skipped_existing` and never rewritten.

## Requirements

**Input** (FR-01, FR-73; D28, D33)

- WHEN `create_artifact` is called THE SYSTEM SHALL accept an optional `id` string, absent by
  default. WHEN a `create_artifacts` or `migrate_artifacts` descriptor carries an `id` key THE
  SYSTEM SHALL treat it the same way for that entry. There is no batch-level `id`.
- WHEN `id` is supplied THE SYSTEM SHALL accept it only if it is a `str` that fully matches
  `[A-Za-z0-9]([A-Za-z0-9._-]{0,126}[A-Za-z0-9])?` and contains no `..`. That means 1 to 128
  characters, ASCII only, a letter or digit at both ends, and no `/`, because the character set
  excludes it.
- WHEN it does not THE SYSTEM SHALL return `{"error": "validation_error", "message": "id must be
  1-128 characters from A-Z, a-z, 0-9, '.', '_' and '-', must start and end with a letter or
  digit, and must not contain '..'"}`. The message is exactly that text and does not echo the value.
  The response comes before any storage call, failure-log append or embedding. An empty string or a
  non-string value counts as a supplied id that fails. Only an omitted `id` (`None`, or no descriptor
  key) means "generate".
- THE SYSTEM SHALL never slugify, lowercase, trim or suffix a supplied id, and SHALL never strip an
  extension from it.

**Key** (FR-08, FR-73; D28, D32)

- WHEN `id` is supplied THE SYSTEM SHALL use it as the bare id, giving the key
  `{WRITE_PREFIX}/{id}{file_extension}`. `generate_artifact_id` does not run, so there is no hash
  suffix and no date anchor. Tier, type, title and `generated` are stored as metadata as usual but
  play no part in the key. WHEN `id` is absent THE SYSTEM SHALL generate the id exactly as T77 and
  T79 leave it.
- THE SYSTEM SHALL resolve the bare id in one function in `artifact.py`. The create path, the
  `create_artifacts` duplicate pre-flight and the `migrate_artifacts` existence probe SHALL all call
  it, so the key that is probed or compared is always the key that is written. This extends T79's
  "same resolved value" rule (T79 `## Requirements`, "Identity").
- The create response is unchanged: `artifact_id` is the full key.

**Collision** (FR-08, FR-13, C-05; D28, D51)

- THE SYSTEM SHALL rely on create's conditional write (`IfNoneMatch: "*"`, T78) as the only
  uniqueness check. Supplied and generated ids share one namespace per scope, and whichever lands
  first wins. The other create gets T78's `validation_error` naming `update_artifact`. There is no
  supplied-versus-generated lookup and no case-insensitive lookup.

**Update** (FR-75; D51)

- `update_artifact` and `update_artifacts` gain no `id` parameter. They address the artifact by
  `artifact_id` and never move the key (T78), and that holds for supplied-id artifacts too.

**Unchanged by construction** (AGENTS.md Non-Negotiable Rules; D33)

- THE SYSTEM SHALL leave unchanged `_scope.py`, every `is_own_scope` and `startswith(scope + "/")`
  guard, `build_scope_filter`, and in `reconcile.py` both `_PROBE_KEY_MARKER` and the vector-key `#`
  split. The proof is under "Decisions taken in this spec".

**Rule text** (plan.md `## Phase 15`, T87 done condition)

- AGENTS.md's Working Conventions key-scheme bullet and its Non-Negotiable "Never generate random or
  UUID artifact keys" SHALL carry the amendment. The wording is in Files to Touch.

### Decisions taken in this spec

**The parameter is `id`.** It is the OKF frontmatter key and the producer's field name, so a
migration descriptor maps `id:` to `id` one-to-one. `artifact_id` was rejected: every other tool
uses it for the *full* key, and the create response returns it as the full key. One name meaning
two things is the problem ADR-017 `## Context`, "Forces", fixes for `status`. Shadowing the builtin
follows the `type` precedent (`# noqa: A002`).

**One fixed message that does not echo the value.** The rule is short enough to state whole. A
caller-sized string is not reflected back, and one exact text gives one assertion. In bulk results
the entry's position already identifies the descriptor.

**Empty or non-string is rejected, not treated as absent.** Treating `""` as "generate", or `5` as
`"5"`, would be a repair, and D33 says ids are never repaired. On the MCP surface, FastMCP's
argument validation rejects a non-string before the tool runs. In a bulk descriptor, which is an
untyped dict, the validator rejects it.

**ASCII and full-string matching.** The match covers the whole string. A `$` anchor would accept a
trailing newline. It uses no `IGNORECASE`, `\w`, `\d` or `str.isalnum()`, each of which admits
non-ASCII characters (`IGNORECASE` admits the Kelvin sign U+212A for `[A-Za-z]`). `..` is rejected
anywhere in the id, as D33 states. With no `/` allowed, it could never form a path segment anyway.

**The gate and scope guards are unaffected — proof.** The key is `W + "/" + id + ext`, where `W` is
the server's own `WRITE_PREFIX`. The server concatenates it, and the caller never supplies `W`.
1. `is_own_scope(key, W)` is true for every id. Update, archive, delete and reconcile therefore
   admit exactly the keys this server wrote.
2. The id contains no `/`, so it can only lengthen the final path segment and never add a segment.
   For any reader prefix `P`, `key.startswith(P + "/")` therefore holds exactly when it holds for a
   generated id with the same extension.
3. `is_cross_scope_readable` reads `tier` and `visibility` from metadata, and `build_scope_filter`
   filters on the `scope` metadata (`W`). Neither inspects the id.

No gate code changes, so the mutation Scope gains no code.

**Code that parses id structure, re-verified 2026-10-13.** The brainstorming notes named a `/`
split and the probe marker in `reconcile.py`. The full list is longer, and every entry is safe
because D33 excludes `/`, `#`, `?` and `%`:
- `reconcile.py`, orphan scan: `rsplit("/", 1)[-1]`. The final segment is exactly `{id}{ext}`.
- `reconcile.py`: `vk.split("#")[0]` on vector keys `{key}#{slug}`. Vector keys are built in
  `write.py` `write_artifact_inner` and `reconcile.py`.
- `arkeology-studio.html`, `artifactTarget`: splits on `#` and `?`, then `decodeURIComponent`.
- `arkeology-studio.html`, the detail view's scope label: `split("/")`.
- `references.py` `_rewrite_body_line`: `partition("#")`. This acts on link paths, not on ids.

Nothing parses a date, type or hash out of an id.

**The probe marker cannot collide.** `_PROBE_KEY_MARKER` is `_arkeology_`, and the orphan scan
matches it as a prefix of the final segment, which is `{id}{ext}`. A supplied id's first character
is alphanumeric (D33), so it never starts with `_`. T77 already rewords the marker comment to cover
D33 ids.

**No new length exposure.** After T77, a generated tier-2 id can reach 141 characters: a type slug
of up to 60, a date of 10, a title slug of up to 60, a hash of 8 and 3 dashes. A 128-character
supplied id is shorter, so the S3 key and S3 Vectors key limits (1024), the filterable
`artifact_id` budget and the `$in` id chunking in `_search_helper.py` all face nothing longer than
today. `check_metadata_budgets` still measures the assembled dicts.

**Out of scope, noted:** `file_extension` is only checked for a leading `.`, so it can contain `/`.
That is a pre-existing nesting vector that applies equally to generated ids, and T87 does not widen
it.

## Boundaries

**Always:**
- Validate a supplied id before any storage call, failure-log append or embedding.
- Resolve every key through the one `artifact.py` function, never inline.
- Keep the `public` / `_inner` pattern with `try/except Exception`, and log to stderr only.

**Ask First:**
- Any validator rule beyond D33, for example rejecting an id that ends `.md`.
- Adding `id` to the update tools.
- Adding `file_extension` validation.

**Never:**
- Repair, normalise or hash-suffix a supplied id, or add a case-insensitive uniqueness check.
- Change `_scope.py`, any scope guard or `_PROBE_KEY_MARKER`.
- Take over T88's work. The migration skill passes frontmatter `id:` as the descriptor `id`, runs
  the AC-81 manifest-wide duplicate check, and adds the resolver to `references.py`
  `build_path_to_id_map`. The `migrating-to-arkeology` offline id snippet, `backfilling-references`
  and `test_skill_artifact_id_drift.py` also belong to T88. T87 makes the server honour `id` end to
  end, which is what T88 builds on.
- Edit the schema resource (T89), or README, SERVER-REFERENCE or CHANGELOG (T91).

<!-- IMPLEMENTATION BLOCK — agent-owned -->

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_artifact.py` | Modify | First. Validator and resolver table (see Testing Approach) |
| `src/arkeology/artifact.py` | Modify | Add the id resolver (suggested name `resolve_artifact_id`; the contract fixes the signature). It returns the validated supplied id verbatim, or `generate_artifact_id`'s output when `id` is absent, and raises `ValueError` with the exact message. Module and `generate_artifact_id` docstrings: the hash suffix applies to generated ids only |
| `tests/unit/test_tools_write.py` | Modify | Stories 1–3 |
| `src/arkeology/tools/write.py` | Modify | `create_artifact` and its inner function take `id`, resolve the key through the resolver, and map `ValueError` to `validation_error` |
| `tests/unit/test_tools_write_artifacts.py` | Modify | Story 4, bulk |
| `src/arkeology/tools/write_artifacts.py` | Modify | The pre-flight calls the resolver with `d.get("id")`. An invalid id falls into the existing `except` and is reported by the entry. Forward the descriptor `id` |
| `tests/unit/test_tools_migrate_artifacts.py` | Modify | Story 4, migration |
| `src/arkeology/tools/migrate_artifacts.py` | Modify | The existence probe calls the resolver with the descriptor `id`. An invalid id takes the existing defer-to-create branch |
| `tests/unit/test_tools_read.py` | Modify | Gate test with a supplied-id key |
| `tests/unit/test_tools_reconcile.py` | Modify | A supplied-id orphan is re-indexed, not treated as a probe |
| `tests/unit/test_server.py` | Modify | `create_artifact` exposes an optional `id` and forwards it |
| `src/arkeology/server.py` | Modify | `create_artifact` gains `id: str \| None = None` and forwards it. Its docstring states the rule. The `create_artifacts` and `migrate_artifacts` docstrings mention the descriptor `id` |
| `tests/integration/test_tools_write.py` | Modify | AC-76 round trip against real AWS |
| `AGENTS.md` | Modify | The two bullets below |

**AGENTS.md, Working Conventions**: replace the bullet beginning "Tier 2 artifact IDs are
date-anchored" with:

> - An artifact key is `{WRITE_PREFIX}/{id}{file_extension}`. When the writer supplies `id`, it is the id verbatim — case-preserved, never slugified or lowercased, no hash suffix — validated against `[A-Za-z0-9._-]` with an alphanumeric first and last character, no `..`, and at most 128 characters, and rejected with `validation_error`, never repaired, when it does not fit; its uniqueness is the producer's guarantee, and ids differing only in case are distinct keys. Otherwise the id is generated: tier 2 is date-anchored, `{type_slug}-{date}-{title_slug}-{hash}` with `{date}` the UTC calendar day of `generated.at`; tier 3 is date-independent, `{type_slug}-{title_slug}-{hash}` — `hash` is a deterministic 8-hex-char SHA-256 prefix of the full original title, always appended to a generated id, and disambiguates the empty-slug/truncation/punctuation-collapse collision classes — do not alter this scheme. `create_artifact` rejects a key that already exists (`validation_error`, atomically); only `update_artifact`, addressed by `artifact_id`, replaces an artifact, and it never changes the key

This rewrite also states the T78 and T79 facts, which have landed by then (T87 is blocked by T79),
so T91 does not need to re-edit this bullet.

**AGENTS.md, Non-Negotiable Rules**: replace "Never generate random or UUID artifact keys — keys
are fully deterministic from artifact attributes" with:

> - Never generate random or UUID artifact keys — a key is either the writer-supplied `id`, used verbatim, or generated deterministically from artifact attributes; a supplied id is an attribute like any other, which amends this rule rather than breaking it (deterministic artifact ids ADR, `## Revision — 2026-09-25 (accepted 2026-10-13)`)

## Contract Amendments

Make these before the tests, on top of T77, T78 and T79's amendments:

- **`docs/contracts/data/s3.artifact.md`**:
  - Add a `###` symbol for the id resolver, covering the D33 rule, the exact `ValueError` message,
    and "absent means generate".
  - `### generate_artifact_id`: its output is the fallback bare id. "Equal output implies equal
    inputs" holds among generated ids only, because a supplied id may equal one.
  - `## Storage Shape`, Key: the bare id is the supplied `id` or the generated id.
  - `## Compatibility Guarantees`: the key-scheme bullet becomes "ids are the supplied id verbatim
    or deterministic from attributes; never random. The hash suffix is always appended to a
    *generated* id and never to a supplied one."
- **`docs/contracts/modules/arkeology.tools.write.md`**, `### create_artifact`:
  - Parameter: `id`.
  - Errors: `validation_error` with the exact message.
  - Invariants: the key form; a supplied id is never transformed; supplied and generated ids share
    one namespace under the conditional create.
- **`docs/contracts/modules/arkeology.tools.write_artifacts.md`**, `### create_artifacts`:
  - The descriptor `id` key.
  - The duplicate pre-flight compares resolved keys.
  - An invalid id fails only its entry.
- **`docs/contracts/modules/arkeology.tools.migrate_artifacts.md`**: the existence probe uses the
  resolved key, including the descriptor `id`. Skip-never-overwrite is unchanged.

## Testing Approach

**TDD order** (each test file is confirmed red before the implementation file it gates):

1. `tests/unit/test_artifact.py`, then `artifact.py`.
   - Accepted, returned verbatim:
     - `ADR-005.okf-adoption`
     - `a`
     - `Z9`
     - `a.-_b`
     - a 128-character id
   - Rejected with the exact message:
     - `""`
     - `.a`, `a.`, `-a`, `a-`
     - `_arkeology_x`, which pins the probe-marker proof
     - `a/b`, `a..b`
     - a 129-character id
     - `a b`, `a#b`, `a?b`, `a%41`
     - `é`, `ａ`
     - `K` (the Kelvin sign)
     - `"a\n"`
     - `5`
   - Absent `id`: the output equals `generate_artifact_id` for tier 2 and tier 3 (FR-08, AC-76).
2. `tests/unit/test_tools_write.py`, then `tools/write.py`.
   - AC-76 round trip:
     - the returned key;
     - an S3 object exists at that key;
     - every vector key starts `{key}#`;
     - `read_artifact` returns the content.
   - With `.txt`, the key ends `.txt`.
   - An invalid id gives the exact message, and spies show no `put_object`, no embed call and no
     failure-log entry (AC-76).
   - Recreating supplied id X with a different title gives `validation_error`, with the original
     unchanged (FR-08, FR-13).
   - Supplied-equals-generated collisions are rejected in both directions (C-05).
   - `Spec-A` and `spec-a` both succeed (D33).
   - Two tier-2 creates with the same type, title and day but different supplied ids give two
     artifacts (D32).
   - A retitle via `update_artifact` keeps a supplied-id key (FR-15, FR-75).
3. `tests/unit/test_tools_write_artifacts.py`, then `tools/write_artifacts.py`.
   - Descriptor `id` is honoured.
   - Two equal supplied ids: the later entry fails naming the first index.
   - A supplied id equal to another descriptor's generated id is caught the same way.
   - An invalid id fails its own entry only.
4. `tests/unit/test_tools_migrate_artifacts.py`, then `tools/migrate_artifacts.py`.
   - A `head_object` spy is called with `{WRITE_PREFIX}/{id}.md`.
   - A re-run gives `skipped_existing` with no write.
5. `tests/unit/test_tools_read.py` and `tests/unit/test_tools_reconcile.py`. These are
   characterisation tests that pass on first run, because no gate or reconcile code changes. That
   is the point, so they are not red-first.
   - A foreign tier-2 supplied-id artifact is denied, and a foreign tier-3 shared one is readable.
   - A supplied-id orphan is re-indexed and not skipped.
6. `tests/unit/test_server.py`, then `server.py`.
   - The `create_artifact` schema lists an optional string `id`.
   - The value is forwarded.
7. Integration.

**AC-80.** T87 removes no name, so there is no rejection test.

**Integration tests this change breaks:** none. `id` is optional, and absent means today's
behaviour. Add one test to `tests/integration/test_tools_write.py`. It runs AC-76 against real S3
and S3 Vectors: create `ADR-005.okf-adoption`, `read_artifact` it, and check that
`search_artifacts` returns the exact key. A key with uppercase letters and dots, in both stores, is
the behaviour moto only approximates.

**Mutation testing.** T87 changes no file in `only_mutate`, so no run is required.

## Open Questions

None. ADR-017 `## Decision` "5. Identity", the deterministic artifact ids ADR's accepted revision,
FR-08, FR-73, AC-76 and plan.md's T87 entry agree. The `s3.artifact` Compatibility Guarantees
forbid dropping the hash suffix, which conflicts with D28. That is a contract that is out of date
against an accepted ADR, not a contradiction to rule on, and the amendment above resolves it.
