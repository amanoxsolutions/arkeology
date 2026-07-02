"""Unit tests for tests.integration._isolation (C-4 fix — run-scoped test isolation).

Exercises the isolation helpers with moto-mocked S3 / S3 Vectors clients so the
teardown logic is verified without touching real AWS. See AGENTS.md Testing
Conventions: mock AWS with moto, and query_vectors/list_vectors_by_metadata use
the shared matches_filter implementation exercised by the moto extension in
tests/unit/conftest.py.
"""

import os

from pytest_mock import MockerFixture

from cairn_mcp.clients.s3 import S3ClientImpl
from cairn_mcp.clients.vectors import VectorsClientImpl
from tests.integration._isolation import (
    RunScope,
    apply_run_scope_env,
    generate_run_scope,
    teardown_run_scope,
)

_UNIT_VEC = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]


class _NoOpS3:
    """Stand-in S3 client that does nothing — isolates vector-side assertions."""

    def list_objects(self, prefix: str) -> list[str]:
        return []

    def delete_object(self, key: str) -> None:
        pass


class _NoOpVectors:
    """Stand-in vectors client that does nothing — isolates S3-side assertions."""

    def list_vectors_by_metadata(self, filter_expr: dict) -> list[str]:
        return []

    def delete_vectors(self, keys: list[str]) -> None:
        pass


# ---------------------------------------------------------------------------
# generate_run_scope
# ---------------------------------------------------------------------------


def test_generate_run_scope_produces_disjoint_prefixes_rooted_at_integration_tests() -> None:
    """write_prefix and foreign_prefix share a run_id, both rooted at 'integration-tests/'."""
    scope = generate_run_scope()

    assert scope.write_prefix == f"integration-tests/{scope.run_id}"
    assert scope.foreign_prefix == f"integration-tests/{scope.run_id}-foreign"
    assert scope.write_prefix != scope.foreign_prefix
    # Neither prefix is a string-prefix of the other's sibling artifacts —
    # write_prefix + "/" must not match anything under foreign_prefix.
    assert not scope.foreign_prefix.startswith(scope.write_prefix + "/")


def test_generate_run_scope_is_unique_per_call() -> None:
    """Two calls produce different run IDs — no collision across concurrent runs."""
    scope_a = generate_run_scope()
    scope_b = generate_run_scope()

    assert scope_a.run_id != scope_b.run_id
    assert scope_a.write_prefix != scope_b.write_prefix


# ---------------------------------------------------------------------------
# apply_run_scope_env
# ---------------------------------------------------------------------------


def test_apply_run_scope_env_overrides_operator_values() -> None:
    """apply_run_scope_env replaces operator-configured WRITE_PREFIX/READ_PREFIXES.

    Uses an injected plain dict rather than the real os.environ so this test
    cannot leak state into unrelated tests running later in the same session.
    """
    env = {"WRITE_PREFIX": "team/project", "READ_PREFIXES": "team-b,team-c"}
    scope = RunScope(
        run_id="01test",
        write_prefix="integration-tests/01test",
        foreign_prefix="integration-tests/01test-foreign",
    )

    apply_run_scope_env(scope, env=env)

    assert env["WRITE_PREFIX"] == "integration-tests/01test"
    assert env["READ_PREFIXES"] == "integration-tests/01test-foreign"


def test_apply_run_scope_env_sets_values_when_operator_vars_absent() -> None:
    """apply_run_scope_env works even when the operator never set these vars."""
    env: dict[str, str] = {}
    scope = RunScope(
        run_id="01test2",
        write_prefix="integration-tests/01test2",
        foreign_prefix="integration-tests/01test2-foreign",
    )

    apply_run_scope_env(scope, env=env)

    assert env["WRITE_PREFIX"] == "integration-tests/01test2"
    assert env["READ_PREFIXES"] == "integration-tests/01test2-foreign"


def test_apply_run_scope_env_defaults_to_os_environ() -> None:
    """Without an explicit env mapping, apply_run_scope_env falls back to os.environ.

    apply_run_scope_env mutates os.environ directly (by design — the real
    conftest fixture needs the override to persist for the whole session), so
    monkeypatch cannot auto-revert it here; the original values are restored
    manually in the finally block instead.
    """
    original_write = os.environ.get("WRITE_PREFIX")
    original_read = os.environ.get("READ_PREFIXES")
    scope = RunScope(
        run_id="01test3",
        write_prefix="integration-tests/01test3",
        foreign_prefix="integration-tests/01test3-foreign",
    )

    try:
        apply_run_scope_env(scope)

        assert os.environ["WRITE_PREFIX"] == "integration-tests/01test3"
        assert os.environ["READ_PREFIXES"] == "integration-tests/01test3-foreign"
    finally:
        _restore_env_var("WRITE_PREFIX", original_write)
        _restore_env_var("READ_PREFIXES", original_read)


