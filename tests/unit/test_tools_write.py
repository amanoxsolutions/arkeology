"""Unit tests for arkeology.tools.write.

Tests write_artifact() and its embedding helper functions using moto-backed clients.
"""

import asyncio
import json
import logging

import botocore.exceptions
import pytest
from pytest_mock import MockerFixture

from arkeology.artifact import S3_USER_METADATA_MAX_BYTES, VECTOR_FILTERABLE_METADATA_MAX_BYTES
from arkeology.clients.fakes.fake_bedrock import FakeBedrockClient
from arkeology.clients.s3 import S3ClientImpl
from arkeology.clients.vectors import VectorsClientImpl
from arkeology.errors import AnnotationUnavailableError, ArtifactConflictError, CredentialError
from arkeology.tools.link_metadata import link_metadata
from arkeology.tools.reconcile import reconcile_index
from arkeology.tools.write import _record_partial_write_credential_error, write_artifact
from tests.unit.conftest import _make_settings

# Base write kwargs
_BASE_WRITE_KWARGS: dict = {
    "type": "code_review",
    "team": "platform",
    "project": "arkeology",
    "tier": 2,
    "date": "2026-05-30",
    "status": "active",
    "title": "Fix auth bug",
    "description": "Review of the auth module.",
    "content": (
        "## Summary\n\nAll looks good.\n\n"
        "## Details\n\nSee inline comments.\n\n"
        "## Action Items\n\nNone."
    ),
    "visibility": "shared",
}

_ONE_SECTION_KWARGS: dict = {
    **_BASE_WRITE_KWARGS,
    "content": "No headings here — just plain content.",
}


# ---------------------------------------------------------------------------
# _record_partial_write_credential_error (G-1, Task 68)
# ---------------------------------------------------------------------------
#
# Direct unit test for the newly extracted helper — mirrors _record_partial_write's
# shared shape but for the CredentialError-after-S3-success case (six duplicated
# call sites collapsed into one-liners against this helper).


def test_record_partial_write_credential_error_logs_and_returns_credential_dict(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pytest.TempPathFactory,
) -> None:
    log_path = tmp_path / "failures.jsonl"
    settings = _make_settings(monkeypatch, FAILURE_LOG_PATH=str(log_path))
    exc = CredentialError("simulated", "bedrock", Exception("simulated"))

    result = _record_partial_write_credential_error(
        settings,
        artifact_id="artifacts/a1.md",
        title="A Title",
        artifact_type="code_review",
        tier=2,
        date="2026-08-19",
        failure_step="bedrock_embed",
        exc=exc,
    )

    assert result == {
        "error": "credential_error",
        "message": str(exc),
        "artifact_id": "artifacts/a1.md",
    }
    logged = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert len(logged) == 1
    assert logged[0]["artifact_id"] == "artifacts/a1.md"
    assert logged[0]["failure_step"] == "bedrock_embed"
    assert logged[0]["reason"] == str(exc)


# ---------------------------------------------------------------------------
# write_artifact — happy path
# ---------------------------------------------------------------------------
#
# Note: unit tests for the section-embedding-text helpers and the section
# filter/cap/truncate pipeline (formerly private to this module) now live in
# tests/unit/test_tools_section_pipeline.py — they moved to
# arkeology.tools._section_pipeline as a shared helper used by both
# write_artifact and reconcile_index.


async def test_three_section_content_indexes_three_sections(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """Three-section content → sections_indexed == 3 and 3 vectors in index."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )

    assert result["sections_indexed"] == 3
    artifact_id = result["artifact_id"]
    all_keys = vectors_client.list_vectors_by_metadata({})
    matching_keys = [k for k in all_keys if k == artifact_id or k.startswith(artifact_id + "#")]
    assert len(matching_keys) == 3


async def test_h2_heading_slug_collision_indexes_both_sections_distinctly(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """Two H2 headings that normalise to the same section_slug (e.g.
    'Notes' and 'Notes!' both collapse to 'notes' — punctuation is stripped and
    case is folded by section_slug) currently collide on the same vector key
    (``f"{s3_key}#{section_slug(heading)}"``). ``new_keys: set[str]`` silently
    collapses the duplicate key, so ``sections_indexed`` under-reports the true
    section count and the second section's vector overwrites the first's in
    the batch put — real content loss. Both sections must be embedded as
    distinct vectors (e.g. via a numeric disambiguation suffix on repeat
    slugs) once fixed.
    """
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()

    content = (
        "## Notes\n\n"
        "This is the first notes section with enough body content to pass the "
        "fifty character minimum length filter easily.\n\n"
        "## Notes!\n\n"
        "This is the second notes section with deliberately different content, "
        "also long enough to pass the same minimum length filter.\n"
    )
    kwargs = {**_BASE_WRITE_KWARGS, "title": "Heading collision test", "content": content}

    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    assert result.get("sections_indexed") == 2, (
        f"Expected 2 distinct sections indexed despite the colliding slug "
        f"('Notes' and 'Notes!' both normalise to 'notes'), got: {result}"
    )

    artifact_id = result["artifact_id"]
    all_keys = vectors_client.list_vectors_by_metadata({})
    matching_keys = [k for k in all_keys if k == artifact_id or k.startswith(artifact_id + "#")]
    assert len(matching_keys) == 2, (
        f"Expected 2 distinct vector keys for the colliding-slug sections, got: {matching_keys}"
    )


async def test_no_section_content_indexes_one_document_fallback(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """No-section content → sections_indexed == 1 (document-level fallback)."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_ONE_SECTION_KWARGS,
    )

    assert result["sections_indexed"] == 1


async def test_s3_contains_content_at_correct_key(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """After write_artifact, S3 contains the content at the returned artifact_id key."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )

    artifact_id = result["artifact_id"]
    stored_content = s3_client.get_object(artifact_id)
    assert stored_content == _BASE_WRITE_KWARGS["content"]


async def test_returned_artifact_id_is_full_s3_key(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """Returned artifact_id is the full S3 key including write_prefix."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )

    artifact_id = result["artifact_id"]
    assert artifact_id.startswith(settings.write_prefix + "/")


async def test_section_vector_keys_contain_hash_separator(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """Vector keys for sections have format {s3_key}#{section_slug}."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )

    artifact_id = result["artifact_id"]
    all_keys = vectors_client.list_vectors_by_metadata({})
    section_keys = [k for k in all_keys if k.startswith(artifact_id + "#")]
    assert len(section_keys) == 3
    for key in section_keys:
        assert "#" in key


async def test_document_fallback_vector_key_has_no_hash(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """Document-level fallback vector key equals {s3_key} (no # suffix)."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_ONE_SECTION_KWARGS,
    )

    artifact_id = result["artifact_id"]
    all_keys = vectors_client.list_vectors_by_metadata({})
    assert artifact_id in all_keys
    assert not any(k.startswith(artifact_id + "#") for k in all_keys)


async def test_vector_metadata_includes_artifact_id_and_scope(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """Each vector's metadata includes artifact_id (full S3 key) and scope (write_prefix)."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )

    artifact_id = result["artifact_id"]
    all_keys = vectors_client.list_vectors_by_metadata({})
    entries = vectors_client.get_vectors(all_keys)
    for entry in entries:
        assert entry["metadata"]["artifact_id"] == artifact_id
        assert entry["metadata"]["scope"] == settings.write_prefix


async def test_response_has_artifact_id_and_sections_indexed(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """Response dict has keys 'artifact_id' and 'sections_indexed'."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )

    assert "artifact_id" in result
    assert "sections_indexed" in result


# ---------------------------------------------------------------------------
# Collision guard: same-key write rejected by default, overwrite flag opts in
# ---------------------------------------------------------------------------


async def test_same_key_write_without_overwrite_returns_validation_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """Writing to an already-existing key without overwrite=True → validation_error."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()

    await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )
    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )

    assert result.get("error") == "validation_error"
    assert "message" in result


async def test_same_key_write_without_overwrite_does_not_mutate_s3_content(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """A rejected same-key write leaves the existing S3 object's content untouched."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()

    first = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )
    original_content = s3_client.get_object(first["artifact_id"])

    changed_kwargs = {**_BASE_WRITE_KWARGS, "content": "## Summary\n\nSomething different."}
    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **changed_kwargs,
    )

    assert result.get("error") == "validation_error"
    assert s3_client.get_object(first["artifact_id"]) == original_content
    assert len(s3_client.list_objects("")) == 1


async def test_same_key_write_without_overwrite_does_not_mutate_vectors(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """A rejected same-key write does not add, remove, or change any existing vectors."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()

    await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )
    keys_before = sorted(vectors_client.list_vectors_by_metadata({}))

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )

    assert result.get("error") == "validation_error"
    assert sorted(vectors_client.list_vectors_by_metadata({})) == keys_before


async def test_same_key_write_with_overwrite_true_succeeds(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """Writing to an already-existing key WITH overwrite=True → succeeds and updates content."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()

    first = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )

    changed_kwargs = {**_BASE_WRITE_KWARGS, "content": "## Summary\n\nUpdated content."}
    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        overwrite=True,
        **changed_kwargs,
    )

    assert "error" not in result
    assert result["artifact_id"] == first["artifact_id"]
    assert "Updated content." in s3_client.get_object(result["artifact_id"])
    assert len(s3_client.list_objects("")) == 1


# ---------------------------------------------------------------------------
# Atomic conditional-create put closes the head_object-then-put_object TOCTOU race
# ---------------------------------------------------------------------------


async def test_conditional_put_race_returns_validation_error_no_vectors_written(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """Simulates the TOCTOU race the head_object fast-path cannot catch: head_object
    reports the key does not exist (as if a concurrent writer had not yet completed when
    this call checked), but the key already exists by the time the atomic conditional
    put_object executes. The conditional put must be the authoritative guard: it is
    rejected with the same validation_error shape, and no embedding/vector work happens.
    """
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()

    # Key already exists (the "other" concurrent writer already won).
    await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )
    keys_before = sorted(vectors_client.list_vectors_by_metadata({}))

    # Only spy from here on — the setup write above legitimately embeds 3 sections.
    embed_spy = mocker.spy(bedrock, "embed")

    # Force the fast-path check to (incorrectly) report "not existing".
    mocker.patch.object(s3_client, "head_object", side_effect=KeyError("simulated race"))

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )

    assert result.get("error") == "validation_error"
    assert "artifact_id" in result
    assert embed_spy.call_count == 0, "no embedding work must happen after a rejected put"
    assert sorted(vectors_client.list_vectors_by_metadata({})) == keys_before


async def test_overwrite_false_put_object_called_with_if_none_match_true(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """overwrite=False → the actual s3.put_object call requests the atomic
    conditional-create (if_none_match=True), not just a friendly pre-check."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    spy = mocker.spy(s3_client, "put_object")

    await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )

    assert spy.call_count == 1
    assert spy.call_args.kwargs.get("if_none_match") is True


async def test_overwrite_true_put_object_called_without_if_none_match(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """overwrite=True on an existing key → the s3.put_object call is not a
    conditional-create (no if_none_match=True): it goes through the CAS retry loop
    instead, whose conditional-update guard is if_match (not if_none_match) —
    and which also asserts the if_match token equals the object's pre-write ETag."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()

    first = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )
    pre_write_etag = s3_client.head_object(first["artifact_id"])["ETag"]

    spy = mocker.spy(s3_client, "put_object")
    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        overwrite=True,
        **_BASE_WRITE_KWARGS,
    )

    assert "error" not in result
    assert spy.call_count == 1
    assert not spy.call_args.kwargs.get("if_none_match")
    assert spy.call_args.kwargs.get("if_match") == pre_write_etag


# ---------------------------------------------------------------------------
# Tier 2 idempotency
# ---------------------------------------------------------------------------


async def test_tier2_write_twice_same_date_one_s3_object(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """Write same tier 2 artifact twice (same date, overwrite=True) → exactly 1 S3 object."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()

    await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )
    await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        overwrite=True,
        **_BASE_WRITE_KWARGS,
    )

    assert len(s3_client.list_objects("")) == 1


async def test_tier2_write_twice_same_date_vector_count_unchanged(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """Write same tier 2 artifact twice (same date, overwrite=True) → vector count unchanged
    (upsert)."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()

    result1 = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )
    count_after_first = len(vectors_client.list_vectors_by_metadata({}))
    result2 = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        overwrite=True,
        **_BASE_WRITE_KWARGS,
    )

    assert result1["artifact_id"] == result2["artifact_id"]
    assert len(vectors_client.list_vectors_by_metadata({})) == count_after_first


async def test_tier2_different_dates_produce_distinct_keys(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """Write same tier 2 artifact on two different dates → 2 distinct S3 keys."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()

    kwargs_day1 = {**_BASE_WRITE_KWARGS, "date": "2026-05-30"}
    kwargs_day2 = {**_BASE_WRITE_KWARGS, "date": "2026-05-31"}

    result1 = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs_day1
    )
    result2 = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs_day2
    )

    assert result1["artifact_id"] != result2["artifact_id"]
    assert len(s3_client.list_objects("")) == 2


# ---------------------------------------------------------------------------
# Tier 3 re-write (orphan cleanup)
# ---------------------------------------------------------------------------


async def test_tier3_rewrite_fewer_sections_cleans_orphans(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """Tier 3: first write 3 sections, re-write 2 → orphan section C key is absent."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()

    three_section_content = "## Alpha\n\nBody A.\n\n## Beta\n\nBody B.\n\n## Gamma\n\nBody C."
    two_section_content = "## Alpha\n\nBody A.\n\n## Beta\n\nBody B."

    kwargs_3 = {**_BASE_WRITE_KWARGS, "tier": 3, "content": three_section_content}
    kwargs_2 = {**_BASE_WRITE_KWARGS, "tier": 3, "content": two_section_content}

    result1 = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs_3
    )
    artifact_id = result1["artifact_id"]

    all_keys_before = vectors_client.list_vectors_by_metadata({})
    keys_before = [k for k in all_keys_before if k.startswith(artifact_id)]
    assert len(keys_before) == 3

    await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        overwrite=True,
        **kwargs_2,
    )

    all_keys_after = vectors_client.list_vectors_by_metadata({})
    keys_after = [k for k in all_keys_after if k.startswith(artifact_id)]
    assert len(keys_after) == 2
    gamma_keys = [k for k in keys_after if "gamma" in k]
    assert len(gamma_keys) == 0


