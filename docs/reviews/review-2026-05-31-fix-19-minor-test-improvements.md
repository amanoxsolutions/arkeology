---
type: code_review
title: Review Fix 19 — Minor Test Quality Improvements
description: Code review spec for ten test suite issues — mutable module-level dicts, in-place handler clearing, missing docstrings, untested fake filter behaviour, inconsistent pytestmark style, and missing integration client conftest.
tags: []
timestamp: 2026-05-31T00:00:00Z
okf_version: "0.1"
status: ready
references: []
authored:
  by: "developer"
  date: "2026-05-31"
revised:
  by: "developer"
  date: "2026-08-12"
---
# Review Fix 19 — Minor Test Quality Improvements

## Verification — 2026-08-12

Re-verified finding-by-finding against current `main`. Unlike fix-16/17/18/20, this one
is a mixed result: `f642725` (2026-05-31, same day as this review) implemented some
items but not all, and the four still-open items have never been picked up since — none
of them are hard-blocked, they simply were not part of that PR's scope and nothing
later touched them.

- **Resolved:** 4 of 10 — module docstrings added to test files; `os.environ` usage in
  integration client tests is now self-documenting via module docstrings; and one item
  (a dedicated `tests/integration/clients/conftest.py`) is superseded by a broader
  session-scoped `tests/integration/conftest.py` that loads `.env` for *all* integration
  tests, not just the clients subfolder.
- **Still valid (unchanged since the review, not yet done):** 4 — mutable `_BASE_*`
  test-constant dicts are still plain `dict`, never wrapped in `MappingProxyType`;
  `reset_root_logger` in `test_server.py` still calls `root.handlers.clear()` rather
  than `root.handlers = []`; `test_tools_write.py` (now ~4,000 lines) still has no
  growth comment near its test count; and the `kwargs_2` variable name in
  `test_tools_write.py` was never renamed to `kwargs_rewrite`.
- **No longer applicable:** 2 — `FakeVectorsClient` no longer exists (the hand-rolled
  fake was retired in favour of moto + `FakeBedrockClient` only, per a later test-infra
  migration; its filter behaviour is now covered by moto-backed
  `list_vectors_by_metadata`/`query_vectors` tests instead); and `_SOURCE_KWARGS` in
  `test_tools_freshness.py` no longer exists — replaced by parameterised factory
  functions that take `date` as an explicit required argument, which structurally
  prevents the "missing field" ambiguity this finding warned about.
