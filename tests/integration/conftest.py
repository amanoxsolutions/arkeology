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

RUN-SCOPED ISOLATION:
    The suite must be safe to run against ANY configured store — .env still
    supplies AWS credentials and resource names (bucket/index/region), but
    the operator's WRITE_PREFIX and READ_PREFIXES are never used. Immediately
    after .env is loaded, ``isolate_run_scope`` below overwrites both in
    os.environ with an ephemeral ``integration-tests/<run-id>`` pair (see
    ``tests/integration/_isolation.py``). Every ``Settings()`` built by any
    test file's own fixtures afterwards therefore sees only run-scoped
    values. Session-end teardown best-effort deletes everything written
    under those prefixes.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from arkeology.clients.s3 import S3ClientImpl
from arkeology.clients.vectors import VectorsClientImpl
from arkeology.config import Settings
from tests.integration._isolation import (
    RunScope,
    apply_run_scope_env,
    generate_run_scope,
    teardown_run_scope,
)

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
# Run-scoped isolation
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def isolate_run_scope(load_env: None) -> Iterator[RunScope]:
    """Override WRITE_PREFIX/READ_PREFIXES with an ephemeral run-scoped pair.

    Session-scoped and autouse: per pytest's fixture ordering rules, autouse
    fixtures run before explicitly-requested fixtures of the same scope, so
    this always overwrites the environment before any test file's own
    session-scoped ``settings()`` fixture constructs a ``Settings()`` object
    — exactly mirroring how ``load_env`` (also session-scoped autouse) already
    guarantees .env values are visible before Settings() is built. Explicitly
    depending on ``load_env`` makes that ordering a hard dependency rather
    than an incidental one.

    Teardown (best-effort) deletes every S3 object and vector written under
    both prefixes, using a dedicated client pair built from the post-override
    Settings — independent of whichever s3/vectors fixtures individual test
    files construct for themselves.
    """
    scope = generate_run_scope()
    apply_run_scope_env(scope)

    settings = Settings()
    s3 = S3ClientImpl(
        region=settings.aws_region,
        profile=settings.aws_profile,
        bucket=settings.artifact_bucket,
    )
    vectors = VectorsClientImpl(
        region=settings.aws_region,
        profile=settings.aws_profile,
        bucket=settings.vectors_bucket,
        index=settings.vectors_index,
    )

    yield scope

    teardown_run_scope(s3, vectors, scope)


@pytest.fixture(scope="session")
def integration_settings(load_env: None, isolate_run_scope: RunScope) -> Settings:
    """Session-scoped Settings constructed from environment after isolation is applied."""
    return Settings()