async def test_tier3_rewrite_more_sections(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """Tier 3: first write 1 section, re-write 3 → 3 vectors after re-write."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()

    three_section_content = "## Alpha\n\nBody A.\n\n## Beta\n\nBody B.\n\n## Gamma\n\nBody C."
    kwargs_1 = {**_BASE_WRITE_KWARGS, "tier": 3, "content": "## Alpha\n\nBody A."}
    kwargs_3 = {**_BASE_WRITE_KWARGS, "tier": 3, "content": three_section_content}

    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs_1
    )
    artifact_id = result["artifact_id"]

    await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        overwrite=True,
        **kwargs_3,
    )

    all_keys = vectors_client.list_vectors_by_metadata({})
    keys_after = [k for k in all_keys if k.startswith(artifact_id)]
    assert len(keys_after) == 3


async def test_tier3_rewrite_identical_sections_count_unchanged(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """Tier 3: re-write with identical sections → vector count unchanged."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()

    content = "## Alpha\n\nBody A.\n\n## Beta\n\nBody B."
    kwargs = {**_BASE_WRITE_KWARGS, "tier": 3, "content": content}

    await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )
    count_after_first = len(vectors_client.list_vectors_by_metadata({}))

    await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        overwrite=True,
        **kwargs,
    )
    assert len(vectors_client.list_vectors_by_metadata({})) == count_after_first


# ---------------------------------------------------------------------------
# Tier 3 key stability
# ---------------------------------------------------------------------------


async def test_tier3_different_dates_same_artifact_id(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """Tier 3: writes with different dates, same type+title → same artifact_id."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()

    kwargs_day1 = {**_BASE_WRITE_KWARGS, "tier": 3, "date": "2026-05-30"}
    kwargs_day2 = {**_BASE_WRITE_KWARGS, "tier": 3, "date": "2026-06-15"}

    result1 = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs_day1
    )
    result2 = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        overwrite=True,
        **kwargs_day2,
    )

    assert result1["artifact_id"] == result2["artifact_id"]


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


async def test_validation_description_too_long_no_s3_call(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """description > 280 chars → validation_error response; S3 put_object NOT called."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()

    kwargs = {**_BASE_WRITE_KWARGS, "description": "x" * 281}
    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    assert result.get("error") == "validation_error"
    assert "message" in result
    assert len(s3_client.list_objects("")) == 0


async def test_validation_invalid_type_no_s3_call(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """Invalid type → validation_error response; S3 put_object NOT called."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()

    kwargs = {**_BASE_WRITE_KWARGS, "type": "invalid_type"}
    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    assert result.get("error") == "validation_error"
    assert "message" in result
    assert len(s3_client.list_objects("")) == 0


async def test_validation_invalid_tier_no_s3_call(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """Invalid tier → validation_error response; S3 put_object NOT called."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()

    kwargs = {**_BASE_WRITE_KWARGS, "tier": 1}
    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    assert result.get("error") == "validation_error"
    assert "message" in result
    assert len(s3_client.list_objects("")) == 0


async def test_validation_wrong_type_tier_string_returns_validation_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """tier="2" (string, not int) must return validation_error, not internal_error.

    Pydantic's lax coercion accepts the string "2" for the ``Artifact`` model's
    ``tier: int`` field (coercing it to the valid int 2), so the model
    construction itself does not raise. The bug is that
    ``generate_artifact_id`` downstream is called with the original,
    un-coerced string parameter rather than the validated ``artifact.tier``,
    so ``_require_valid_tier`` raises a plain ``ValueError`` — caught only by
    the outer blanket ``except Exception`` and surfaced as internal_error.
    """
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()

    kwargs = {**_BASE_WRITE_KWARGS, "tier": "2"}
    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    assert result.get("error") == "validation_error", (
        f"Expected error='validation_error' for wrong-type tier, got: {result}"
    )
    assert "message" in result
    assert len(s3_client.list_objects("")) == 0


async def test_validation_invalid_visibility_no_s3_call(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """Invalid visibility → validation_error response; S3 put_object NOT called."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()

    kwargs = {**_BASE_WRITE_KWARGS, "visibility": "public"}
    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    assert result.get("error") == "validation_error"
    assert "message" in result
    assert len(s3_client.list_objects("")) == 0


@pytest.mark.parametrize("field", ["tags", "source_artifacts"])
async def test_validation_comma_in_list_element_rejected_before_any_write(
    field: str,
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: MockerFixture,
) -> None:
    """A comma inside a tags or source_artifacts element makes the two stores disagree:
    S3 object metadata comma-joins the list into one string, so the read path splits the
    element back into two, while vector metadata keeps it whole and the list/search path
    returns one. The write must be rejected with validation_error before any storage
    operation — no put_object, no put_vectors_batch."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    put_spy = mocker.spy(s3_client, "put_object")
    batch_spy = mocker.spy(vectors_client, "put_vectors_batch")

    kwargs = {**_BASE_WRITE_KWARGS, field: ["a,b"]}

    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    assert result.get("error") == "validation_error", result
    assert field in result["message"]
    assert put_spy.call_count == 0
    assert batch_spy.call_count == 0
    assert len(s3_client.list_objects("")) == 0
    assert len(vectors_client.list_vectors_by_metadata({})) == 0


# ---------------------------------------------------------------------------
# Credential failures
# ---------------------------------------------------------------------------


async def test_s3_credential_failure_returns_error_bedrock_not_called(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """S3 credential failure → error in response; bedrock.embed NOT called."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    spy = mocker.spy(bedrock, "embed")
    mocker.patch.object(
        s3_client,
        "head_object",
        side_effect=CredentialError(
            message="simulated",
            service="s3",
            original=Exception("simulated"),
        ),
    )

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )

    assert result.get("error") == "credential_error"
    assert spy.call_count == 0


async def test_bedrock_credential_failure_returns_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    tmp_path: pytest.TempPathFactory,
    mocker: pytest.MonkeyPatch,
) -> None:
    """Bedrock credential failure → error in response (S3 already written by this
    point — a failure-log entry is written, hence the tmp-path-scoped log)."""
    log_path = tmp_path / "failures.jsonl"
    settings = _make_settings(monkeypatch, FAILURE_LOG_PATH=str(log_path))
    bedrock = FakeBedrockClient()
    mocker.patch.object(
        bedrock,
        "embed",
        side_effect=CredentialError("simulated", "bedrock", Exception("simulated")),
    )

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )

    assert result.get("error") == "credential_error"


# ---------------------------------------------------------------------------
# T1: vector metadata stores tags as list
# ---------------------------------------------------------------------------


async def test_vector_metadata_tags_is_list(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """After successful write, tags in vector metadata is a list (not a string)."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()

    kwargs = {**_BASE_WRITE_KWARGS, "tags": ["auth", "security"]}
    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    s3_key = result["artifact_id"]
    all_keys = vectors_client.list_vectors_by_metadata({})
    relevant_keys = [k for k in all_keys if k.startswith(s3_key)]
    vec_results = vectors_client.get_vectors(relevant_keys)
    assert len(vec_results) > 0
    for entry in vec_results:
        assert isinstance(entry["metadata"]["tags"], list), (
            f"Expected list, got {type(entry['metadata']['tags'])}"
        )


# ---------------------------------------------------------------------------
# T2: S3 metadata stores tags and source_artifacts as comma-joined strings
# ---------------------------------------------------------------------------


async def test_s3_metadata_tags_and_source_artifacts_are_strings(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """After successful write, S3 metadata stores tags and source_artifacts
    as comma-joined strings (not lists), per S3 metadata constraints."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()

    kwargs = {
        **_BASE_WRITE_KWARGS,
        "tags": ["auth", "security"],
        "source_artifacts": ["adr-one", "adr-two"],
    }
    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    s3_key = result["artifact_id"]
    meta = s3_client.head_object(s3_key)
    assert isinstance(meta["tags"], str), f"Expected str in S3 metadata, got {type(meta['tags'])}"
    assert meta["tags"] == "auth,security"
    assert isinstance(meta["source_artifacts"], str), (
        f"Expected str in S3 metadata, got {type(meta['source_artifacts'])}"
    )
    assert meta["source_artifacts"] == "adr-one,adr-two"


# ---------------------------------------------------------------------------
# T15: Throttle retry and partial write failure log
# ---------------------------------------------------------------------------


def _throttle_error() -> botocore.exceptions.ClientError:
    return botocore.exceptions.ClientError(
        {"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}},
        "InvokeModel",
    )


def _non_throttle_error() -> botocore.exceptions.ClientError:
    return botocore.exceptions.ClientError(
        {"Error": {"Code": "ValidationException", "Message": "Bad input"}},
        "InvokeModel",
    )


class _ThrottleThenSucceedBedrock(FakeBedrockClient):
    """Raises ThrottlingException on the first embed call, then succeeds."""

    def __init__(self) -> None:
        super().__init__()
        self._call_count = 0

    def embed(self, text: str, model_id: str, dimensions: int) -> list[float]:
        self._call_count += 1
        if self._call_count == 1:
            raise _throttle_error()
        return super().embed(text, model_id, dimensions)


class _ThrottleAlwaysBedrock(FakeBedrockClient):
    """Raises ThrottlingException on every embed call."""

    def embed(self, text: str, model_id: str, dimensions: int) -> list[float]:
        raise _throttle_error()


class _NonThrottleErrorBedrock(FakeBedrockClient):
    """Raises a non-throttle ClientError on every embed call."""

    def embed(self, text: str, model_id: str, dimensions: int) -> list[float]:
        raise _non_throttle_error()


async def _instant_sleep(_seconds: float) -> None:
    """Drop-in replacement for asyncio.sleep that returns immediately."""


async def test_throttle_on_doc_fallback_returns_partial_write_no_retry(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    tmp_path: pytest.TempPathFactory,
) -> None:
    """Throttle on doc-level embed → immediate partial_write; no write.py-level retry.

    write.py delegates retry to BedrockClientImpl; the document-level fallback path
    does not retry throttle errors itself.
    """
    log_path = tmp_path / "failures.jsonl"
    settings = _make_settings(monkeypatch, FAILURE_LOG_PATH=str(log_path))
    bedrock = _ThrottleAlwaysBedrock()

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_ONE_SECTION_KWARGS,
    )

    assert result.get("error") == "partial_write"
    assert "artifact_id" in result
    assert log_path.exists()


async def test_throttle_retry_both_fail_returns_partial_write(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    tmp_path: pytest.TempPathFactory,
) -> None:
    """Throttle on both embed calls → partial_write error; artifact_id in response."""
    log_path = tmp_path / "failures.jsonl"
    monkeypatch.setattr(asyncio, "sleep", _instant_sleep)
    settings = _make_settings(monkeypatch, FAILURE_LOG_PATH=str(log_path))
    bedrock = _ThrottleAlwaysBedrock()

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_ONE_SECTION_KWARGS,
    )

    assert result.get("error") == "partial_write"
    assert "artifact_id" in result


async def test_throttle_retry_both_fail_writes_failure_log_bedrock_embed(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    tmp_path: pytest.TempPathFactory,
) -> None:
    """Throttle on both embed calls → failure log entry with failure_step='bedrock_embed'."""
    log_path = tmp_path / "failures.jsonl"
    monkeypatch.setattr(asyncio, "sleep", _instant_sleep)
    settings = _make_settings(monkeypatch, FAILURE_LOG_PATH=str(log_path))
    bedrock = _ThrottleAlwaysBedrock()

    await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_ONE_SECTION_KWARGS,
    )

    assert log_path.exists()
    entries = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert len(entries) == 1
    assert entries[0]["failure_step"] == "bedrock_embed"


async def test_non_throttle_error_returns_partial_write_no_retry(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    tmp_path: pytest.TempPathFactory,
) -> None:
    """Non-throttle ClientError → no retry; partial_write error; failure log written."""
    log_path = tmp_path / "failures.jsonl"
    settings = _make_settings(monkeypatch, FAILURE_LOG_PATH=str(log_path))
    bedrock = _NonThrottleErrorBedrock()

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_ONE_SECTION_KWARGS,
    )

    assert result.get("error") == "partial_write"
    assert "artifact_id" in result
    assert log_path.exists()
    entries = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert len(entries) == 1
    assert entries[0]["failure_step"] == "bedrock_embed"


async def test_put_vector_failure_returns_partial_write_with_log(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    tmp_path: pytest.TempPathFactory,
    mocker: pytest.MonkeyPatch,
) -> None:
    """S3 write succeeds, put_vectors_batch raises → partial_write error; failure log written."""
    log_path = tmp_path / "failures.jsonl"
    settings = _make_settings(monkeypatch, FAILURE_LOG_PATH=str(log_path))
    bedrock = FakeBedrockClient()
    mocker.patch.object(
        vectors_client,
        "put_vectors_batch",
        side_effect=RuntimeError("simulated put_vectors_batch failure"),
    )

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_ONE_SECTION_KWARGS,
    )

    assert result.get("error") == "partial_write"
    assert "artifact_id" in result
    assert log_path.exists()
    entries = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert len(entries) == 1
    assert entries[0]["failure_step"] == "put_vector"


async def test_failure_log_entry_contains_all_required_fields(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    tmp_path: pytest.TempPathFactory,
    mocker: pytest.MonkeyPatch,
) -> None:
    """Failure log entry contains all required fields with correct types."""
    log_path = tmp_path / "failures.jsonl"
    settings = _make_settings(monkeypatch, FAILURE_LOG_PATH=str(log_path))
    bedrock = FakeBedrockClient()
    mocker.patch.object(
        vectors_client,
        "put_vectors_batch",
        side_effect=RuntimeError("simulated put_vectors_batch failure"),
    )

    await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_ONE_SECTION_KWARGS,
    )

    entry = json.loads(log_path.read_text().splitlines()[0])
    required_fields = (
        "artifact_id",
        "title",
        "type",
        "tier",
        "date",
        "failure_step",
        "reason",
        "timestamp",
    )
    for field in required_fields:
        assert field in entry, f"Missing field: {field}"
    assert entry["title"] == _ONE_SECTION_KWARGS["title"]
    assert entry["type"] == _ONE_SECTION_KWARGS["type"]
    assert entry["tier"] == _ONE_SECTION_KWARGS["tier"]
    assert entry["date"] == _ONE_SECTION_KWARGS["date"]
    from datetime import datetime

    datetime.fromisoformat(entry["timestamp"])


async def test_failure_log_appends_across_multiple_failures(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    tmp_path: pytest.TempPathFactory,
    mocker: pytest.MonkeyPatch,
) -> None:
    """Two separate partial write failures → failure log has two entries (append behaviour).

    Uses two distinct titles (rather than retrying the same key) so the collision
    guard does not interfere — this test verifies failure-log append behaviour, not
    overwrite semantics.
    """
    log_path = tmp_path / "failures.jsonl"
    settings = _make_settings(monkeypatch, FAILURE_LOG_PATH=str(log_path))
    bedrock = FakeBedrockClient()
    mocker.patch.object(
        vectors_client,
        "put_vectors_batch",
        side_effect=RuntimeError("simulated put_vectors_batch failure"),
    )

    for title in ("First failing artifact", "Second failing artifact"):
        await write_artifact(
            s3=s3_client,
            vectors=vectors_client,
            bedrock=bedrock,
            settings=settings,
            **{**_ONE_SECTION_KWARGS, "title": title},
        )

    lines = log_path.read_text().splitlines()
    assert len(lines) == 2
    for line in lines:
        entry = json.loads(line)
        assert entry["failure_step"] == "put_vector"


async def test_bedrock_credential_error_writes_failure_log(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    tmp_path: pytest.TempPathFactory,
    mocker: pytest.MonkeyPatch,
) -> None:
    """Bedrock CredentialError (doc-level fallback path) → credential_error response;
    a failure-log entry IS written since the S3 put has already succeeded by
    this point — without it, reconcile_index has no way to discover and repair the
    artifact's missing vector index entry."""
    log_path = tmp_path / "failures.jsonl"
    settings = _make_settings(monkeypatch, FAILURE_LOG_PATH=str(log_path))
    bedrock = FakeBedrockClient()
    mocker.patch.object(
        bedrock,
        "embed",
        side_effect=CredentialError("simulated", "bedrock", Exception("simulated")),
    )

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_ONE_SECTION_KWARGS,
    )

    assert result.get("error") == "credential_error"
    assert log_path.exists()
    entries = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert len(entries) == 1
    assert entries[0]["failure_step"] == "bedrock_embed"
    assert entries[0]["artifact_id"] == result["artifact_id"]


async def test_put_vector_credential_error_writes_failure_log(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    tmp_path: pytest.TempPathFactory,
    mocker: pytest.MonkeyPatch,
) -> None:
    """put_vectors_batch CredentialError (doc-level fallback path) → credential_error
    response; a failure-log entry IS written."""
    log_path = tmp_path / "failures.jsonl"
    settings = _make_settings(monkeypatch, FAILURE_LOG_PATH=str(log_path))
    bedrock = FakeBedrockClient()
    mocker.patch.object(
        vectors_client,
        "put_vectors_batch",
        side_effect=CredentialError(
            message="AWS credentials are invalid or expired (simulated).",
            service="s3vectors",
            original=Exception("simulated credential failure"),
        ),
    )

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_ONE_SECTION_KWARGS,
    )

    assert result.get("error") == "credential_error"
    assert log_path.exists()
    entries = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert len(entries) == 1
    assert entries[0]["failure_step"] == "put_vector"
    assert entries[0]["artifact_id"] == result["artifact_id"]


# ---------------------------------------------------------------------------
# Spec 18 — Orphan cleanup skipped for new artifacts
# ---------------------------------------------------------------------------


async def test_new_artifact_skips_orphan_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """New artifact (head_object 404) → list_vectors_by_metadata NOT called."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    spy = mocker.spy(vectors_client, "list_vectors_by_metadata")

    await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )

    assert spy.call_count == 0


async def test_existing_artifact_runs_orphan_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """Existing artifact (head_object returns meta) → list_vectors_by_metadata called."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()

    await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )

    spy = mocker.spy(vectors_client, "list_vectors_by_metadata")

    await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        overwrite=True,
        **_BASE_WRITE_KWARGS,
    )

    assert spy.call_count >= 1


# ---------------------------------------------------------------------------
# Orphan cleanup is best-effort — a cleanup failure must not invert a durable write
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orphan_cleanup_list_failure_does_not_fail_write(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """A non-credential failure listing existing vectors during orphan cleanup must NOT
    invert an already-successful write — by Step 8 the artifact is durably in S3 and its
    new section vectors are indexed, so the result must still report success.
    """
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()

    await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )

    # list_vectors_by_metadata is now called twice on an overwriting write: once for
    # the T47 read-forward (Step 4a, must succeed so link fields are not lost) and once
    # for orphan cleanup (Step 8, best-effort). Let the first (read-forward) call
    # through and only fail from the second call onward, isolating this test to the
    # orphan-cleanup failure it is meant to exercise.
    original_list = vectors_client.list_vectors_by_metadata
    call_count = 0

    def _list_fails_after_first(*args: object, **kwargs: object) -> list[str]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return original_list(*args, **kwargs)  # type: ignore[arg-type]
        raise RuntimeError("boom")

    mocker.patch.object(
        vectors_client, "list_vectors_by_metadata", side_effect=_list_fails_after_first
    )

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        overwrite=True,
        **_BASE_WRITE_KWARGS,
    )

    assert "error" not in result, f"cleanup failure must not fail the write, got: {result}"
    assert result.get("artifact_id"), f"artifact_id missing: {result}"
    assert "sections_indexed" in result


