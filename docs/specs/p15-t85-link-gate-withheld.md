---
type: Spec
id: p15-t85-link-gate-withheld
title: "T85 — Cross-Scope Gate on sources and relationships, with the {withheld: n} Marker"
description: Every capability that returns a foreign-scope artifact's link fields or content removes the sources and relationships entries pointing at artifacts the reader cannot read, and appends one {withheld: n} entry to each list it shortened, both in the returned field and in the returned content's frontmatter, without modifying the stored object. Own-scope readers receive both lists and the content exactly as stored. All redaction code sits in files already in the mutation-testing Scope.
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
  - id: spec-t84
    resource: docs/specs/p15-t84-sources-relationships.md
    title: "T84 — sources + relationships in One Structured Annotation; link_metadata → add_artifact_links"
    last_modified: 2026-10-13T17:23:06Z
  - id: spec-t87
    resource: docs/specs/p15-t87-supplied-ids.md
    title: "T87 — Producer-Supplied id Becomes the Artifact Id"
    last_modified: 2026-10-13T16:38:44Z
  - id: adr-access
    resource: docs/architecture-decisions/adr-2026-05-29-tier-based-access-control.md
    title: Tier-Based Cross-Scope Access Control Model
    last_modified: 2026-09-25T00:00:00Z
  - id: adr-malformed
    resource: docs/architecture-decisions/adr-2026-09-14-malformed-persisted-data-policy.md
    title: How Arkeology Treats Malformed and Ambiguous Persisted Data
    last_modified: 2026-09-29T00:00:00Z
  - id: contract-read
    resource: docs/contracts/modules/arkeology.tools.read.md
    title: arkeology.tools.read
    last_modified: 2026-09-14T00:00:00Z
  - id: contract-list
    resource: docs/contracts/modules/arkeology.tools.list.md
    title: arkeology.tools.list
    last_modified: 2026-09-14T00:00:00Z
  - id: contract-synthesise
    resource: docs/contracts/modules/arkeology.tools.synthesise.md
    title: arkeology.tools.synthesise
    last_modified: 2026-09-14T00:00:00Z
  - id: contract-resources
    resource: docs/contracts/modules/arkeology.resources.md
    title: arkeology.resources
    last_modified: 2026-09-04T00:00:00Z
  - id: okf-issue-32
    resource: https://github.com/GoogleCloudPlatform/open-knowledge-format/issues/32
relationships:
  - to: adr-2026-09-25-okf-v02-adoption
    type: implements
  - to: p15-t84-sources-relationships
    type: builds_on
generated:
  by: "axians-architect/claude-opus-5.5"
  at: 2026-10-13T18:07:52Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-09T22:23:38Z
---

# T85 — Cross-Scope Gate on `sources` and `relationships`, with the `{withheld: n}` Marker

## TL;DR

A foreign-scope reader is someone reading an artifact from another team's scope. After T84, such a
reader gets `sources` unfiltered, and any unreadable `relationships` entries are dropped without a
trace. T85 changes this for every capability that returns a foreign artifact's link fields or
content. Each entry pointing at an artifact the reader cannot read is removed, and one
`{withheld: n}` entry is appended to each list that lost entries. This applies to the returned field
and to the `sources:`/`relationships:` blocks of the returned content's frontmatter alike. Own-scope
readers, and the stored object, are untouched.

## 1. Problem Statement

FR-10 promises that an artifact never exposes a pointer to an artifact the reader could not read
independently. After T84 that promise fails in three places:

- `sources` entries that name a tier-2 artifact reach foreign readers unfiltered. This was always a
  gap, not a choice (D38).
- `relationships` entries are dropped silently. A list that looks complete when it is not leads the
  reader to judge a document on provenance it does not actually rest on (D47).
- The content's frontmatter carries the same entries, written there by migration as
  `arkeology://artifact/{id}` (FR-52). Redacting only the field would therefore be decorative
  (D49).

Not taken: bare-id links on read surfaces. T84's Open Question 2 is about following links, not
redaction, and plan entry 85 does not include it.

The five user stories, kept below as labelled examples (Story 1 to Story 5), are all P1.

