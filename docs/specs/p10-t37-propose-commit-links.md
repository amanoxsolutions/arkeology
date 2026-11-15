---
type: Spec
id: p10-t37-propose-commit-links
title: T37 — propose_commit_links Tool
description: Spec for a read-only MCP tool that discovers own-scope artifacts with no commit_refs, optionally bounded by a write-time ULID, for operator confirmation before linking.
tags: []
status: stable
okf_version: "0.2"
sources:
  - resource: docs/brainstorming/brainstorming-2026-06-06-artifact-commit-refs.md
    title: Artifact Commit References
    last_modified: 2026-07-03T00:00:00Z
  - resource: docs/specs/p10-t35-filter-range-operators.md
    title: T35 — Filter Range Operators ($gte / $lte)
    last_modified: 2026-06-06T00:00:00Z
  - resource: docs/specs/p10-t36-commit-refs-metadata-fields.md
    title: T36 — commit_refs and last_edited_ulid Metadata Fields
    last_modified: 2026-07-03T00:00:00Z
  - resource: docs/specs/p12-t58-commit-refs-cap-references-removal.md
    title: T58 — commit_refs Vector-Metadata Cap (20) + references Vector-Metadata Removal + propose_commit_links Multi-Section Fix
  - resource: docs/contracts/modules/arkeology.tools.propose_commit_links.md
    title: arkeology.tools.propose_commit_links
  - resource: .docs/reviews/architecture-review-2026-11-15-arkeology-phases-9-10-12.md
    title: "Architecture review — Arkeology, plan phases 9, 10 and 12"
  - resource: docs/specs/p9-t31a-setting-up-arkeology-skill.md
    title: T31a — Setting-Up-Arkeology Skill
  - resource: docs/contracts/data/s3-annotations.artifact.md
    title: s3-annotations.artifact
  - resource: docs/contracts/data/s3vectors.artifact.md
    title: s3vectors.artifact
  - resource: docs/contracts/data/s3.artifact.md
    title: s3.artifact
generated:
  by: "axians-analyst/unknown"
  at: 2026-06-06T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-15T20:35:38Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
  - by: "axians-architect/claude-fable-5-2"
    at: 2026-11-15T20:45:07Z
---

# T37 — `propose_commit_links` Tool

## TL;DR

Add a read-only MCP tool `propose_commit_links` that discovers own-scope artifacts that
have no `commit_refs` yet, optionally bounded to those written since a given write-time
ULID. It presents the candidate list to the agent for confirmation before any write occurs —
it has no side effects. It answers which artifacts in the scope were never linked to a commit;
`link_metadata` (`p12-t49-link-metadata`) writes the links.

## 1. Problem Statement

An agent sometimes needs to know which artifacts in its scope have never been associated with a
commit SHA: after a migration, whose artifacts all start unlinked, or when a session no longer
holds the list of what it wrote. The ordinary post-commit step needs no discovery — it links the
identifiers the session's own write responses returned (`p9-t31a-setting-up-arkeology-skill`
R35). Without a discovery tool, the agent would have to reconstruct the unlinked set manually by
inspecting all artifacts — expensive and error-prone. `propose_commit_links` provides that
discovery in a single call: it returns a candidate list with human-readable timestamps so the
operator can confirm, trim, or augment the set before calling `link_metadata` (the write half,
`p12-t49-link-metadata`). The candidates are keyed on scope and write time, not on who wrote
them: in a scope several engineers write, a proposal lists their unlinked artifacts too, and only
the operator's confirmation keeps those out of a link.
Whether an artifact is already linked is decided from its `commit_refs` S3 object annotation, the
field's sole source of truth; `p12-t58-commit-refs-cap-references-removal` owns that eligibility
read and what happens when it fails.

All five user stories this spec covers — discover unlinked artifacts since a given write time;
discover all unlinked artifacts in scope (no `since_ulid`); response includes a human-readable
timestamp; own-scope only, foreign-scope artifacts excluded; and credential failure returns a
structured error — are P1.

## 2. Rules — Discovering candidates

### R1 — With `since_ulid`, only own-scope artifacts written at or after it are proposed

When `propose_commit_links` is called with `since_ulid`, the system reads the own-scope candidates
from the vector index and then keeps, in process, only those whose `last_edited_ulid >=
since_ulid`. The bound is never placed in the filter expression sent to the index, which rejects
a range on a string value (`s3vectors.artifact` § Compatibility Guarantees). The agent passes as
`since_ulid` a `last_edited_ulid` the server returned — that of the session's first
`write_artifact` success response — so only artifacts written since then that have no
`commit_refs` are returned, whoever wrote them.