@pytest.mark.asyncio
async def test_orphan_cleanup_delete_failure_does_not_fail_write(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """A non-credential failure deleting orphan vectors must NOT fail the write; the new
    content is written and the new section vectors are indexed regardless.
    """
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()

    three = "## Alpha\n\nBody A.\n\n## Beta\n\nBody B.\n\n## Gamma\n\nBody C."
    two = "## Alpha\n\nBody A.\n\n## Beta\n\nBody B."
    kwargs_3 = {**_BASE_WRITE_KWARGS, "tier": 3, "content": three}
    kwargs_2 = {**_BASE_WRITE_KWARGS, "tier": 3, "content": two}

    first = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs_3
    )
    artifact_id = first["artifact_id"]

    # Re-write with fewer sections → orphan exists → delete_vectors is called and fails.
    mocker.patch.object(vectors_client, "delete_vectors", side_effect=RuntimeError("boom"))

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        overwrite=True,
        **kwargs_2,
    )

    assert "error" not in result, f"cleanup failure must not fail the write, got: {result}"
    assert result.get("artifact_id") == artifact_id
    assert result.get("sections_indexed") == 2


@pytest.mark.asyncio
async def test_orphan_cleanup_credential_failure_does_not_fail_write(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """A CredentialError during orphan cleanup must also not invert a durable write —
    cleanup is best-effort (the write already succeeded before Step 8).
    """
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()

    await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )

    # See test_orphan_cleanup_list_failure_does_not_fail_write: list_vectors_by_metadata
    # is now also used by the T47 read-forward (Step 4a), which must succeed. Only fail
    # from the second call onward so this test still isolates the orphan-cleanup
    # (Step 8) credential failure it is meant to exercise.
    original_list = vectors_client.list_vectors_by_metadata
    call_count = 0

    def _list_fails_after_first(*args: object, **kwargs: object) -> list[str]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return original_list(*args, **kwargs)  # type: ignore[arg-type]
        raise CredentialError(
            message="AWS credentials are invalid or expired (simulated).",
            service="s3vectors",
            original=Exception("simulated"),
        )

    mocker.patch.object(
        vectors_client, "list_vectors_by_metadata", side_effect=_list_fails_after_first
    )

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        overwrite=True,
        **_BASE_WRITE_KWARGS,
    )

    assert "error" not in result, (
        f"cleanup credential failure must not fail the write, got: {result}"
    )
    assert result.get("artifact_id")


# ---------------------------------------------------------------------------
# T67 — Step 8 delete_vectors bounded inline retry + orphan_keys failure-log kind
# ---------------------------------------------------------------------------


def _orphan_transient_error(
    code: str = "RequestTimeoutException",
) -> botocore.exceptions.ClientError:
    """A ClientError carrying one of the three documented DeleteVectors transient codes."""
    return botocore.exceptions.ClientError(
        {"Error": {"Code": code, "Message": "Retry your request"}},
        "DeleteVectors",
    )


def _orphan_non_transient_error() -> botocore.exceptions.ClientError:
    """A ClientError whose code is not in the transient retry set."""
    return botocore.exceptions.ClientError(
        {"Error": {"Code": "ValidationException", "Message": "Bad input"}},
        "DeleteVectors",
    )


async def _seed_artifact_with_orphan(
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    bedrock: FakeBedrockClient,
    settings: object,
) -> str:
    """Write a tier-3 artifact with 3 sections. The caller then overwrites it with 2
    sections (dropping the ``gamma`` section), producing exactly one real orphan vector
    key (``f"{artifact_id}#gamma"``) for Step 8 to compute and attempt to delete."""
    three = "## Alpha\n\nBody A.\n\n## Beta\n\nBody B.\n\n## Gamma\n\nBody C."
    kwargs_3 = {**_BASE_WRITE_KWARGS, "tier": 3, "content": three}
    first = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs_3
    )
    artifact_id: str = first["artifact_id"]
    return artifact_id


_TWO_SECTION_OVERWRITE_CONTENT = "## Alpha\n\nBody A.\n\n## Beta\n\nBody B."


@pytest.mark.asyncio
async def test_orphan_delete_transient_error_then_success_retries_and_succeeds(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
    tmp_path: pytest.TempPathFactory,
) -> None:
    """A transient ClientError on the first delete_vectors attempt, succeeding on the
    retry: delete_vectors is called exactly twice, time.sleep is called exactly once
    (mocked, never actually sleeps), the write still returns its normal success
    response, and no failure-log entry is written."""
    log_path = tmp_path / "failures.jsonl"
    settings = _make_settings(monkeypatch, FAILURE_LOG_PATH=str(log_path))
    bedrock = FakeBedrockClient()
    artifact_id = await _seed_artifact_with_orphan(s3_client, vectors_client, bedrock, settings)

    kwargs_2 = {**_BASE_WRITE_KWARGS, "tier": 3, "content": _TWO_SECTION_OVERWRITE_CONTENT}
    delete_spy = mocker.patch.object(
        vectors_client, "delete_vectors", side_effect=[_orphan_transient_error(), None]
    )
    sleep_spy = mocker.patch("arkeology.tools.write.time.sleep")

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        overwrite=True,
        **kwargs_2,
    )

    assert "error" not in result
    assert result.get("artifact_id") == artifact_id
    assert delete_spy.call_count == 2
    assert sleep_spy.call_count == 1
    assert not settings.failure_log_path.exists(), (
        "a successful retry must not write a failure-log entry"
    )


@pytest.mark.asyncio
async def test_orphan_delete_transient_error_exhausted_logs_failure(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
    tmp_path: pytest.TempPathFactory,
) -> None:
    """A transient ClientError on every delete_vectors attempt: the retry budget is
    exhausted (called exactly twice, never more), a failure-log entry is written with
    failure_step='orphan_vector_cleanup' and orphan_keys matching the computed orphan
    set exactly, and the write still returns its normal success response."""
    log_path = tmp_path / "failures.jsonl"
    settings = _make_settings(monkeypatch, FAILURE_LOG_PATH=str(log_path))
    bedrock = FakeBedrockClient()
    artifact_id = await _seed_artifact_with_orphan(s3_client, vectors_client, bedrock, settings)

    kwargs_2 = {**_BASE_WRITE_KWARGS, "tier": 3, "content": _TWO_SECTION_OVERWRITE_CONTENT}
    delete_spy = mocker.patch.object(
        vectors_client, "delete_vectors", side_effect=_orphan_transient_error()
    )
    sleep_spy = mocker.patch("arkeology.tools.write.time.sleep")

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        overwrite=True,
        **kwargs_2,
    )

    assert "error" not in result
    assert result.get("artifact_id") == artifact_id
    assert delete_spy.call_count == 2
    assert sleep_spy.call_count == 1

    log_lines = settings.failure_log_path.read_text(encoding="utf-8").splitlines()
    entries = [json.loads(line) for line in log_lines]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["artifact_id"] == artifact_id
    assert entry["failure_step"] == "orphan_vector_cleanup"
    assert entry["orphan_keys"] == [f"{artifact_id}#gamma"]
    assert "reconcile_attempts" not in entry


@pytest.mark.asyncio
async def test_orphan_delete_credential_error_not_retried_logs_failure(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
    tmp_path: pytest.TempPathFactory,
) -> None:
    """A CredentialError from delete_vectors is never retried (called exactly once) and
    goes straight to the fallback failure-log entry; the write still returns its normal
    success response."""
    log_path = tmp_path / "failures.jsonl"
    settings = _make_settings(monkeypatch, FAILURE_LOG_PATH=str(log_path))
    bedrock = FakeBedrockClient()
    artifact_id = await _seed_artifact_with_orphan(s3_client, vectors_client, bedrock, settings)

    kwargs_2 = {**_BASE_WRITE_KWARGS, "tier": 3, "content": _TWO_SECTION_OVERWRITE_CONTENT}
    cred_exc = CredentialError(
        message="AWS credentials are invalid or expired (simulated).",
        service="s3vectors",
        original=Exception("simulated"),
    )
    delete_spy = mocker.patch.object(vectors_client, "delete_vectors", side_effect=cred_exc)
    sleep_spy = mocker.patch("arkeology.tools.write.time.sleep")

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        overwrite=True,
        **kwargs_2,
    )

    assert "error" not in result
    assert result.get("artifact_id") == artifact_id
    assert delete_spy.call_count == 1
    assert sleep_spy.call_count == 0

    log_lines = settings.failure_log_path.read_text(encoding="utf-8").splitlines()
    entries = [json.loads(line) for line in log_lines]
    assert len(entries) == 1
    assert entries[0]["failure_step"] == "orphan_vector_cleanup"
    assert entries[0]["orphan_keys"] == [f"{artifact_id}#gamma"]


