---
type: Spec
id: p10-t39-caller-controlled-artifact-concurrency
title: T39 — Caller-Controlled artifact_concurrency on write_artifacts and migrate_artifacts
description: Spec to replace the ARTIFACT_CONCURRENCY env var with a per-call artifact_concurrency parameter on write_artifacts and migrate_artifacts, with capping and warning behaviour.
tags: []
status: stable
okf_version: "0.2"
sources:
  - resource: docs/brainstorming/brainstorming-2026-06-10-migrate-artifacts-concurrency.md
    title: migrate_artifacts — Caller-Controlled Concurrency Parameter
    last_modified: 2026-06-11T00:00:00Z
  - resource: docs/planning-artifacts/requirements.md
    title: Arkeology — Requirements
    last_modified: 2026-09-24T00:00:00Z
  - resource: docs/contracts/modules/arkeology.tools.write_artifacts.md
    title: arkeology.tools.write_artifacts
  - resource: docs/contracts/modules/arkeology.tools.migrate_artifacts.md
    title: arkeology.tools.migrate_artifacts
  - resource: .docs/reviews/architecture-review-2026-11-15-arkeology-phases-9-10-12.md
    title: "Architecture review — Arkeology, plan phases 9, 10 and 12"
generated:
  by: "axians-architect/unknown"
  at: 2026-06-11T00:00:00Z
revised:
  by: "axians-architect/claude-opus-5-5"
  at: 2026-11-15T20:19:59Z
verified:
  - by: "human:mlnrt"
    at: 2026-10-07T08:09:33Z
  - by: "axians-architect/claude-fable-5-2"
    at: 2026-11-15T20:45:07Z
---

# T39 — Caller-Controlled `artifact_concurrency` on `write_artifacts` and `migrate_artifacts`

## TL;DR

Replace the `ARTIFACT_CONCURRENCY` server env var with an optional per-call
`artifact_concurrency` parameter (default 3) on `write_artifacts` and `migrate_artifacts`.
Out-of-range values are never rejected: above 15 is capped to 15, below 1 is substituted
with the default 3; both produce a top-level `concurrency_warning` field in the response. The migration
skill passes a computed `artifact_concurrency` without asking the operator, names it in its progress
line, and sends 3.B3 and 3.B5 calls in fixed batches of 15 descriptors, giving the operator a
progress update after every batch.

## 1. Problem Statement

`ARTIFACT_CONCURRENCY` is a server-level env var that requires a server restart to change.
For one-time bulk operations like migration, this is the wrong friction point: the operator
cannot right-size concurrency for the description phase (Nova Lite) versus the write phase
(Titan embeddings × `SECTION_CONCURRENCY`) without editing their MCP client config and
restarting. A per-call parameter lets the skill pass a different value for each sequential
call (`dry_run=True` then `dry_run=False`) with no configuration change.

All five user stories this spec covers — high concurrency for the description phase;
conservative concurrency forwarded to the write phase; direct callers of `write_artifacts`
controlling concurrency per call; the operator seeing the concurrency value each migration call
uses, without being asked for one; and the `ARTIFACT_CONCURRENCY` env var being ignored at startup
and runtime — are P1.

## 2. Rules — `artifact_concurrency` on `write_artifacts`

### R1 — `write_artifacts` takes an optional per-call `artifact_concurrency` and never rejects a call on it

When `write_artifacts` is called, the optional `artifact_concurrency` parameter decides how many
artifacts are processed concurrently for that call, regardless of any environment variable. The
tool never rejects a call on the concurrency parameter alone: out-of-range handling is symmetric,
every case proceeds with all writes, and the effective value (after any substitution) is what
the `asyncio.Semaphore` receives.

| `artifact_concurrency` supplied | Effective concurrency | Response |
|---|---|---|
| Omitted | Default 3 | No warning |
| 1 ≤ `artifact_concurrency` ≤ 15 | At most that many artifacts concurrently, via `asyncio.Semaphore` | No warning |
| > 15 | Capped to 15 | Top-level `"concurrency_warning"` field identifying the requested value and the effective cap |
| < 1 | The default (3) substituted | Top-level `"concurrency_warning"` field identifying the supplied value and the substituted value |

