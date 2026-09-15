"""Unit tests for arkeology.tools.health.

Tests health_check() using moto-backed S3 and S3 Vectors clients plus FakeBedrockClient.
"""

import threading
from typing import Any

import pytest
from pytest_mock import MockerFixture

from arkeology.clients.fakes.fake_bedrock import FakeBedrockClient
from arkeology.clients.s3 import S3ClientImpl
from arkeology.clients.vectors import VectorsClientImpl
from arkeology.errors import AnnotationUnavailableError, CredentialError
from arkeology.tools.health import health_check
from tests.unit.conftest import _make_settings

# Mirrors health.py's f"read_prefix:{prefix}" key construction, so the assertion
# builds the key the same way the source does rather than hard-coding it.
_READ_PREFIX = "other-team"

# ---------------------------------------------------------------------------
# All healthy
# ---------------------------------------------------------------------------


async def test_all_healthy_all_ok(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """All components healthy → all entries have status='ok'."""
    settings = _make_settings(monkeypatch, READ_PREFIXES="")
    bedrock = FakeBedrockClient()

    result = await health_check(
        settings=settings, s3=s3_client, vectors=vectors_client_8, bedrock=bedrock
    )

    assert result["s3"]["status"] == "ok"
    assert result["vectors"]["status"] == "ok"
    assert result["bedrock"]["status"] == "ok"
    assert result["write_prefix"]["status"] == "ok"


async def test_response_keys_present_no_read_prefixes(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """No read prefixes → response has s3, vectors, bedrock, write_prefix; no read_prefix keys."""
    settings = _make_settings(monkeypatch, READ_PREFIXES="")
    bedrock = FakeBedrockClient()

    result = await health_check(
        settings=settings, s3=s3_client, vectors=vectors_client_8, bedrock=bedrock
    )

    assert "s3" in result
    assert "vectors" in result
    assert "bedrock" in result
    assert "write_prefix" in result
    read_prefix_keys = [k for k in result if k.startswith("read_prefix:")]
    assert len(read_prefix_keys) == 0


async def test_two_read_prefixes_two_keys(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """Two read prefixes configured → two 'read_prefix:...' keys in response."""
    settings = _make_settings(monkeypatch, READ_PREFIXES="team-a,team-b")
    bedrock = FakeBedrockClient()

    result = await health_check(
        settings=settings, s3=s3_client, vectors=vectors_client_8, bedrock=bedrock
    )

    read_prefix_keys = [k for k in result if k.startswith("read_prefix:")]
    assert len(read_prefix_keys) == 2


# ---------------------------------------------------------------------------
# Individual failures
# ---------------------------------------------------------------------------


async def test_s3_head_bucket_credential_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """head_bucket raises CredentialError → s3 entry is 'error'; others 'ok'."""
    settings = _make_settings(monkeypatch, READ_PREFIXES="")
    mocker.patch.object(
        s3_client,
        "head_bucket",
        side_effect=CredentialError(
            message="simulated",
            service="s3",
            original=Exception("simulated"),
        ),
    )
    bedrock = FakeBedrockClient()

    result = await health_check(
        settings=settings, s3=s3_client, vectors=vectors_client_8, bedrock=bedrock
    )

    assert result["s3"]["status"] == "error"


async def test_vectors_describe_index_not_found_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_no_index: VectorsClientImpl,
) -> None:
    """describe_index raises VectorIndexNotFoundError → vectors entry is 'error'; others 'ok'."""
    settings = _make_settings(monkeypatch, READ_PREFIXES="")
    bedrock = FakeBedrockClient()

    result = await health_check(
        settings=settings, s3=s3_client, vectors=vectors_client_no_index, bedrock=bedrock
    )

    assert result["vectors"]["status"] == "error"
    assert result["s3"]["status"] == "ok"


async def test_bedrock_embed_credential_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """embed raises CredentialError → bedrock entry is 'error'; others 'ok'."""
    settings = _make_settings(monkeypatch, READ_PREFIXES="")
    bedrock = FakeBedrockClient()
    mocker.patch.object(
        bedrock,
        "embed",
        side_effect=CredentialError("simulated", "bedrock", Exception("simulated")),
    )

    result = await health_check(
        settings=settings, s3=s3_client, vectors=vectors_client_8, bedrock=bedrock
    )

    assert result["bedrock"]["status"] == "error"
    assert result["s3"]["status"] == "ok"
    assert result["vectors"]["status"] == "ok"


async def test_write_prefix_put_object_failure(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """put_object raises on write-prefix probe → write_prefix entry is 'error'; others 'ok'."""
    settings = _make_settings(monkeypatch, READ_PREFIXES="")
    mocker.patch.object(s3_client, "put_object", side_effect=RuntimeError("Simulated put failure"))
    bedrock = FakeBedrockClient()

    result = await health_check(
        settings=settings, s3=s3_client, vectors=vectors_client_8, bedrock=bedrock
    )

    assert result["write_prefix"]["status"] == "error"
    assert result["s3"]["status"] == "ok"


async def test_read_prefix_list_objects_failure(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """list_objects raises on first read prefix → that entry 'error'; others 'ok'."""
    settings = _make_settings(monkeypatch, READ_PREFIXES="team-a")
    mocker.patch.object(
        s3_client, "list_objects", side_effect=RuntimeError("Simulated list failure")
    )
    bedrock = FakeBedrockClient()

    result = await health_check(
        settings=settings, s3=s3_client, vectors=vectors_client_8, bedrock=bedrock
    )

    read_prefix_keys = [k for k in result if k.startswith("read_prefix:")]
    assert len(read_prefix_keys) == 1
    assert result[read_prefix_keys[0]]["status"] == "error"
    assert result["s3"]["status"] == "ok"


# ---------------------------------------------------------------------------
# All failures — no unhandled exception
# ---------------------------------------------------------------------------


async def test_all_failures_all_error_no_exception(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_no_index: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """All probes raise → all entries 'error'; no unhandled exception propagates."""
    settings = _make_settings(monkeypatch, READ_PREFIXES="team-a")
    mocker.patch.object(s3_client, "head_bucket", side_effect=RuntimeError("simulated"))
    mocker.patch.object(s3_client, "put_object", side_effect=RuntimeError("simulated"))
    mocker.patch.object(s3_client, "list_objects", side_effect=RuntimeError("simulated"))
    bedrock = FakeBedrockClient()
    mocker.patch.object(
        bedrock,
        "embed",
        side_effect=CredentialError("simulated", "bedrock", Exception("simulated")),
    )

    result = await health_check(
        settings=settings, s3=s3_client, vectors=vectors_client_no_index, bedrock=bedrock
    )

    assert isinstance(result, dict)
    for key in ["s3", "vectors", "bedrock", "write_prefix"]:
        assert result[key]["status"] == "error"


# ---------------------------------------------------------------------------
# Response shape
# ---------------------------------------------------------------------------


async def test_ok_entries_have_no_message(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """'ok' entries have no 'message' field (or it is absent/null)."""
    settings = _make_settings(monkeypatch, READ_PREFIXES="")
    bedrock = FakeBedrockClient()

    result = await health_check(
        settings=settings, s3=s3_client, vectors=vectors_client_8, bedrock=bedrock
    )

    for component in ["s3", "vectors", "bedrock", "write_prefix"]:
        entry = result[component]
        assert entry["status"] == "ok"
        assert entry.get("message") is None or "message" not in entry


async def test_error_entries_have_nonempty_message(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_no_index: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """'error' entries always include a non-empty 'message' string."""
    settings = _make_settings(monkeypatch, READ_PREFIXES="")
    mocker.patch.object(
        s3_client,
        "head_bucket",
        side_effect=CredentialError(
            message="simulated",
            service="s3",
            original=Exception("simulated"),
        ),
    )
    bedrock = FakeBedrockClient()
    mocker.patch.object(
        bedrock,
        "embed",
        side_effect=CredentialError("simulated", "bedrock", Exception("simulated")),
    )

    result = await health_check(
        settings=settings, s3=s3_client, vectors=vectors_client_no_index, bedrock=bedrock
    )

    for component in ["s3", "vectors", "bedrock"]:
        entry = result[component]
        if entry["status"] == "error":
            assert "message" in entry
            assert isinstance(entry["message"], str)
            assert len(entry["message"]) > 0


async def test_status_field_only_ok_or_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """status field is always 'ok' or 'error' — no other values."""
    settings = _make_settings(monkeypatch, READ_PREFIXES="team-x")
    bedrock = FakeBedrockClient()

    result = await health_check(
        settings=settings, s3=s3_client, vectors=vectors_client_8, bedrock=bedrock
    )

    for key, entry in result.items():
        assert isinstance(entry, dict), f"Entry for '{key}' is not a dict: {entry}"
        assert entry["status"] in ("ok", "error"), (
            f"Unexpected status '{entry['status']}' for key '{key}'"
        )


# ---------------------------------------------------------------------------
# bedrock_text_model probe
# ---------------------------------------------------------------------------


async def test_bedrock_text_model_absent_when_not_configured(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """When BEDROCK_TEXT_MODEL is not set, bedrock_text_model key is absent from result."""
    settings = _make_settings(monkeypatch, READ_PREFIXES="")
    bedrock = FakeBedrockClient()

    result = await health_check(
        settings=settings, s3=s3_client, vectors=vectors_client_8, bedrock=bedrock
    )

    assert "bedrock_text_model" not in result


async def test_bedrock_text_model_ok_when_configured(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
) -> None:
    """When BEDROCK_TEXT_MODEL is set and reachable, bedrock_text_model status is 'ok'."""
    settings = _make_settings(
        monkeypatch, READ_PREFIXES="", BEDROCK_TEXT_MODEL="amazon.nova-lite-v1:0"
    )
    bedrock = FakeBedrockClient()

    result = await health_check(
        settings=settings, s3=s3_client, vectors=vectors_client_8, bedrock=bedrock
    )

    assert result["bedrock_text_model"]["status"] == "ok"


async def test_bedrock_text_model_error_on_invoke_failure(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """invoke_text_model raises RuntimeError → bedrock_text_model 'error' with message, no cause."""
    settings = _make_settings(
        monkeypatch, READ_PREFIXES="", BEDROCK_TEXT_MODEL="amazon.nova-lite-v1:0"
    )
    bedrock = FakeBedrockClient()
    mocker.patch.object(bedrock, "invoke_text_model", side_effect=RuntimeError("model unreachable"))

    result = await health_check(
        settings=settings, s3=s3_client, vectors=vectors_client_8, bedrock=bedrock
    )

    assert result["bedrock_text_model"]["status"] == "error"
    assert "message" in result["bedrock_text_model"]
    assert len(result["bedrock_text_model"]["message"]) > 0
    assert "cause" not in result["bedrock_text_model"]


async def test_bedrock_text_model_credential_error_returns_cause(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """invoke_text_model CredentialError → status 'error' and cause 'credential_error'."""
    settings = _make_settings(
        monkeypatch, READ_PREFIXES="", BEDROCK_TEXT_MODEL="amazon.nova-lite-v1:0"
    )
    bedrock = FakeBedrockClient()
    mocker.patch.object(
        bedrock,
        "invoke_text_model",
        side_effect=CredentialError(
            message="simulated",
            service="bedrock",
            original=Exception("simulated"),
        ),
    )

    result = await health_check(
        settings=settings, s3=s3_client, vectors=vectors_client_8, bedrock=bedrock
    )

    assert result["bedrock_text_model"]["status"] == "error"
    assert result["bedrock_text_model"].get("cause") == "credential_error"


async def test_bedrock_text_model_failure_does_not_skip_other_probes(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """bedrock_text_model probe failure does not prevent other probes from running."""
    settings = _make_settings(
        monkeypatch, READ_PREFIXES="", BEDROCK_TEXT_MODEL="amazon.nova-lite-v1:0"
    )
    bedrock = FakeBedrockClient()
    mocker.patch.object(bedrock, "invoke_text_model", side_effect=RuntimeError("model unreachable"))

    result = await health_check(
        settings=settings, s3=s3_client, vectors=vectors_client_8, bedrock=bedrock
    )

    assert result["s3"]["status"] == "ok"
    assert result["vectors"]["status"] == "ok"
    assert result["bedrock"]["status"] == "ok"
    assert result["write_prefix"]["status"] == "ok"
    assert result["bedrock_text_model"]["status"] == "error"


# ---------------------------------------------------------------------------
# Spec 08 — CredentialError cause distinction in health probes
# ---------------------------------------------------------------------------


async def test_s3_probe_credential_error_returns_cause(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """S3 probe CredentialError → cause is 'credential_error'."""
    settings = _make_settings(monkeypatch, READ_PREFIXES="")
    mocker.patch.object(
        s3_client,
        "head_bucket",
        side_effect=CredentialError(
            message="simulated",
            service="s3",
            original=Exception("simulated"),
        ),
    )
    bedrock = FakeBedrockClient()

    result = await health_check(
        settings=settings, s3=s3_client, vectors=vectors_client_8, bedrock=bedrock
    )

    s3_entry = result.get("s3", result.get("s3_write", {}))
    assert s3_entry.get("status") == "error"
    assert s3_entry.get("cause") == "credential_error"


async def test_vectors_probe_credential_error_returns_cause(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """Vectors probe CredentialError → cause is 'credential_error'."""
    settings = _make_settings(monkeypatch, READ_PREFIXES="")
    mocker.patch.object(
        vectors_client_8,
        "describe_index",
        side_effect=CredentialError(
            message="simulated",
            service="s3vectors",
            original=Exception("simulated"),
        ),
    )
    bedrock = FakeBedrockClient()

    result = await health_check(
        settings=settings, s3=s3_client, vectors=vectors_client_8, bedrock=bedrock
    )

    vec_entry = result.get("vectors", result.get("s3_vectors", {}))
    assert vec_entry.get("status") == "error"
    assert vec_entry.get("cause") == "credential_error"


async def test_bedrock_probe_credential_error_returns_cause(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """Bedrock probe CredentialError → cause is 'credential_error'."""
    settings = _make_settings(monkeypatch, READ_PREFIXES="")
    bedrock = FakeBedrockClient()
    mocker.patch.object(
        bedrock,
        "embed",
        side_effect=CredentialError("simulated", "bedrock", Exception("simulated")),
    )

    result = await health_check(
        settings=settings, s3=s3_client, vectors=vectors_client_8, bedrock=bedrock
    )

    bedrock_entry = result.get("bedrock", result.get("bedrock_embed", {}))
    assert bedrock_entry.get("status") == "error"
    assert bedrock_entry.get("cause") == "credential_error"


async def test_generic_error_has_no_cause_field(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """Generic RuntimeError in probe → no 'cause' key in result."""
    settings = _make_settings(monkeypatch, READ_PREFIXES="")
    mocker.patch.object(s3_client, "head_bucket", side_effect=RuntimeError("boom"))
    mocker.patch.object(s3_client, "put_object", side_effect=RuntimeError("boom"))
    bedrock = FakeBedrockClient()

    result = await health_check(
        settings=settings, s3=s3_client, vectors=vectors_client_8, bedrock=bedrock
    )

    s3_entry = result.get("s3", result.get("s3_write", {}))
    assert s3_entry.get("status") == "error"
    assert "cause" not in s3_entry


async def test_credential_error_in_one_probe_does_not_skip_others(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """S3 CredentialError → other probes still return 'ok'."""
    settings = _make_settings(monkeypatch, READ_PREFIXES="")
    mocker.patch.object(
        s3_client,
        "head_bucket",
        side_effect=CredentialError(
            message="simulated",
            service="s3",
            original=Exception("simulated"),
        ),
    )
    bedrock = FakeBedrockClient()

    result = await health_check(
        settings=settings, s3=s3_client, vectors=vectors_client_8, bedrock=bedrock
    )

    for key, entry in result.items():
        if isinstance(entry, dict) and "s3" not in key:
            assert entry.get("status") == "ok", f"{key} should still be ok"


# ---------------------------------------------------------------------------
# M22 Bug 1 — CredentialError on write_prefix probe must include write_prefix key
# ---------------------------------------------------------------------------


async def test_credential_error_on_write_prefix_probe_key_present(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """When s3.put_object raises CredentialError during the write_prefix probe, the
    probe branch must not swallow it with a bare ``pass`` and leave
    result["write_prefix"] absent — it must be present with an appropriate status.

    Scenario:
    - Mock s3.put_object to raise CredentialError specifically for the probe key.
    - Call health_check.
    - Expected: result["write_prefix"] is present (either 'ok' or 'error' — but present).
    """
    settings = _make_settings(monkeypatch, READ_PREFIXES="")
    bedrock = FakeBedrockClient()

    # Only fail on the probe key write; allow head_bucket to succeed normally. The
    # probe key carries a per-invocation ULID suffix, so match by prefix rather than
    # an exact literal.
    probe_key_prefix = f"{settings.write_prefix}/_arkeology_health_probe"
    original_put = s3_client.put_object

    def put_object_side_effect(key: str, content: str, metadata: dict) -> None:
        if key.startswith(probe_key_prefix):
            raise CredentialError(
                message="simulated credential error on probe put",
                service="s3",
                original=Exception("simulated"),
            )
        original_put(key, content, metadata)

    mocker.patch.object(s3_client, "put_object", side_effect=put_object_side_effect)

    result = await health_check(
        settings=settings, s3=s3_client, vectors=vectors_client_8, bedrock=bedrock
    )

    assert "write_prefix" in result, (
        "M22 Bug 1: result['write_prefix'] must be present even when CredentialError is raised "
        "on the write_prefix probe; current code does 'pass' and omits the key entirely."
    )


# ---------------------------------------------------------------------------
# M22 Bug 2 — probe object must be cleaned up even when get_object fails
# ---------------------------------------------------------------------------


async def test_probe_object_cleaned_up_when_get_object_fails(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """M22 Bug 2: When s3.put_object succeeds but s3.get_object raises, the probe object
    is left in S3 (no cleanup).  After the fix, s3.delete_object must be called for the
    probe key regardless of whether get_object succeeded.

    Scenario:
    - s3.put_object succeeds (for the probe key).
    - s3.get_object raises RuntimeError for the probe key.
    - Expected: s3.delete_object is called (best-effort cleanup).
    """
    settings = _make_settings(monkeypatch, READ_PREFIXES="")
    bedrock = FakeBedrockClient()

    # The probe key carries a per-invocation ULID suffix, so match by prefix rather
    # than an exact literal.
    probe_key_prefix = f"{settings.write_prefix}/_arkeology_health_probe"

    # put_object succeeds (default moto behaviour)
    # get_object raises for the probe key
    original_get = s3_client.get_object

    def get_object_side_effect(key: str) -> str:
        if key.startswith(probe_key_prefix):
            raise RuntimeError("simulated get_object failure on probe key")
        return original_get(key)

    mocker.patch.object(s3_client, "get_object", side_effect=get_object_side_effect)
    delete_spy = mocker.spy(s3_client, "delete_object")

    await health_check(settings=settings, s3=s3_client, vectors=vectors_client_8, bedrock=bedrock)

    # Verify that delete_object was called for the probe key (cleanup)
    called_keys = [call.args[0] for call in delete_spy.call_args_list]
    assert any(key.startswith(probe_key_prefix) for key in called_keys), (
        f"M22 Bug 2: s3.delete_object must be called for the probe key as cleanup "
        f"even when get_object fails, but delete was only called for: {called_keys}"
    )


async def test_probe_key_is_unique_per_invocation(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """Two health_check calls sharing one WRITE_PREFIX must not reuse the same fixed
    probe key — a constant key means two hosts sharing one scope can delete each
    other's in-flight probe object mid-round-trip and report a spurious write_prefix
    failure. The probe key must be unique per invocation (ULID-suffixed), matching
    startup.py's pattern."""
    settings = _make_settings(monkeypatch, READ_PREFIXES="")
    bedrock = FakeBedrockClient()

    seen_keys: list[str] = []
    original_put = s3_client.put_object

    def _recording_put(key: str, *args: object, **kwargs: object) -> None:
        seen_keys.append(key)
        original_put(key, *args, **kwargs)  # type: ignore[arg-type]

    mocker.patch.object(s3_client, "put_object", side_effect=_recording_put)

    await health_check(settings=settings, s3=s3_client, vectors=vectors_client_8, bedrock=bedrock)
    await health_check(settings=settings, s3=s3_client, vectors=vectors_client_8, bedrock=bedrock)

    probe_key_prefix = f"{settings.write_prefix}/_arkeology_health_probe"
    probe_keys = [key for key in seen_keys if key.startswith(probe_key_prefix)]

    assert len(probe_keys) == 2
    assert len(set(probe_keys)) == 2, (
        "Each health_check invocation must use a distinct probe key so two hosts "
        "sharing WRITE_PREFIX cannot race on the same S3 object"
    )


async def test_probes_run_off_the_event_loop(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """Every probe is a blocking boto3 round trip. Running them inline on the calling
    event-loop thread blocks it for the full S3 + Vectors + Bedrock latency, so each
    must be offloaded to a worker thread the way every other tool offloads its AWS
    calls."""
    settings = _make_settings(monkeypatch, READ_PREFIXES=_READ_PREFIX)
    bedrock = FakeBedrockClient()
    main_thread = threading.current_thread()
    seen_threads: list[threading.Thread] = []

    def _spy(target: Any, method: str) -> None:
        original = getattr(target, method)

        def _record(*args: Any, **kwargs: Any) -> Any:
            seen_threads.append(threading.current_thread())
            return original(*args, **kwargs)

        mocker.patch.object(target, method, side_effect=_record)

    for method in ("head_bucket", "put_object", "get_object", "delete_object", "list_objects"):
        _spy(s3_client, method)
    _spy(vectors_client_8, "describe_index")
    _spy(bedrock, "embed")

    result = await health_check(
        settings=settings, s3=s3_client, vectors=vectors_client_8, bedrock=bedrock
    )

    assert result["s3"]["status"] == "ok"
    assert result["vectors"]["status"] == "ok"
    assert result["bedrock"]["status"] == "ok"
    assert result["write_prefix"]["status"] == "ok"
    assert result[f"read_prefix:{_READ_PREFIX}"]["status"] == "ok"
    assert seen_threads, "no probe was ever called"
    assert all(t is not main_thread for t in seen_threads), (
        "health probes ran on the event-loop thread — they must be offloaded"
    )


# ---------------------------------------------------------------------------
# T74.5 — annotations are a hard runtime dependency and must be probed
# ---------------------------------------------------------------------------


async def test_health_check_probes_the_annotation_store(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """Annotations are the sole durable store for both link fields, so a health check
    that never touches them cannot observe the health it reports.

    Startup check 8 proves availability once, at start; an IAM policy edited afterwards
    drifts silently, and every component then reports ``ok`` on a deployment where
    every link-field read fails.
    """
    settings = _make_settings(monkeypatch, READ_PREFIXES="")
    bedrock = FakeBedrockClient()
    get_spy = mocker.spy(s3_client, "get_object_annotation")

    result = await health_check(
        settings=settings, s3=s3_client, vectors=vectors_client_8, bedrock=bedrock
    )

    assert "error" not in result
    assert get_spy.call_count >= 1
    assert result["annotations"]["status"] == "ok", (
        "the annotation probe must report under its own documented key — an annotation "
        "denial is not a write-permission problem and sends the operator elsewhere"
    )


async def test_health_check_reports_a_drifted_annotation_policy_without_hiding_others(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """A denied annotation call surfaces as a component error, and only that component's.

    Every probe is independent: an annotation failure must not stop S3, Vectors or
    Bedrock being probed and reported, or the check hides exactly the correlated
    outage it exists to diagnose.
    """
    settings = _make_settings(monkeypatch, READ_PREFIXES="")
    bedrock = FakeBedrockClient()
    mocker.patch.object(
        s3_client,
        "get_object_annotation",
        side_effect=AnnotationUnavailableError(
            "S3 object annotations are unavailable for this bucket.", "s3", Exception("boom")
        ),
    )

    result = await health_check(
        settings=settings, s3=s3_client, vectors=vectors_client_8, bedrock=bedrock
    )

    assert "error" not in result
    assert result["s3"]["status"] == "ok"
    assert result["vectors"]["status"] == "ok"
    assert result["bedrock"]["status"] == "ok"
    assert result["annotations"]["status"] == "error", (
        "a denied annotation call must surface under the annotations key — asserting "
        "only that some component errored passes just as well when the wrong one does"
    )
    assert [
        key
        for key, entry in result.items()
        if isinstance(entry, dict) and entry.get("status") == "error"
    ] == ["annotations"]