@pytest.mark.asyncio
async def test_orphan_delete_non_transient_error_not_retried_logs_failure(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
    tmp_path: pytest.TempPathFactory,
) -> None:
    """A ClientError whose code is not one of the three transient codes is never
    retried (called exactly once) and goes straight to the fallback failure-log entry;
    the write still returns its normal success response."""
    log_path = tmp_path / "failures.jsonl"
    settings = _make_settings(monkeypatch, FAILURE_LOG_PATH=str(log_path))
    bedrock = FakeBedrockClient()
    artifact_id = await _seed_artifact_with_orphan(s3_client, vectors_client, bedrock, settings)

    kwargs_2 = {**_BASE_WRITE_KWARGS, "tier": 3, "content": _TWO_SECTION_OVERWRITE_CONTENT}
    delete_spy = mocker.patch.object(
        vectors_client, "delete_vectors", side_effect=_orphan_non_transient_error()
    )
    sleep_spy = mocker.patch("arkeology.tools.write.time.sleep")

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        overwrite=True,
        **kwargs_2,
    )

    assert "error" not in result
    assert result.get("artifact_id") == artifact_id
    assert delete_spy.call_count == 1
    assert sleep_spy.call_count == 0

    log_lines = settings.failure_log_path.read_text(encoding="utf-8").splitlines()
    entries = [json.loads(line) for line in log_lines]
    assert len(entries) == 1
    assert entries[0]["failure_step"] == "orphan_vector_cleanup"
    assert entries[0]["orphan_keys"] == [f"{artifact_id}#gamma"]


# ---------------------------------------------------------------------------
# Spec 19 — CredentialError from head_object returns credential_error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_head_object_credential_error_returns_credential_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """CredentialError raised by head_object → credential_error response; write not attempted."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    mocker.patch.object(
        s3_client,
        "head_object",
        side_effect=CredentialError(
            message="AWS credentials are invalid or expired (simulated).",
            service="s3",
            original=Exception("simulated"),
        ),
    )

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )

    assert result.get("error") == "credential_error"
    assert len(s3_client.list_objects("")) == 0


# ---------------------------------------------------------------------------
# Helpers shared by T26 / T28 tests
# ---------------------------------------------------------------------------


def _make_sections_content(count: int, body_length: int = 120) -> str:
    """Build Markdown with ``count`` H2 sections, each body ``body_length`` chars long."""
    parts = [f"## Section {i}\n\n{'x' * body_length}" for i in range(1, count + 1)]
    return "\n\n".join(parts)


def _make_mixed_sections_content(
    long_count: int, short_count: int, long_len: int = 120, short_len: int = 10
) -> str:
    """Build Markdown with a mix of long and short sections (long sections first)."""
    parts = [f"## Long {i}\n\n{'x' * long_len}" for i in range(1, long_count + 1)]
    parts += [f"## Short {i}\n\n{'x' * short_len}" for i in range(1, short_count + 1)]
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# T26 — Concurrent embedding and batched put_vectors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_sections_embeds_all_concurrently(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """8-section document → embed called 8 times; put_vectors_batch called exactly once."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    embed_spy = mocker.spy(bedrock, "embed")
    batch_spy = mocker.spy(vectors_client, "put_vectors_batch")

    content = _make_sections_content(8)
    kwargs = {**_BASE_WRITE_KWARGS, "content": content}

    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    assert "error" not in result
    assert embed_spy.call_count == 8
    assert batch_spy.call_count == 1


