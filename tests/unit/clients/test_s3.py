"""Unit tests for S3ClientImpl.put_object metadata ASCII sanitization.

Uses the `s3_client` fixture from conftest (moto-backed, bucket pre-created).
"""

from cairn_mcp.clients.s3 import S3ClientImpl


def test_put_object_ascii_metadata_unchanged(s3_client: S3ClientImpl) -> None:
    """ASCII metadata values are stored and retrieved unchanged (baseline)."""
    metadata = {"title": "Plain ASCII Title", "artifact_type": "adr"}
    s3_client.put_object(key="test/plain.md", body="content", metadata=metadata)
    stored = s3_client.head_object("test/plain.md")
    assert stored["title"] == "Plain ASCII Title"
    assert stored["artifact_type"] == "adr"


def test_put_object_unicode_em_dash_sanitized(s3_client: S3ClientImpl) -> None:
    """Metadata with an em dash (U+2014) succeeds; stored title drops the em dash."""
    metadata = {"title": "A title \u2014 with em dash", "artifact_type": "adr"}
    # Must not raise ParamValidationError
    s3_client.put_object(key="test/emdash.md", body="content", metadata=metadata)
    stored = s3_client.head_object("test/emdash.md")
    assert "\u2014" not in stored["title"]
    assert "title" in stored["title"].lower() or "A title" in stored["title"]


def test_put_object_accented_letters_normalized(s3_client: S3ClientImpl) -> None:
    """Metadata with accented letters (café) succeeds; é is normalized to e."""
    metadata = {"title": "caf\u00e9", "artifact_type": "note"}
    s3_client.put_object(key="test/accented.md", body="content", metadata=metadata)
    stored = s3_client.head_object("test/accented.md")
    assert stored["title"] == "cafe"