**Example**

- Given an agent calling `write_artifacts` directly, when it passes `artifact_concurrency=10`,
  then the server uses a semaphore of 10 for that call regardless of any environment variable:
  `write_artifacts(artifact_concurrency=10, artifacts=[...])` processes up to 10 artifacts
  concurrently.
- `write_artifacts(artifact_concurrency=20, ...)` caps to 15, writes all artifacts
  successfully, and returns `{"results": [...], "concurrency_warning": "..."}` with a non-empty
  warning string identifying the requested and effective values.
- `write_artifacts(artifact_concurrency=0, ...)` substitutes the default (3), writes all
  artifacts successfully, and returns a `concurrency_warning` field.
- `write_artifacts()` with no parameter behaves as before with effective concurrency of 3.

### R9 — Both MCP tool registrations declare `artifact_concurrency` and forward it unchanged

When `write_artifacts` or `migrate_artifacts` is called over MCP, the tool registered on the server
declares the optional `artifact_concurrency` parameter, with default 3, and passes the caller's
value unchanged to the tool function, which applies R1–R4 to it. The registration never clamps,
substitutes or drops the value itself.

**Example**

- Given an MCP call to `write_artifacts` with `artifact_concurrency=10`, then the tool function
  receives 10; with the parameter omitted, it receives 3; with 20, it receives 20 and caps it per
  R1.

Source: FR-25; FR-26

## 3. Rules — `artifact_concurrency` on `migrate_artifacts`

### R2 — `migrate_artifacts` applies the same substitution rules as `write_artifacts`

When `migrate_artifacts` is called with `artifact_concurrency` > 15 or < 1, the system applies
the same substitution rules as `write_artifacts` and includes a `"concurrency_warning"` field in the
response. The effective value (after any substitution) is what is forwarded from
`migrate_artifacts` to `write_artifacts`.

**Example**

- `migrate_artifacts(dry_run=True, artifact_concurrency=20)` caps to 15, runs successfully,
  returns enriched descriptors, and includes a non-empty `concurrency_warning` field in the response.

### R3 — On `dry_run=True`, the effective value bounds concurrent Nova Lite description calls

When `migrate_artifacts(dry_run=True)` is called, the system uses the effective
`artifact_concurrency` to bound concurrent Nova Lite description calls.

**Example**

- **Given** a migration with 30 files, **when** the skill calls
  `migrate_artifacts(dry_run=True, artifact_concurrency=15, ...)`, **then** the server runs
  up to 15 Nova Lite description calls concurrently and returns enriched descriptors.
- `migrate_artifacts(dry_run=True, artifact_concurrency=15)` uses a description semaphore
  of 15 — verified by spy on `asyncio.Semaphore` or by call-count assertion.

### R4 — On `dry_run=False`, the effective value is forwarded to `write_artifacts`

When `migrate_artifacts(dry_run=False)` is called, the system forwards the effective
`artifact_concurrency` to `write_artifacts`.

**Example**

- **Given** a migration with 30 files, **when** the skill calls
  `migrate_artifacts(dry_run=False, artifact_concurrency=3)`, **then** the server forwards
  `artifact_concurrency=3` to `write_artifacts` so at most 3 artifacts write concurrently.
- `migrate_artifacts(dry_run=False, artifact_concurrency=3)` results in `write_artifacts`
  being called with an effective semaphore of 3 — verified by spy on `asyncio.Semaphore`.

## 4. Rules — `ARTIFACT_CONCURRENCY` removed

### R5 — The `ARTIFACT_CONCURRENCY` env var is ignored at startup and runtime

When `ARTIFACT_CONCURRENCY` is present in the environment, the system ignores it; the
`Settings` class does not define a field for it. The env var is removed entirely — the server
is not yet deployed anywhere, so there is no migration burden.

**Example**

