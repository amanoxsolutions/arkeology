"""Unit tests for arkeology.tools._section_pipeline.

Covers the shared section-embedding pipeline (min-length filter, max-sections cap,
per-section truncation, and embedding-text construction) factored out of write.py
so write_artifact and reconcile_index apply byte-for-byte identical rules
(Phase 12 review M-3).

Also includes a write/reconcile parity test proving the exact text sent to
``bedrock.embed`` is identical between the two call paths for a section that gets
truncated — the RED proof for M-3.
"""

from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from arkeology.clients.fakes.fake_bedrock import FakeBedrockClient
from arkeology.clients.s3 import S3ClientImpl
from arkeology.clients.vectors import VectorsClientImpl
from arkeology.config import Settings
from arkeology.tools._section_pipeline import (
    build_document_embedding_text,
    build_section_embedding_text,
    prepare_sections_for_embedding,
)
from arkeology.tools.reconcile import reconcile_index
from arkeology.tools.write import write_artifact
from tests.unit.conftest import _make_settings as _make_settings_base


def _make_settings(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> Settings:
    return _make_settings_base(monkeypatch, **overrides)


def _make_sections_content(count: int, body_length: int = 120) -> str:
    """Build Markdown with ``count`` H2 sections, each body ``body_length`` chars long."""
    parts = [f"## Section {i}\n\n{'x' * body_length}" for i in range(1, count + 1)]
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# build_section_embedding_text
# ---------------------------------------------------------------------------


def test_section_embed_starts_with_title() -> None:
    """build_section_embedding_text output starts with 'Title: {title}'."""
    text = build_section_embedding_text(
        title="Fix auth bug",
        artifact_type="code_review",
        tags=[],
        section_heading="Summary",
        section_body="All looks good.",
    )
    assert text.startswith("Title: Fix auth bug")


def test_section_embed_contains_type() -> None:
    """build_section_embedding_text output contains 'Type: {type}'."""
    text = build_section_embedding_text(
        title="Fix auth bug",
        artifact_type="code_review",
        tags=[],
        section_heading="Summary",
        section_body="All looks good.",
    )
    assert "Type: code_review" in text


def test_section_embed_contains_tags_when_present() -> None:
    """build_section_embedding_text output contains tags when tags non-empty."""
    text = build_section_embedding_text(
        title="Fix auth bug",
        artifact_type="code_review",
        tags=["auth", "security"],
        section_heading="Summary",
        section_body="All looks good.",
    )
    assert "Tags:" in text
    assert "auth" in text
    assert "security" in text


def test_section_embed_omits_tags_when_empty() -> None:
    """build_section_embedding_text omits the Tags line when tags is empty."""
    text = build_section_embedding_text(
        title="Fix auth bug",
        artifact_type="code_review",
        tags=[],
        section_heading="Summary",
        section_body="All looks good.",
    )
    assert "Tags:" not in text


def test_section_embed_contains_heading_and_body() -> None:
    """build_section_embedding_text contains the section heading and body."""
    text = build_section_embedding_text(
        title="Fix auth bug",
        artifact_type="code_review",
        tags=[],
        section_heading="Summary",
        section_body="All looks good.",
    )
    assert "Summary" in text
    assert "All looks good." in text


# ---------------------------------------------------------------------------
# build_document_embedding_text
# ---------------------------------------------------------------------------


def test_document_embed_starts_with_title() -> None:
    """build_document_embedding_text output starts with 'Title: {title}'."""
    text = build_document_embedding_text(
        title="Fix auth bug",
        artifact_type="code_review",
        tags=[],
        description="Review of the auth module.",
    )
    assert text.startswith("Title: Fix auth bug")


def test_document_embed_contains_type() -> None:
    """build_document_embedding_text output contains 'Type: {type}'."""
    text = build_document_embedding_text(
        title="Fix auth bug",
        artifact_type="code_review",
        tags=[],
        description="Review of the auth module.",
    )
    assert "Type: code_review" in text


def test_document_embed_contains_description() -> None:
    """build_document_embedding_text output contains 'Description: {description}'."""
    text = build_document_embedding_text(
        title="Fix auth bug",
        artifact_type="code_review",
        tags=[],
        description="Review of the auth module.",
    )
    assert "Description: Review of the auth module." in text


def test_document_embed_omits_tags_when_empty() -> None:
    """build_document_embedding_text omits the Tags line when tags is empty."""
    text = build_document_embedding_text(
        title="Fix auth bug",
        artifact_type="code_review",
        tags=[],
        description="A description.",
    )
    assert "Tags:" not in text


def test_document_embed_contains_tags_when_present() -> None:
    """build_document_embedding_text contains tags when tags non-empty."""
    text = build_document_embedding_text(
        title="Fix auth bug",
        artifact_type="code_review",
        tags=["payments"],
        description="A description.",
    )
    assert "Tags:" in text


# ---------------------------------------------------------------------------
# prepare_sections_for_embedding — min-length filter, max-sections cap, truncation
# ---------------------------------------------------------------------------


def test_prepare_sections_no_sections_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Content with no ``##`` headings → empty list (caller falls back to document-level)."""
    settings = _make_settings(monkeypatch)
    result = prepare_sections_for_embedding(
        "Just plain text, no headings.",
        title="T",
        artifact_type="code_review",
        tags=[],
        settings=settings,
    )
    assert result == []


def test_prepare_sections_min_length_filters_short_sections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sections shorter than embed_min_section_length are dropped."""
    settings = _make_settings(monkeypatch, EMBED_MIN_SECTION_LENGTH="50")
    content = (
        "## Short\n\n" + "x" * 10 + "\n\n"
        "## Long A\n\n" + "x" * 200 + "\n\n"
        "## Long B\n\n" + "x" * 200
    )
    result = prepare_sections_for_embedding(
        content, title="T", artifact_type="code_review", tags=[], settings=settings
    )
    assert [p.heading for p in result] == ["Long A", "Long B"]


def test_prepare_sections_max_sections_caps(monkeypatch: pytest.MonkeyPatch) -> None:
    """More sections than embed_max_sections → capped to the limit, in original order."""
    settings = _make_settings(monkeypatch, EMBED_MAX_SECTIONS="3")
    content = _make_sections_content(5)
    result = prepare_sections_for_embedding(
        content, title="T", artifact_type="code_review", tags=[], settings=settings
    )
    assert [p.heading for p in result] == ["Section 1", "Section 2", "Section 3"]


def test_prepare_sections_truncates_body_before_embedding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A section body longer than embed_max_section_length is truncated in embed_text,
    but the truncation is embedding-input-only (the pipeline never touches S3 content)."""
    settings = _make_settings(monkeypatch, EMBED_MAX_SECTION_LENGTH="50")
    body = "a" * 200
    content = f"## Long Section\n\n{body}"
    result = prepare_sections_for_embedding(
        content, title="T", artifact_type="code_review", tags=[], settings=settings
    )
    assert len(result) == 1
    assert "a" * 101 not in result[0].embed_text
    assert "a" * 50 in result[0].embed_text


def test_prepare_sections_zero_length_disables_truncation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """EMBED_MAX_SECTION_LENGTH=0 disables truncation — full body appears in embed_text."""
    settings = _make_settings(monkeypatch, EMBED_MAX_SECTION_LENGTH="0")
    body = "a" * 500
    content = f"## Long Section\n\n{body}"
    result = prepare_sections_for_embedding(
        content, title="T", artifact_type="code_review", tags=[], settings=settings
    )
    assert body in result[0].embed_text


def test_prepare_sections_filter_applied_before_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """Min-length filter runs before the max-sections cap (order matters)."""
    settings = _make_settings(monkeypatch, EMBED_MIN_SECTION_LENGTH="50", EMBED_MAX_SECTIONS="2")
    content = (
        "## Short\n\n" + "x" * 10 + "\n\n"
        "## Long A\n\n" + "x" * 120 + "\n\n"
        "## Long B\n\n" + "x" * 120 + "\n\n"
        "## Long C\n\n" + "x" * 120
    )
    result = prepare_sections_for_embedding(
        content, title="T", artifact_type="code_review", tags=[], settings=settings
    )
    # "Short" is filtered first; of the 3 remaining, only 2 survive the cap.
    assert [p.heading for p in result] == ["Long A", "Long B"]


# ---------------------------------------------------------------------------
# M-3 — write/reconcile parity: identical embed text for a truncated section
# ---------------------------------------------------------------------------

_M3_S3_META: dict[str, str] = {
    "type": "implementation_note",
    "team": "platform",
    "project": "arkeology",
    "tier": "2",
    "date": "2026-01-01",
    "status": "active",
    "title": "Parity Artifact",
    "visibility": "shared",
    "tags": "",
    "author_role": "",
    "description": "Parity test artifact.",
    "source_artifacts": "",
}


async def test_write_and_reconcile_embed_identical_truncated_text(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client_8: VectorsClientImpl,
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    """M-3 RED proof: a section that write_artifact truncates before embedding must be
    truncated identically when reconcile_index later re-embeds the same content — the
    exact text passed to bedrock.embed must match between the two paths.

    Before the fix, reconcile_index embedded the full untruncated body on every
    replay, sending different (longer) text to Bedrock than write_artifact did.
    """
    settings = _make_settings(
        monkeypatch,
        tmp_path=tmp_path,
        EMBED_MAX_SECTION_LENGTH="50",
        BEDROCK_EMBEDDING_DIMENSIONS="8",
    )
    long_body = "a" * 500
    content = f"## Long Section\n\n{long_body}"

    write_bedrock = FakeBedrockClient(dimension=8)
    write_embed_spy = mocker.spy(write_bedrock, "embed")

    write_result = await write_artifact(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_8,
        bedrock=write_bedrock,
        type="implementation_note",
        team="platform",
        project="arkeology",
        tier=2,
        date="2026-01-01",
        title="Parity Artifact",
        description="Parity test artifact.",
        content=content,
        visibility="shared",
    )
    assert "error" not in write_result
    assert write_embed_spy.call_count == 1
    write_embed_text = write_embed_spy.call_args_list[0].args[0]

    # Now force reconcile to re-embed the same artifact via the failure log.
    artifact_id = write_result["artifact_id"]
    from arkeology.failure_log import append_failure_entry

    append_failure_entry(
        settings.failure_log_path,
        {
            "artifact_id": artifact_id,
            "title": "Parity Artifact",
            "type": "implementation_note",
            "tier": 2,
            "date": "2026-01-01",
            "failure_step": "put_vector",
            "reason": "forced replay for parity test",
            "timestamp": "2026-01-01T00:00:00+00:00",
        },
    )

    reconcile_bedrock = FakeBedrockClient(dimension=8)
    reconcile_embed_spy = mocker.spy(reconcile_bedrock, "embed")

    reconcile_result = await reconcile_index(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client_8,
        bedrock=reconcile_bedrock,
    )
    assert "error" not in reconcile_result
    assert reconcile_embed_spy.call_count == 1
    reconcile_embed_text = reconcile_embed_spy.call_args_list[0].args[0]

    assert reconcile_embed_text == write_embed_text
    assert len(long_body) not in [len(write_embed_text), len(reconcile_embed_text)]
