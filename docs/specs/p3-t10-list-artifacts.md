---
type: Spec
id: p3-t10-list-artifacts
title: T10 — List Artifacts Tool
description: Feature spec for the list_artifacts MCP tool that provides metadata-only browsing of the artifact store with filter-driven retrieval and cross-scope gate enforcement.
tags: []
status: stable
okf_version: "0.2"
sources:
  - resource: docs/planning-artifacts/requirements.md
    title: Arkeology — Requirements
  - resource: docs/architecture-decisions/adr-2026-09-14-malformed-persisted-data-policy.md
    title: How Arkeology Treats Malformed and Ambiguous Persisted Data
  - resource: .docs/reviews/architecture-review-2026-11-15-arkeology-phases-9-10-12.md
    title: "Architecture review — Arkeology, plan phases 9, 10 and 12"
generated:
  by: "axians-architect/unknown"
  at: 2026-05-30T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-15T18:56:17Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
---

# T10 — List Artifacts Tool

## TL;DR

`list_artifacts` gives agents a metadata-only, filter-driven view across the artifact store, with no
semantic ranking, for browsing what exists when they do not yet know what to ask for. It returns one
record per artifact from vector metadata alone, defaults to active artifacts, and applies the same
cross-scope gate as search and read: own-scope artifacts unrestricted, foreign-scope artifacts limited
to tier 3 shared. An artifact's link fields, `commit_refs` and `references`, come only when the caller
asks for them, because they are the one part of an entry that costs a read per artifact.

## 1. Problem Statement

Semantic search is query-driven: an agent must already know what to ask for. But when starting a new
task or doing housekeeping, the agent may need to browse what exists — all artifacts for a project,
everything tagged with a feature, all archived docs from last month. An agent starting a session wants
to see everything stored for the current project before deciding where to focus; an agent reviewing
the authentication module wants only code reviews tagged with `auth`; a microservices team that
subscribes to the platform scope should see platform ADRs in their listing. The list tool provides a
metadata-only view across the artifact store with filter-driven retrieval and no semantic ranking. It
applies the same cross-scope gate as search and read: own-scope artifacts are unrestricted;
foreign-scope artifacts are limited to tier 3 shared.

All four stories this spec covers are priority P1.

## 2. Rules — Filters and status

### R1 — Filter-driven listing from the vector index

When `list_artifacts` is called, the system queries the vector index for all artifacts matching the
supplied filters (type, tags, team, project, tier, status); if no filters are supplied, it returns all
active artifacts visible to this deployment. Filters are evaluated server-side using the metadata
stored in the vector index. When no artifact matches, an empty list is returned — not an error.

**Example**

- Given several active artifacts written with the same `project`, when `list_artifacts` is called with
  the `project` filter, then all matching artifacts appear in the response with their metadata and
  description — no content.
- Given artifacts of various types and tags, when `list_artifacts` is called with `type="code_review"`
  and `tags=["auth"]`, then only artifacts matching both constraints are returned.
- Given no artifacts matching the combined filter, when `list_artifacts` returns, then an empty list is
  returned — not an error.

Source: none

### R2 — A listing that does not ask for link fields reads vector metadata only

When `list_artifacts` is called without asking for link fields, everything its response carries
comes from vector metadata: the call makes its one vector-index query and no S3 request of any kind
— no object content, no object metadata, no object annotation. Asking for link fields adds the reads
R11 states.

Source: R11

### R3 — `status` defaults to `"active"`

When no `status` filter is provided, the system defaults to `status="active"`, excluding archived
artifacts; the caller must explicitly pass `status="inactive"` to see archived artifacts.

**Example**

- Given a mix of active and archived artifacts in the same project, when `list_artifacts` is called
  without a `status` override, then only active artifacts are returned.
- Given the same project with archived artifacts, when `list_artifacts` is called with
  `status="inactive"`, then only inactive artifacts are returned.

Source: none

### R4 — `status="all"` is the one all-inclusive sentinel

When `list_artifacts` is called with `status="all"`, the value is recognised as an explicit
all-inclusive sentinel: the status clause is omitted entirely, so both active and inactive own-scope
(and eligible foreign-scope) artifacts are returned. Any other literal value (including the default
`"active"`) still filters normally; `"all"` is the only recognised sentinel.

Rationale: it closes a bug in `arkeology_studio`'s browser UI, where the "All" status filter option
sent `value=""`, which `loadList` then omitted from the call arguments — falling through to the
server's `status="active"` default and making "All" unreachable.

Source: none

### R5 — The `"all"` sentinel belongs to the `status` parameter, not to `list_artifacts`

The `status="all"` sentinel is not a property of `list_artifacts` — it is a property of the `status`
parameter, and every query-shaped tool that exposes one honours it identically. `search_artifacts`
honours it as `docs/specs/p2-t8-search-artifacts.md`'s `> **Revised (2026-08-12)**` note states. The
convention, and its obligation on any future tool exposing `status`, is recorded in
`docs/architecture-decisions/adr-2026-08-12-status-all-sentinel-convention.md`.

Source: docs/architecture-decisions/adr-2026-08-12-status-all-sentinel-convention.md