## 2. Rules — What a foreign reader sees

### R1 — A foreign reader learns how much is hidden, not what

**Story 1.** Setup: reader R has own scope `R` and read prefix `P`. Artifact `P/a.md` is tier 3 and
`shared`. Its stored `sources` are, in order:

1. `arkeology://artifact/P/t2.md` (tier 2)
2. `arkeology://artifact/hid` (a bare id, which resolves to `P/hid.md`, tier 3 `hidden`)
3. `https://example.com/spec`

Its content frontmatter lists the same three entries.

- **Read.** Given that setup, when R calls `read_artifact`, then `sources` is
  `[{resource: "https://example.com/spec"}, {withheld: 2}]`. The content's frontmatter `sources:`
  block holds the URL entry followed by `- withheld: 2`, and every other byte equals the stored
  content.
- **Every other surface.** Given the same artifact, when R lists it, receives it as a
  `synthesise_artifacts` result, or reads `arkeology://artifact/P/a.md`, then the field (listing) or
  the content (synthesis, resource) carries the same redaction.
- **Nothing leaks.** No response anywhere carries `t2`, `hid`, or their titles or `last_modified`
  values. `arkeology://artifacts` carries none of them either.
- **Stored and own-scope views unchanged.** The stored object is byte-identical afterwards. A reader
  whose own scope is `P` sees all three entries, in the field and in the content, exactly as stored.

Source: AC-78, FR-10, D47–D49

## 3. Rules — Who gets redacted

### R2 — Only a foreign carrier the gate admitted is redacted; an own-scope carrier is returned as stored, without a frontmatter parse or a vector-index call

The **carrier** is the artifact whose fields or content are being returned.

- When the carrier's key is in the reader's own scope (`is_own_scope`, i.e.
  `startswith(scope + "/")`), the system must return:
  - both lists exactly as stored;
  - the content byte-identical;
  - no marker;

  and it must do so without parsing frontmatter or calling the vector index. This keeps the read
  contract's postcondition that an own-scope read issues zero vector-index scans.
- When the carrier is a foreign artifact the gate admitted, the system must apply the redaction this
  spec states: which entries are gated, the marker, the frontmatter rewrite, the surfaces and the
  disclosure rules.

Source: FR-10

## 4. Rules — Which entries are gated

### R3 — Every `relationships` entry is Arkeology-pointing, its `to` resolved against the carrier's key

Every `relationships` entry is Arkeology-pointing. Its `to` must be resolved through T84's resolver
in `_scope.py` against the carrier's key. A bare id therefore resolves into the carrier's scope,
never the reader's.

**Example (Story 2 — Relationships are redacted the same way)**

- Given `relationships` `[{to: P/t2.md, type: supersedes}, {to: R/mine.md, type: builds_on},
  {to: shr, type: amends}]`, where `shr` resolves to `P/shr.md` (tier 3, `shared`):
  - when R reads it, R gets the `R/mine.md` entry and the `shr` entry in that order, then
    `{withheld: 1}`.

Source: D38, D47, AC-78

### R4 — A `sources` entry is Arkeology-pointing when its `resource`, ignoring surrounding whitespace and letter case, begins with `arkeology:`

A `sources` entry is Arkeology-pointing when its `resource`, ignoring surrounding whitespace and
letter case, begins with `arkeology:`. The system must return every other `resource` unchanged.
That covers URLs, unresolved paths, and OKF scope descriptors.

**Why:** lenient scheme match. URI schemes are case-insensitive (RFC 3986). Over-withholding an odd
`arkeology:` source fails closed; under-withholding would leak.

Source: D38, D47

### R5 — An Arkeology-pointing entry is kept only when its resolved key is readable under the existing gate

The system must keep an Arkeology-pointing entry only when its resolved key is readable under the
existing gate. That means `resolve_readable_targets`, which applies `is_cross_scope_readable`:

- own scope by prefix;
- foreign only when the target is tier 3 and `shared`.

The system must withhold the entry in every other case, including when:

- the resolver yields no key;
- the target has no vector;
- the target does not exist.

Source: D38, D47

### R6 — A malformed frontmatter entry is withheld, not fatal