@pytest.mark.asyncio
async def test_write_sections_batch_put_called_once(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """5-section document → put_vectors_batch called exactly once (not 5 times)."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    batch_spy = mocker.spy(vectors_client, "put_vectors_batch")

    content = _make_sections_content(5)
    kwargs = {**_BASE_WRITE_KWARGS, "content": content}

    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    assert "error" not in result
    assert batch_spy.call_count == 1


class _FailOnSecondEmbedBedrock(FakeBedrockClient):
    """Raises RuntimeError on the 2nd outer embed() call — thread-safe counter."""

    import threading

    def __init__(self) -> None:
        super().__init__()
        self._call_count = 0
        self._lock = __import__("threading").Lock()

    def embed(self, text: str, model_id: str, dimensions: int) -> list[float]:
        with self._lock:
            self._call_count += 1
            count = self._call_count
        if count == 2:
            raise RuntimeError("simulated embed failure on 2nd call")
        return super().embed(text, model_id, dimensions)


@pytest.mark.asyncio
async def test_write_any_embed_failure_aborts_atomically(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """Any embed failure → put_vectors_batch never called; response contains partial_write."""
    settings = _make_settings(monkeypatch)
    bedrock = _FailOnSecondEmbedBedrock()
    batch_spy = mocker.spy(vectors_client, "put_vectors_batch")

    # 8 sections: the 2nd embed call will raise, aborting the whole batch
    content = _make_sections_content(8)
    kwargs = {**_BASE_WRITE_KWARGS, "content": content}

    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    assert result.get("error") == "partial_write"
    assert batch_spy.call_count == 0


@pytest.mark.asyncio
async def test_write_embed_credential_error_aborts(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
    tmp_path: pytest.TempPathFactory,
) -> None:
    """CredentialError on any embed → response error == 'credential_error'; no vectors
    written; a failure-log entry IS written since S3 already succeeded."""
    log_path = tmp_path / "failures.jsonl"
    settings = _make_settings(monkeypatch, FAILURE_LOG_PATH=str(log_path))
    bedrock = FakeBedrockClient()
    mocker.patch.object(
        bedrock,
        "embed",
        side_effect=CredentialError("simulated", "bedrock", Exception("simulated")),
    )
    batch_spy = mocker.spy(vectors_client, "put_vectors_batch")

    content = _make_sections_content(3)
    kwargs = {**_BASE_WRITE_KWARGS, "content": content}

    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    assert result.get("error") == "credential_error"
    assert batch_spy.call_count == 0
    assert log_path.exists()
    entries = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert len(entries) == 1
    assert entries[0]["failure_step"] == "bedrock_embed"


@pytest.mark.asyncio
async def test_write_sections_semaphore_default(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """10-section write completes without error under default SECTION_CONCURRENCY=5."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()

    content = _make_sections_content(10)
    kwargs = {**_BASE_WRITE_KWARGS, "content": content}

    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    assert "error" not in result
    assert result["sections_indexed"] == 10


# ---------------------------------------------------------------------------
# T27 — Throttle fix: no asyncio.sleep from write.py
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_throttle_exhausted_calls_embed_exactly_twice(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """Throttle exhausted → embed called exactly once; error is partial_write.

    write.py delegates retry to BedrockClientImpl; the write tool itself calls
    embed exactly once per document-level fallback and propagates any exception.
    """
    settings = _make_settings(monkeypatch)
    # _ThrottleAlwaysBedrock raises botocore ThrottlingException on every call
    bedrock = _ThrottleAlwaysBedrock()
    embed_spy = mocker.spy(bedrock, "embed")

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_ONE_SECTION_KWARGS,
    )

    assert embed_spy.call_count == 1
    assert result.get("error") == "partial_write"


@pytest.mark.asyncio
async def test_no_extra_sleep_from_write_on_throttle(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """write.py must not call asyncio.sleep with a positive argument on throttle.

    The sleep-with-jitter belongs in BedrockClientImpl, not in the write tool.
    Any asyncio.sleep(0) is acceptable (yield-to-event-loop pattern); only positive
    values indicate a retry delay injected by write.py.
    """
    settings = _make_settings(monkeypatch)
    bedrock = _ThrottleAlwaysBedrock()

    positive_sleep_calls: list[float] = []

    async def capture_sleep(delay: float) -> None:
        if delay > 0:
            positive_sleep_calls.append(delay)

    mocker.patch("asyncio.sleep", side_effect=capture_sleep)

    await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_ONE_SECTION_KWARGS,
    )

    assert positive_sleep_calls == [], (
        f"write.py called asyncio.sleep with positive delay(s): {positive_sleep_calls}. "
        "The retry sleep must live in BedrockClientImpl, not in write.py."
    )


# ---------------------------------------------------------------------------
# T28 — Configurable section caps and min-length filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_short_section_skipped(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """Sections shorter than EMBED_MIN_SECTION_LENGTH are skipped; only longer ones are embedded."""
    settings = _make_settings(monkeypatch, EMBED_MIN_SECTION_LENGTH="50")
    bedrock = FakeBedrockClient()
    embed_spy = mocker.spy(bedrock, "embed")

    # Section 1: 10 chars (skipped). Sections 2 & 3: 200 chars each (pass filter).
    content = (
        "## Short Section\n\n" + "x" * 10 + "\n\n"
        "## Long Section A\n\n" + "x" * 200 + "\n\n"
        "## Long Section B\n\n" + "x" * 200
    )
    kwargs = {**_BASE_WRITE_KWARGS, "content": content}

    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    assert "error" not in result
    assert embed_spy.call_count == 2
    assert result["sections_indexed"] == 2


@pytest.mark.asyncio
async def test_all_sections_short_falls_back_to_document(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """When all sections are filtered by min-length, document-level embed is used as fallback."""
    settings = _make_settings(monkeypatch, EMBED_MIN_SECTION_LENGTH="50")
    bedrock = FakeBedrockClient()
    embed_spy = mocker.spy(bedrock, "embed")

    # Both sections have bodies of only 10 chars — both below the 50-char threshold
    content = "## Tiny A\n\n" + "x" * 10 + "\n\n## Tiny B\n\n" + "x" * 10
    kwargs = {**_BASE_WRITE_KWARGS, "content": content}

    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    assert "error" not in result
    # Document-level fallback: exactly one embed call, one vector indexed
    assert embed_spy.call_count == 1
    assert result["sections_indexed"] == 1


@pytest.mark.asyncio
async def test_min_length_zero_skips_no_sections(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """EMBED_MIN_SECTION_LENGTH=0 disables the filter — all sections are embedded."""
    settings = _make_settings(monkeypatch, EMBED_MIN_SECTION_LENGTH="0")
    bedrock = FakeBedrockClient()
    embed_spy = mocker.spy(bedrock, "embed")

    # Mix of very short and longer sections; with min=0 all 4 pass
    content = (
        "## Tiny\n\nx\n\n"
        "## Small\n\n" + "x" * 5 + "\n\n"
        "## Medium\n\n" + "x" * 80 + "\n\n"
        "## Large\n\n" + "x" * 200
    )
    kwargs = {**_BASE_WRITE_KWARGS, "content": content}

    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    assert "error" not in result
    assert embed_spy.call_count == 4
    assert result["sections_indexed"] == 4


@pytest.mark.asyncio
async def test_sections_capped_at_max(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """25-section document with EMBED_MAX_SECTIONS=20 → only 20 sections are embedded."""
    settings = _make_settings(monkeypatch, EMBED_MAX_SECTIONS="20")
    bedrock = FakeBedrockClient()
    embed_spy = mocker.spy(bedrock, "embed")

    content = _make_sections_content(25)
    kwargs = {**_BASE_WRITE_KWARGS, "content": content}

    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    assert "error" not in result
    assert embed_spy.call_count == 20
    assert result["sections_indexed"] == 20


@pytest.mark.asyncio
async def test_sections_under_cap_not_truncated(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """10-section document with EMBED_MAX_SECTIONS=20 → all 10 sections are embedded (no cap)."""
    settings = _make_settings(monkeypatch, EMBED_MAX_SECTIONS="20")
    bedrock = FakeBedrockClient()
    embed_spy = mocker.spy(bedrock, "embed")

    content = _make_sections_content(10)
    kwargs = {**_BASE_WRITE_KWARGS, "content": content}

    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    assert "error" not in result
    assert embed_spy.call_count == 10
    assert result["sections_indexed"] == 10


@pytest.mark.asyncio
async def test_length_filter_then_cap(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """Filter applied first, then cap: 30 sections (5 short) → 25 pass filter, capped at 20."""
    settings = _make_settings(monkeypatch, EMBED_MIN_SECTION_LENGTH="50", EMBED_MAX_SECTIONS="20")
    bedrock = FakeBedrockClient()
    embed_spy = mocker.spy(bedrock, "embed")

    # 25 long sections (120 chars) + 5 short sections (10 chars)
    content = _make_mixed_sections_content(long_count=25, short_count=5)
    kwargs = {**_BASE_WRITE_KWARGS, "content": content}

    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    assert "error" not in result
    # 25 long pass filter; capped at 20
    assert embed_spy.call_count == 20
    assert result["sections_indexed"] == 20


@pytest.mark.asyncio
async def test_all_filtered_then_capped_falls_back(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """All sections filtered by a very large min-length → document-level fallback (1 embed)."""
    # Set min-length so large that all section bodies are below threshold
    settings = _make_settings(monkeypatch, EMBED_MIN_SECTION_LENGTH="10000")
    bedrock = FakeBedrockClient()
    embed_spy = mocker.spy(bedrock, "embed")

    content = _make_sections_content(5, body_length=50)  # 50 chars each — far below 10000
    kwargs = {**_BASE_WRITE_KWARGS, "content": content}

    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    assert "error" not in result
    # All filtered → document-level fallback: one embed, one vector
    assert embed_spy.call_count == 1
    assert result["sections_indexed"] == 1


# ---------------------------------------------------------------------------
# Z1 — P4 Section body truncation before embed (EMBED_MAX_SECTION_LENGTH)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_section_body_truncated_before_embed(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """Section body > embed_max_section_length → bedrock.embed receives truncated body.

    The embed text must not contain the full 200-char body; only the first 100 chars
    of the body should appear in the embedding input.
    """
    # Red: EMBED_MAX_SECTION_LENGTH is not a Settings field yet; write.py never truncates.
    settings = _make_settings(monkeypatch, EMBED_MAX_SECTION_LENGTH="100")
    bedrock = FakeBedrockClient()
    embed_spy = mocker.spy(bedrock, "embed")

    body = "a" * 200
    content = f"## Truncation Test\n\n{body}"
    kwargs = {**_BASE_WRITE_KWARGS, "content": content}

    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    assert "error" not in result
    embed_texts = [call.args[0] for call in embed_spy.call_args_list]
    assert len(embed_texts) >= 1
    # With EMBED_MAX_SECTION_LENGTH=100, no embed call should contain 101+ consecutive 'a's
    assert all("a" * 101 not in text for text in embed_texts), (
        "bedrock.embed received the full untruncated body — truncation not implemented"
    )


@pytest.mark.asyncio
async def test_section_full_body_stored_in_s3_despite_embed_truncation(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """S3 stores the full untruncated body even when EMBED_MAX_SECTION_LENGTH is set.

    The truncation is embedding-input-only; the stored content is always the original.
    """
    settings = _make_settings(monkeypatch, EMBED_MAX_SECTION_LENGTH="100")
    bedrock = FakeBedrockClient()
    embed_spy = mocker.spy(bedrock, "embed")

    body = "a" * 200
    content = f"## Truncation Test\n\n{body}"
    kwargs = {**_BASE_WRITE_KWARGS, "content": content}

    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    assert "error" not in result
    # S3 must store the full untruncated content
    stored = s3_client.get_object(result["artifact_id"])
    assert body in stored, "S3 must contain the full untruncated body"

    # Embed must have received the truncated body (not the full 200 chars)
    embed_texts = [call.args[0] for call in embed_spy.call_args_list]
    assert all("a" * 101 not in text for text in embed_texts), (
        "bedrock.embed received the full untruncated body — truncation not implemented"
    )


@pytest.mark.asyncio
async def test_sections_under_max_length_are_all_embedded(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """Sections whose bodies are below EMBED_MAX_SECTION_LENGTH are embedded unchanged.

    This is the normal-path case: every section should appear in sections_indexed
    and bedrock.embed must receive the full (untruncated) body for each section.
    """
    settings = _make_settings(monkeypatch, EMBED_MAX_SECTION_LENGTH="200")
    bedrock = FakeBedrockClient()
    embed_spy = mocker.spy(bedrock, "embed")

    body_a = "a" * 50  # well under the 200-char limit
    body_b = "b" * 75  # well under the 200-char limit
    content = f"## Section A\n\n{body_a}\n\n## Section B\n\n{body_b}"
    kwargs = {**_BASE_WRITE_KWARGS, "content": content}

    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    # Both sections must be indexed — document-level fallback must NOT fire
    assert result["sections_indexed"] == 2, (
        f"Expected 2 sections indexed, got {result['sections_indexed']}. "
        "Sections under embed_max_section_length may have been silently dropped."
    )

    # Each embed call must carry the full (untruncated) body
    embed_texts = [call.args[0] for call in embed_spy.call_args_list]
    assert any(body_a in text for text in embed_texts), (
        "Full body_a not found in any bedrock.embed call — section was dropped or truncated"
    )
    assert any(body_b in text for text in embed_texts), (
        "Full body_b not found in any bedrock.embed call — section was dropped or truncated"
    )


@pytest.mark.asyncio
async def test_embed_max_section_length_zero_disables_truncation(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """EMBED_MAX_SECTION_LENGTH=0 → section bodies passed to embed unmodified.

    Zero is the special sentinel that disables the truncation guard entirely.
    """
    settings = _make_settings(monkeypatch, EMBED_MAX_SECTION_LENGTH="0")
    bedrock = FakeBedrockClient()
    embed_spy = mocker.spy(bedrock, "embed")

    body = "b" * 500
    content = f"## Big Section\n\n{body}"
    kwargs = {**_BASE_WRITE_KWARGS, "content": content}

    await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    # Red: Settings doesn't have embed_max_section_length yet — attribute access fails
    assert getattr(settings, "embed_max_section_length", "NOT_SET") == 0, (
        "Settings.embed_max_section_length not yet implemented"
    )
    embed_texts = [call.args[0] for call in embed_spy.call_args_list]
    # With limit=0, the full 500-char body must appear in at least one embed call
    assert any("b" * 500 in text for text in embed_texts), (
        "Full body should be passed unchanged when embed_max_section_length=0"
    )


@pytest.mark.asyncio
async def test_section_truncation_logged_at_debug(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When a section body is truncated, the event is logged at DEBUG level.

    The truncation now happens inside the shared ``arkeology.tools._section_pipeline``
    helper, not in ``arkeology.tools.write`` directly, so the log is emitted
    under that module's logger.
    """
    settings = _make_settings(monkeypatch, EMBED_MAX_SECTION_LENGTH="50")
    bedrock = FakeBedrockClient()

    body = "c" * 200  # body exceeds the 50-char limit
    content = f"## Long Section\n\n{body}"
    kwargs = {**_BASE_WRITE_KWARGS, "content": content}

    with caplog.at_level(logging.DEBUG, logger="arkeology.tools._section_pipeline"):
        await write_artifact(
            s3=s3_client,
            vectors=vectors_client,
            bedrock=bedrock,
            settings=settings,
            **kwargs,
        )

    # Red: write.py does not log truncation yet
    truncation_logs = [r for r in caplog.records if "truncat" in r.message.lower()]
    assert len(truncation_logs) >= 1, (
        "Expected at least one DEBUG log message mentioning 'truncat' — not yet implemented"
    )


# ---------------------------------------------------------------------------
# T36 — last_edited_ulid and commit_refs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_response_includes_last_edited_ulid(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """write_artifact response includes 'last_edited_ulid' as a non-empty string."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )

    assert "last_edited_ulid" in result
    assert isinstance(result["last_edited_ulid"], str)
    assert len(result["last_edited_ulid"]) > 0


@pytest.mark.asyncio
async def test_write_successive_ulids_are_monotonic(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """Two successive write_artifact calls produce monotonically ordered ULIDs."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()

    result1 = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **{**_BASE_WRITE_KWARGS, "title": "First artifact"},
    )
    result2 = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **{**_BASE_WRITE_KWARGS, "title": "Second artifact"},
    )

    assert result1["last_edited_ulid"] <= result2["last_edited_ulid"]


@pytest.mark.asyncio
async def test_write_last_edited_ulid_in_s3_metadata(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """S3 put_object is called with 'last_edited_ulid' in the metadata dict."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    spy = mocker.spy(s3_client, "put_object")

    await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )

    _, _, metadata = spy.call_args.args
    assert "last_edited_ulid" in metadata
    assert isinstance(metadata["last_edited_ulid"], str)
    assert len(metadata["last_edited_ulid"]) > 0


@pytest.mark.asyncio
async def test_write_last_edited_ulid_in_vector_metadata(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """put_vectors_batch is called with 'last_edited_ulid' in each vector's metadata."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    spy = mocker.spy(vectors_client, "put_vectors_batch")

    await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )

    items = spy.call_args.args[0]
    for item in items:
        assert "last_edited_ulid" in item["metadata"]
        assert isinstance(item["metadata"]["last_edited_ulid"], str)


@pytest.mark.asyncio
async def test_write_commit_refs_stored_in_annotation_and_vector_metadata(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """commit_refs=['abc1234'] stored as a comma-joined S3 annotation (T47/ADR-011,
    NOT S3 user-defined metadata) and as list[str] in vector metadata."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    s3_spy = mocker.spy(s3_client, "put_object")
    vec_spy = mocker.spy(vectors_client, "put_vectors_batch")

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **{**_BASE_WRITE_KWARGS, "commit_refs": ["abc1234"]},
    )

    _, _, s3_meta = s3_spy.call_args.args
    assert "commit_refs" not in s3_meta

    assert s3_client.get_object_annotation(result["artifact_id"], "commit_refs") == "abc1234"

    vec_items = vec_spy.call_args.args[0]
    for item in vec_items:
        assert item["metadata"]["commit_refs"] == ["abc1234"]


@pytest.mark.asyncio
async def test_write_empty_commit_refs_annotation_absent(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """commit_refs=[] → no commit_refs annotation is written, no S3 metadata key, and
    the field is omitted from vector metadata."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    s3_spy = mocker.spy(s3_client, "put_object")
    vec_spy = mocker.spy(vectors_client, "put_vectors_batch")

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )

    _, _, s3_meta = s3_spy.call_args.args
    assert "commit_refs" not in s3_meta

    with pytest.raises(KeyError):
        s3_client.get_object_annotation(result["artifact_id"], "commit_refs")

    vec_items = vec_spy.call_args.args[0]
    for item in vec_items:
        assert "commit_refs" not in item["metadata"]


# ---------------------------------------------------------------------------
# T46 — references field
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_references_never_stored_in_vector_metadata(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """T58: references=['a-1', 'b-2'] is never written into vector metadata, even
    though non-empty — the S3 annotation is its sole durable store and sole read
    surface as of T58."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    vec_spy = mocker.spy(vectors_client, "put_vectors_batch")

    await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **{**_BASE_WRITE_KWARGS, "references": ["a-1", "b-2"]},
    )

    vec_items = vec_spy.call_args.args[0]
    for item in vec_items:
        assert "references" not in item["metadata"]


@pytest.mark.asyncio
async def test_write_empty_references_omitted_from_vector_metadata(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """references=[] (or omitted) omits the 'references' key from vector metadata."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    vec_spy = mocker.spy(vectors_client, "put_vectors_batch")

    await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )

    vec_items = vec_spy.call_args.args[0]
    for item in vec_items:
        assert "references" not in item["metadata"]


@pytest.mark.asyncio
async def test_write_references_not_stored_in_s3_metadata(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """references is never written to S3 user-defined object metadata (durable copy is T47's job).

    Preserves the dual-encoding split: S3 object metadata carries only
    write-time-set identity fields; the annotation-backed durable copy is added
    in T47 (ADR-011). This spec only covers vector metadata + read/list surfacing.
    """
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    s3_spy = mocker.spy(s3_client, "put_object")

    await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **{**_BASE_WRITE_KWARGS, "references": ["a-1"]},
    )

    _, _, s3_meta = s3_spy.call_args.args
    assert "references" not in s3_meta


# ---------------------------------------------------------------------------
# T47 — annotation dual-write in the write path + overwrite preservation (AC-60)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_references_stored_in_annotation_not_vector_metadata(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """references=['a-1', 'b-2'] is written as a comma-joined S3 annotation — its sole
    durable store as of T58 — and never appears in vector metadata."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    vec_spy = mocker.spy(vectors_client, "put_vectors_batch")

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **{**_BASE_WRITE_KWARGS, "references": ["a-1", "b-2"]},
    )

    assert s3_client.get_object_annotation(result["artifact_id"], "references") == "a-1,b-2"
    vec_items = vec_spy.call_args.args[0]
    for item in vec_items:
        assert "references" not in item["metadata"]


@pytest.mark.asyncio
async def test_write_empty_references_annotation_absent(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """references=[] → no references annotation is written."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )

    with pytest.raises(KeyError):
        s3_client.get_object_annotation(result["artifact_id"], "references")


@pytest.mark.asyncio
async def test_write_fresh_artifact_no_link_fields_skips_annotation_delete_calls(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """A fresh (never-existed) artifact write with no commit_refs/references supplied
    has nothing to clear — apply_link_annotations must not issue pointless
    delete_object_annotation round trips for fields that never had a value."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    delete_spy = mocker.spy(s3_client, "delete_object_annotation")

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )

    assert "error" not in result
    assert delete_spy.call_count == 0, (
        "A fresh write with no commit_refs/references supplied must not call "
        f"delete_object_annotation at all — got {delete_spy.call_count} call(s)"
    )


@pytest.mark.asyncio
async def test_write_annotations_written_after_put_object_before_put_vectors_batch(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """Durable-first ordering (ADR-011, Story 3): PutObject → annotation write →
    put_vectors_batch, so a failed vector write can self-heal from the durable side
    via a later reconcile_index (T48)."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()

    call_order: list[str] = []

    original_put_object = s3_client.put_object

    def _put_object(*args: object, **kwargs: object) -> None:
        call_order.append("put_object")
        return original_put_object(*args, **kwargs)  # type: ignore[arg-type]

    original_put_annotation = s3_client.put_object_annotation

    def _put_annotation(*args: object, **kwargs: object) -> None:
        call_order.append("put_object_annotation")
        return original_put_annotation(*args, **kwargs)  # type: ignore[arg-type]

    original_batch = vectors_client.put_vectors_batch

    def _put_batch(*args: object, **kwargs: object) -> None:
        call_order.append("put_vectors_batch")
        return original_batch(*args, **kwargs)  # type: ignore[arg-type]

    mocker.patch.object(s3_client, "put_object", side_effect=_put_object)
    mocker.patch.object(s3_client, "put_object_annotation", side_effect=_put_annotation)
    mocker.patch.object(vectors_client, "put_vectors_batch", side_effect=_put_batch)

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **{**_BASE_WRITE_KWARGS, "commit_refs": ["abc1234"]},
    )

    assert "error" not in result
    assert call_order == ["put_object", "put_object_annotation", "put_vectors_batch"]


@pytest.mark.asyncio
async def test_write_with_link_fields_triggers_no_extra_embed_call(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """Supplying commit_refs/references triggers no additional Bedrock embed call — the
    annotation write is metadata-only and never re-embeds (Story 1 AC)."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    embed_spy = mocker.spy(bedrock, "embed")

    await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **{**_BASE_WRITE_KWARGS, "commit_refs": ["abc1234"], "references": ["a-1"]},
    )

    # _BASE_WRITE_KWARGS content has exactly 3 sections (Summary, Details, Action Items) —
    # one embed call per section, and none extra for the annotation write.
    assert embed_spy.call_count == 3


@pytest.mark.asyncio
async def test_tier3_overwrite_preserves_commit_refs_and_replaces_references(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """AC-60 (core test) for the reference-field value semantics: a tier-3
    overwrite must not lose commit_refs that were accumulated on
    the artifact, even though the underlying PutObject clears S3 annotations — the prior
    commit_refs must be read forward and merged (union) with any newly supplied value.
    references, by contrast, is REPLACED outright: the overwrite here supplies only a new
    reference (no new commit_refs), and the post-write references must be exactly the
    supplied list — not unioned with the prior stored value (ADR-011 decision 4)."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    tier3_kwargs = {**_BASE_WRITE_KWARGS, "tier": 3}

    first = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **{**tier3_kwargs, "commit_refs": ["abc1234"], "references": ["a-1"]},
    )
    artifact_id = first["artifact_id"]

    # Sanity: the durable annotation copy exists after the first write.
    assert s3_client.get_object_annotation(artifact_id, "commit_refs") == "abc1234"

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        overwrite=True,
        **{
            **tier3_kwargs,
            "content": "## Summary\n\nUpdated content.",
            "references": ["b-2"],
        },
    )

    assert "error" not in result
    assert result["artifact_id"] == artifact_id

    # PutObject cleared the annotations; the write path must have read commit_refs
    # forward from the durable stores and re-applied it (union), while references is
    # replaced outright with exactly the value supplied to this call.
    assert s3_client.get_object_annotation(artifact_id, "commit_refs") == "abc1234"
    assert s3_client.get_object_annotation(artifact_id, "references") == "b-2"

    keys = vectors_client.list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}})
    entries = vectors_client.get_vectors(keys)
    assert entries, "expected at least one vector for the overwritten artifact"
    for entry in entries:
        assert entry["metadata"]["commit_refs"] == ["abc1234"]
        # T58: references is never written to vector metadata, regardless of value.
        assert "references" not in entry["metadata"]


@pytest.mark.asyncio
async def test_tier3_overwrite_omitted_references_clears_field(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """A tier-3 overwrite that omits references (normalised to [] by the public
    wrapper) clears the field entirely: the annotation is deleted and the vector
    metadata key is absent — references mirrors the artifact's current frontmatter,
    so a write that no longer lists it must shed it (ADR-011 decision 4,
    operator-confirmed intended)."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    tier3_kwargs = {**_BASE_WRITE_KWARGS, "tier": 3}

    first = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **{**tier3_kwargs, "references": ["a-1"]},
    )
    artifact_id = first["artifact_id"]
    assert s3_client.get_object_annotation(artifact_id, "references") == "a-1"

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        overwrite=True,
        **{**tier3_kwargs, "content": "## Summary\n\nUpdated content."},
    )

    assert "error" not in result
    with pytest.raises(KeyError):
        s3_client.get_object_annotation(artifact_id, "references")

    keys = vectors_client.list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}})
    entries = vectors_client.get_vectors(keys)
    assert entries
    for entry in entries:
        assert "references" not in entry["metadata"]


@pytest.mark.asyncio
async def test_link_metadata_backfilled_reference_dropped_by_subsequent_overwrite(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """Documents the frozen link_metadata/overwrite interaction (ADR-011 decision 4):
    link_metadata backfills references=["z-9"] onto an artifact whose references is
    ["a-1"] (union, link_metadata's own merge is unchanged) — but a subsequent ordinary
    overwrite supplying only references=["a-1"] then replaces the field back down to
    ["a-1"], dropping "z-9". This is the expected, intentional consequence of
    references being a claim about current state, not a defect."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    tier3_kwargs = {**_BASE_WRITE_KWARGS, "tier": 3}

    first = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **{**tier3_kwargs, "references": ["a-1"]},
    )
    artifact_id = first["artifact_id"]

    link_result = await link_metadata(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client,
        artifact_ids=[artifact_id],
        references=["z-9"],
    )
    assert link_result.get("linked") == 1
    assert s3_client.get_object_annotation(artifact_id, "references") == "a-1,z-9"

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        overwrite=True,
        **{**tier3_kwargs, "content": "## Summary\n\nUpdated content.", "references": ["a-1"]},
    )

    assert "error" not in result
    assert s3_client.get_object_annotation(artifact_id, "references") == "a-1"
    keys = vectors_client.list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}})
    entries = vectors_client.get_vectors(keys)
    assert entries
    # T58: references is never written to vector metadata — the annotation assertion
    # above is this test's sole surface for the documented drop-"z-9" behaviour.
    for entry in entries:
        assert "references" not in entry["metadata"]


@pytest.mark.asyncio
async def test_tier2_explicit_overwrite_preserves_prior_link_fields(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """The tier-2 explicit-replacement overwrite path (ADR-011 decision 4) also
    preserves prior commit_refs/references — the same read-forward + merge applies
    regardless of tier."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()

    first = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **{**_BASE_WRITE_KWARGS, "commit_refs": ["abc1234"]},
    )
    artifact_id = first["artifact_id"]

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        overwrite=True,
        **{**_BASE_WRITE_KWARGS, "content": "## Summary\n\nUpdated content."},
    )

    assert "error" not in result
    assert s3_client.get_object_annotation(artifact_id, "commit_refs") == "abc1234"

    keys = vectors_client.list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}})
    entries = vectors_client.get_vectors(keys)
    for entry in entries:
        assert entry["metadata"]["commit_refs"] == ["abc1234"]


