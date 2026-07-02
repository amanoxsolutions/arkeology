"""Run-scoped isolation for the integration test suite (review finding C-4).

The integration suite must be safe to run against ANY configured store,
including one already holding real team memory. The operator-configured
``WRITE_PREFIX`` / ``READ_PREFIXES`` from the project ``.env`` are never used
by the suite — they are replaced unconditionally with an ephemeral prefix
pair rooted at ``integration-tests/<run-id>`` before any ``Settings()`` is
constructed (see ``tests/integration/conftest.py``).

Session-end teardown (best-effort) deletes every S3 object and vector written
under those prefixes so a test run leaves no trace behind, whether it passed
or failed.
"""

from __future__ import annotations

import logging
import os
from collections.abc import MutableMapping
from dataclasses import dataclass

from ulid import ULID

from cairn_mcp.clients.interfaces import S3ClientInterface, VectorsClientInterface

logger = logging.getLogger(__name__)

_RUN_PREFIX_ROOT = "integration-tests"


@dataclass(frozen=True)
class RunScope:
    """Ephemeral prefix pair generated for one integration test session.

    Attributes:
        run_id: Lowercase ULID unique to this test session.
        write_prefix: Own-scope prefix — becomes ``WRITE_PREFIX``.
        foreign_prefix: A second, disjoint prefix — becomes the sole entry in
            ``READ_PREFIXES`` so cross-scope tests have an ephemeral foreign
            scope available instead of an operator-configured real one.
    """

    run_id: str
    write_prefix: str
    foreign_prefix: str


def generate_run_scope() -> RunScope:
    """Build a fresh :class:`RunScope` with a new, unique run ID."""
    run_id = str(ULID()).lower()
    return RunScope(
        run_id=run_id,
        write_prefix=f"{_RUN_PREFIX_ROOT}/{run_id}",
        foreign_prefix=f"{_RUN_PREFIX_ROOT}/{run_id}-foreign",
    )


def apply_run_scope_env(scope: RunScope, env: MutableMapping[str, str] | None = None) -> None:
    """Override ``WRITE_PREFIX`` / ``READ_PREFIXES`` in the given environment mapping.

    Must be called after ``.env`` has been loaded and before any
    ``Settings()`` is constructed — every ``Settings()`` built afterwards (by
    any test file's own fixtures) sees these run-scoped values, never the
    operator-configured ones.

    Args:
        scope: The run scope whose prefixes replace the operator's.
        env: Mapping to mutate; defaults to ``os.environ``. Tests inject a
            plain ``dict`` here to exercise this function without touching
            the real process environment (and therefore without leaking
            state into unrelated tests running later in the same session).
    """
    target = env if env is not None else os.environ
    target["WRITE_PREFIX"] = scope.write_prefix
    target["READ_PREFIXES"] = scope.foreign_prefix


def teardown_run_scope(
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    scope: RunScope,
) -> None:
    """Best-effort delete everything written under this run's prefixes.

    Deletes S3 objects and vectors under both ``write_prefix`` and
    ``foreign_prefix``. Every step is isolated in its own try/except — a
    failure in one does not prevent the others from being attempted. This is
    session-end cleanup, not a test assertion; it never raises.

    Args:
        s3: S3 client scoped to the artifact bucket.
        vectors: S3 Vectors client scoped to the vectors index.
        scope: The run scope to tear down.
    """
    for prefix in (scope.write_prefix, scope.foreign_prefix):
        _delete_s3_objects_under_prefix(s3, prefix)
        _delete_vectors_for_scope(vectors, prefix)


def _delete_s3_objects_under_prefix(s3: S3ClientInterface, prefix: str) -> None:
    """Delete every S3 object under ``prefix + "/"``.

    The trailing slash avoids the false-prefix-match bug AGENTS.md warns
    about for scope checks (``prefix`` alone would also match a sibling like
    ``"{prefix}-foreign"``).
    """
    try:
        keys = s3.list_objects(f"{prefix}/")
    except Exception:
        logger.warning("Teardown: failed to list S3 objects under %r", prefix, exc_info=True)
        return
    for key in keys:
        try:
            s3.delete_object(key)
        except Exception:
            logger.warning("Teardown: failed to delete S3 object %r", key, exc_info=True)


def _delete_vectors_for_scope(vectors: VectorsClientInterface, prefix: str) -> None:
    """Delete every vector whose ``scope`` metadata equals ``prefix`` exactly.

    Mirrors the ``{"scope": {"$eq": write_prefix}}`` filter already used by
    ``purge.py`` and ``_search_helper.py`` — exact equality, no prefix
    matching needed since ``scope`` is always stored as the literal prefix.
    """
    try:
        keys = vectors.list_vectors_by_metadata({"scope": {"$eq": prefix}})
    except Exception:
        logger.warning("Teardown: failed to list vectors for scope %r", prefix, exc_info=True)
        return
    if not keys:
        return
    try:
        vectors.delete_vectors(keys)
    except Exception:
        logger.warning("Teardown: failed to delete vectors for scope %r", prefix, exc_info=True)
