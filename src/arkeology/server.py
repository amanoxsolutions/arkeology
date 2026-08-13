"""FastMCP server instance and transport configuration for arkeology."""

import importlib.metadata
import logging
from typing import Any

import fastmcp
from fastmcp.apps.config import AppConfig
from fastmcp.server.context import Context
from fastmcp.tools.base import ToolResult

from arkeology.clients.interfaces import (
    BedrockClientInterface,
    S3ClientInterface,
    VectorsClientInterface,
)
from arkeology.config import Settings
from arkeology.resources import register_data_resources, register_resources, register_ui_resource
from arkeology.tools.archive import archive_artifact as _archive_artifact
from arkeology.tools.delete import delete_artifact as _delete_artifact
from arkeology.tools.freshness import check_synthesis_freshness as _check_synthesis_freshness
from arkeology.tools.health import health_check as _health_check
from arkeology.tools.link_metadata import link_metadata as _link_metadata
from arkeology.tools.list import list_artifacts as _list_artifacts
from arkeology.tools.migrate_artifacts import migrate_artifacts as _migrate_artifacts
from arkeology.tools.propose_commit_links import propose_commit_links as _propose_commit_links
from arkeology.tools.purge import purge_archived as _purge_archived
from arkeology.tools.read import read_artifact as _read_artifact
from arkeology.tools.reconcile import reconcile_index as _reconcile_index
from arkeology.tools.search import search_artifacts as _search_artifacts
from arkeology.tools.studio import arkeology_studio as _arkeology_studio
from arkeology.tools.synthesise import synthesise_artifacts as _synthesise_artifacts
from arkeology.tools.write import write_artifact as _write_artifact
from arkeology.tools.write_artifacts import write_artifacts as _write_artifacts

logger = logging.getLogger(__name__)

try:
    _version = importlib.metadata.version("arkeology")
except importlib.metadata.PackageNotFoundError:
    _version = "0.0.0-dev"
