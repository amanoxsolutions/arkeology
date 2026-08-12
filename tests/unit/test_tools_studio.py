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
    """A credential-error dict from the inner list call must surface as a
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
    # …nor decorated with the listing's cap metadata.
    assert "total_count" not in result.structured_content


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
# Bounded fallback listing (T44 revision (c))
# ---------------------------------------------------------------------------


def _artifact(artifact_id: str, date: str) -> dict[str, str]:
    return {"artifact_id": artifact_id, "date": date}


async def _run_fallback(
    settings: Settings,
    mocker: MockerFixture,
    artifacts: list[dict[str, str]],
) -> ToolResult:
    """Run arkeology_studio on a non-supporting host over a canned inner listing."""
    from arkeology.tools import studio

    mocker.patch.object(studio, "_list_artifacts_inner", return_value={"artifacts": artifacts})
    ctx = MagicMock()
    ctx.client_supports_extension.return_value = False
    return await studio.arkeology_studio(settings=settings, vectors=MagicMock(), ctx=ctx)


@pytest.mark.asyncio
async def test_fallback_listing_is_capped_and_reports_total_count(
    settings: Settings,
    mocker: MockerFixture,
) -> None:
    """An oversized scope is capped, and total_count reports the pre-cap match count."""
    from arkeology.tools.studio import FALLBACK_LISTING_CAP

    over_cap = FALLBACK_LISTING_CAP + 17
    artifacts = [_artifact(f"artifacts/a-{i:03d}", "2026-01-01") for i in range(over_cap)]

    result = await _run_fallback(settings, mocker, artifacts)

    assert result.structured_content is not None
    assert len(result.structured_content["artifacts"]) == FALLBACK_LISTING_CAP
    assert result.structured_content["total_count"] == over_cap
    assert result.structured_content["write_prefix"] == settings.write_prefix


@pytest.mark.asyncio
async def test_fallback_listing_keeps_the_newest_artifacts(
    settings: Settings,
    mocker: MockerFixture,
) -> None:
    """Ordering is date descending with an artifact_id ascending tie-break, and the
    cap retains the head of that order — the newest artifacts, never an arbitrary slice."""
    from arkeology.tools.studio import FALLBACK_LISTING_CAP

    # Oldest first on the way in, so a cap that ignored ordering would keep the oldest.
    artifacts = [
        _artifact(f"artifacts/a-{i:03d}", f"2026-01-{i % 28 + 1:02d}")
        for i in range(FALLBACK_LISTING_CAP + 10)
    ]
    # Two passes, not one reverse=True sort: the tie-break runs ascending while the
    # date runs descending, so a single reversed key would invert the tie-break too.
    expected = sorted(artifacts, key=lambda a: a["artifact_id"])
    expected = sorted(expected, key=lambda a: a["date"], reverse=True)

    result = await _run_fallback(settings, mocker, artifacts)

    assert result.structured_content is not None
    returned = result.structured_content["artifacts"]
    assert returned == expected[:FALLBACK_LISTING_CAP]


@pytest.mark.asyncio
async def test_fallback_listing_below_cap_is_complete(
    settings: Settings,
    mocker: MockerFixture,
) -> None:
    """A scope smaller than the cap is returned whole, with total_count matching."""
    artifacts = [_artifact(f"artifacts/a-{i}", "2026-01-01") for i in range(3)]

    result = await _run_fallback(settings, mocker, artifacts)

    assert result.structured_content is not None
    assert len(result.structured_content["artifacts"]) == 3
    assert result.structured_content["total_count"] == 3


@pytest.mark.asyncio
async def test_fallback_truncation_is_stated_in_the_content_text(
    settings: Settings,
    mocker: MockerFixture,
) -> None:
    """When the cap truncates, the text states both counts and how to get the rest."""
    from arkeology.tools.studio import FALLBACK_LISTING_CAP

    over_cap = FALLBACK_LISTING_CAP + 5
    artifacts = [_artifact(f"artifacts/a-{i:03d}", "2026-01-01") for i in range(over_cap)]

    result = await _run_fallback(settings, mocker, artifacts)

    text = result.content[0].text  # type: ignore[attr-defined]
    assert str(FALLBACK_LISTING_CAP) in text
    assert str(over_cap) in text
    assert "list_artifacts" in text


@pytest.mark.asyncio
async def test_fallback_below_cap_does_not_claim_truncation(
    settings: Settings,
    mocker: MockerFixture,
) -> None:
    """A complete listing must not tell the caller that artifacts were withheld."""
    artifacts = [_artifact("artifacts/a-1", "2026-01-01")]

    result = await _run_fallback(settings, mocker, artifacts)

    text = result.content[0].text  # type: ignore[attr-defined]
    assert "list_artifacts" not in text


# ---------------------------------------------------------------------------
# M21 — _arkeology_studio_inner must exist (refactor to _inner convention)
# ---------------------------------------------------------------------------


def test_arkeology_studio_inner_function_exists() -> None:
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