@pytest.mark.asyncio
async def test_write_credential_error_from_annotation_write_is_structured(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
    tmp_path: pytest.TempPathFactory,
) -> None:
    """A CredentialError raised by put_object_annotation surfaces as a structured
    credential_error including artifact_id — never a raw exception — and no vector
    write is attempted. A failure-log entry IS written since the S3 put has
    already succeeded by this point — the annotation write happens after PutObject."""
    log_path = tmp_path / "failures.jsonl"
    settings = _make_settings(monkeypatch, FAILURE_LOG_PATH=str(log_path))
    bedrock = FakeBedrockClient()
    mocker.patch.object(
        s3_client,
        "put_object_annotation",
        side_effect=CredentialError("expired", "s3", Exception("boom")),
    )
    batch_spy = mocker.spy(vectors_client, "put_vectors_batch")

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **{**_BASE_WRITE_KWARGS, "commit_refs": ["abc1234"]},
    )

    assert result["error"] == "credential_error"
    assert "artifact_id" in result
    assert batch_spy.call_count == 0
    assert log_path.exists()
    entries = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert len(entries) == 1
    assert entries[0]["failure_step"] == "annotation_write"
    assert entries[0]["artifact_id"] == result["artifact_id"]


@pytest.mark.asyncio
async def test_write_overwrite_cas_put_object_credential_error_includes_artifact_id(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """A CredentialError raised by the overwrite CAS retry loop's ``s3.put_object``
    call surfaces ``artifact_id`` in its response, matching its two sibling
    CredentialError handlers in the same loop iteration."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()

    first = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )
    artifact_id = first["artifact_id"]

    mocker.patch.object(
        s3_client,
        "put_object",
        side_effect=CredentialError("expired", "s3", Exception("boom")),
    )

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        overwrite=True,
        **{**_BASE_WRITE_KWARGS, "content": "## Summary\n\nUpdated content."},
    )

    assert result["error"] == "credential_error"
    assert result["artifact_id"] == artifact_id


# ---------------------------------------------------------------------------
# T52 — annotation availability graceful degrade (write path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_annotation_unavailable_still_succeeds_with_warning(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """An AnnotationUnavailableError raised by the durable annotation write must never
    lose the artifact (ADR-011 decision 5): content and vectors are still persisted and
    the response carries a non-empty top-level 'warning' instead of an 'error'."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    mocker.patch.object(
        s3_client,
        "put_object_annotation",
        side_effect=AnnotationUnavailableError(
            "S3 object annotations are unavailable for this bucket.", "s3", Exception("boom")
        ),
    )

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **{**_BASE_WRITE_KWARGS, "commit_refs": ["abc1234"]},
    )

    assert "error" not in result
    assert result["artifact_id"]
    assert result["sections_indexed"] == 3
    assert result.get("warning")

    # Content is durably stored despite the annotation failure.
    stored_content = s3_client.get_object(result["artifact_id"])
    assert stored_content == _BASE_WRITE_KWARGS["content"]

    # Vectors carry the supplied commit_refs even though the durable annotation
    # copy could not be written.
    keys = vectors_client.list_vectors_by_metadata({"artifact_id": {"$eq": result["artifact_id"]}})
    entries = vectors_client.get_vectors(keys)
    assert entries
    for entry in entries:
        assert entry["metadata"]["commit_refs"] == ["abc1234"]


@pytest.mark.asyncio
async def test_write_without_link_fields_no_warning_when_annotations_available(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """A normal write with annotations available carries no 'warning' field."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )

    assert "error" not in result
    assert "warning" not in result


# ---------------------------------------------------------------------------
# file_extension parameter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_file_extension_txt_produces_key_ending_in_txt(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """file_extension='.txt' → returned artifact_id ends with '.txt'."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        file_extension=".txt",
        **_BASE_WRITE_KWARGS,
    )

    assert "error" not in result
    assert result["artifact_id"].endswith(".txt")


@pytest.mark.asyncio
async def test_file_extension_without_dot_returns_validation_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """file_extension without leading dot → validation_error; no AWS calls made."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        file_extension="nodot",
        **_BASE_WRITE_KWARGS,
    )

    assert result.get("error") == "validation_error"
    assert "message" in result
    assert len(s3_client.list_objects("")) == 0


@pytest.mark.asyncio
async def test_default_file_extension_is_md(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """Default file_extension → returned artifact_id ends with '.md'."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )

    assert "error" not in result
    assert result["artifact_id"].endswith(".md")


# ---------------------------------------------------------------------------
# M11 — dedicated embed executor
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# M12 — partial_write message includes failure log path (T15 AC)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_partial_write_embed_message_includes_failure_log_path(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    tmp_path: pytest.TempPathFactory,
) -> None:
    """partial_write on embed failure → message includes the failure log path (T15 AC).

    A caller receiving partial_write must be able to locate the failure log entry
    without searching — the path is embedded in the error message.
    """
    log_path = tmp_path / "failures.jsonl"
    settings = _make_settings(monkeypatch, FAILURE_LOG_PATH=str(log_path))
    bedrock = _FailOnSecondEmbedBedrock()

    content = _make_sections_content(3)
    kwargs = {**_BASE_WRITE_KWARGS, "content": content}

    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    assert result.get("error") == "partial_write"
    assert str(log_path) in result["message"]


@pytest.mark.asyncio
async def test_partial_write_put_vector_message_includes_failure_log_path(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    tmp_path: pytest.TempPathFactory,
    mocker: pytest.MonkeyPatch,
) -> None:
    """partial_write on put_vectors_batch failure → message includes the failure log path."""
    log_path = tmp_path / "failures.jsonl"
    settings = _make_settings(monkeypatch, FAILURE_LOG_PATH=str(log_path))
    bedrock = FakeBedrockClient()
    mocker.patch.object(
        vectors_client,
        "put_vectors_batch",
        side_effect=RuntimeError("simulated put failure"),
    )

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_ONE_SECTION_KWARGS,
    )

    assert result.get("error") == "partial_write"
    assert str(log_path) in result["message"]


def test_embed_executor_has_adequate_max_workers() -> None:
    """_EMBED_EXECUTOR must be sized for the maximum compound concurrency.

    Peak demand = artifact_concurrency_max (15) × SECTION_CONCURRENCY default (5).
    The dedicated pool must not be smaller than that product so that SECTION_CONCURRENCY
    semaphore slots across all concurrent artifact writes can all run simultaneously.
    """
    import arkeology.tools.write as write_module
    from arkeology.tools._concurrency import _ARTIFACT_CONCURRENCY_MAX

    expected_min = _ARTIFACT_CONCURRENCY_MAX * 5  # 5 = SECTION_CONCURRENCY default
    assert write_module._EMBED_EXECUTOR._max_workers >= expected_min


def test_embed_executor_not_created_at_import_time() -> None:
    """_EMBED_EXECUTOR (a 300-thread pool) must not be constructed merely by importing
    write.py — a module-level ``ThreadPoolExecutor(max_workers=300, ...)``
    spins up 300 OS threads at import time, every time the module is (re)imported,
    regardless of whether write_artifact is ever called. It should be created lazily,
    on first actual use.
    """
    import importlib
    from unittest.mock import patch

    import arkeology.tools.write as write_module

    try:
        with patch("concurrent.futures.ThreadPoolExecutor") as mock_executor_cls:
            importlib.reload(write_module)
            assert mock_executor_cls.call_count == 0, (
                "ThreadPoolExecutor must not be constructed merely by importing "
                "arkeology.tools.write — it should be created lazily on first use"
            )
    finally:
        # Restore the module to its normal (real ThreadPoolExecutor) state
        # regardless of the outcome above, so later tests in this session are
        # unaffected.
        importlib.reload(write_module)