_app = fastmcp.FastMCP(name="arkeology", version=_version)
register_resources(_app)
register_ui_resource(_app)


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
        tags: list[str] | None = None,
        author_role: str | None = None,
        source_artifacts: list[str] | None = None,
        commit_refs: list[str] | None = None,
        references: list[str] | None = None,
        status: str = "active",
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Write an artifact to S3 and index its sections in S3 Vectors.

        A write whose generated key already exists is rejected with a
        validation_error unless overwrite=True is passed explicitly.
        """
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
            tags=tags,
            author_role=author_role,
            source_artifacts=source_artifacts,
            commit_refs=commit_refs,
            references=references,
            status=status,
            overwrite=overwrite,
        )

    @_app.tool()
    async def search_artifacts(
        query: str,
        top_k: int | None = None,
        type: str | None = None,
        tags: list[str] | None = None,
        team: str | None = None,
        project: str | None = None,
        tier: int | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        """Search artifacts by semantic similarity.

        status defaults to "active"; pass the explicit sentinel status="all" to
        search regardless of status.
        """
        return await _search_artifacts(
            settings=settings,
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            query=query,
            top_k=top_k,
            type=type,
            tags=tags,
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

    @_app.tool()
    async def list_artifacts(
        type: str | None = None,
        team: str | None = None,
        project: str | None = None,
        status: str = "active",
        tags: list[str] | None = None,
        tier: int | None = None,
        commit_refs: list[str] | None = None,
        references: list[str] | None = None,
    ) -> dict[str, Any]:
        """List artifacts by metadata filters without a semantic query.

        status defaults to "active"; pass the explicit sentinel status="all" to
        return artifacts regardless of status.
        """
        return await _list_artifacts(
            settings=settings,
            s3=s3,
            vectors=vectors,
            bedrock=None,
            type=type,
            team=team,
            project=project,
            status=status,
            tags=tags,
            tier=tier,
            commit_refs=commit_refs,
            references=references,
        )

    @_app.tool()
    async def archive_artifact(artifact_id: str) -> dict[str, Any]:
        """Archive an artifact by setting its status to 'inactive'."""
        return await _archive_artifact(
            settings=settings,
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            artifact_id=artifact_id,
        )

    @_app.tool()
    async def delete_artifact(
        artifact_id: str,
        confirm: bool = False,
    ) -> dict[str, Any]:
        """Hard-delete a single artifact from S3 and the vector index."""
        return await _delete_artifact(
            settings=settings,
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            artifact_id=artifact_id,
            confirm=confirm,
        )

    @_app.tool()
    async def purge_archived(confirm: bool = False) -> dict[str, Any]:
        """Hard-delete all archived (inactive) artifacts in the own scope."""
        return await _purge_archived(
            settings=settings,
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            confirm=confirm,
        )

    @_app.tool()
    async def health_check() -> dict[str, Any]:
        """Probe all configured components and return a per-component status."""
        return await _health_check(
            settings=settings,
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
        )

    @_app.tool()
    async def synthesise_artifacts(
        query: str,
        top_k: int = 10,
        type: str | None = None,
        tags: list[str] | None = None,
        team: str | None = None,
        project: str | None = None,
    ) -> dict[str, Any]:
        """Search artifacts and return full content for the top results."""
        return await _synthesise_artifacts(
            settings=settings,
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            query=query,
            top_k=top_k,
            type=type,
            tags=tags,
            team=team,
            project=project,
        )

    @_app.tool()
    async def reconcile_index() -> dict[str, Any]:
        """Replay failure log and scan for orphaned S3 objects, re-indexing any found."""
        return await _reconcile_index(
            settings=settings,
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
        )

    @_app.tool()
    async def check_synthesis_freshness(confirm: bool = False) -> dict[str, Any]:
        """Audit synthesis freshness; delete malformed (empty-source) syntheses if confirm=True."""
        return await _check_synthesis_freshness(
            settings=settings,
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            confirm=confirm,
        )

    @_app.tool()
    async def write_artifacts(
        artifacts: list[dict[str, Any]],
        overwrite: bool = False,
        artifact_concurrency: int = 3,
    ) -> dict[str, Any]:
        """Write a list of artifact descriptors concurrently.

        overwrite is a batch-level default for the collision guard; each
        descriptor may include its own "overwrite" key to override it.

        artifact_concurrency bounds how many artifacts are written concurrently
        (p10-t39). Must be in [1, 15]; values above 15 are capped to 15 and values
        below 1 are substituted with the default 3 — both cases add a top-level
        "warning" field to the response rather than rejecting the call. Defaults
        to 3 when omitted.
        """
        return await _write_artifacts(
            settings=settings,
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            artifacts=artifacts,
            overwrite=overwrite,
            artifact_concurrency=artifact_concurrency,
        )

    @_app.tool()
    async def migrate_artifacts(
        descriptors: list[dict[str, Any]],
        dry_run: bool = True,
        artifact_concurrency: int = 3,
    ) -> dict[str, Any]:
        """Migrate artifacts, generating missing descriptions via Nova Lite.

        Never overwrites: a descriptor whose generated key already exists is skipped
        (not written, not an error) and reported under "skipped_existing" — re-running
        a migration over an already-imported corpus is idempotent and non-destructive.
        """
        return await _migrate_artifacts(
            settings=settings,
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            descriptors=descriptors,
            dry_run=dry_run,
            artifact_concurrency=artifact_concurrency,
        )

    @_app.tool()
    async def propose_commit_links(
        commit_sha: str,
        since_ulid: str | None = None,
    ) -> dict[str, Any]:
        """Discover own-scope artifacts with no commit_refs, optionally since a session ULID."""
        return await _propose_commit_links(
            settings=settings,
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            commit_sha=commit_sha,
            since_ulid=since_ulid,
        )

    @_app.tool()
    async def link_metadata(
        artifact_ids: list[str],
        commit_refs: list[str] | None = None,
        references: list[str] | None = None,
    ) -> dict[str, Any]:
        """Backfill commit_refs and/or references onto existing own-scope artifacts.

        Dual-writes the merged, deduplicated values to durable S3 annotations
        (first) and vector metadata (second), reusing existing embeddings — no
        Bedrock call, no content mutation, no last_edited_ulid change.
        """
        return await _link_metadata(
            settings=settings,
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            artifact_ids=artifact_ids,
            commit_refs=commit_refs,
            references=references,
        )

    @_app.tool(app=AppConfig(resource_uri="ui://arkeology-studio/index.html"))
    async def arkeology_studio(ctx: Context) -> ToolResult:
        """Browse artifacts in Arkeology Studio — triggers the inline MCP App browser."""
        return await _arkeology_studio(
            settings=settings,
            s3=s3,
            vectors=vectors,
            ctx=ctx,
        )

    register_data_resources(_app, settings, s3, vectors, bedrock)


def run() -> None:
    """Start the arkeology MCP server using stdio transport.

    Logs startup and delegates to FastMCP's stdio run loop.
    FastMCP handles SIGTERM/SIGINT natively via its event loop.
    """
    logger.info("arkeology v%s starting", _version)
    _app.run(transport="stdio")
    logger.info("arkeology shutting down")