**Example**

- Given three artifacts: A written before the session (ULID < since_ulid), B written during
  the session with no `commit_refs`, and C written during the session with
  `commit_refs=["prev"]`; when `propose_commit_links` is called with `since_ulid` set to a
  value between A's and B's ULID, then only B appears in the proposed list.

Source: FR-31; AC-37; p9-t31a-setting-up-arkeology-skill R35

### R2 — Without `since_ulid`, all own-scope artifacts are scanned regardless of age

When `propose_commit_links` is called without `since_ulid`, the system retrieves all own-scope
artifacts from the vector index without a time-range filter. An agent runs the tool this way to
find every artifact in scope that has never been linked to a commit.

**Example**

- Given several own-scope artifacts, some with `commit_refs` and some without, when
  `propose_commit_links` is called without `since_ulid`, then all artifacts without
  `commit_refs` are returned regardless of age.

### R3 — Candidates are deduplicated by `artifact_id`, then kept only when `commit_refs` is absent or empty

When results are assembled, the system deduplicates by `artifact_id` (multiple section vectors
per artifact are common) and then keeps only artifacts whose `commit_refs`, read from the
artifact's S3 object annotation, is absent or empty — never from a vector's metadata, whose copy is
capped and per-section. A failed read fails the whole call; no candidate is ever treated as
unlinked because its read failed. Candidate filtering is client-side — no `$exists` operator is
needed or added. When no artifact qualifies, `proposed` is an empty list — not an error.

**Example**

- Given no unlinked artifacts in the time range, when `propose_commit_links` returns, then
  `proposed` is an empty list — not an error.
- Given own-scope artifacts that all have `commit_refs`, when called without `since_ulid`,
  then `proposed` is empty.

Source: p12-t58-commit-refs-cap-references-removal R9, R10

### R4 — Only own-scope artifacts are proposed; foreign-scope artifacts are excluded

Scope is own-scope only: the filter uses `{"scope": {"$eq": settings.write_prefix}}`. Foreign-scope
artifacts never appear in `proposed` — only own-scope artifacts can be commit-linked.

**Example**

- Given a foreign-scope tier-3 shared artifact that has no `commit_refs`, when
  `propose_commit_links` is called, then it does NOT appear in `proposed` — only own-scope
  artifacts can be commit-linked.

## 3. Rules — Response

### R5 — Each proposed entry carries the artifact's identity and a human-readable write time

When an artifact qualifies, the system includes in its entry: `artifact_id`, `title`, `type`,
`last_edited_ulid`, and `last_edited_at` (ISO-8601 datetime string derived from the ULID via
`python-ulid`). The proposal does not say who wrote an artifact, so the operator tells their own
work from a teammate's by its title, type and write time.

**Example**

- Given an artifact with a known `last_edited_ulid`, when it appears in `proposed`, then
  the entry includes a `last_edited_at` field containing a non-empty ISO-8601 datetime
  string derived from that ULID.

### R6 — An artifact without `last_edited_ulid` is a candidate only when no `since_ulid` is given, with null timestamps

When `last_edited_ulid` is absent from an artifact's metadata and the call carries no `since_ulid`,
the artifact is still a candidate for linking, and the system includes `last_edited_ulid: null` and
`last_edited_at: null` in its entry. When the call carries `since_ulid`, the in-process bound of R1
excludes the artifact, as `s3.artifact` § Storage Shape states for an absent token.

**Examples**

- Given an own-scope artifact D with no `commit_refs` and no `last_edited_ulid`, when
  `propose_commit_links` is called without `since_ulid`, then D appears with
  `last_edited_ulid: null` and `last_edited_at: null`.
- Given the same artifact D, when `propose_commit_links` is called with any `since_ulid`, then D
  does not appear.

### R7 — A successful call returns the proposed list and the supplied `commit_sha`

When `propose_commit_links` completes successfully, the system returns
`{"proposed": [...], "commit_sha": "<the supplied commit_sha>"}`.

### R8 — A failure returns one structured error code

When `propose_commit_links` fails, the system returns one structured error, never a raw
exception, with the code `arkeology.tools.propose_commit_links` § propose_commit_links lists under
Errors: `credential_error` for a `CredentialError` from any store read, `annotation_unavailable`
when a candidate's annotation read finds the annotation store unavailable or access to it denied,
and `internal_error` for any other failure. A candidate whose object is gone is not a failure: it
is dropped silently, as that contract and `p12-t58-commit-refs-cap-references-removal` R10
state.