def _restore_env_var(name: str, original_value: str | None) -> None:
    if original_value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = original_value


# ---------------------------------------------------------------------------
# teardown_run_scope — S3
# ---------------------------------------------------------------------------


def test_teardown_deletes_s3_objects_under_prefix_only(s3_client: S3ClientImpl) -> None:
    """teardown_run_scope removes objects under the run prefixes but leaves siblings intact."""
    scope = RunScope(
        run_id="01abc",
        write_prefix="integration-tests/01abc",
        foreign_prefix="integration-tests/01abc-foreign",
    )
    s3_client.put_object(f"{scope.write_prefix}/artifact-one.md", "content-1", {})
    s3_client.put_object(f"{scope.foreign_prefix}/artifact-two.md", "content-2", {})
    # A sibling prefix that merely shares the run_id as a string-prefix must survive —
    # guards against the false-prefix-match bug AGENTS.md warns about.
    s3_client.put_object("integration-tests/01abc-unrelated/artifact-three.md", "content-3", {})
    s3_client.put_object("artifacts/untouched.md", "content-4", {})

    teardown_run_scope(s3_client, _NoOpVectors(), scope)

    remaining = s3_client.list_objects("")
    assert f"{scope.write_prefix}/artifact-one.md" not in remaining
    assert f"{scope.foreign_prefix}/artifact-two.md" not in remaining
    assert "integration-tests/01abc-unrelated/artifact-three.md" in remaining
    assert "artifacts/untouched.md" in remaining


def test_teardown_s3_list_failure_does_not_raise(
    s3_client: S3ClientImpl, mocker: MockerFixture
) -> None:
    """A failure listing S3 objects is swallowed — teardown is best-effort, never fatal."""
    scope = generate_run_scope()
    mocker.patch.object(s3_client, "list_objects", side_effect=Exception("boom"))

    teardown_run_scope(s3_client, _NoOpVectors(), scope)


# ---------------------------------------------------------------------------
# teardown_run_scope — Vectors
# ---------------------------------------------------------------------------


def test_teardown_deletes_vectors_matching_scope_metadata_only(
    vectors_client_8: VectorsClientImpl,
) -> None:
    """teardown_run_scope removes vectors whose 'scope' metadata is the run prefix."""
    scope = generate_run_scope()
    vectors_client_8.put_vector(
        f"{scope.write_prefix}/artifact-one",
        _UNIT_VEC,
        {"artifact_id": f"{scope.write_prefix}/artifact-one", "scope": scope.write_prefix},
    )
    vectors_client_8.put_vector(
        f"{scope.foreign_prefix}/artifact-two",
        _UNIT_VEC,
        {"artifact_id": f"{scope.foreign_prefix}/artifact-two", "scope": scope.foreign_prefix},
    )
    vectors_client_8.put_vector(
        "artifacts/untouched",
        _UNIT_VEC,
        {"artifact_id": "artifacts/untouched", "scope": "artifacts"},
    )

    teardown_run_scope(_NoOpS3(), vectors_client_8, scope)

    remaining = vectors_client_8.list_vectors_by_metadata({})
    assert f"{scope.write_prefix}/artifact-one" not in remaining
    assert f"{scope.foreign_prefix}/artifact-two" not in remaining
    assert "artifacts/untouched" in remaining


def test_teardown_vectors_list_failure_does_not_raise(
    vectors_client_8: VectorsClientImpl, mocker: MockerFixture
) -> None:
    """A failure listing vectors is swallowed — teardown is best-effort, never fatal."""
    scope = generate_run_scope()
    mocker.patch.object(vectors_client_8, "list_vectors_by_metadata", side_effect=Exception("boom"))

    teardown_run_scope(_NoOpS3(), vectors_client_8, scope)


def test_teardown_no_vectors_to_delete_skips_delete_call(
    vectors_client_8: VectorsClientImpl, mocker: MockerFixture
) -> None:
    """When no vectors match the scope, delete_vectors is never called (nothing to chunk)."""
    scope = generate_run_scope()
    spy = mocker.spy(vectors_client_8, "delete_vectors")

    teardown_run_scope(_NoOpS3(), vectors_client_8, scope)

    spy.assert_not_called()