When a frontmatter entry is not a mapping, or its `resource` (for sources) or `to` (for
relationships) is absent or not a string, the system must withhold it.

- Stored field entries cannot hit this rule: T84 validates them at write.
- The same rule removes a forged `withheld` entry authored into the content.

**Why:** the marker stays honest — something is hidden. One sloppy entry does not cost the whole
document.

Source: D38, D47

### R7 — With no vector client, a foreign read withholds every target outside the reader's own scope

When no vector client is available on a foreign read, the system must withhold every target outside
the reader's own scope. Today's read skips the `references` filter when `vectors` is `None`. That
fails open, and this rule closes it.

Source: D38, D47

## 5. Rules — The marker

### R8 — A list that lost entries keeps stored order and ends with exactly one `{withheld: n}`; a list that lost none gets no marker

When at least one entry is withheld from a list, the system must:

1. remove those entries;
2. keep the remaining entries in stored order;
3. append exactly one `{withheld: n}` as the list's last element.

`n` is an integer: the number of entries removed from that list in that place. The marker's only key
is `withheld`.

When nothing is withheld from a list, the system must emit no marker for it.

No path, option or output format may omit the marker. Every surface goes through the one redaction.

**Example (Story 3 — Nothing withheld, nothing added)**

- Given a foreign artifact whose Arkeology-pointing entries are all readable, or which has none,
  when R reads it, then both fields are as stored, the content is byte-identical, and no marker
  appears.

Source: D47, D48, OKF GitHub issue #32, FR-10

### R9 — `n` counts entries, not distinct targets, separately per list and per place

`n` must count entries, not distinct targets. Counting distinct targets would reveal that two hidden
entries name one artifact.

`sources` and `relationships` are counted separately, and so are the field and the frontmatter. Each
count is taken from its own entries. The counts normally agree. If the annotation and the content
disagree, the counts can differ, and neither reveals a withheld entry.

**Example (Story 5 — The count reveals only a count)**

- Given three withheld entries — two naming the same tier-2 target and one naming a foreign key
  that does not exist — when R reads the artifact, then the marker is `{withheld: 3}`. A foreign
  key that does not exist is withheld and counted exactly like one that exists but is unreadable.

Source: D47, D48, OKF GitHub issue #32, AC-78

## 6. Rules — Frontmatter rewrite

### R10 — Content has frontmatter only when it opens with a `---` line and has a closing `---` line; without it, the content is returned unchanged

Content has frontmatter only when it opens with a `---` line and has a closing `---` line. The same
rule is `references.py`'s `_frontmatter_end_index`.