**Example**

- Given a credential failure during the vector scan, when `propose_commit_links` returns,
  then it returns `{"error": "credential_error", "message": ...}` — not a raw exception.

### R9 — `propose_commit_links` makes no writes

When `propose_commit_links` is called, the system makes no writes — it is strictly read-only.

## 4. Boundaries

**Always:**
- Scope is own-scope only: filter uses `{"scope": {"$eq": settings.write_prefix}}`.
- Candidate filtering (checking for empty `commit_refs`) is client-side, on each candidate's
  annotation — no `$exists` operator is needed or added.
- The tool receives `settings`, `s3`, `vectors`, and `bedrock` as injected dependencies;
  `s3` reads each candidate's `commit_refs` annotation and `bedrock` is unused.
- The tool function is registered on `_app` in `server.py` via its `register_tools()`
  call.

**Ask First:**
- Nothing — all constraints are defined.

**Never:**
- Do not write to S3 or vector store — this is a read-only tool.
- Do not include foreign-scope artifacts in `proposed` — they cannot be linked by the
  caller's scope.
- Do not add a `$exists` operator to `filter.py` — client-side filtering of `commit_refs`
  absence is sufficient and simpler.

## 5. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_propose_commit_links.py` | Create | Written first (Red) |
| `src/arkeology/tools/propose_commit_links.py` | Create | Written after unit tests (Green) |
| `src/arkeology/server.py` | Modify | Register `propose_commit_links` on `_app` |

### Contracts

- `docs/contracts/modules/arkeology.tools.propose_commit_links.md` § propose_commit_links — the tool's signature, eligibility source, own-scope rule, response and errors (R1–R9).
- `docs/contracts/data/s3-annotations.artifact.md` § read_link_annotations and § Not-Found Semantics — the per-candidate `commit_refs` read that decides eligibility, and a gone object versus a failed read (R3).
- `docs/contracts/data/s3vectors.artifact.md` § Storage Shape and § Compatibility Guarantees — the `scope` and `last_edited_ulid` keys the scan reads, and the `since_ulid` bound applied in process, never by the index (R1, R2, R4, R6).
- `docs/contracts/data/s3.artifact.md` § Storage Shape — the absent `last_edited_ulid` that the `since_ulid` bound excludes (R6).

### Testing Approach

**TDD cycle (unit):** write `test_tools_propose_commit_links.py` → fail → implement
`tools/propose_commit_links.py` → pass → register in `server.py`.

**`test_tools_propose_commit_links.py` — unit tests (moto + FakeBedrockClient):**

Use the `aws_mock`, `s3_client`, and `vectors_client_with_index` fixtures from
`tests/unit/conftest.py`. Pre-seed the vector index using `vectors.put_vectors_batch`
directly (no need to call `write_artifact`; the test controls metadata precisely), and set a
linked artifact's `commit_refs` annotation, which is what eligibility is decided from.

Seed data: at least four artifacts:
- `artifact-A`: own-scope, `last_edited_ulid = ULID_LOW`, `commit_refs = []` (absent)
- `artifact-B`: own-scope, `last_edited_ulid = ULID_HIGH`, `commit_refs = []` (absent)
- `artifact-C`: own-scope, `last_edited_ulid = ULID_HIGH`, `commit_refs` annotation `["abc123"]` (linked)
- `artifact-D`: foreign-scope, tier 3 shared, no `commit_refs`

Where `ULID_LOW < ULID_MID < ULID_HIGH` are deterministic ULID strings (hardcoded in
tests for reproducibility — generate them once from the ULID library and paste as
constants).

Test cases:
- `since_ulid = ULID_MID` → only `artifact-B` in proposed (A excluded by time, C linked, D
  foreign-scope).
- `since_ulid` absent → both `artifact-A` and `artifact-B` in proposed (C linked, D
  foreign).
- All artifacts have `commit_refs` → `proposed` is `[]`.
- Response shape: each entry has `artifact_id`, `title`, `type`, `last_edited_ulid`,
  `last_edited_at` (non-null for entries with ULID, null for entries without).
- Artifact with no `last_edited_ulid` in metadata, called without `since_ulid` → entry has
  `last_edited_ulid: null`, `last_edited_at: null`, still included as a candidate; the same
  artifact called with any `since_ulid` → absent from `proposed` (R6).
- `list_vectors_by_metadata` raises `CredentialError` → `credential_error`.
- `get_vectors` raises `CredentialError` → `credential_error`.
