"""Tests for server startup and logging configuration."""

import logging
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

from arkeology.__main__ import configure_logging
from arkeology.server import _app, register_tools
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
    monkeypatch.setattr("arkeology.server._write_artifact", mock_write)

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
        project="arkeology",
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
    monkeypatch.setattr("arkeology.server._write_artifact", mock_write)

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
        project="arkeology",
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
# MCP tool layer — the overwrite flag is reachable by MCP callers
# ---------------------------------------------------------------------------


async def test_write_artifact_mcp_layer_forwards_overwrite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """write_artifact MCP tool forwards overwrite to the underlying _write_artifact."""
    settings = _make_settings(monkeypatch)
    mock_write = AsyncMock(return_value={"artifact_id": "artifacts/test"})
    monkeypatch.setattr("arkeology.server._write_artifact", mock_write)

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
        project="arkeology",
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
    monkeypatch.setattr("arkeology.server._write_artifact", mock_write)

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
        project="arkeology",
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
    monkeypatch.setattr("arkeology.server._write_artifacts", mock_write_batch)

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
# MCP tool layer — file_extension is reachable by MCP callers
# ---------------------------------------------------------------------------


async def test_write_artifact_mcp_layer_forwards_file_extension(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """write_artifact MCP tool forwards file_extension to the underlying _write_artifact,
    and defaults it to ".md" when the caller omits it — the module contract lists it in
    the signature, so the MCP wrapper must expose it rather than silently pinning ".md"."""
    settings = _make_settings(monkeypatch)
    mock_write = AsyncMock(return_value={"artifact_id": "artifacts/test"})
    monkeypatch.setattr("arkeology.server._write_artifact", mock_write)

    register_tools(
        settings=settings,
        s3=MagicMock(),
        vectors=MagicMock(),
        bedrock=MagicMock(),
    )
    tool = await _app.get_tool("write_artifact")
    common = {
        "type": "code_review",
        "team": "platform",
        "project": "arkeology",
        "tier": 2,
        "date": "2026-06-12",
        "title": "Test",
        "description": "A test.",
        "content": "## Summary\n\nOK.",
        "visibility": "shared",
    }
    await tool.fn(**common, file_extension=".txt")
    await tool.fn(**common)

    assert mock_write.call_args_list[0].kwargs["file_extension"] == ".txt"
    assert mock_write.call_args_list[1].kwargs["file_extension"] == ".md"


async def test_write_artifacts_mcp_layer_forwards_file_extension(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """write_artifacts MCP tool forwards the batch-level file_extension to
    _write_artifacts, and defaults it to ".md" when the caller omits it."""
    settings = _make_settings(monkeypatch)
    mock_write_batch = AsyncMock(return_value={"results": []})
    monkeypatch.setattr("arkeology.server._write_artifacts", mock_write_batch)

    register_tools(
        settings=settings,
        s3=MagicMock(),
        vectors=MagicMock(),
        bedrock=MagicMock(),
    )
    tool = await _app.get_tool("write_artifacts")
    await tool.fn(artifacts=[], file_extension=".txt")
    await tool.fn(artifacts=[])

    assert mock_write_batch.call_args_list[0].kwargs["file_extension"] == ".txt"
    assert mock_write_batch.call_args_list[1].kwargs["file_extension"] == ".md"


# ---------------------------------------------------------------------------
# MCP tool layer — write_artifacts exposes artifact_concurrency
# ---------------------------------------------------------------------------


async def test_write_artifacts_mcp_layer_forwards_artifact_concurrency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """write_artifacts MCP tool forwards a caller-supplied artifact_concurrency to
    the underlying _write_artifacts — requirements.md FR-25 / p10-t39 document it as
    caller-controllable, so the MCP signature must actually expose it."""
    settings = _make_settings(monkeypatch)
    mock_write_batch = AsyncMock(return_value={"results": []})
    monkeypatch.setattr("arkeology.server._write_artifacts", mock_write_batch)

    register_tools(
        settings=settings,
        s3=MagicMock(),
        vectors=MagicMock(),
        bedrock=MagicMock(),
    )
    tool = await _app.get_tool("write_artifacts")
    await tool.fn(artifacts=[], artifact_concurrency=10)

    mock_write_batch.assert_awaited_once()
    _, call_kwargs = mock_write_batch.call_args
    assert call_kwargs["artifact_concurrency"] == 10


async def test_write_artifacts_mcp_layer_artifact_concurrency_defaults_to_three(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """write_artifacts MCP tool defaults artifact_concurrency to 3 when the caller
    omits it, matching the inner function's default."""
    settings = _make_settings(monkeypatch)
    mock_write_batch = AsyncMock(return_value={"results": []})
    monkeypatch.setattr("arkeology.server._write_artifacts", mock_write_batch)

    register_tools(
        settings=settings,
        s3=MagicMock(),
        vectors=MagicMock(),
        bedrock=MagicMock(),
    )
    tool = await _app.get_tool("write_artifacts")
    await tool.fn(artifacts=[])

    mock_write_batch.assert_awaited_once()
    _, call_kwargs = mock_write_batch.call_args
    assert call_kwargs["artifact_concurrency"] == 3


async def test_write_artifacts_mcp_layer_out_of_range_artifact_concurrency_forwarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An out-of-range artifact_concurrency is forwarded as-is (not pre-validated at
    the MCP layer) — the inner function owns clamping + warning behaviour, so the
    MCP layer must not silently reinterpret or reject it."""
    settings = _make_settings(monkeypatch)
    mock_write_batch = AsyncMock(return_value={"results": [], "warning": "capped"})
    monkeypatch.setattr("arkeology.server._write_artifacts", mock_write_batch)

    register_tools(
        settings=settings,
        s3=MagicMock(),
        vectors=MagicMock(),
        bedrock=MagicMock(),
    )
    tool = await _app.get_tool("write_artifacts")
    result = await tool.fn(artifacts=[], artifact_concurrency=20)

    mock_write_batch.assert_awaited_once()
    _, call_kwargs = mock_write_batch.call_args
    assert call_kwargs["artifact_concurrency"] == 20
    assert result.get("warning") == "capped"


# ---------------------------------------------------------------------------
# MCP tool layer — CRITICAL-2: list_artifacts forwards commit_refs
# ---------------------------------------------------------------------------


async def test_list_artifacts_mcp_layer_forwards_commit_refs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """list_artifacts MCP tool forwards commit_refs to the underlying _list_artifacts."""
    settings = _make_settings(monkeypatch)
    mock_list: AsyncMock = AsyncMock(return_value={"artifacts": []})
    monkeypatch.setattr("arkeology.server._list_artifacts", mock_list)

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


async def test_list_artifacts_mcp_layer_rejects_references_kwarg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """list_artifacts MCP tool no longer accepts references= (T59): since T58
    stopped writing references into vector metadata, the filter parameter is
    removed outright rather than silently ignored."""
    settings = _make_settings(monkeypatch)
    mock_list: AsyncMock = AsyncMock(return_value={"artifacts": []})
    monkeypatch.setattr("arkeology.server._list_artifacts", mock_list)

    register_tools(
        settings=settings,
        s3=MagicMock(),
        vectors=MagicMock(),
        bedrock=MagicMock(),
    )
    tool = await _app.get_tool("list_artifacts")
    with pytest.raises(TypeError):
        await tool.fn(references=["a-1"])  # type: ignore[call-arg]

    mock_list.assert_not_awaited()


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
    monkeypatch.setattr("arkeology.server._link_metadata", mock_link)

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
    monkeypatch.setattr("arkeology.server._propose_commit_links", mock_propose)

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


async def test_register_tools_registers_full_tool_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """register_tools must expose exactly the 16 documented MCP tools —
    catches an accidental omission or an orphaned extra registration that individual
    per-tool tests wouldn't notice."""
    settings = _make_settings(monkeypatch)

    register_tools(
        settings=settings,
        s3=MagicMock(),
        vectors=MagicMock(),
        bedrock=MagicMock(),
    )
    tools = await _app.list_tools()

    assert {t.name for t in tools} == {
        "write_artifact",
        "search_artifacts",
        "read_artifact",
        "list_artifacts",
        "archive_artifact",
        "delete_artifact",
        "purge_archived",
        "health_check",
        "synthesise_artifacts",
        "reconcile_index",
        "check_synthesis_freshness",
        "write_artifacts",
        "migrate_artifacts",
        "propose_commit_links",
        "link_metadata",
        "arkeology_studio",
    }