- **Given** `ARTIFACT_CONCURRENCY=10` is present in the environment, **when** the server
  starts, **then** no startup error is raised and the value has no effect on any tool call.
- `Settings(...)` does not raise `ValidationError` when `ARTIFACT_CONCURRENCY` is set
  (the field is absent from `Settings`; the env var is silently ignored via `extra="ignore"`).
- `write_artifacts()` with no explicit `artifact_concurrency` uses 3, not the env var.

## 5. Rules — Migration skill

### R6 — The skill passes a computed `artifact_concurrency` without asking, and names it in its progress line

When the migrating-to-arkeology skill calls `migrate_artifacts` — in 3.A3, 3.B3 and 3.B5 — it
passes `artifact_concurrency = min(file_count, 15)` without asking the operator, and names the
value in the progress line it reports for that call. It never stops to ask for a concurrency value
and gives no quota explanation. When the operator states a value of their own, at any point, the
skill passes that value on every later call of the migration; the server applies R1 and R2 to it.

**Example**

- Given 95 pending files, when 3.B5 runs, then the skill asks nothing about concurrency, passes
  `artifact_concurrency=15`, and reports progress such as "Written 15 of 95 files
  (artifact_concurrency 15)".
- Given the operator says to use 5 during the migration, then every later call passes
  `artifact_concurrency=5`, and each batch still holds 15 descriptors (R7).

**Why:** the server never rejects a value — it clamps and warns — and the computed value is the
same formula every time, so a question before each call asks the operator to tune something they
have no basis to answer differently.

Source: FR-23; FR-26

### R7 — In 3.B3 and 3.B5 the skill sends fixed batches of 15 descriptors

When the migrating-to-arkeology skill executes 3.B3 or 3.B5, it splits the pending descriptor list
into batches of 15 descriptors, whatever `artifact_concurrency` is, and calls `migrate_artifacts`
once per batch, reporting progress to the operator after each batch. This batching is an explicit
**stdio workaround**. When Streamable HTTP + SSE is adopted, the batching loop is removed and
replaced with a single call per phase; `artifact_concurrency` retains its server-side semaphore
role.

**Example**

- Given 40 pending descriptors, when 3.B5 runs, then `migrate_artifacts` is called three times,
  with 15, 15 and 10 descriptors, and progress is reported after each call.

**Why:** 15 is the server's own ceiling on `artifact_concurrency` (R1), so a batch never holds more
artifacts than one call may process at once; keeping it fixed means a lower concurrency the
operator supplies makes each call slower without changing the progress steps.

Source: FR-23

### R8 — The skill's step text for 3.A3, 3.B3 and 3.B5

The migrating-to-arkeology skill's `SKILL.md` carries this text:

**Step 3.A3** — before the `migrate_artifacts` call:

