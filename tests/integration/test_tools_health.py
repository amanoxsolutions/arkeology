"""Integration tests for cairn_mcp.tools.health.

Requires real AWS credentials and configured .env file.
All tests decorated with @pytest.mark.integration.
"""

import pytest

from cairn_mcp.clients.bedrock import BedrockClientImpl
from cairn_mcp.clients.s3 import S3ClientImpl
from cairn_mcp.clients.vectors import VectorsClientImpl
from cairn_mcp.config import Settings
from cairn_mcp.tools.health import health_check


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings()


@pytest.fixture(scope="session")
def s3(settings: Settings) -> S3ClientImpl:
    return S3ClientImpl(
        region=settings.aws_region,
        profile=settings.aws_profile,
        bucket=settings.artifact_bucket,
    )


@pytest.fixture(scope="session")
def vectors(settings: Settings) -> VectorsClientImpl:
    return VectorsClientImpl(
        region=settings.aws_region,
        profile=settings.aws_profile,
        bucket=settings.vectors_bucket,
        index=settings.vectors_index,
    )


@pytest.fixture(scope="session")
def bedrock(settings: Settings) -> BedrockClientImpl:
    return BedrockClientImpl(
        region=settings.aws_region,
        profile=settings.aws_profile,
    )


@pytest.mark.integration
async def test_health_check_all_components_ok(
    settings: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """Correctly configured environment → all components report 'ok'."""
    result = await health_check(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)

    assert result["s3"]["status"] == "ok"
    assert result["vectors"]["status"] == "ok"
    assert result["bedrock"]["status"] == "ok"
    assert result["write_prefix"]["status"] == "ok"


@pytest.mark.integration
async def test_health_check_expected_keys_present(
    settings: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """Health check response contains all expected top-level keys."""
    result = await health_check(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)

    assert "s3" in result
    assert "vectors" in result
    assert "bedrock" in result
    assert "write_prefix" in result

    # One key per read prefix
    expected_read_keys = [f"read_prefix:{p}" for p in settings.read_prefixes_list]
    for key in expected_read_keys:
        assert key in result, f"Expected '{key}' in health check response"


@pytest.mark.integration
async def test_health_check_never_raises(
    settings: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """health_check never raises — always returns a structured dict."""
    result = await health_check(settings=settings, s3=s3, vectors=vectors, bedrock=bedrock)

    assert isinstance(result, dict)
    for key, entry in result.items():
        assert isinstance(entry, dict), f"Entry for '{key}' is not a dict"
        assert "status" in entry, f"No 'status' field in entry for '{key}'"
        assert entry["status"] in ("ok", "error"), (
            f"Unexpected status '{entry['status']}' for '{key}'"
        )
