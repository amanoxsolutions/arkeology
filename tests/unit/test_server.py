"""Tests for server startup and logging configuration."""

import logging
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

from cairn_mcp.__main__ import configure_logging
from cairn_mcp.server import _app, register_tools
from tests.unit.conftest import _make_settings


def test_configure_logging_debug_sets_level() -> None:
    """configure_logging('DEBUG') sets the root logger to DEBUG."""
    configure_logging("DEBUG")
    assert logging.getLogger().level == logging.DEBUG


def test_configure_logging_info_sets_level() -> None:
    """configure_logging('INFO') sets the root logger to INFO."""
    configure_logging("INFO")
    assert logging.getLogger().level == logging.INFO


def test_configure_logging_warning_sets_level() -> None:
    """configure_logging('WARNING') sets the root logger to WARNING."""
    configure_logging("WARNING")
    assert logging.getLogger().level == logging.WARNING


def test_configure_logging_error_sets_level() -> None:
    """configure_logging('ERROR') sets the root logger to ERROR."""
    configure_logging("ERROR")
    assert logging.getLogger().level == logging.ERROR


def test_configure_logging_invalid_falls_back_to_info() -> None:
    """configure_logging with an invalid level falls back to INFO."""
    configure_logging("TRACE")
    assert logging.getLogger().level == logging.INFO


def test_configure_logging_handler_goes_to_stderr() -> None:
    """Root logger has exactly one StreamHandler directed at stderr."""
    configure_logging("INFO")
    root = logging.getLogger()
    stream_handlers = [h for h in root.handlers if isinstance(h, logging.StreamHandler)]
    assert len(stream_handlers) == 1
    assert stream_handlers[0].stream is sys.stderr


def test_configure_logging_only_one_handler_after_multiple_calls() -> None:
    """Calling configure_logging multiple times does not accumulate handlers."""
    configure_logging("INFO")
    configure_logging("DEBUG")
    configure_logging("INFO")
    root = logging.getLogger()
    assert len(root.handlers) == 1


@pytest.fixture(autouse=True)
def reset_root_logger() -> None:
    """Reset root logger handlers after each test to avoid cross-test pollution."""
    yield  # type: ignore[misc]
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# MCP tool layer — CRITICAL-1: write_artifact forwards commit_refs
# ---------------------------------------------------------------------------


async def test_write_artifact_mcp_layer_forwards_commit_refs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """write_artifact MCP tool forwards commit_refs to the underlying _write_artifact."""
    settings = _make_settings(monkeypatch)
    mock_write = AsyncMock(return_value={"artifact_id": "artifacts/test"})
    monkeypatch.setattr("cairn_mcp.server._write_artifact", mock_write)

    register_tools(
        settings=settings,
        s3=MagicMock(),
        vectors=MagicMock(),
        bedrock=MagicMock(),
    )
    tool = await _app.get_tool("write_artifact")
    await tool.fn(
        type="code_review",
        team="platform",
        project="cairn",
        tier=2,
        date="2026-06-12",
        title="Test",
        description="A test.",
        content="## Summary\n\nOK.",
        visibility="shared",
        commit_refs=["abc1234"],
    )

    mock_write.assert_awaited_once()
    _, call_kwargs = mock_write.call_args
    assert call_kwargs["commit_refs"] == ["abc1234"]


# ---------------------------------------------------------------------------
# MCP tool layer — T46: write_artifact / list_artifacts forward references
# ---------------------------------------------------------------------------