> Use `artifact_concurrency = min(file_count, 15)` — or the operator's own value, if they gave
> one — without asking. Name it when reporting the result (e.g. "Migrated 8 files
> (artifact_concurrency 8)").

**Step 3.B3** — replace the single `migrate_artifacts(dry_run=True)` call with a batch loop:

> Use `artifact_concurrency = min(file_count, 15)` — or the operator's own value, if they gave
> one — without asking.
>
> Split the pending descriptor list into batches of 15. For each batch:
> call `migrate_artifacts(dry_run=True, artifact_concurrency=…, descriptors=batch)`,
> write the returned descriptions back to `ARKEOLOGY_IMPORT.yaml` as `description`,
> and report progress naming the value (e.g. "Described 15 of 95 files
> (artifact_concurrency 15)"). Continue until all batches are processed.
>
> *(stdio workaround — when Streamable HTTP + SSE is available, replace this loop with a
> single call that receives per-description SSE events; the artifact_concurrency parameter
> remains unchanged.)*

**Step 3.B5** — replace the single `migrate_artifacts(dry_run=False)` call with a batch loop:

> Use `artifact_concurrency = min(file_count, 15)` — or the operator's own value, if they gave
> one — without asking.
>
> Split the pending descriptor list into batches of 15. For each batch:
> call `migrate_artifacts(dry_run=False, artifact_concurrency=…, descriptors=batch)`,
> update each entry's `status` and `artifact_id` in `ARKEOLOGY_IMPORT.yaml` from its result
> (the mapping is `p9-t30-write-artifacts` R16's), and report progress naming the value (e.g.
> "Written 15 of 95 files (artifact_concurrency 15)"). Continue until all batches are processed.
>
> *(stdio workaround — same as 3.B3; remove the loop when SSE is available.)*

## 6. Boundaries

**Always:**
- `SECTION_CONCURRENCY` env var is unchanged — server configuration, default 5.
- Out-of-range handling is symmetric: > 15 → cap to 15 + warning; < 1 → substitute
  default 3 + warning; in-range → no warning; omitted → default 3, no warning. The tool
  never rejects a call on the concurrency parameter alone.
- Effective value (after any substitution) is what the semaphore receives and what is
  forwarded from `migrate_artifacts` to `write_artifacts`.
- `write_artifact` (single-artifact write) is unchanged — `artifact_concurrency` is added
  to bulk tools only.
- The skill batching in 3.B3 and 3.B5 (batches of 15 descriptors, independent of
  `artifact_concurrency`) is an explicit **stdio workaround**. When Streamable HTTP + SSE is
  adopted, the batching loop is removed and replaced with a single call per phase;
  `artifact_concurrency` retains its server-side semaphore role.

**Ask First:**
- None.

**Never:**
- Do not add `artifact_concurrency` to `write_artifact` (single write).
- Do not rename or remove `SECTION_CONCURRENCY` or any other existing env var.
- Do not add a compound `artifact_concurrency × section_concurrency ≤ ceiling` validation
  in this task — note it as a future concern in the module docstring and move on.
- Do not have the migration skill ask for a concurrency value or explain the embedding quota
  before a call (R6) — revisit if migrations at the computed value are throttled by Bedrock.

## 7. For the developer agent

### Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/test_tools_write_artifacts.py` | Modify | Replace `monkeypatch.setenv("ARTIFACT_CONCURRENCY", ...)` with `artifact_concurrency=` parameter; add cap+warn test (> 15); add substitute+warn test (< 1); confirm no warning when in-range |
| `src/arkeology/tools/write_artifacts.py` | Modify | Add `artifact_concurrency: int = 3` to public + inner signatures; clamp to [1, 15] at top of `_inner`, adding `"concurrency_warning"` to response dict when clamped; semaphore uses effective value |
| `tests/unit/test_tools_migrate_artifacts.py` | Modify | Replace `monkeypatch.setenv("ARTIFACT_CONCURRENCY", ...)` with parameter; add > 15 cap+warn test; add < 1 substitute+warn test; add forward-to-write-phase test |
| `src/arkeology/tools/migrate_artifacts.py` | Modify | Add `artifact_concurrency: int = 3`; clamp to [1, 15] + warn; use effective value for description semaphore; pass effective value to `_write_artifacts` call |
| `tests/unit/test_config.py` | Modify | Remove `ARTIFACT_CONCURRENCY` test blocks; add one test confirming `ARTIFACT_CONCURRENCY` in env raises no `ValidationError` |
| `src/arkeology/config.py` | Modify | Remove `ARTIFACT_CONCURRENCY` field, `validate_artifact_concurrency` validator, and `artifact_concurrency` property |
| `tests/unit/test_server.py` | Modify | R9: an MCP call to each of `write_artifacts` and `migrate_artifacts` forwards a supplied `artifact_concurrency` unchanged, forwards 3 when it is omitted, and forwards an out-of-range value unclamped (`test_write_artifacts_mcp_layer_forwards_artifact_concurrency` and its siblings) |
| `src/arkeology/server.py` | Modify | R9: the `write_artifacts` and `migrate_artifacts` tool definitions declare `artifact_concurrency: int = 3` and forward it to the tool function |
| `plugins/arkeology/skills/migrating-to-arkeology/SKILL.md` | Modify | R8's text in 3.A3, 3.B3 and 3.B5: the computed `artifact_concurrency` passed without asking and named in each progress line, no quota explanation, and batches of 15 descriptors in 3.B3 and 3.B5 |

### Contracts

- `docs/contracts/modules/arkeology.tools.write_artifacts.md` § write_artifacts — `artifact_concurrency`, its clamp and the top-level `concurrency_warning` (R1, R9).
- `docs/contracts/modules/arkeology.tools.migrate_artifacts.md` § migrate_artifacts — the same parameter on the migration tool, bounding description calls and forwarded to the write phase (R2–R4, R6–R9).

### Testing Approach

TDD — each test file is written and run (Red) before the implementation file it gates.

#### Round 1 — `write_artifacts` parameter

`tests/unit/test_tools_write_artifacts.py` (modify → Red) →
`src/arkeology/tools/write_artifacts.py` (modify → Green)

Tests to add or update:

- **Update C3** (was `ARTIFACT_CONCURRENCY=1`): change `monkeypatch.setenv(...)` to
  `artifact_concurrency=1` keyword argument; remove the monkeypatch call entirely.
- **Update C5** (was `ARTIFACT_CONCURRENCY=2`): same change.
- Add: `artifact_concurrency=15` → all artifacts written; `written=True` for every entry;
  no `"concurrency_warning"` key in response.
- Add: `artifact_concurrency=20` → all artifacts written; response contains `"concurrency_warning"`
  key mentioning 20 and 15; semaphore constructed with 15 (spy confirms).
- Add: `artifact_concurrency=0` → all artifacts written; response contains `"concurrency_warning"`
  key mentioning 0 and 3 (default substituted); semaphore constructed with 3 (spy confirms).
- Add: omitted `artifact_concurrency` → semaphore constructed with 3; no `"concurrency_warning"` key.

#### Round 2 — `migrate_artifacts` parameter

`tests/unit/test_tools_migrate_artifacts.py` (modify → Red) →
`src/arkeology/tools/migrate_artifacts.py` (modify → Green)

Tests to add or update:

- **Update E8** (was `ARTIFACT_CONCURRENCY=2`): change to `artifact_concurrency=2` parameter.
- Add: `artifact_concurrency=20` with missing descriptions → descriptions generated,
  enriched descriptors returned, `"concurrency_warning"` key present; `bedrock.invoke_text_model`
  called with semaphore of 15.
- Add: `artifact_concurrency=0` with missing descriptions → descriptions generated,
  enriched descriptors returned, `"concurrency_warning"` key present; semaphore of 3 used.
- Add: `dry_run=True, artifact_concurrency=5` → description semaphore constructed with 5;
  no `"concurrency_warning"` key.
- Add: `dry_run=False, artifact_concurrency=5` → `write_artifacts` semaphore constructed
  with 5 (spy on `asyncio.Semaphore` inside `_write_artifacts_inner`).

#### Round 3 — config cleanup

`tests/unit/test_config.py` (modify → Red) → `src/arkeology/config.py` (modify → Green)

- Remove the `ARTIFACT_CONCURRENCY` test block (tests T26 / Z1 label — default, custom,
  zero-invalid, negative-invalid).
- Add: `monkeypatch.setenv("ARTIFACT_CONCURRENCY", "10")` then construct `Settings(...)`
  → no `ValidationError`; confirm `hasattr(settings, "artifact_concurrency")` is `False`
  (or `getattr(settings, "artifact_concurrency", "NOT_SET") == "NOT_SET"`).


#### Round 4 — MCP registration (R9)

`tests/unit/test_server.py` (modify → Red) → `src/arkeology/server.py` (modify → Green)

- For each of `write_artifacts` and `migrate_artifacts`: a supplied value reaches the tool
  function unchanged; an omitted one arrives as 3; 20 arrives as 20 (the clamp is the tool
  function's, R1).

#### SKILL.md changes (no unit tests)

The `SKILL.md` step text for 3.A3, 3.B3 and 3.B5 is stated in R8; it has no unit tests.
