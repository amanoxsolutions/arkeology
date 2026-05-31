---
type: feature-spec
feature: review-fix-19-minor-test-improvements
created: 2026-05-31
status: ready
---

# Review Fix 19 — Minor Test Quality Improvements

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
- WHEN integration tests are collected THE SYSTEM SHALL mark all tests with
  `pytest.mark.integration` via module-level `pytestmark = pytest.mark.integration`.
- WHEN `tests/integration/clients/conftest.py` loads `.env` THE SYSTEM SHALL use
  `python-dotenv` `load_dotenv()` so each client test file does not repeat it.
- WHEN mutable `_BASE_*` dicts are used as test constants THE SYSTEM SHALL be wrapped
  with `types.MappingProxyType` or replaced with fixtures to prevent cross-test mutation.
- WHEN `reset_root_logger` clears handlers THE SYSTEM SHALL use `logger.handlers = []`
  not `handlers.clear()`.

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