## 3. Rules — Cross-scope gate

### R6 — Foreign-scope artifacts are listed only when tier 3 and shared

When cross-scope results are assembled, the system includes foreign-scope artifacts only if `tier=3`
AND `visibility="shared"`; own-scope artifacts are never gated. The cross-scope gate uses the same
`startswith(scope + "/")` logic as read and search.

**Example**

- Given a tier 3 shared artifact in a foreign scope, when `list_artifacts` is called without scope
  filters, then the artifact appears in the response.
- Given a tier 2 artifact in a foreign scope, when `list_artifacts` is called, then the artifact is
  excluded from results.
- Given a tier 3 hidden artifact in a foreign scope, when `list_artifacts` is called, then the artifact
  is excluded from results.

Source: none

### R7 — A foreign-scope entry's `references` drop what the reader could not read

When link fields are requested (R11), each `list_artifacts` entry carries the `references` field, and
a foreign-scope entry's `references` list drops any entry the requesting reader could not independently read (i.e. not itself tier 3 shared) —
batched into a single additional query across the whole result page rather than one lookup per
artifact per reference, to avoid an N×M cost. Own-scope entries are never filtered. Full semantics:
`docs/specs/p12-t46-references-field.md`'s forward-pointer note; rationale: ADR-012's "Cross-scope
reference visibility" section.

Source: p12-t46, ADR-012

## 4. Rules — Response

### R8 — One record per artifact

When multiple section vectors for the same artifact match the filter, the system deduplicates by
`artifact_id` and returns exactly one record per artifact.

Source: none

### R9 — Records carry metadata and description only

When `list_artifacts` returns successfully, each artifact's record carries `artifact_id`, `type`,
`team`, `project`, `tier`, `date`, `status`, `title`, `visibility`, `tags`, `author_role`,
`description`. No `content` field: results contain metadata and description only — no full content.

Source: NFR-02

### R11 — `list_artifacts` returns `commit_refs` and `references` only when the caller asks for them

⚠️ Hard to reverse: every caller of `list_artifacts` is written against the default entry shape, and
the meaning of an absent key — "not fetched", never "none" — is what a caller branches on.

`list_artifacts` takes `include_links`, default false (its type and place in the signature:
`arkeology.tools.list` § list_artifacts).

- **False:** no entry carries `commit_refs` or `references` — the keys are absent, never `[]` — and
  the call reads no S3 object annotation and makes no reference-readability lookup.
- **True:** every entry carries both, read from the artifact's S3 object annotations, `[]` when the
  artifact has none. A failed or
  ambiguous annotation read fails the whole call with a structured error — never an entry reporting
  `[]`. An artifact whose object turns out to be gone is omitted from the page and counted under
  `skipped_deleted_count`.
- **False, gone object:** with nothing read per artifact, the call cannot see that an object is gone.
  An artifact whose object was deleted while its section vectors remain is listed until
  `reconcile_index` prunes those vectors; `read_artifact` on it returns `not_found`.
- The `commit_refs` filter works identically either way, and `read_artifact` returns both fields on
  every successful read without being asked.

**Example**

- Given an own-scope artifact written with `commit_refs=["abc1234"]` and
  `references=["team-a/payments/adr-use-postgres-abc12345.md"]`, when `list_artifacts` is called
  with no arguments, then its entry has neither a `commit_refs` nor a `references` key, and no
  annotation is read for any artifact on the page. When it is called with `include_links=True`,
  then its entry carries `commit_refs: ["abc1234"]` and the same `references`.
- Given an artifact written with no link fields, when `list_artifacts` is called with
  `include_links=True`, then its entry carries `commit_refs: []` and `references: []`.
- Given a page of three artifacts where the annotation read of one raises
  `AnnotationUnavailableError`, when `list_artifacts` is called with `include_links=True`, then the
  call returns `annotation_unavailable`; called without it, the same page lists all three.
- Given an artifact whose object was deleted while its vectors remain, when `list_artifacts` is
  called without `include_links`, then the artifact is listed; with `include_links=True`, it is
  omitted and `skipped_deleted_count` is 1.

**Why:** The two fields live only in S3 object annotations, so carrying them costs two annotation
reads per listed artifact, and no consumer of an ordinary listing uses them: the
`arkeology://artifacts` index shows identifier, title, type and description, and the Studio browser
gets an artifact's links through `read_artifact`. An absent key rather than `[]` keeps "not fetched" distinguishable from "has
none", the distinction the rule against degrading a failed link read to empty exists to protect.

Source: FR-28, AC-34, FR-51, AC-56; adr-2026-09-14-malformed-persisted-data-policy D6

## 5. Rules — Errors

### R10 — Credential errors return a structured error

When a `CredentialError` is raised — for example a credential failure during the vector scan —
`list_artifacts` returns a structured error, never a raw exception.

Source: none

## 6. Boundaries

**Always:**
- The tool receives `settings`, `s3` (used only for the annotation reads of R11), `vectors`, and
  `bedrock` (unused) as injected dependencies.

**Ask First:**
- Nothing — all constraints are defined.