async def test_write_artifact_mcp_layer_forwards_references(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """write_artifact MCP tool forwards references to the underlying _write_artifact."""
    settings = _make_settings(monkeypatch)
    mock_write = AsyncMock(return_value={"artifact_id": "artifacts/test"})
    monkeypatch.setattr("cairn_mcp.server._write_artifact", mock_write)

    register_tools(
        settings=settings,
        s3=MagicMock(),
        vectors=MagicMock(),
        bedrock=MagicMock(),
    )
    tool = await _app.get_tool("write_artifact")
    await tool.fn(
        type="code_review",
        team="platform",
        project="cairn",
        tier=2,
        date="2026-06-12",
        title="Test",
        description="A test.",
        content="## Summary\n\nOK.",
        visibility="shared",
        references=["a-1"],
    )

    mock_write.assert_awaited_once()
    _, call_kwargs = mock_write.call_args
    assert call_kwargs["references"] == ["a-1"]


# ---------------------------------------------------------------------------
# MCP tool layer — C-3: overwrite flag is reachable by MCP callers
# ---------------------------------------------------------------------------


async def test_write_artifact_mcp_layer_forwards_overwrite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """write_artifact MCP tool forwards overwrite to the underlying _write_artifact."""
    settings = _make_settings(monkeypatch)
    mock_write = AsyncMock(return_value={"artifact_id": "artifacts/test"})
    monkeypatch.setattr("cairn_mcp.server._write_artifact", mock_write)

    register_tools(
        settings=settings,
        s3=MagicMock(),
        vectors=MagicMock(),
        bedrock=MagicMock(),
    )
    tool = await _app.get_tool("write_artifact")
    await tool.fn(
        type="code_review",
        team="platform",
        project="cairn",
        tier=2,
        date="2026-06-12",
        title="Test",
        description="A test.",
        content="## Summary\n\nOK.",
        visibility="shared",
        overwrite=True,
    )

    mock_write.assert_awaited_once()
    _, call_kwargs = mock_write.call_args
    assert call_kwargs["overwrite"] is True


async def test_write_artifact_mcp_layer_overwrite_defaults_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """write_artifact MCP tool defaults overwrite to False when the caller omits it."""
    settings = _make_settings(monkeypatch)
    mock_write = AsyncMock(return_value={"artifact_id": "artifacts/test"})
    monkeypatch.setattr("cairn_mcp.server._write_artifact", mock_write)

    register_tools(
        settings=settings,
        s3=MagicMock(),
        vectors=MagicMock(),
        bedrock=MagicMock(),
    )
    tool = await _app.get_tool("write_artifact")
    await tool.fn(
        type="code_review",
        team="platform",
        project="cairn",
        tier=2,
        date="2026-06-12",
        title="Test",
        description="A test.",
        content="## Summary\n\nOK.",
        visibility="shared",
    )

    mock_write.assert_awaited_once()
    _, call_kwargs = mock_write.call_args
    assert call_kwargs["overwrite"] is False


async def test_write_artifacts_mcp_layer_forwards_overwrite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """write_artifacts MCP tool forwards the batch-level overwrite to _write_artifacts."""
    settings = _make_settings(monkeypatch)
    mock_write_batch = AsyncMock(return_value={"results": []})
    monkeypatch.setattr("cairn_mcp.server._write_artifacts", mock_write_batch)

    register_tools(
        settings=settings,
        s3=MagicMock(),
        vectors=MagicMock(),
        bedrock=MagicMock(),
    )
    tool = await _app.get_tool("write_artifacts")
    await tool.fn(artifacts=[], overwrite=True)

    mock_write_batch.assert_awaited_once()
    _, call_kwargs = mock_write_batch.call_args
    assert call_kwargs["overwrite"] is True


# ---------------------------------------------------------------------------
# MCP tool layer — CRITICAL-2: list_artifacts forwards commit_refs
# ---------------------------------------------------------------------------


async def test_list_artifacts_mcp_layer_forwards_commit_refs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """list_artifacts MCP tool forwards commit_refs to the underlying _list_artifacts."""
    settings = _make_settings(monkeypatch)
    mock_list: AsyncMock = AsyncMock(return_value={"artifacts": []})
    monkeypatch.setattr("cairn_mcp.server._list_artifacts", mock_list)

    register_tools(
        settings=settings,
        s3=MagicMock(),
        vectors=MagicMock(),
        bedrock=MagicMock(),
    )
    tool = await _app.get_tool("list_artifacts")
    await tool.fn(commit_refs=["abc1234"])

    mock_list.assert_awaited_once()
    _, call_kwargs = mock_list.call_args
    assert call_kwargs["commit_refs"] == ["abc1234"]


async def test_list_artifacts_mcp_layer_forwards_references(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """list_artifacts MCP tool forwards references to the underlying _list_artifacts."""
    settings = _make_settings(monkeypatch)
    mock_list: AsyncMock = AsyncMock(return_value={"artifacts": []})
    monkeypatch.setattr("cairn_mcp.server._list_artifacts", mock_list)

    register_tools(
        settings=settings,
        s3=MagicMock(),
        vectors=MagicMock(),
        bedrock=MagicMock(),
    )
    tool = await _app.get_tool("list_artifacts")
    await tool.fn(references=["a-1"])

    mock_list.assert_awaited_once()
    _, call_kwargs = mock_list.call_args
    assert call_kwargs["references"] == ["a-1"]


# ---------------------------------------------------------------------------
# T49 — link_commit superseded by link_metadata
# ---------------------------------------------------------------------------


async def test_link_commit_no_longer_registered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """link_commit (p10-t38) is retired — it must not be registered on the app
    once link_metadata (T49) supersedes it."""
    settings = _make_settings(monkeypatch)

    register_tools(
        settings=settings,
        s3=MagicMock(),
        vectors=MagicMock(),
        bedrock=MagicMock(),
    )
    tool = await _app.get_tool("link_commit")
    assert tool is None


async def test_link_metadata_registered_and_forwards_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """link_metadata is registered and forwards artifact_ids/commit_refs/references
    to the underlying _link_metadata implementation."""
    settings = _make_settings(monkeypatch)
    mock_link: AsyncMock = AsyncMock(
        return_value={"linked": 1, "skipped": 0, "next_since_ulid": "01ABC"}
    )
    monkeypatch.setattr("cairn_mcp.server._link_metadata", mock_link)

    register_tools(
        settings=settings,
        s3=MagicMock(),
        vectors=MagicMock(),
        bedrock=MagicMock(),
    )
    tool = await _app.get_tool("link_metadata")
    assert tool is not None
    await tool.fn(artifact_ids=["artifacts/a1"], commit_refs=["abc1234"], references=["a-1"])

    mock_link.assert_awaited_once()
    _, call_kwargs = mock_link.call_args
    assert call_kwargs["artifact_ids"] == ["artifacts/a1"]
    assert call_kwargs["commit_refs"] == ["abc1234"]
    assert call_kwargs["references"] == ["a-1"]


async def test_propose_commit_links_still_registered_and_functional(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """propose_commit_links (FR-31) is retained unchanged by T49 — still registered
    and still forwards its arguments to the underlying implementation."""
    settings = _make_settings(monkeypatch)
    mock_propose: AsyncMock = AsyncMock(return_value={"proposed": []})
    monkeypatch.setattr("cairn_mcp.server._propose_commit_links", mock_propose)

    register_tools(
        settings=settings,
        s3=MagicMock(),
        vectors=MagicMock(),
        bedrock=MagicMock(),
    )
    tool = await _app.get_tool("propose_commit_links")
    assert tool is not None
    await tool.fn(commit_sha="abc1234", since_ulid="01ABC")

    mock_propose.assert_awaited_once()
    _, call_kwargs = mock_propose.call_args
    assert call_kwargs["commit_sha"] == "abc1234"
    assert call_kwargs["since_ulid"] == "01ABC"
