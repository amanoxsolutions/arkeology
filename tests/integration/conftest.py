"""Integration test configuration.

Loads the project's .env file into os.environ before any integration fixture
runs so that os.environ["AWS_REGION"] etc. are available without having to
export variables into the shell manually.

Priority (highest first):
    1. Real shell env vars — never overridden by this file.
    2. Values in .env — loaded here if the shell var is absent.

If required variables are still missing after loading .env, tests are
skipped with a clear message rather than failing with a raw KeyError.

WHY a session fixture instead of pytest_configure:
    pytest_configure is a global hook — it runs for every session regardless
    of which tests are collected.  Loading .env there would contaminate unit
    tests when running ``uv run pytest -m 'not integration'`` because
    BEDROCK_EMBEDDING_DIMENSIONS (and other vars) would be set from .env
    before unit-test fixtures build their Settings() objects.
    A session-scoped autouse fixture in this conftest only executes when at
    least one test in tests/integration/ is collected, leaving unit tests
    with a clean environment.
"""

import os
import uuid
from pathlib import Path

import pytest

from cairn_mcp.config import Settings

# .env lives at the project root — three levels up from this file:
# tests/integration/conftest.py → tests/integration → tests → project root
_ENV_FILE = Path(__file__).parent.parent.parent / ".env"

# Vars that every concrete client needs; used to gate all integration tests.
_REQUIRED_VARS = ["AWS_REGION", "ARTIFACT_BUCKET", "VECTORS_BUCKET", "VECTORS_INDEX"]


@pytest.fixture(scope="session", autouse=True)
def load_env() -> None:
    """Load .env into os.environ once per session before any integration test runs.

    python-dotenv is always available as a dependency of pydantic-settings.
    override=False means real shell env vars always win.

    Being session-scoped and autouse means it runs exactly once per session
    — but ONLY when tests from this directory are collected.  Unit-only runs
    are unaffected.
    """
    if _ENV_FILE.exists():
        from dotenv import load_dotenv

        load_dotenv(_ENV_FILE, override=False)


@pytest.fixture(autouse=True)
def require_env_vars(load_env: None) -> None:
    """Skip the test if any required env var is missing.

    Gives a clear skip reason instead of a raw KeyError in the fixture setup.
    Explicitly depends on load_env to guarantee .env is loaded first.
    """
    missing = [v for v in _REQUIRED_VARS if not os.environ.get(v)]
    if missing:
        pytest.skip(
            f"Integration test skipped — set these variables in .env or your shell: "
            f"{', '.join(missing)}"
        )


# ---------------------------------------------------------------------------
# Spec 14 — Unique run ID for integration test isolation
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def unique_run_id() -> str:
    """Session-scoped unique run ID to isolate parallel test runs.

    Appended to artifact titles/IDs so concurrent test sessions do not
    collide. Format: 8-char hex from uuid4.
    """
    return uuid.uuid4().hex[:8]


@pytest.fixture(scope="session")
def integration_settings(load_env: None) -> Settings:
    """Session-scoped Settings constructed from environment after load_env runs."""
    return Settings()
