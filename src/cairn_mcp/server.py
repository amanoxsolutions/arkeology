"""FastMCP server instance and transport configuration for cairn-mcp."""

import importlib.metadata
import logging
from typing import Any

import fastmcp

from cairn_mcp.clients.interfaces import (
    BedrockClientInterface,
    S3ClientInterface,
    VectorsClientInterface,
)
from cairn_mcp.config import Settings
from cairn_mcp.tools.read import read_artifact as _read_artifact
from cairn_mcp.tools.search import search_artifacts as _search_artifacts
from cairn_mcp.tools.write import write_artifact as _write_artifact

logger = logging.getLogger(__name__)

_version = importlib.metadata.version("cairn-mcp")
_app = fastmcp.FastMCP(name="cairn-mcp", version=_version)


def register_tools(
    settings: Settings,
    s3: S3ClientInterface,
    vectors: VectorsClientInterface,
    bedrock: BedrockClientInterface,
) -> None:
    """Register all MCP tools on the FastMCP app with injected clients.

    Called once from ``__main__.py`` after clients are constructed. Each tool
    closure captures the live client references so unit tests can invoke the
    underlying functions directly without going through FastMCP.

    Args:
        settings: Validated server configuration.
        s3: Concrete S3 client.
        vectors: Concrete S3 Vectors client.
        bedrock: Concrete Bedrock client.
    """

    @_app.tool()
    async def write_artifact(
        type: str,
        team: str,
        project: str,
        tier: int,
        date: str,
        title: str,
        description: str,
        content: str,
        visibility: str,
        feature_tags: list[str] | None = None,
        author_role: str | None = None,
        source_artifacts: list[str] | None = None,
        status: str = "active",
    ) -> dict[str, Any]:
        """Write an artifact to S3 and index its sections in S3 Vectors."""
        return await _write_artifact(
            settings=settings,
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            type=type,
            team=team,
            project=project,
            tier=tier,
            date=date,
            title=title,
            description=description,
            content=content,
            visibility=visibility,
            feature_tags=feature_tags,
            author_role=author_role,
            source_artifacts=source_artifacts,
            status=status,
        )

    @_app.tool()
    async def search_artifacts(
        query: str,
        top_k: int | None = None,
        type: str | None = None,
        feature_tags: list[str] | None = None,
        team: str | None = None,
        project: str | None = None,
        tier: int | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        """Search artifacts by semantic similarity."""
        return await _search_artifacts(
            settings=settings,
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            query=query,
            top_k=top_k,
            type=type,
            feature_tags=feature_tags,
            team=team,
            project=project,
            tier=tier,
            status=status,
        )

    @_app.tool()
    async def read_artifact(artifact_id: str) -> dict[str, Any]:
        """Read a single artifact's content and metadata from S3."""
        return await _read_artifact(
            settings=settings,
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            artifact_id=artifact_id,
        )


def run() -> None:
    """Start the cairn-mcp MCP server using stdio transport.

    Logs startup and delegates to FastMCP's stdio run loop.
    FastMCP handles SIGTERM/SIGINT natively via its event loop.
    """
    logger.info("cairn-mcp v%s starting", _version)
    _app.run(transport="stdio")
    logger.info("cairn-mcp shutting down")