@pytest.mark.asyncio
async def test_embed_uses_dedicated_executor(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """Section embed calls must go through _EMBED_EXECUTOR, not the default asyncio executor.

    Verifies that run_in_executor(_EMBED_EXECUTOR, ...) is used rather than to_thread(),
    so compound concurrency (artifact_concurrency × section_concurrency) is bounded by the
    dedicated pool and not by asyncio's default executor.
    """
    import arkeology.tools.write as write_module

    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    submit_spy = mocker.spy(write_module._EMBED_EXECUTOR, "submit")

    content = _make_sections_content(3)
    kwargs = {**_BASE_WRITE_KWARGS, "content": content}

    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    assert "error" not in result
    # 3 sections → 3 run_in_executor calls → 3 submit() calls on _EMBED_EXECUTOR
    assert submit_spy.call_count == 3


@pytest.mark.asyncio
async def test_doc_fallback_embed_uses_dedicated_executor(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """Document-fallback embed (no sections) must also use _EMBED_EXECUTOR."""
    import arkeology.tools.write as write_module

    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    submit_spy = mocker.spy(write_module._EMBED_EXECUTOR, "submit")

    # No H2 headings → falls through to document-level embedding
    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_ONE_SECTION_KWARGS,
    )

    assert "error" not in result
    # 1 document-level embed → exactly 1 submit call
    assert submit_spy.call_count == 1


# ---------------------------------------------------------------------------
# T55 — write-path metadata size + charset validation, fail-fast pre-write
# ---------------------------------------------------------------------------


async def test_oversize_s3_metadata_rejected_before_any_write(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    tmp_path: pytest.TempPathFactory,
    mocker: pytest.MonkeyPatch,
) -> None:
    """An oversize source_artifacts value pushes the S3 user-metadata aggregate past its
    2 KB budget. This value is non-filterable in vector metadata (excluded from the 2 KB
    filterable budget) and small relative to the 40 KB total budget, so it isolates the S3
    budget specifically. The write must be rejected with validation_error and must perform
    NO head_object/put_object/put_vectors_batch call and append NO failure-log entry —
    failure mode being guarded against is exactly the case where S3 succeeds first and
    only the vector write fails later, leaving a partial write that reconcile replays
    forever.
    """
    log_path = tmp_path / "failures.jsonl"
    settings = _make_settings(monkeypatch, FAILURE_LOG_PATH=str(log_path))
    bedrock = FakeBedrockClient()
    head_spy = mocker.spy(s3_client, "head_object")
    put_spy = mocker.spy(s3_client, "put_object")
    batch_spy = mocker.spy(vectors_client, "put_vectors_batch")

    oversize_source = "a" * (S3_USER_METADATA_MAX_BYTES + 200)
    kwargs = {**_BASE_WRITE_KWARGS, "source_artifacts": [oversize_source]}

    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    assert result.get("error") == "validation_error"
    assert head_spy.call_count == 0
    assert put_spy.call_count == 0
    assert batch_spy.call_count == 0
    assert not log_path.exists()
    assert len(s3_client.list_objects("")) == 0
    assert len(vectors_client.list_vectors_by_metadata({})) == 0


async def test_oversize_tags_rejected_before_any_write(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    tmp_path: pytest.TempPathFactory,
    mocker: pytest.MonkeyPatch,
) -> None:
    """A very large tags list breaches the vector filterable-metadata budget (tags is a
    filterable field). Today it also breaches the S3 aggregate budget because tags is
    mirrored into S3 user-metadata pre-T47 — either guard rejects the write before any
    storage operation, which is what this test verifies: validation_error, zero
    head_object/put_object/put_vectors_batch calls, no failure-log entry.
    """
    log_path = tmp_path / "failures.jsonl"
    settings = _make_settings(monkeypatch, FAILURE_LOG_PATH=str(log_path))
    bedrock = FakeBedrockClient()
    head_spy = mocker.spy(s3_client, "head_object")
    put_spy = mocker.spy(s3_client, "put_object")
    batch_spy = mocker.spy(vectors_client, "put_vectors_batch")

    huge_tag = "t" * (S3_USER_METADATA_MAX_BYTES + 200)
    kwargs = {**_BASE_WRITE_KWARGS, "tags": [huge_tag]}

    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    assert result.get("error") == "validation_error"
    assert head_spy.call_count == 0
    assert put_spy.call_count == 0
    assert batch_spy.call_count == 0
    assert not log_path.exists()


async def test_oversize_metadata_leaves_nothing_for_reconcile_to_replay(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    tmp_path: pytest.TempPathFactory,
) -> None:
    """After a rejected oversize write, reconcile_index finds nothing to replay: no S3
    object was created and no failure-log entry exists, so the failure never becomes a
    self-perpetuating reconcile-replay loop.
    """
    log_path = tmp_path / "failures.jsonl"
    settings = _make_settings(monkeypatch, FAILURE_LOG_PATH=str(log_path))
    bedrock = FakeBedrockClient()

    oversize_source = "a" * (S3_USER_METADATA_MAX_BYTES + 200)
    kwargs = {**_BASE_WRITE_KWARGS, "source_artifacts": [oversize_source]}

    write_result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )
    assert write_result.get("error") == "validation_error"

    reconcile_result = await reconcile_index(
        settings=settings, s3=s3_client, vectors=vectors_client, bedrock=bedrock
    )

    assert reconcile_result["reconciled"] == []
    assert reconcile_result["failed"] == []
    assert reconcile_result["failure_log_entries_before"] == 0
    assert reconcile_result["orphans_found"] == 0


async def test_control_char_in_title_rejected_as_validation_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """A control character (e.g. newline) in title must surface as a structured
    validation_error — never a raw exception (previously this reached urllib3 as a bare
    ValueError once the value hit S3's HTTP-header transport)."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    put_spy = mocker.spy(s3_client, "put_object")

    kwargs = {**_BASE_WRITE_KWARGS, "title": "Bad\ntitle"}

    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    assert result.get("error") == "validation_error"
    assert "message" in result
    assert put_spy.call_count == 0


async def test_non_ascii_title_written_and_read_back_via_vector_metadata(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """A non-Latin title writes successfully; the vector metadata (search's title source)
    holds the raw, undamaged UTF-8 title — never a percent-encoded or stripped copy."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()

    kwargs = {**_ONE_SECTION_KWARGS, "title": "日本語のタイトル"}
    result = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **kwargs
    )

    assert "error" not in result
    artifact_id = result["artifact_id"]
    keys = vectors_client.list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}})
    entries = vectors_client.get_vectors(keys)
    assert entries[0]["metadata"]["title"] == "日本語のタイトル"


# ---------------------------------------------------------------------------
# T55 budget re-check must cover the T47 read-forward
# merge on an overwrite. Step 3c only measures the *supplied* commit_refs/
# references; the Step 4a merge unions them with the values already indexed
# in vector metadata and can push the enlarged list past the 2 KB filterable
# budget with no re-check in between — reintroducing the exact deterministic
# partial-write / failure-log-replay loop T55 exists to prevent.
# ---------------------------------------------------------------------------

# Each list is comfortably under VECTOR_FILTERABLE_METADATA_MAX_BYTES (2048) on
# its own once combined with the artifact's other filterable fields, but their
# union is not — this isolates the missing post-merge re-check rather than
# re-testing the pre-merge Step 3c guard already covered above.
#
# T58: the union's entry count is deliberately kept AT (not over)
# COMMIT_REFS_VECTOR_METADATA_MAX_ENTRIES (2 * _LINK_FIELD_ITEM_COUNT == 20) so
# cap_commit_refs_for_vectors is a no-op here — this test isolates a pure byte-budget
# breach that survives the cap, not the cap's own entry-count truncation (covered
# separately by the dedicated T58 cap tests below).
_LINK_FIELD_ITEM_LEN = 80
_LINK_FIELD_ITEM_COUNT = 10


def _make_link_field_batch(prefix: str) -> list[str]:
    """Build a list of unique commit-ref-shaped strings for budget-breach tests."""
    return [f"{prefix}{i:04d}" + "x" * _LINK_FIELD_ITEM_LEN for i in range(_LINK_FIELD_ITEM_COUNT)]


@pytest.mark.asyncio
async def test_overwrite_merged_commit_refs_exceeding_filterable_budget_rejected(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    tmp_path: pytest.TempPathFactory,
    mocker: pytest.MonkeyPatch,
) -> None:
    """A tier-3 overwrite whose *supplied* commit_refs pass the pre-merge Step 3c
    check, but whose union with the *already-indexed* commit_refs (read forward by
    Step 4a) breaches the vector filterable-metadata budget, must be rejected with
    validation_error — with NO put_object, NO put_vectors_batch, and NO failure-log
    entry on the overwrite attempt. The original artifact and vectors must be left
    completely untouched.
    """
    log_path = tmp_path / "failures.jsonl"
    settings = _make_settings(monkeypatch, FAILURE_LOG_PATH=str(log_path))
    bedrock = FakeBedrockClient()
    tier3_kwargs = {**_BASE_WRITE_KWARGS, "tier": 3}

    existing_refs = _make_link_field_batch("a")
    new_refs = _make_link_field_batch("b")
    # Sanity: each batch alone is under budget — the breach only appears after the union.
    assert len(json.dumps(existing_refs).encode("utf-8")) < VECTOR_FILTERABLE_METADATA_MAX_BYTES
    assert len(json.dumps(new_refs).encode("utf-8")) < VECTOR_FILTERABLE_METADATA_MAX_BYTES

    first = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **{**tier3_kwargs, "commit_refs": existing_refs},
    )
    assert "error" not in first
    artifact_id = first["artifact_id"]

    put_spy = mocker.spy(s3_client, "put_object")
    batch_spy = mocker.spy(vectors_client, "put_vectors_batch")

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        overwrite=True,
        **{**tier3_kwargs, "content": "## Summary\n\nUpdated content.", "commit_refs": new_refs},
    )

    assert result.get("error") == "validation_error"
    assert put_spy.call_count == 0
    assert batch_spy.call_count == 0
    assert not log_path.exists()

    # The original artifact and its vector metadata are untouched by the rejected overwrite.
    stored_content = s3_client.get_object(artifact_id)
    assert "Updated content" not in stored_content
    keys = vectors_client.list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}})
    entries = vectors_client.get_vectors(keys)
    assert entries, "expected the original vectors to remain indexed"
    for entry in entries:
        assert entry["metadata"]["commit_refs"] == existing_refs


@pytest.mark.asyncio
async def test_overwrite_merged_commit_refs_under_budget_still_succeeds(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """Positive case: an overwrite whose merged (existing + supplied) commit_refs
    stay under the filterable budget must still succeed — the post-merge re-check
    must not reject writes that were always going to fit.
    """
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    tier3_kwargs = {**_BASE_WRITE_KWARGS, "tier": 3}

    first = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **{**tier3_kwargs, "commit_refs": ["abc1234"]},
    )
    assert "error" not in first
    artifact_id = first["artifact_id"]

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        overwrite=True,
        **{**tier3_kwargs, "content": "## Summary\n\nUpdated content.", "commit_refs": ["def5678"]},
    )

    assert "error" not in result
    keys = vectors_client.list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}})
    entries = vectors_client.get_vectors(keys)
    for entry in entries:
        assert entry["metadata"]["commit_refs"] == ["abc1234", "def5678"]


# ---------------------------------------------------------------------------
# T58 — commit_refs vector-metadata cap (20 most-recently-appended entries)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_fresh_commit_refs_over_cap_vector_capped_annotation_full(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """A fresh write supplying 21 short commit_refs (well under the byte budget) must
    succeed — never rejected for entry count alone — with the vector-metadata copy
    carrying only the last 20, while the annotation carries the complete, uncapped
    list of 21."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    vec_spy = mocker.spy(vectors_client, "put_vectors_batch")
    refs = [f"sha{i:04d}" for i in range(21)]

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **{**_ONE_SECTION_KWARGS, "commit_refs": refs},
    )

    assert "error" not in result
    assert s3_client.get_object_annotation(result["artifact_id"], "commit_refs") == ",".join(refs)
    vec_items = vec_spy.call_args.args[0]
    for item in vec_items:
        assert item["metadata"]["commit_refs"] == refs[-20:]
        assert len(item["metadata"]["commit_refs"]) == 20


@pytest.mark.asyncio
async def test_write_overwrite_merged_commit_refs_over_cap_vector_capped_annotation_full(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """An overwrite whose read-forward merge (existing ∪ supplied) produces more than 20
    short commit_refs entries must still succeed — the vector-metadata copy carries only
    the last 20 of the merged list, while the annotation carries the complete, uncapped
    merge."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    tier3_kwargs = {**_ONE_SECTION_KWARGS, "tier": 3}
    existing_refs = [f"existing{i:03d}" for i in range(15)]
    new_refs = [f"new{i:03d}" for i in range(10)]
    full_merged = list(dict.fromkeys(existing_refs + new_refs))
    assert len(full_merged) == 25  # sanity: exceeds the 20-entry cap

    first = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **{**tier3_kwargs, "commit_refs": existing_refs},
    )
    assert "error" not in first
    artifact_id = first["artifact_id"]

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        overwrite=True,
        **{**tier3_kwargs, "content": "## Summary\n\nUpdated content.", "commit_refs": new_refs},
    )

    assert "error" not in result
    assert s3_client.get_object_annotation(artifact_id, "commit_refs") == ",".join(full_merged)
    keys = vectors_client.list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}})
    entries = vectors_client.get_vectors(keys)
    assert entries
    for entry in entries:
        assert entry["metadata"]["commit_refs"] == full_merged[-20:]
        assert len(entry["metadata"]["commit_refs"]) == 20


# ---------------------------------------------------------------------------
# Union-of-both-stores authority model
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_overwrite_read_forward_preserves_annotation_only_value(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
) -> None:
    """RED: after a partial dual-write (e.g. an out-of-band ``link_metadata`` call)
    leaves the annotation copy ahead of the vector copy — the annotation holds a value
    vector metadata lacks — a tier-3 overwrite's Step 4a read-forward must preserve the
    union of both stores. Before the fix, Step 4a sourced the existing link fields from
    vector metadata only, so the annotation-only value was silently dropped: PutObject
    wipes the S3 annotation, and the read-forward never saw the value to re-apply it.
    """
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    tier3_kwargs = {**_BASE_WRITE_KWARGS, "tier": 3}

    first = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **{**tier3_kwargs, "commit_refs": ["abc1234"]},
    )
    assert "error" not in first
    artifact_id = first["artifact_id"]

    # Simulate a partial dual-write: an out-of-band annotation update succeeded, but the
    # paired vector-metadata update did not — the annotation copy now holds a value
    # ("def5678") the vector copy lacks.
    s3_client.put_object_annotation(artifact_id, "commit_refs", "abc1234,def5678")

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        overwrite=True,
        **{**tier3_kwargs, "content": "## Summary\n\nUpdated content."},
    )

    assert "error" not in result
    keys = vectors_client.list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}})
    entries = vectors_client.get_vectors(keys)
    assert entries, "expected at least one vector for the overwritten artifact"
    for entry in entries:
        assert entry["metadata"]["commit_refs"] == ["abc1234", "def5678"]
    assert s3_client.get_object_annotation(artifact_id, "commit_refs") == "abc1234,def5678"


# ---------------------------------------------------------------------------
# Optimistic-concurrency (ETag compare-and-swap) writes — ADR-011 decision 6
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_overwrite_put_object_called_with_if_match_from_captured_etag(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """An overwriting write's put_object call is conditional on the object's ETag
    captured by the existence check (if_match), not merely if_none_match=False."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    tier3_kwargs = {**_BASE_WRITE_KWARGS, "tier": 3}

    first = await write_artifact(
        s3=s3_client, vectors=vectors_client, bedrock=bedrock, settings=settings, **tier3_kwargs
    )
    artifact_id = first["artifact_id"]
    current_etag = s3_client.head_object(artifact_id)["ETag"]

    spy = mocker.spy(s3_client, "put_object")
    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        overwrite=True,
        **{**tier3_kwargs, "content": "## Summary\n\nUpdated content."},
    )

    assert "error" not in result
    assert spy.call_count == 1
    assert spy.call_args.kwargs.get("if_match") == current_etag


