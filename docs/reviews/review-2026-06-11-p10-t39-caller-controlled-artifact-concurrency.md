---
type: code_review
title: P10-T39 — Caller-Controlled artifact_concurrency on write_artifacts and migrate_artifacts
description: Code review for Phase 10 Task 39, which replaced the ARTIFACT_CONCURRENCY server env var with a per-call artifact_concurrency parameter on write_artifacts and migrate_artifacts.
tags: []
timestamp: 2026-06-11T00:00:00Z
okf_version: "0.1"
status: done
references: []
authored:
  by: "developer"
  date: "2026-06-11"
revised:
  by: ""
  date: ""
---

# P10-T39 — Caller-Controlled `artifact_concurrency` on `write_artifacts` and `migrate_artifacts`

## Description

Code review for Phase 10 Task 39. The task replaced the `ARTIFACT_CONCURRENCY` server
env var with a per-call `artifact_concurrency: int = 3` parameter on `write_artifacts`
and `migrate_artifacts`, updated the migration skill with batching and a concurrency
recommendation step, and removed the field from `Settings`. 77 unit tests pass; ruff
and mypy are clean.

## Spec and ADRs Consulted

- `docs/specs/p10-t39-caller-controlled-artifact-concurrency.md`

## Files Reviewed

- `src/arkeology/tools/write_artifacts.py`
- `src/arkeology/tools/migrate_artifacts.py`
- `src/arkeology/config.py`
- `tests/unit/test_tools_write_artifacts.py`
- `tests/unit/test_tools_migrate_artifacts.py`
- `tests/unit/test_config.py`
- `skills/migrating-to-arkeology/SKILL.md`

## Findings

### Spec Alignment

All requirements and acceptance criteria verified against the spec. One spec
self-contradiction noted (see Minor finding M2) — the implementation follows the
prescribed SKILL.md text, which is correct.

### Critical

None.

### Major

**M1 — E13 semaphore spy is non-discriminating (`test_tools_migrate_artifacts.py`)**

Test E13 ("dry_run=False, artifact_concurrency=5 → write_artifacts semaphore=5") exists
to prove that `migrate_artifacts` forwards the effective value to `write_artifacts`.
However, the chosen value (5) collides with the default `SECTION_CONCURRENCY` (also 5,
from `write.py` line 302). `_write_artifact_inner` creates `asyncio.Semaphore(settings.section_concurrency)`
**per artifact**; with 3 artifacts and `section_concurrency=5`, the spy sees `[5, 5, 5, 5]`
regardless of whether the artifact-concurrency semaphore was 5 (forwarded correctly) or 3
(write_artifacts falling back to its own default). The test passes either way because
`5 in semaphore_values` is satisfied by the section semaphores alone.

Fix: use an `artifact_concurrency` value that differs from `section_concurrency`. For
example, `artifact_concurrency=7` is in-range, differs from both the default (3) and the
section semaphore default (5), and produces `semaphore_values = [7, 5, 5, 5]`. Then
`assert 7 in semaphore_values` correctly fails if forwarding is broken (breaking would
produce `[3, 5, 5, 5]`).

```python
# Current — non-discriminating
result = await migrate_artifacts(..., dry_run=False, artifact_concurrency=5)
assert 5 in semaphore_values  # section semaphores also produce 5 — passes even if broken

# Fixed
result = await migrate_artifacts(..., dry_run=False, artifact_concurrency=7)
assert 7 in semaphore_values  # only the artifact-concurrency semaphore produces 7
```

### Minor

**m1 — In-place mutation of `write_result` in `migrate_artifacts.py` (line 209)**

```python
if warning is not None:
    write_result["warning"] = warning
return write_result
```

This mutates the dict returned by `write_artifacts` directly. The invariant that prevents
a double-warning bug — `effective` is always in `[1, 15]`, so `write_artifacts` never adds
its own warning — is not locally visible from this code. If that invariant ever breaks
(e.g., a future change passes a raw value), the migration warning silently overwrites the
write-phase warning.

Prefer a non-mutating form that is safe regardless of what `write_artifacts` returns:

```python
if warning is not None:
    return {**write_result, "warning": warning}
return write_result
```

**m2 — Spec acceptance criteria for Story 4 contradicts prescribed SKILL.md text for 3.A3**

Story 4 AC states: "For 3.A3 and 3.B3 (description or dry-run phase): explanation
references Nova Lite concurrent calls." However, the spec's own SKILL.md changes section
prescribes text for 3.A3 that only references the Titan embedding ceiling — no mention of
Nova Lite, which is correct because 3.A3 is a `dry_run=False` write phase using agent-
provided descriptions. The implementation correctly follows the prescribed text, not the
ambiguous AC. This is a spec authoring inconsistency, not a code defect. No code change
needed, but the spec AC should be tightened on the next revision cycle.

### Nits

- **`"ARTIFACT_CONCURRENCY"` remains in `clean_env` fixture** (`test_config.py` line 32).
  This is intentional and correct — the new `test_artifact_concurrency_env_var_is_silently_ignored`
  test relies on the fixture clearing the env var before setting it explicitly. No change
  needed.

## Recommendations

1. **Fix E13** (major) — change `artifact_concurrency=5` to `artifact_concurrency=7` (or
   any value ≠ `section_concurrency=5`) and update the assertion to `assert 7 in semaphore_values`.
   This is a one-line test change that makes the forwarding proof correct.

2. **Address m1** (minor, low risk) — use `{**write_result, "warning": warning}` instead of
   in-place mutation at `migrate_artifacts.py` line 209. Improves robustness against future
   changes without altering behaviour.

3. **Everything else is clean.** Clamping logic, warning placement, double-warning
   isolation, `asyncio.Semaphore(0)` safety, `ARTIFACT_CONCURRENCY` removal, `SECTION_CONCURRENCY`
   preservation, `write_artifact` unchanged, SKILL.md batching steps, stdio-workaround
   notes, and config `hasattr` test — all correct.

## Items Resolved Since Last Review

N/A — first review.