**Never:**
- Do not fetch S3 object content or S3 object metadata for the list response — all needed data is in
  vector metadata — and read object annotations only when link fields are requested (R11).
- Do not return more than one record per `artifact_id` even if multiple section vectors match the
  filter.
- Link fields on every listing by default — revisit if a consumer of ordinary listings comes to need
  them on every entry.

## 7. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_list.py` | Create | Written first (Red) |
| `src/arkeology/tools/list.py` | Create | Written after unit tests (Green) |
| `tests/integration/test_tools_list.py` | Create | Written before integration wiring |
| `src/arkeology/server.py` | Modify | Register `list_artifacts` tool on `_app` |
| `tests/unit/test_tools_list.py` | Modify | R11 tests — Red first. Existing assertions that every entry carries `commit_refs` / `references`, or that a gone object is counted, move under `include_links=True` |
| `src/arkeology/tools/list.py` | Modify | Add `include_links: bool = False`; when false, skip the per-artifact annotation reads and the reference-readability lookup and leave both keys off every entry |
| `tests/unit/test_server.py` | Modify | The `list_artifacts` wrapper forwards `include_links` — Red first |
| `src/arkeology/server.py` | Modify | Add `include_links: bool = False` to the `list_artifacts` wrapper, its docstring, and the call it forwards |
| `src/arkeology/resources.py` | Modify | The `arkeology://schema/artifact` text says the `commit_refs` field `list_artifacts` returns shows the complete list; qualify it with `include_links=True` |
| `SERVER-REFERENCE.md` | Modify | `list_artifacts` row: document `include_links`, and that the returned `commit_refs` comes only with it |

### Contracts

- `modules/arkeology.tools.list.md` § list_artifacts — `include_links`, the entry shape with and
  without it, and which errors only the opted-in call can return.

### Testing Approach

**TDD cycle A (unit):** write `test_tools_list.py` first → fail → implement `tools/list.py` → unit
tests pass.

**TDD cycle B (integration):** write integration tests first → fail → wire tool → pass.

**`test_tools_list.py` — unit tests (FakeVectorsClient, no S3 or Bedrock calls):**

Seed the fake vector index with vectors covering: own-scope active tier 2, own-scope active tier 3
shared, own-scope inactive tier 2, own-scope active tier 2 with type `code_review` and feature tag
`auth`, foreign-scope active tier 3 shared, foreign-scope active tier 2, foreign-scope active tier 3
hidden. Each artifact has multiple section vectors to verify deduplication.

Default behaviour:
- No filters → only own-scope and foreign-scope tier 3 shared active artifacts returned.
- `status` defaults to `"active"` → inactive artifacts absent from results.
- `status="inactive"` override → only inactive artifacts returned.

Filter combinations:
- `type="code_review"` → only code reviews.
- `tags=["auth"]` → only artifacts with `"auth"` tag.
- `type="code_review"` + `tags=["auth"]` → intersection.
- `team="platform"` → only platform artifacts.
- `project="infra"` → only infra project artifacts.
- `tier=3` → only tier 3 artifacts.
- No matching artifacts → empty list returned, no error.

Deduplication:
- Two section vectors for the same `artifact_id` → one record in results.
- Correct fields present: artifact_id, type, team, project, tier, date, status, title, visibility,
  tags, author_role, description. No `content` field.
- `tags` in response is a list, not a comma-separated string.

Cross-scope gate:
- Foreign-scope tier 3 shared → included.
- Foreign-scope tier 2 → excluded.
- Foreign-scope tier 3 hidden → excluded.

Credential failure:
- `list_vectors_by_metadata` raises `CredentialError` → structured error response.
- `get_vectors` raises `CredentialError` → structured error response.

**TDD cycle C (R11) — each test file before the implementation file it gates:**

1. `tests/unit/test_tools_list.py` → `src/arkeology/tools/list.py`:
   - No `include_links` → no entry has `commit_refs` or `references`; a spy on the S3 client's
     annotation read records zero calls; no reference-readability query is issued.
   - `include_links=True` → every entry carries both, `[]` for an artifact with none; foreign-scope
     `references` filtered as R7.
   - `include_links=True` and one annotation read raising `AnnotationUnavailableError` →
     `annotation_unavailable`; the same page without `include_links` lists every artifact.
   - `include_links=True` and one read raising `CredentialError` → `credential_error`.
   - An artifact whose object is deleted but whose vectors remain → listed without `include_links`;
     omitted with `skipped_deleted_count: 1` under `include_links=True`.
   - `commit_refs=["abc1234"]` filter → same matches with and without `include_links`.
2. `tests/unit/test_server.py` → `src/arkeology/server.py`: the wrapper forwards `include_links`,
   default false.
3. `src/arkeology/resources.py` schema text and `SERVER-REFERENCE.md`, after both cycles are green.

**`tests/integration/test_tools_list.py` — integration tests (`@pytest.mark.integration`):**

- Write 2 artifacts; list with no filters → both appear.
- Write artifact then archive it; list with default filter → archived artifact absent; list with
  `status="inactive"` → archived artifact present.
- Write artifacts with different types; list with type filter → correct subset returned.
- Non-existent filter → empty list, no error.
