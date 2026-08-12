"""Unit tests for arkeology.tools.studio.

Tests arkeology_studio() — the MCP App entry-point that triggers the inline browser
widget on supporting hosts and falls back to a structured artifact listing on
non-supporting hosts.

Four tests:
- non-supporting host → ToolResult with structured_content containing artifacts + write_prefix
- supporting host     → ToolResult with no structured_content (iframe loads data itself)
- exception path      → error ToolResult (is_error=True)
"""

from unittest.mock import MagicMock

import pytest
from fastmcp.tools.base import ToolResult
from pytest_mock import MockerFixture

from arkeology.config import Settings
from tests.unit.conftest import _make_settings as _make_settings_base


def _make_settings(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> Settings:
    return _make_settings_base(monkeypatch, **overrides)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    return _make_settings(monkeypatch)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_arkeology_studio_non_supporting_host_returns_structured_content(
    settings: Settings,
    mocker: MockerFixture,
) -> None:
    """Non-supporting host receives structured_content with artifacts and write_prefix."""
    from arkeology.tools import studio

    mocker.patch.object(
        studio,
        "_list_artifacts_inner",
        return_value={"artifacts": [{"artifact_id": "artifacts/adr-test"}]},
    )

    ctx = MagicMock()
    ctx.client_supports_extension.return_value = False
    vectors = MagicMock()

    result = await studio.arkeology_studio(settings=settings, vectors=vectors, ctx=ctx)

    assert isinstance(result, ToolResult)
    assert not result.is_error
    assert result.content, "Expected at least one content block"
    text = result.content[0].text  # type: ignore[attr-defined]
    assert "not supported" in text
    assert result.structured_content is not None
    assert "artifacts" in result.structured_content
    assert "write_prefix" in result.structured_content


@pytest.mark.asyncio
async def test_arkeology_studio_non_supporting_host_credential_error_is_propagated(
    settings: Settings,
    mocker: MockerFixture,
) -> None:
    """M-11(a): a credential-error dict from the inner list call must surface as a
    structured error, not be coerced into a successful empty listing — otherwise
    expired credentials read as "the store is empty" (PRD FR-12)."""
    from arkeology.tools import studio

    mocker.patch.object(
        studio,
        "_list_artifacts_inner",
        return_value={
            "error": "credential_error",
            "message": "AWS credentials are invalid or expired.",
        },
    )

    ctx = MagicMock()
    ctx.client_supports_extension.return_value = False
    vectors = MagicMock()

    result = await studio.arkeology_studio(settings=settings, vectors=vectors, ctx=ctx)

    assert isinstance(result, ToolResult)
    assert result.is_error, "A credential-error listing must not report success"
    text = result.content[0].text  # type: ignore[attr-defined]
    assert "credentials" in text.lower() or "credential_error" in text.lower()
    assert result.structured_content is not None
    assert result.structured_content.get("error") == "credential_error"
    # The error must never be silently rewritten as an empty artifact listing.
    assert "artifacts" not in result.structured_content


@pytest.mark.asyncio
async def test_arkeology_studio_supporting_host_omits_structured_content(
    settings: Settings,
) -> None:
    """Supporting host receives a short confirmation only — no structured_content."""
    from arkeology.tools.studio import arkeology_studio

    ctx = MagicMock()
    ctx.client_supports_extension.return_value = True
    vectors = MagicMock()

    result = await arkeology_studio(settings=settings, vectors=vectors, ctx=ctx)

    assert isinstance(result, ToolResult)
    assert not result.is_error
    assert result.content, "Expected at least one content block"
    text = result.content[0].text  # type: ignore[attr-defined]
    assert "Arkeology Studio opened" in text
    assert result.structured_content is None


@pytest.mark.asyncio
async def test_arkeology_studio_exception_returns_error_tool_result(
    settings: Settings,
) -> None:
    """When an unexpected exception occurs inside arkeology_studio, it returns an error result."""
    from arkeology.tools.studio import arkeology_studio

    ctx = MagicMock()
    ctx.client_supports_extension.side_effect = RuntimeError("boom")
    vectors = MagicMock()

    result = await arkeology_studio(settings=settings, vectors=vectors, ctx=ctx)

    assert isinstance(result, ToolResult)
    assert result.is_error
    text = result.content[0].text  # type: ignore[attr-defined]
    assert "boom" in text, f"Expected error message in content, got: {text!r}"


# ---------------------------------------------------------------------------
# M21 — _arkeology_studio_inner must exist (refactor to _inner convention)
# ---------------------------------------------------------------------------


def test_m21_arkeology_studio_inner_function_exists() -> None:
    """M21: The project convention requires every tool's public function to delegate to
    an ``_inner`` variant.  arkeology_studio currently has an inline try/except and no
    ``_arkeology_studio_inner`` function.  After the refactor, ``_arkeology_studio_inner`` must
    be importable from arkeology.tools.studio.

    Before the refactor this test raises ImportError / AttributeError and fails.
    """
    try:
        from arkeology.tools.studio import _arkeology_studio_inner  # noqa: F401
    except ImportError as exc:
        raise AssertionError(
            "M21: _arkeology_studio_inner is not exported from arkeology.tools.studio. "
            "Refactor arkeology_studio to delegate to _arkeology_studio_inner per "
            "project convention."
        ) from exc

    assert callable(_arkeology_studio_inner), (
        "M21: _arkeology_studio_inner must be a callable function, not a non-callable object"
    )