@pytest.mark.asyncio
async def test_overwrite_annotation_apply_uses_new_etag_from_put_object(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """The annotation re-apply following an overwriting write's put_object uses that
    put_object call's NEW ETag (ETag1) as if_match, not the pre-write ETag (ETag0)."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    tier3_kwargs = {**_BASE_WRITE_KWARGS, "tier": 3}

    first = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **{**tier3_kwargs, "commit_refs": ["abc1234"]},
    )
    artifact_id = first["artifact_id"]
    old_etag = s3_client.head_object(artifact_id)["ETag"]

    annotation_spy = mocker.spy(s3_client, "put_object_annotation")
    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        overwrite=True,
        **{**tier3_kwargs, "content": "## Summary\n\nUpdated content.", "commit_refs": ["abc1234"]},
    )

    assert "error" not in result
    new_etag = s3_client.head_object(artifact_id)["ETag"]
    assert new_etag != old_etag
    assert annotation_spy.call_count == 1
    assert annotation_spy.call_args.kwargs.get("if_match") == new_etag


@pytest.mark.asyncio
async def test_fresh_write_annotation_apply_has_no_if_match(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """A fresh (non-overwriting) write has nothing to race against (ADR-011 decision 6)
    — its annotation apply is unconditional (if_match=None)."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    annotation_spy = mocker.spy(s3_client, "put_object_annotation")

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **{**_BASE_WRITE_KWARGS, "commit_refs": ["abc1234"]},
    )

    assert "error" not in result
    assert annotation_spy.call_count == 1
    assert annotation_spy.call_args.kwargs.get("if_match") is None


@pytest.mark.asyncio
async def test_overwrite_cas_conflict_then_retry_succeeds_with_both_contributions(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """A conflict on the first CAS attempt's put_object (simulating a concurrent
    writer's own successful conditional write landing first) causes a retry that
    re-reads and re-merges, eventually succeeding with a state that includes BOTH
    the concurrent writer's contribution and this call's own supplied value — not
    one silently dropped."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    tier3_kwargs = {**_BASE_WRITE_KWARGS, "tier": 3}

    first = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **{**tier3_kwargs, "commit_refs": ["existing-sha"]},
    )
    artifact_id = first["artifact_id"]

    original_put_object = s3_client.put_object
    call_count = 0

    def _simulate_conflict_then_succeed(*args: object, **kwargs: object) -> str:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # A concurrent writer's own change lands between our read and our write.
            s3_client.put_object_annotation(
                artifact_id, "commit_refs", "existing-sha,concurrent-sha"
            )
            raise ArtifactConflictError(artifact_id)
        return original_put_object(*args, **kwargs)  # type: ignore[arg-type]

    mocker.patch.object(s3_client, "put_object", side_effect=_simulate_conflict_then_succeed)

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        overwrite=True,
        **{**tier3_kwargs, "content": "## Summary\n\nUpdated content.", "commit_refs": ["new-sha"]},
    )

    assert "error" not in result
    assert call_count == 2
    assert (
        s3_client.get_object_annotation(artifact_id, "commit_refs")
        == "existing-sha,concurrent-sha,new-sha"
    )
    keys = vectors_client.list_vectors_by_metadata({"artifact_id": {"$eq": artifact_id}})
    entries = vectors_client.get_vectors(keys)
    for entry in entries:
        assert entry["metadata"]["commit_refs"] == ["existing-sha", "concurrent-sha", "new-sha"]


@pytest.mark.asyncio
async def test_overwrite_annotation_conflict_retries_whole_cycle(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """A conflict on the annotation-apply call (simulating a concurrent object change
    landing between this call's own put_object and its annotation write) retries the
    WHOLE cycle — including a fresh put_object — not just the annotation call."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    tier3_kwargs = {**_BASE_WRITE_KWARGS, "tier": 3}

    first = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **{**tier3_kwargs, "commit_refs": ["existing-sha"]},
    )
    artifact_id = first["artifact_id"]

    put_object_spy = mocker.spy(s3_client, "put_object")
    original_put_annotation = s3_client.put_object_annotation
    call_count = 0

    def _fail_once(*args: object, **kwargs: object) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ArtifactConflictError(artifact_id)
        return original_put_annotation(*args, **kwargs)  # type: ignore[arg-type]

    mocker.patch.object(s3_client, "put_object_annotation", side_effect=_fail_once)

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        overwrite=True,
        **{**tier3_kwargs, "content": "## Summary\n\nUpdated content.", "commit_refs": ["new-sha"]},
    )

    assert "error" not in result
    assert put_object_spy.call_count == 2, "whole cycle must be retried, not just the annotation"
    assert s3_client.get_object_annotation(artifact_id, "commit_refs") == "existing-sha,new-sha"


@pytest.mark.asyncio
async def test_overwrite_persistent_cas_conflict_returns_conflict_error(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
    tmp_path: pytest.TempPathFactory,
) -> None:
    """A persistent conflict (every CAS attempt's put_object fails) returns a
    structured 'conflict' error after the bounded attempt count — never a raw
    exception. Nothing was ever durably written by this call, so no failure-log
    entry is produced, and the original artifact/annotation are untouched."""
    log_path = tmp_path / "failures.jsonl"
    settings = _make_settings(monkeypatch, FAILURE_LOG_PATH=str(log_path))
    bedrock = FakeBedrockClient()
    tier3_kwargs = {**_BASE_WRITE_KWARGS, "tier": 3}

    first = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **{**tier3_kwargs, "commit_refs": ["existing-sha"]},
    )
    artifact_id = first["artifact_id"]

    put_spy = mocker.patch.object(
        s3_client, "put_object", side_effect=ArtifactConflictError(artifact_id)
    )
    batch_spy = mocker.spy(vectors_client, "put_vectors_batch")

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        overwrite=True,
        **{**tier3_kwargs, "content": "## Summary\n\nUpdated content.", "commit_refs": ["new-sha"]},
    )

    assert result.get("error") == "conflict"
    assert result.get("artifact_id") == artifact_id
    assert put_spy.call_count == 3
    assert batch_spy.call_count == 0
    assert not log_path.exists()
    assert s3_client.get_object_annotation(artifact_id, "commit_refs") == "existing-sha"
    assert "Updated content" not in s3_client.get_object(artifact_id)


@pytest.mark.asyncio
async def test_overwrite_persistent_annotation_conflict_after_durable_write_logs_partial(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
    tmp_path: pytest.TempPathFactory,
) -> None:
    """When the object body IS durably written (put_object always succeeds) but the
    annotation apply persistently conflicts, exhausting retries must still record a
    failure-log entry — the object/annotation side was already durably written before
    the conflict was hit, so the entry must not be falsely omitted (mirrors the
    existing partial-write discipline)."""
    log_path = tmp_path / "failures.jsonl"
    settings = _make_settings(monkeypatch, FAILURE_LOG_PATH=str(log_path))
    bedrock = FakeBedrockClient()
    tier3_kwargs = {**_BASE_WRITE_KWARGS, "tier": 3}

    first = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **{**tier3_kwargs, "commit_refs": ["existing-sha"]},
    )
    artifact_id = first["artifact_id"]

    mocker.patch.object(
        s3_client,
        "put_object_annotation",
        side_effect=ArtifactConflictError(artifact_id),
    )

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        overwrite=True,
        **{
            **tier3_kwargs,
            "content": "## Summary\n\nUpdated content again.",
            "commit_refs": ["new-sha"],
        },
    )

    assert result.get("error") == "conflict"
    assert log_path.exists()
    entries = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert len(entries) == 1
    assert entries[0]["failure_step"] == "annotation_write"
    assert entries[0]["artifact_id"] == artifact_id
    # Content WAS durably updated on the final attempt even though we report conflict.
    assert "Updated content again" in s3_client.get_object(artifact_id)


@pytest.mark.asyncio
async def test_overwrite_vector_writes_remain_unconditional_despite_cas_retry(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    mocker: pytest.MonkeyPatch,
) -> None:
    """Vector writes stay unconditional in every scenario — put_vectors_batch is
    called with no conditional parameter, regardless of CAS retry outcome on the
    object side (no S3 Vectors CAS surface exists; ADR-011 decision 6)."""
    settings = _make_settings(monkeypatch)
    bedrock = FakeBedrockClient()
    tier3_kwargs = {**_BASE_WRITE_KWARGS, "tier": 3}

    first = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **{**tier3_kwargs, "commit_refs": ["existing-sha"]},
    )
    artifact_id = first["artifact_id"]

    original_put_object = s3_client.put_object
    call_count = 0

    def _conflict_once(*args: object, **kwargs: object) -> str:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ArtifactConflictError(artifact_id)
        return original_put_object(*args, **kwargs)  # type: ignore[arg-type]

    mocker.patch.object(s3_client, "put_object", side_effect=_conflict_once)
    batch_spy = mocker.spy(vectors_client, "put_vectors_batch")

    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        overwrite=True,
        **{**tier3_kwargs, "content": "## Summary\n\nUpdated content.", "commit_refs": ["new-sha"]},
    )

    assert "error" not in result
    assert batch_spy.call_count == 1
    assert batch_spy.call_args.kwargs == {}
    items = batch_spy.call_args.args[0]
    for item in items:
        assert "if_match" not in item
        assert set(item.keys()) == {"key", "vector", "metadata"}


# ---------------------------------------------------------------------------
# An unknown/transient annotation ClientError
# (e.g. SlowDown) must degrade to a structured partial_write response with a
# failure-log entry, not escape uncaught to the blanket internal_error handler.
# ---------------------------------------------------------------------------


def _unknown_annotation_client_error() -> botocore.exceptions.ClientError:
    """A transient S3 error that is neither credential-related, annotation-
    unavailable, nor a conflict — e.g. SlowDown/RequestTimeout."""
    return botocore.exceptions.ClientError(
        {"Error": {"Code": "SlowDown", "Message": "Please reduce your request rate."}},
        "PutObjectAnnotation",
    )


async def test_create_annotation_write_unknown_error_returns_partial_write(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    tmp_path: pytest.TempPathFactory,
    mocker: pytest.MonkeyPatch,
) -> None:
    """Fresh-create path: an unknown ClientError (e.g. SlowDown, not credential, not
    annotation-unavailable, not a conflict) from the annotation write must degrade to
    partial_write with a failure-log entry — the S3 object and vectors are already
    durably written by this point and must not be lost."""
    log_path = tmp_path / "failures.jsonl"
    settings = _make_settings(monkeypatch, FAILURE_LOG_PATH=str(log_path))
    bedrock = FakeBedrockClient()
    mocker.patch.object(
        s3_client, "put_object_annotation", side_effect=_unknown_annotation_client_error()
    )

    kwargs = {**_BASE_WRITE_KWARGS, "commit_refs": ["sha1"]}
    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **kwargs,
    )

    assert result.get("error") == "partial_write"
    assert "artifact_id" in result
    assert s3_client.get_object(result["artifact_id"]) == kwargs["content"]
    assert log_path.exists()
    entries = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert entries[-1]["failure_step"] == "annotation_write"
    assert entries[-1]["artifact_id"] == result["artifact_id"]


async def test_overwrite_annotation_write_unknown_error_returns_partial_write(
    monkeypatch: pytest.MonkeyPatch,
    s3_client: S3ClientImpl,
    vectors_client: VectorsClientImpl,
    tmp_path: pytest.TempPathFactory,
    mocker: pytest.MonkeyPatch,
) -> None:
    """Overwrite/CAS path: same unknown-ClientError scenario, on a re-write of an
    already-existing artifact — the new content is already durably written by the
    time the annotation write fails, so this must also degrade to partial_write with
    a failure-log entry rather than an uncaught exception."""
    log_path = tmp_path / "failures.jsonl"
    settings = _make_settings(monkeypatch, FAILURE_LOG_PATH=str(log_path))
    bedrock = FakeBedrockClient()

    first = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        **_BASE_WRITE_KWARGS,
    )

    mocker.patch.object(
        s3_client, "put_object_annotation", side_effect=_unknown_annotation_client_error()
    )

    changed_kwargs = {
        **_BASE_WRITE_KWARGS,
        "content": "## Summary\n\nUpdated content.",
        "commit_refs": ["sha1"],
    }
    result = await write_artifact(
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock,
        settings=settings,
        overwrite=True,
        **changed_kwargs,
    )

    assert result.get("error") == "partial_write"
    assert result.get("artifact_id") == first["artifact_id"]
    assert "Updated content." in s3_client.get_object(result["artifact_id"])
    assert log_path.exists()
    entries = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert entries[-1]["failure_step"] == "annotation_write"
    assert entries[-1]["artifact_id"] == result["artifact_id"]