When there is no frontmatter, the system must return the content unchanged. Everything is then body,
and the body is out of scope (D47's stated limit).

Source: D49, ADR-017 `## Deferred to the Specs` "How the returned frontmatter is rewritten", D47

### R11 — A link block is a top-level `sources` or `relationships` key line plus its following lines; every such block is processed

A link block is a top-level `sources` or `relationships` key line plus its following lines:

- the key line sits at column 0, the key may be quoted, and a trailing comment is allowed;
- the block runs to the next column-0 line that is not a list item, comment or blank line, or to
  the closing delimiter.

The system must process every such block, including a duplicated key. A key nested under another key
is not a link field.

Source: D49, ADR-017 `## Deferred to the Specs` "How the returned frontmatter is rewritten"

### R12 — Each link block is parsed on its own; it stays byte-identical unless it loses entries, and a block-style block that loses entries is rewritten line by line

The system must parse each block on its own as YAML.

- When the value is null or an empty list, or nothing is withheld from it, the system must leave the
  block byte-identical.
- When entries are withheld and the block is block-style, the system must rewrite it. Block-style
  means one list-item line per entry, all at one indentation, with the item count equal to the
  parsed length. The rewrite:
  1. deletes each withheld entry's lines — its item line and every line up to the next item or the
     end of the block;
  2. leaves every other line byte-identical;
  3. inserts `- withheld: n` at the items' indentation as the block's last item, using the
     content's own line ending.

**Why:** line surgery per block, not re-serialisation. The ADR requires every byte outside the two
blocks to stay as stored. Re-dumping the YAML would rewrite kept entries (`last_modified` would come
back as a datetime). Parsing the whole frontmatter would deny content over unrelated sloppiness: an
unquoted colon in a title breaks PyYAML, and that would cost a foreign reader an artifact AC-07
makes readable. So each block is parsed alone, and the parse is only the authority on entries.

Source: D49, ADR-017 `## Deferred to the Specs` "How the returned frontmatter is rewritten"

### R13 — Content whose link block cannot be redacted is not returned

When the block does not parse, is not a list, or must lose entries but is not block-style, the
system must not return the content:

- `read_artifact`, and so the artifact resource, returns `corrupt_metadata` naming
  `frontmatter sources` or `frontmatter relationships`, never echoing the block (D50, case 5);
- `synthesise_artifacts` skips the result and counts it under `skipped_malformed_count`.

**Example (Story 4 — Frontmatter that cannot be redacted is not served to a foreign reader)**

- Given a foreign artifact whose frontmatter `sources:` block is not parseable YAML:
  - when R reads it, then the result is `corrupt_metadata` naming `frontmatter sources`, and the
    block's text is not echoed;
  - when it is a `synthesise_artifacts` result, then it is skipped and counted under
    `skipped_malformed_count`;
  - an own-scope reader reads it unchanged.

**Why:** fail closed on an unredactable block. Returning the block unchanged leaks. Dropping the
block would need a count the server cannot know. `corrupt_metadata` and skip-and-count are the
malformed-data policy's single-read and iterating rules, and the read contract already allows
`corrupt_metadata` on an admitted foreign artifact. Only foreign readers of the rare
non-block-style or broken block pay.

Source: D49, ADR-017 `## Deferred to the Specs` "How the returned frontmatter is rewritten", D50, malformed-data policy ADR

### R14 — Every byte outside the rewritten blocks stays equal to the stored content, and the stored object is never written

The system must keep every byte outside the rewritten blocks equal to the stored content, and must
never write the stored object or its annotations.

Source: D49, ADR-017 `## Deferred to the Specs` "How the returned frontmatter is rewritten"

## 7. Rules — Surfaces

### R15 — What each capability returns to a foreign reader, its redaction and its gate lookups are as this table states

| Capability | Returns to a foreign reader | Redaction | Gate lookups |
|---|---|---|---|
| `read_artifact` | Both fields and the content | Both fields and the frontmatter | One batched lookup per call, covering the targets of the field and the frontmatter |
| `list_artifacts` | Both fields | The fields | One batched lookup per page (today's pattern) |
| `synthesise_artifacts` | Content (no link fields, per T84) | The frontmatter, before the response-byte budget measures it | At most one per foreign result that names a foreign target |
| `arkeology://artifact/{id*}` | Content | Inherited from `read_artifact`; an error renders as error markdown | None of its own |
| `arkeology://artifacts` | A table of id, title, type and description | Inherited from `list_artifacts`; it renders nothing link-shaped | None of its own |
| `arkeology_studio` | The fallback listing, and the UI's `read_artifact` content | Inherited. The UI renders content, frontmatter included, exactly as received, so the marker is shown. No Studio change | None |
| `search_artifacts` | Neither (T84) | None — not a surface | None |
| `create_*`, `update_*`, `add_artifact_links`, `migrate_artifacts` | Own scope only | Never | None |
| Freshness check, delete and archive warnings, purge, reconcile, `propose_commit_links` | Own-scope carriers only (D48) | Never. They act on stored entries | None |

Source: ADR-017 `### 7.`, final paragraph; D48, D49

## 8. Rules — Disclosure

### R16 — A withheld entry's target, resource, title or timestamp is never logged, and `corrupt_metadata` on `links` never echoes the payload

- The system must not log a withheld entry's target, resource, title or timestamp. It logs the
  count at most. The server's stderr belongs to the reader's deployment.
- The system must keep T84's rule that `corrupt_metadata` on `links` never echoes the payload.

## 9. Rules — Where the code lives

### R17 — The Arkeology-pointing classification goes in `_scope.py` and all redaction code in `_reference_filter.py`, so `only_mutate` is unchanged

- **`_scope.py`.**
  - The gate predicate stays `is_cross_scope_readable`.
  - T85 adds the Arkeology-pointing classification beside T84's resolver. It decides which entries
    the gate sees, so it is gate logic.
- **`_reference_filter.py`.** All redaction code goes here:
  - the own-scope short-circuit;
  - the batched lookup;
  - the no-vector-client fail-closed rule;
  - entry removal, the count and the marker;
  - the frontmatter rewrite.
- **Call sites.** `read.py`, `list.py` and `synthesise.py` call the redaction unconditionally, so
  the own-scope decision lives in mutation scope. Today it is hand-typed in `read.py`'s Step 4b.
- **Mutation Scope.**
  - Both files are already in `only_mutate`, so `only_mutate` is unchanged.
  - No gate implementation lands outside `_scope.py`.
  - T91 updates only wording: AGENTS.md's Repository Structure row and Scope sentence for
    `_reference_filter.py`. Nothing moved, so the Scope itself does not change.

**Why:** no new module. A separate frontmatter module would sit outside `only_mutate`. A leak there
would be exactly the silent, unrecoverable failure the Scope exists for.

Source: AGENTS.md `## Conventions` (mutation Scope)

## 10. Boundaries

**Always:**

- Route every surface through the one redaction in `_reference_filter.py`.
- Resolve every target through T84's resolver against the carrier.
- Use `startswith(scope + "/")`.
- Use the `_inner` + `try/except Exception` pattern.
- Log to stderr only.
- Run `mutmut` alone after the change, then clear `__pycache__`.

**Ask First:**

- Redacting the body.
- Changing the marker's shape or position. An OKF GitHub issue #32 ruling would trigger this.
- Widening `only_mutate`.
- Adding a surface that returns link fields or content.

**Never:**

- Write the stored object or its annotations.
- Return a withheld entry's id, resource, title, timestamp or position in any form.
- Emit a marker to an own-scope reader.
- Put gate logic outside `_scope.py`.
- Re-serialise the whole frontmatter.
- Log withheld targets.
- Fall back to unredacted content on any error.

## 11. For the developer agent

### Files to Touch

T85 lands after T84 and edits the code as T84 leaves it.

| File | Action | Notes |
|------|--------|-------|
| `src/arkeology/tools/_scope.py` | Modify | Add the Arkeology-pointing classification next to T84's resolver |
| `src/arkeology/tools/_reference_filter.py` | Modify | Add field redaction and the frontmatter rewrite: own-scope short-circuit, no-vector-client fail-closed, the count and the marker. Update the module docstring |
| `src/arkeology/tools/read.py` | Modify | Replace Step 4b with one redaction covering both fields and the content. Map an unredactable block to `corrupt_metadata` |
| `src/arkeology/tools/list.py` | Modify | Replace Step 5's filter with page-batched redaction of both lists |
| `src/arkeology/tools/synthesise.py` | Modify | Rewrite a foreign result's content before measuring the budget. Skip and count an unredactable one |
| `pyproject.toml` | Modify | Update the `[tool.mutmut]` comment on `_reference_filter.py` only. The list is unchanged |
| `src/arkeology/resources.py` | Docstrings only (uncertain) | The data-resource docstrings mention the gate. The behaviour is inherited |
| `src/arkeology/static/arkeology-studio.html` | None | Renders the content as received |

### Contracts

Contract amendments. These go on top of T84's amendments, before any tests are written.

- **`modules/arkeology.tools.read.md`**
  - Replace the `references` filtering invariant with the redaction rule: both lists, the marker,
    and the frontmatter rewrite.
  - Add to **Errors**: `corrupt_metadata` for an unredactable frontmatter block on a foreign read,
    naming the block and never echoing it. Also add that `credential_error` can arise at the
    redaction lookup.
  - Add to **Postconditions**:
    - returned content is byte-identical for an own-scope reader;
    - a foreign reader's content differs only inside rewritten link blocks;
    - a foreign read with no vector client withholds every foreign target.
- **`modules/arkeology.tools.list.md`**: replace the filtering bullet with the redaction and the
  marker, still one batched lookup per page.
- **`modules/arkeology.tools.synthesise.md`**:
  - A foreign result's content is redacted.
  - The budget counts the returned bytes.
  - `skipped_malformed_count` also counts an unredactable result. The repair for that case is the
    owning scope's content, not `reconcile_index`.
- **`modules/arkeology.resources.md`**:
  - `### register_data_resources`: "the same gate as `read_artifact`" now includes its redaction.
  - `### register_ui_resource`: the app renders returned content, frontmatter included, as
    received, and never strips it. This is D48's "Studio must render the marker".
- **`data/s3-annotations.artifact.md`**: none. T84 already reserves `withheld`.

### Testing Approach

**TDD order.** Each test file is confirmed red before the implementation file it gates.

1. `tests/unit/test_tools__scope.py` → `_scope.py`
   - The classification accepts `arkeology:`, `ARKEOLOGY://…` and ` arkeology://…` (leading
     space).
   - URLs and paths are classified as not Arkeology-pointing.
2. `tests/unit/test_tools__reference_filter.py` → `_reference_filter.py`
   - Story 5's count (R9).
   - The marker is last, stored order is kept, and an all-withheld list is exactly the marker.
   - No marker when nothing is withheld.
   - An own-scope carrier: zero vector calls (spy) and identical output.
   - A target in `R-abc/` is withheld for own scope `R`.
   - A bare id resolves into the carrier's scope.
   - No vector client means withheld.
   - A malformed entry or a forged `withheld` entry is withheld.
   - Frontmatter:
     - CRLF and comments in kept entries are preserved;
     - a column-0 sequence, a quoted key and a duplicate key are each handled;
     - `sources: []` is unchanged;
     - a nested `sources:` is untouched;
     - with no frontmatter, or an unclosed `---`, the content is unchanged;
     - a flow-style block with nothing withheld is unchanged, and with entries withheld it fails;
     - an unparseable block fails;
     - every byte outside the block is equal.
3. `tests/unit/test_tools_read.py` → `read.py`
   - **AC-78**, Stories 1–3 on read (R1, R3, R8): field and frontmatter. No withheld token appears
     in `json.dumps(response)`. The stored bytes are unchanged. An own-scope reader gets everything
     in full.
   - Story 4 (R13).
   - `caplog` holds no withheld token.
   - A body citation is left intact. This documents D47's limit.
4. `tests/unit/test_tools_list.py` → `list.py`
   - **AC-78** on list: one batched lookup across the page.
5. `tests/unit/test_tools_synthesise.py` → `synthesise.py`
   - **AC-78** on synthesis.
   - The budget counts redacted bytes.
   - An unredactable result is skipped and counted.
6. `tests/unit/test_resources.py` → `resources.py`
   - **AC-78** on `arkeology://artifact/{id*}` and on `arkeology://artifacts`.

**Changed expectations.** T84 retargets the tests that today assert a silent drop:

- `test_read_cross_scope_reference_filtering_drops_unreadable_target`
- `test_read_cross_scope_reference_missing_target_stripped`
- `test_list_cross_scope_reference_missing_target_stripped`
- the `_reference_filter` tier-2 and `hidden` tests

T85 changes those assertions to expect the marker.

**AC-80.** T85 removes no name, so there is no rejection test.

**Mutation.** After the unit suite is green:

1. Run `uv run mutmut run` alone.
2. Clear `__pycache__`.
3. Triage every survivor in the new `_scope.py` and `_reference_filter.py` code against the
   equivalence classes.

T85 is Done only when no survivor is new and non-equivalent.

**Integration.**

- No existing integration test breaks: none reads a foreign artifact that carries link fields.
- Add one test, `tests/integration/test_tools_read.py::test_foreign_reader_gets_withheld_marker`:
  1. Write a tier-3 `shared` artifact and a tier-2 target into the run's `foreign_prefix`, using
     `Settings` with that prefix as `WRITE_PREFIX`.
  2. Read as `integration_settings`.
  3. Assert AC-78's field and frontmatter.

  This is the first real-AWS exercise of the gate's vector lookup.

### Hand-offs

None.
