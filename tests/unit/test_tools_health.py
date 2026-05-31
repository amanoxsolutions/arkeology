"""Unit tests for cairn_mcp.tools.health.

Tests health_check() using all three fakes (FakeS3, FakeVectors, FakeBedrock).
"""

import pytest

from cairn_mcp.clients.fakes.fake_bedrock import FakeBedrockClient
from cairn_mcp.clients.fakes.fake_s3 import FakeS3Client
from cairn_mcp.clients.fakes.fake_vectors import FakeVectorsClient
from cairn_mcp.tools.health import health_check
from tests.unit.conftest import _make_settings

# ---------------------------------------------------------------------------
# All healthy
# ---------------------------------------------------------------------------


async def test_all_healthy_all_ok(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All components healthy → all entries have status='ok'."""
    settings = _make_settings(monkeypatch, READ_PREFIXES="")
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)

    result = await health_check(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)

    assert result["s3"]["status"] == "ok"
    assert result["vectors"]["status"] == "ok"
    assert result["bedrock"]["status"] == "ok"
    assert result["write_prefix"]["status"] == "ok"


async def test_response_keys_present_no_read_prefixes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No read prefixes → response has s3, vectors, bedrock, write_prefix; no read_prefix keys."""
    settings = _make_settings(monkeypatch, READ_PREFIXES="")
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)

    result = await health_check(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)

    assert "s3" in result
    assert "vectors" in result
    assert "bedrock" in result
    assert "write_prefix" in result
    read_prefix_keys = [k for k in result if k.startswith("read_prefix:")]
    assert len(read_prefix_keys) == 0


async def test_two_read_prefixes_two_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two read prefixes configured → two 'read_prefix:...' keys in response."""
    settings = _make_settings(monkeypatch, READ_PREFIXES="team-a,team-b")
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)

    result = await health_check(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)

    read_prefix_keys = [k for k in result if k.startswith("read_prefix:")]
    assert len(read_prefix_keys) == 2


# ---------------------------------------------------------------------------
# Individual failures
# ---------------------------------------------------------------------------


async def test_s3_head_bucket_credential_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """head_bucket raises CredentialError → s3 entry is 'error'; others 'ok'."""
    settings = _make_settings(monkeypatch, READ_PREFIXES="")
    s3 = FakeS3Client()
    s3.set_credential_failure(True)
    vectors = FakeVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)

    result = await health_check(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)

    assert result["s3"]["status"] == "error"


async def test_vectors_describe_index_not_found_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """describe_index raises VectorIndexNotFoundError → vectors entry is 'error'; others 'ok'."""
    settings = _make_settings(monkeypatch, READ_PREFIXES="")
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=8, index_missing=True)
    bedrock = FakeBedrockClient(dimension=8)

    result = await health_check(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)

    assert result["vectors"]["status"] == "error"
    assert result["s3"]["status"] == "ok"


async def test_bedrock_embed_credential_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """embed raises CredentialError → bedrock entry is 'error'; others 'ok'."""
    settings = _make_settings(monkeypatch, READ_PREFIXES="")
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)
    bedrock.set_credential_failure(True)

    result = await health_check(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)

    assert result["bedrock"]["status"] == "error"
    assert result["s3"]["status"] == "ok"
    assert result["vectors"]["status"] == "ok"


async def test_write_prefix_put_object_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """put_object raises on write-prefix probe → write_prefix entry is 'error'; others 'ok'."""
    settings = _make_settings(monkeypatch, READ_PREFIXES="")

    class FailPutObject(FakeS3Client):
        def put_object(self, key: str, body: str, metadata: dict[str, str]) -> None:
            raise RuntimeError("Simulated put failure")

    s3 = FailPutObject()
    vectors = FakeVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)

    result = await health_check(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)

    assert result["write_prefix"]["status"] == "error"
    assert result["s3"]["status"] == "ok"


async def test_read_prefix_list_objects_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """list_objects raises on first read prefix → that entry 'error'; others 'ok'."""
    settings = _make_settings(monkeypatch, READ_PREFIXES="team-a")

    call_count = {"n": 0}

    class FailListObjects(FakeS3Client):
        def list_objects(self, prefix: str) -> list[str]:
            call_count["n"] += 1
            raise RuntimeError("Simulated list failure")

    s3 = FailListObjects()
    vectors = FakeVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)

    result = await health_check(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)

    read_prefix_keys = [k for k in result if k.startswith("read_prefix:")]
    assert len(read_prefix_keys) == 1
    assert result[read_prefix_keys[0]]["status"] == "error"
    assert result["s3"]["status"] == "ok"


# ---------------------------------------------------------------------------
# All failures — no unhandled exception
# ---------------------------------------------------------------------------


async def test_all_failures_all_error_no_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All fakes raise → all entries 'error'; no unhandled exception propagates."""
    settings = _make_settings(monkeypatch, READ_PREFIXES="team-a")

    class AllFailS3(FakeS3Client):
        def head_bucket(self, bucket: str) -> None:
            raise RuntimeError("Simulated head_bucket failure")

        def put_object(self, key: str, body: str, metadata: dict[str, str]) -> None:
            raise RuntimeError("Simulated put failure")

        def list_objects(self, prefix: str) -> list[str]:
            raise RuntimeError("Simulated list failure")

    s3 = AllFailS3()
    vectors = FakeVectorsClient(dimension=8, index_missing=True)
    bedrock = FakeBedrockClient(dimension=8)
    bedrock.set_credential_failure(True)

    # Must not raise
    result = await health_check(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)

    assert isinstance(result, dict)
    for key in ["s3", "vectors", "bedrock", "write_prefix"]:
        assert result[key]["status"] == "error"


