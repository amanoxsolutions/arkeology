"""Unit tests for cairn_mcp.tools.studio.

Tests cairn_studio() — the MCP App entry-point that triggers the inline browser
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

from cairn_mcp.config import Settings
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
async def test_cairn_studio_non_supporting_host_returns_structured_content(
    settings: Settings,
    mocker: MockerFixture,
) -> None:
    """Non-supporting host receives structured_content with artifacts and write_prefix."""
    from cairn_mcp.tools import studio

    mocker.patch.object(
        studio,
        "_list_artifacts_inner",
        return_value={"artifacts": [{"artifact_id": "artifacts/adr-test"}]},
    )

    ctx = MagicMock()
    ctx.client_supports_extension.return_value = False
    vectors = MagicMock()

    result = await studio.cairn_studio(settings=settings, vectors=vectors, ctx=ctx)

    assert isinstance(result, ToolResult)
    assert not result.is_error
    assert result.content, "Expected at least one content block"
    text = result.content[0].text  # type: ignore[attr-defined]
    assert "not supported" in text
    assert result.structured_content is not None
    assert "artifacts" in result.structured_content
    assert "write_prefix" in result.structured_content


@pytest.mark.asyncio
async def test_cairn_studio_supporting_host_omits_structured_content(
    settings: Settings,
) -> None:
    """Supporting host receives a short confirmation only — no structured_content."""
    from cairn_mcp.tools.studio import cairn_studio

    ctx = MagicMock()
    ctx.client_supports_extension.return_value = True
    vectors = MagicMock()

    result = await cairn_studio(settings=settings, vectors=vectors, ctx=ctx)

    assert isinstance(result, ToolResult)
    assert not result.is_error
    assert result.content, "Expected at least one content block"
    text = result.content[0].text  # type: ignore[attr-defined]
    assert "Cairn Studio opened" in text
    assert result.structured_content is None


@pytest.mark.asyncio
async def test_cairn_studio_exception_returns_error_tool_result(
    settings: Settings,
) -> None:
    """When an unexpected exception occurs inside cairn_studio, it returns an error ToolResult."""
    from cairn_mcp.tools.studio import cairn_studio

    ctx = MagicMock()
    ctx.client_supports_extension.side_effect = RuntimeError("boom")
    vectors = MagicMock()

    result = await cairn_studio(settings=settings, vectors=vectors, ctx=ctx)

    assert isinstance(result, ToolResult)
    assert result.is_error
    text = result.content[0].text  # type: ignore[attr-defined]
    assert "boom" in text, f"Expected error message in content, got: {text!r}"


# ---------------------------------------------------------------------------
# M21 — _cairn_studio_inner must exist (refactor to _inner convention)
# ---------------------------------------------------------------------------


def test_m21_cairn_studio_inner_function_exists() -> None:
    """M21: The project convention requires every tool's public function to delegate to
    an ``_inner`` variant.  cairn_studio currently has an inline try/except and no
    ``_cairn_studio_inner`` function.  After the refactor, ``_cairn_studio_inner`` must
    be importable from cairn_mcp.tools.studio.

    Before the refactor this test raises ImportError / AttributeError and fails.
    """
    try:
        from cairn_mcp.tools.studio import _cairn_studio_inner  # noqa: F401
    except ImportError as exc:
        raise AssertionError(
            "M21: _cairn_studio_inner is not exported from cairn_mcp.tools.studio. "
            "Refactor cairn_studio to delegate to _cairn_studio_inner per project convention."
        ) from exc

    assert callable(_cairn_studio_inner), (
        "M21: _cairn_studio_inner must be a callable function, not a non-callable object"
    )
