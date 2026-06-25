"""Unit tests for cairn_mcp.tools.browse.

Tests cairn_browse() — the simplified MCP App entry-point that triggers the
inline browser widget and returns a short confirmation ToolResult.

Three tests:
- non-supporting host → ToolResult with human-readable confirmation (no error)
- supporting host     → ToolResult with human-readable confirmation (no error)
- exception path      → error ToolResult (is_error=True)
"""

from unittest.mock import MagicMock

import pytest
from fastmcp.tools.base import ToolResult

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
async def test_cairn_browse_non_supporting_host_returns_tool_result(
    settings: Settings,
) -> None:
    """cairn_browse returns a non-error ToolResult when the host does not support the extension."""
    from cairn_mcp.tools.browse import cairn_browse

    ctx = MagicMock()
    ctx.client_supports_extension.return_value = False

    result = await cairn_browse(settings=settings, ctx=ctx)

    assert isinstance(result, ToolResult), f"Expected ToolResult, got {type(result)}: {result!r}"
    assert not result.is_error
    assert result.content, "Expected at least one content block"
    text = result.content[0].text  # type: ignore[attr-defined]
    assert "Cairn browser opened" in text, f"Unexpected text content: {text!r}"


@pytest.mark.asyncio
async def test_cairn_browse_supporting_host_returns_tool_result(
    settings: Settings,
) -> None:
    """cairn_browse returns a non-error ToolResult when the host supports the UI extension."""
    from cairn_mcp.tools.browse import cairn_browse

    ctx = MagicMock()
    ctx.client_supports_extension.return_value = True

    result = await cairn_browse(settings=settings, ctx=ctx)

    assert isinstance(result, ToolResult), f"Expected ToolResult, got {type(result)}: {result!r}"
    assert not result.is_error
    assert result.content, "Expected at least one content block"
    text = result.content[0].text  # type: ignore[attr-defined]
    assert "Cairn browser opened" in text, f"Unexpected text content: {text!r}"


@pytest.mark.asyncio
async def test_cairn_browse_exception_returns_error_tool_result(
    settings: Settings,
) -> None:
    """When an unexpected exception occurs inside cairn_browse, it returns an error ToolResult."""
    from cairn_mcp.tools.browse import cairn_browse

    ctx = MagicMock()
    ctx.client_supports_extension.side_effect = RuntimeError("boom")

    result = await cairn_browse(settings=settings, ctx=ctx)

    assert isinstance(result, ToolResult), f"Expected ToolResult, got {type(result)}: {result!r}"
    assert result.is_error
    text = result.content[0].text  # type: ignore[attr-defined]
    assert "boom" in text, f"Expected error message in content, got: {text!r}"