# ---------------------------------------------------------------------------
# Response shape
# ---------------------------------------------------------------------------


async def test_ok_entries_have_no_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """'ok' entries have no 'message' field (or it is absent/null)."""
    settings = _make_settings(monkeypatch, READ_PREFIXES="")
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)

    result = await health_check(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)

    for component in ["s3", "vectors", "bedrock", "write_prefix"]:
        entry = result[component]
        assert entry["status"] == "ok"
        # message should be absent or None for ok entries
        assert entry.get("message") is None or "message" not in entry


async def test_error_entries_have_nonempty_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """'error' entries always include a non-empty 'message' string."""
    settings = _make_settings(monkeypatch, READ_PREFIXES="")
    s3 = FakeS3Client()
    s3.set_credential_failure(True)
    vectors = FakeVectorsClient(dimension=8, index_missing=True)
    bedrock = FakeBedrockClient(dimension=8)
    bedrock.set_credential_failure(True)

    result = await health_check(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)

    for component in ["s3", "vectors", "bedrock"]:
        entry = result[component]
        if entry["status"] == "error":
            assert "message" in entry
            assert isinstance(entry["message"], str)
            assert len(entry["message"]) > 0


async def test_status_field_only_ok_or_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """status field is always 'ok' or 'error' — no other values."""
    settings = _make_settings(monkeypatch, READ_PREFIXES="team-x")
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)

    result = await health_check(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)

    for key, entry in result.items():
        assert isinstance(entry, dict), f"Entry for '{key}' is not a dict: {entry}"
        assert entry["status"] in ("ok", "error"), (
            f"Unexpected status '{entry['status']}' for key '{key}'"
        )


# ---------------------------------------------------------------------------
# Spec 08 — CredentialError cause distinction in health probes
# ---------------------------------------------------------------------------


async def test_s3_probe_credential_error_returns_cause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S3 probe CredentialError → cause is 'credential_error'."""
    settings = _make_settings(monkeypatch, READ_PREFIXES="")
    s3 = FakeS3Client()
    s3.set_credential_failure(True)
    vectors = FakeVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)

    result = await health_check(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)

    s3_entry = result.get("s3", result.get("s3_write", {}))
    assert s3_entry.get("status") == "error"
    assert s3_entry.get("cause") == "credential_error"


async def test_vectors_probe_credential_error_returns_cause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Vectors probe CredentialError → cause is 'credential_error'."""
    settings = _make_settings(monkeypatch, READ_PREFIXES="")
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=8)
    vectors.set_credential_failure(True)
    bedrock = FakeBedrockClient(dimension=8)

    result = await health_check(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)

    vec_entry = result.get("vectors", result.get("s3_vectors", {}))
    assert vec_entry.get("status") == "error"
    assert vec_entry.get("cause") == "credential_error"


async def test_bedrock_probe_credential_error_returns_cause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bedrock probe CredentialError → cause is 'credential_error'."""
    settings = _make_settings(monkeypatch, READ_PREFIXES="")
    s3 = FakeS3Client()
    vectors = FakeVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)
    bedrock.set_credential_failure(True)

    result = await health_check(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)

    bedrock_entry = result.get("bedrock", result.get("bedrock_embed", {}))
    assert bedrock_entry.get("status") == "error"
    assert bedrock_entry.get("cause") == "credential_error"


async def test_generic_error_has_no_cause_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Generic RuntimeError in probe → no 'cause' key in result."""
    settings = _make_settings(monkeypatch, READ_PREFIXES="")

    class ExplodingS3(FakeS3Client):
        def head_bucket(self, bucket: str) -> None:
            raise RuntimeError("boom")

        def put_object(self, key: str, body: str, metadata: dict) -> None:  # type: ignore[override]
            raise RuntimeError("boom")

    s3 = ExplodingS3()
    vectors = FakeVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)

    result = await health_check(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)

    s3_entry = result.get("s3", result.get("s3_write", {}))
    assert s3_entry.get("status") == "error"
    assert "cause" not in s3_entry


async def test_credential_error_in_one_probe_does_not_skip_others(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S3 CredentialError → other probes still return 'ok'."""
    settings = _make_settings(monkeypatch, READ_PREFIXES="")
    s3 = FakeS3Client()
    s3.set_credential_failure(True)
    vectors = FakeVectorsClient(dimension=8)
    bedrock = FakeBedrockClient(dimension=8)

    result = await health_check(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)

    # At least vectors and bedrock should be OK
    for key, entry in result.items():
        if isinstance(entry, dict) and "s3" not in key:
            assert entry.get("status") == "ok", f"{key} should still be ok"
