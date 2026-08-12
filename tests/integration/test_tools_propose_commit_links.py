"""Integration tests for arkeology.tools.propose_commit_links.

Requires real AWS credentials and configured .env file.
All tests decorated with @pytest.mark.integration.

M-16 (Phase 12 review, Cluster E): propose_commit_links had zero integration
coverage. These tests write real artifacts via write_artifact and confirm the
discovery query (own-scope, no commit_refs, optional since_ulid bound) behaves
correctly against real S3 Vectors.

Note on filter semantics: propose_commit_links resolves candidates via
VectorsClientImpl.list_vectors_by_metadata, which the S3 Vectors ListVectors
API does not support server-side filtering for — matches_filter runs
client-side, in-process, against every page. That code path is therefore
correctly covered by the (non-circular) unit suite. The "$gte on a ULID
string" server-side semantics this tool's filter *shape* exercises are pinned
against real AWS QueryVectors filtering in
tests/integration/clients/test_vectors_filter_semantics.py instead, since that
is the API that actually evaluates filters server-side.
"""

import asyncio

import pytest
from ulid import ULID

from arkeology.clients.bedrock import BedrockClientImpl
from arkeology.clients.s3 import S3ClientImpl
from arkeology.clients.vectors import VectorsClientImpl
from arkeology.config import Settings
from arkeology.tools.delete import delete_artifact
from arkeology.tools.link_metadata import link_metadata
from arkeology.tools.propose_commit_links import propose_commit_links
from arkeology.tools.write import write_artifact


@pytest.fixture(scope="session")
def settings() -> Settings:
    """Session-scoped Settings constructed from environment after load_env runs."""
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


_BASE_KWARGS: dict = {
    "type": "code_review",
    "team": "platform",
    "project": "arkeology",
    "tier": 2,
    "date": "2026-05-30",
    "status": "active",
    "visibility": "shared",
}


@pytest.mark.integration
async def test_propose_commit_links_finds_unlinked_artifact(
    settings: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """A freshly written artifact with no commit_refs is proposed."""
    artifact_id: str = ""
    try:
        result = await write_artifact(
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            settings=settings,
            title="propose_commit_links integration unlinked",
            description="Unlinked artifact for propose_commit_links integration test.",
            content="## Summary\n\nUnlinked content.",
            **_BASE_KWARGS,
        )
        artifact_id = result["artifact_id"]

        proposal = await propose_commit_links(
            settings=settings,
            vectors=vectors,
            commit_sha="deadbeef1234",
        )

        assert "proposed" in proposal
        ids = [e["artifact_id"] for e in proposal["proposed"]]
        assert artifact_id in ids
        assert proposal["commit_sha"] == "deadbeef1234"
    finally:
        if artifact_id:
            await delete_artifact(
                settings=settings,
                s3=s3,
                vectors=vectors,
                bedrock=bedrock,
                artifact_id=artifact_id,
                confirm=True,
            )


@pytest.mark.integration
async def test_propose_commit_links_excludes_linked_artifact(
    settings: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """An artifact whose commit_refs were backfilled via link_metadata is excluded."""
    artifact_id: str = ""
    try:
        result = await write_artifact(
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            settings=settings,
            title="propose_commit_links integration linked",
            description="Linked artifact for propose_commit_links integration test.",
            content="## Summary\n\nLinked content.",
            **_BASE_KWARGS,
        )
        artifact_id = result["artifact_id"]

        link_result = await link_metadata(
            settings=settings,
            s3=s3,
            vectors=vectors,
            artifact_ids=[artifact_id],
            commit_refs=["cafef00d"],
        )
        assert link_result["linked"] == 1

        proposal = await propose_commit_links(
            settings=settings,
            vectors=vectors,
            commit_sha="deadbeef1234",
        )

        ids = [e["artifact_id"] for e in proposal["proposed"]]
        assert artifact_id not in ids
    finally:
        if artifact_id:
            await delete_artifact(
                settings=settings,
                s3=s3,
                vectors=vectors,
                bedrock=bedrock,
                artifact_id=artifact_id,
                confirm=True,
            )


@pytest.mark.integration
async def test_propose_commit_links_since_ulid_excludes_earlier_artifact(
    settings: Settings,
    s3: S3ClientImpl,
    vectors: VectorsClientImpl,
    bedrock: BedrockClientImpl,
) -> None:
    """since_ulid bounds candidates to those written at/after the given ULID.

    Writes one artifact, captures a ULID cursor strictly after it, writes a
    second artifact, then confirms since_ulid=<cursor> includes only the
    second — proving the real $gte-style bound (evaluated client-side by
    list_vectors_by_metadata's matches_filter, per the module docstring) holds
    against real vector metadata written by the real write path.

    ULID lexicographic ordering is dominated by its 48-bit millisecond
    timestamp component, but ties within the same millisecond fall back to a
    random suffix with no guaranteed ordering — a real risk for two writes and
    a cursor generated back-to-back in-process. A short sleep around the
    cursor generation forces each ULID onto a distinct millisecond so the
    comparison is deterministic rather than occasionally flaky.
    """
    earlier_id: str = ""
    later_id: str = ""
    try:
        earlier = await write_artifact(
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            settings=settings,
            title="propose_commit_links integration since-ulid earlier",
            description="Earlier artifact for since_ulid integration test.",
            content="## Summary\n\nEarlier content.",
            **_BASE_KWARGS,
        )
        earlier_id = earlier["artifact_id"]

        await asyncio.sleep(0.05)
        cursor_ulid = str(ULID())
        await asyncio.sleep(0.05)

        later = await write_artifact(
            s3=s3,
            vectors=vectors,
            bedrock=bedrock,
            settings=settings,
            title="propose_commit_links integration since-ulid later",
            description="Later artifact for since_ulid integration test.",
            content="## Summary\n\nLater content.",
            **_BASE_KWARGS,
        )
        later_id = later["artifact_id"]

        proposal = await propose_commit_links(
            settings=settings,
            vectors=vectors,
            commit_sha="deadbeef1234",
            since_ulid=cursor_ulid,
        )

        ids = [e["artifact_id"] for e in proposal["proposed"]]
        assert later_id in ids
        assert earlier_id not in ids
    finally:
        for aid in (earlier_id, later_id):
            if aid:
                await delete_artifact(
                    settings=settings,
                    s3=s3,
                    vectors=vectors,
                    bedrock=bedrock,
                    artifact_id=aid,
                    confirm=True,
                )