- **Changed enough to need restating:** 1 — the `pytestmark` standardisation. The five
  `tests/integration/clients/*.py` files do use module-level `pytestmark =
  pytest.mark.integration` as specified, but the sixteen `tests/integration/test_tools_*.py`
  files were never converted — they still use a per-function `@pytest.mark.integration`
  decorator on every test (73 occurrences), and one file's docstring now documents this
  as the deliberate convention for that directory ("All tests are decorated with
  `@pytest.mark.integration`"). The inconsistency this finding flagged still exists, but
  it has hardened into two different documented within-directory conventions rather than
  one file being an outlier.

See inline `[Verified 2026-08-12 — …]` markers below and the "Items Resolved Since Last
Review" section at the end.

## Problem Statement

Ten small issues in the test suite reduce safety and readability: mutable module-level
dicts can leak state between tests; a `handlers.clear()` call mutates in place rather
than replacing; several test files lack module docstrings; `FakeVectorsClient.query()`
filter behaviour is untested; a large test file lacks a growth comment; a missing `date`
field in `_SOURCE_KWARGS` is unexplained; a misleading variable name obscures test
intent; integration tests directly use `os.environ` without explanation; `pytestmark`
style is inconsistent; and integration client tests lack a shared `conftest.py` for `.env`
loading.

## User Stories

### Story 1 — Fake filter logic is verified (P2)

**Acceptance criteria:**
- Given a `FakeVectorsClient` with two vectors where only one matches a filter, when
  `query()` is called with that filter, then only the matching vector is returned.
- Given a filter that matches no vectors, when `query()` is called, then an empty list
  is returned.

### Story 2 — Integration tests are consistently marked (P2)

**Acceptance criteria:**
- Given any integration test file, when `pytest --collect-only` is run, then every test
  in that file carries the `integration` mark — applied via module-level `pytestmark`.

### Story 3 — Integration client tests load `.env` automatically (P2)

**Acceptance criteria:**
- Given a `conftest.py` in `tests/integration/clients/`, when any client integration
  test is collected, then environment variables from `.env` are loaded without each test
  file calling `load_dotenv()` individually.

## Requirements

- WHEN `FakeVectorsClient.query()` is called with a filter that does not match a vector
  THE SYSTEM SHALL exclude that vector from results (verified by new unit tests).
  **[Verified 2026-08-12 — 🗑️ NO LONGER APPLICABLE.** `FakeVectorsClient` does not exist
  anywhere in `src/`. Per `AGENTS.md`'s testing conventions, S3 and S3 Vectors are now
  mocked exclusively via moto (`@mock_aws` / the `aws_mock` fixture), with
  `FakeBedrockClient` the only hand-rolled fake kept. Filter-match/no-match behaviour is
  covered instead by moto-backed tests such as
  `test_moto_query_vectors_extension.py::test_filter_expr_excludes_non_matching` and the
  `list_vectors_by_metadata` filter tests in `tests/unit/clients/test_vectors.py`. The
  underlying acceptance criteria (filter correctness is tested) is met — just not via
  the class this finding named, because that class was retired by later test-infra work.]
- WHEN integration tests are collected THE SYSTEM SHALL mark all tests with
  `pytest.mark.integration` via module-level `pytestmark = pytest.mark.integration`.
  **[Verified 2026-08-12 — 🔄 CHANGED ENOUGH TO NEED RESTATING.** `tests/integration/clients/*.py`
  (5 files) all use module-level `pytestmark = pytest.mark.integration`, matching this
  requirement exactly. `tests/integration/test_tools_*.py` (16 files) never adopted it —
  every test in those files still carries its own `@pytest.mark.integration` decorator
  (73 occurrences), and this is now stated as intentional in at least one file's
  docstring. Collection-time correctness is unaffected (every test still gets the mark
  either way), so this is a style/maintainability gap, not a broken test suite — but the
  "applied via module-level `pytestmark`" requirement is only half-satisfied on `main`.]
- WHEN `tests/integration/clients/conftest.py` loads `.env` THE SYSTEM SHALL use
  `python-dotenv` `load_dotenv()` so each client test file does not repeat it.
  **[Verified 2026-08-12 — ✅ RESOLVED, superseded by a broader fix.** No
  `tests/integration/clients/conftest.py` exists — instead, a session-scoped, autouse
  `load_env` fixture in `tests/integration/conftest.py` calls
  `load_dotenv(_ENV_FILE, override=False)` once for the *entire* integration suite
  (with a documented rationale for why it's a fixture rather than `pytest_configure`, to
  avoid contaminating unit-test runs). This covers the clients subfolder and every other
  integration test file, which is strictly more than this finding asked for. Not a
  regression.]
- WHEN mutable `_BASE_*` dicts are used as test constants THE SYSTEM SHALL be wrapped
  with `types.MappingProxyType` or replaced with fixtures to prevent cross-test mutation.
  **[Verified 2026-08-12 — ❌ STILL VALID.** Sixteen `_BASE_*`-prefixed module-level
  dicts remain plain, mutable `dict`/`dict[str, ...]` literals across the unit test
  suite (`test_tools_write.py`, `test_tools_purge.py`, `test_tools_archive.py`,
  `test_tools_delete.py`, `test_tools_synthesise.py`, `test_tools_list.py`,
  `test_tools_reconcile.py`, `test_tools_read.py`, `test_tools_link_metadata.py`,
  `test_tools_propose_commit_links.py`, `test_failure_log.py`). None are wrapped in
  `MappingProxyType`; none were replaced with fixtures. No evidence of an actual
  cross-test mutation bug having occurred, but the risk this finding described is
  unchanged.]
- WHEN `reset_root_logger` clears handlers THE SYSTEM SHALL use `logger.handlers = []`
  not `handlers.clear()`.
  **[Verified 2026-08-12 — ❌ STILL VALID.** The `reset_root_logger` autouse fixture in
  `tests/unit/test_server.py` still does `root.handlers.clear(); root.setLevel(...)`,
  unchanged from the pattern this finding flagged.]

## Boundaries

**Never:**
- Change test behavior — this spec is test quality and readability only.
- Move integration client tests to a different location.
- Remove or alter any existing test assertion.

## Files to Touch

| File | Action | Notes |
|------|--------|-------|
| `tests/unit/clients/test_fake_vectors.py` | Modify | Add filter pass and filter reject tests (Red — new tests, no implementation change needed) |
| `tests/conftest.py` (or shared helper) | Modify | Replace `handlers.clear()` with `logger.handlers = []` in `reset_root_logger` (m27) |
| `tests/integration/clients/conftest.py` | Create | Load `.env` via `python-dotenv`; no other logic |
| `tests/unit/test_tools_write.py` | Modify | Wrap `_BASE_*` dicts in `MappingProxyType`; rename `kwargs_2` → `kwargs_rewrite` with comment; add growth comment near test count |
| `tests/unit/test_tools_freshness.py` | Modify | Add `# date provided per-test` comment to `_SOURCE_KWARGS` |
| `tests/integration/` (all files) | Modify | Standardise to module-level `pytestmark = pytest.mark.integration`; remove per-function decorators |
| `tests/integration/clients/` (all files) | Modify | Add comment explaining direct `os.environ` use is intentional |
| Various unit test files missing docstrings | Modify | Add one-line module docstring to each file that lacks one (m28) |

**[Verified 2026-08-12 — per-row status:**
- `test_tools_write.py` row (`_BASE_*` → `MappingProxyType`; `kwargs_2` → `kwargs_rewrite`;
  growth comment) — ❌ **STILL VALID, none applied.** `_BASE_WRITE_KWARGS` is still a
  plain `dict`; `kwargs_2` is still named `kwargs_2` (3 occurrences); no growth comment
  exists near the test count. The file has grown to ~4,000 lines since the review,
  making the growth-comment gap more relevant, not less.
- `test_tools_freshness.py` row (`_SOURCE_KWARGS` comment) — 🗑️ **NO LONGER APPLICABLE.**
  `_SOURCE_KWARGS` does not exist in the current file; metadata is now built by
  parameterised factory functions (e.g. `_synthesis_meta(...)`) that take `date` as an
  explicit required argument on every call site, which removes the ambiguity a comment
  would have explained.
- `tests/integration/` standardisation row — 🔄 **CHANGED ENOUGH TO NEED RESTATING**, see
  the `pytestmark` requirement marker above — only the `clients/` subset was done.
- `tests/integration/clients/` `os.environ` comment row — ✅ **RESOLVED, differently.**
  No inline per-line comment was added next to each `os.environ[...]` access, but every
  client integration test file's module docstring now has an explicit "Environment
  variables required:" block naming each var, which serves the same "why is this
  accessed directly" documentation purpose this finding wanted.
- Missing module docstrings row (m28) — ✅ **RESOLVED.** Every `tests/unit/*.py` and
  `tests/unit/clients/*.py` file has a module docstring except `__init__.py` files,
  which aren't test modules.]

## Testing Approach

This spec is test-quality only. The TDD rule applies to the one behavioural gap:
`FakeVectorsClient.query()` filter correctness.

**`tests/unit/clients/test_fake_vectors.py` additions (these ARE the implementation
gate — `FakeVectorsClient` already exists; new tests exercise untested paths):**
- Two vectors loaded into fake; filter matches only vector A → `query()` returns only
  vector A.
- Filter matches neither vector → `query()` returns empty list.
- No filter passed → `query()` returns all vectors up to `top_k`.

**All other changes in this spec are refactors or comments:** confirm all existing unit
and integration tests pass before and after each change. Run `pytest tests/unit/ -q` and
verify zero regressions.

**`pytestmark` standardisation:** after editing all integration files, run
`pytest tests/integration/ --collect-only -q` and confirm every collected test carries
the `integration` mark.

## Open Questions

*(none — all behaviour is defined)*

## Items Resolved Since Last Review

<!-- changelog-style: prepend new entries -->
- 2026-08-12 — **Re-verification pass (developer): 4 of 10 items resolved, 4 still
  valid (never applied), 2 no longer applicable.** Unlike the other four fix-16/17/18/20
  specs in this batch, `f642725` ("production hardening — 20 review-fix specs",
  2026-05-31) only partially implemented this one, and nothing since has picked up the
  rest. **Resolved:** module docstrings added to unit test files (m28); `.env` loading
  centralised in a session-scoped `tests/integration/conftest.py` fixture covering the
  whole integration suite (broader than the clients-only conftest this spec asked for);
  `os.environ` usage in integration client tests is now explained via each file's module
  docstring "Environment variables required" block; and the five `clients/*.py`
  integration files do use module-level `pytestmark`. **Still valid, unaddressed:**
  `_BASE_*` test-constant dicts remain unwrapped plain `dict`s across ~11 test files
  (cross-test-mutation risk unchanged); `reset_root_logger` in `test_server.py` still
  uses `root.handlers.clear()`; `test_tools_write.py` (now ~4,000 lines, up from its
  size at review time) still lacks a growth comment near its test count; and its
  `kwargs_2` variable was never renamed to `kwargs_rewrite`. **No longer applicable:**
  `FakeVectorsClient` was retired in a later test-infra migration to moto-only mocking
  (filter behaviour is now covered by moto-backed tests instead); `_SOURCE_KWARGS` in
  `test_tools_freshness.py` was replaced by parameterised factory functions that require
  an explicit `date` argument, removing the ambiguity a comment would have addressed.
  **Needs restating:** the `pytestmark` standardisation only ever covered the
  `tests/integration/clients/` subfolder — the sixteen `tests/integration/test_tools_*.py`
  files still use per-function `@pytest.mark.integration` decorators, now documented as
  that directory's own (different) convention rather than an oversight. No code was
  changed by this re-verification pass; the four still-valid items remain real,
  low-priority cleanup opportunities for a future pass.
